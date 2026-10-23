"""ledger.jsonl: one line per paid-call event, per-project spend, and reservations that keep parallel calls in budget.

A paid call is one `id` with several rows: "reserved" (written before the money moves), maybe "submitted" (a job the
provider accepted), then a final status with the real cost. Until a call has a final row it counts at its estimate,
so a call killed half-way still counts against the project, and parallel calls see each other's reservations.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import ProviderError

PENDING = ("reserved", "submitted")
IN_FLIGHT_S = 3600          # an unsettled call older than this is a dead run, not money about to leave the account
LOCK_TIMEOUT_S = 60.0
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_GUARD = threading.Lock()
_HELD = threading.local()


class BudgetRefused(ProviderError):
    """The call was not made: over the project budget, under the balance floor, or the balance was unreadable."""


@dataclass
class Reservation:
    id: str
    project: str
    tool: str
    provider: str
    est_usd: float
    fields: dict = field(default_factory=dict)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_s(ts: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(str(ts))).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def _money(value) -> float:
    try:
        v = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v >= 0 else 0.0


def row_cost(row: dict) -> float:
    """What a call's last row says it costs: its estimate while pending, else its real cost."""
    return _money(row.get("est_usd") if row.get("status") in PENDING else row.get("cost_usd"))


@contextmanager
def _os_lock(path: Path, timeout: float = LOCK_TIMEOUT_S):
    """An exclusive lock other processes respect (the MCP server and a CLI may share one ledger)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise ProviderError(f"ledger is locked by another process ({path}); try again") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise ProviderError(f"ledger is locked by another process ({path}); try again") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


class Ledger:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def locked(self):
        """Re-entrant within a thread; exclusive across threads and processes."""
        key = str(self.path.resolve()).lower()
        with _GUARD:
            lock = _THREAD_LOCKS.setdefault(key, threading.RLock())
        with lock:
            held = _HELD.__dict__.setdefault("keys", set())
            if key in held:             # a second OS lock from this process would wait on itself
                yield
                return
            with _os_lock(self.path.with_name(self.path.name + ".lock")):
                held.add(key)
                try:
                    yield
                finally:
                    held.discard(key)

    # -- reading
    def rows(self) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def calls(self, project: str | None = None, tool: str | None = None) -> dict[str, list[dict]]:
        """Rows grouped by call id, in file order; rows without an id stand alone."""
        out: dict[str, list[dict]] = {}
        for n, row in enumerate(self.rows()):
            if project is not None and row.get("project") != project:
                continue
            if tool is not None and row.get("tool") != tool:
                continue
            out.setdefault(str(row.get("id") or row.get("job") or f"row{n}"), []).append(row)
        return out

    def spent(self, project: str) -> float:
        return round(sum(row_cost(rows[-1]) for rows in self.calls(project).values()), 6)

    def estimated(self, project: str) -> float:
        """The part of spent() that settled at an estimate because the provider reported no cost."""
        total = 0.0
        for rows in self.calls(project).values():
            last = rows[-1]
            if last.get("status") in PENDING:
                continue
            if "estimated_usd" in last:
                total += _money(last.get("estimated_usd"))
            elif last.get("cost_source") == "estimate":
                total += row_cost(last)
        return round(total, 6)

    def in_flight(self, max_age_s: float = IN_FLIGHT_S) -> float:
        """Estimates of every project's unsettled calls younger than max_age_s: not yet off the balance."""
        total = 0.0
        for rows in self.calls().values():
            last = rows[-1]
            if last.get("status") in PENDING and age_s(rows[0].get("ts")) <= max_age_s:
                total += _money(last.get("est_usd"))
        return round(total, 6)

    # -- writing
    def append(self, row: dict) -> dict:
        row = {"ts": utc_now(), **row}
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self.locked():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
        return row

    def reserve(self, *, project: str, tool: str, provider: str, est_usd: float, budget_usd: float,
                min_balance_usd: float | None = None, balance: Callable[[], float] | None = None,
                **fields) -> Reservation:
        """Check the budget and the balance floor and write a 'reserved' row as one step; BudgetRefused if not."""
        est = round(_money(est_usd), 6)
        res = Reservation(uuid.uuid4().hex[:16], project, tool, provider, est, dict(fields))
        base = {"id": res.id, "project": project, "tool": tool, "provider": provider, "est_usd": est, **fields}
        with self.locked():
            why = self._why_not(project, est, budget_usd, min_balance_usd, balance)
            if why:
                self.append({**base, "status": "refused", "cost_usd": 0.0, "error": why})
                raise BudgetRefused(f"{tool}: not done, {why}")
            self.append({**base, "status": "reserved", "cost_usd": 0.0})
        return res

    def _why_not(self, project, est, budget_usd, min_balance_usd, balance) -> str:
        spent = self.spent(project)
        if spent + est > float(budget_usd) + 1e-9:
            return (f"its estimate ${est:.3f} would take this project's paid spend from ${spent:.3f} past its "
                    f"budget of ${float(budget_usd):.2f} (workspace.json budget.per_project_usd). Do without it, "
                    "or ask the owner to raise the budget.")
        if balance is None or min_balance_usd is None:
            return ""
        try:
            bal = float(balance())
        except Exception as exc:  # noqa: BLE001 — no balance read, no purchase
            said = str(exc)[:160] if isinstance(exc, ProviderError) else type(exc).__name__
            hint = "check the provider key in the workspace .env" if re.search(r"HTTP 40[13]|no \w+_KEY", said) \
                else "try again in a minute"
            return f"the account balance could not be read ({said}); {hint}."
        pending = self.in_flight()
        if bal - pending - est < float(min_balance_usd):
            held = f" less ${pending:.2f} still in flight" if pending else ""
            return (f"the account balance ${bal:.2f}{held} minus ${est:.3f} would drop under the "
                    f"${float(min_balance_usd):.2f} floor (budget.min_balance_usd). Do without it.")
        return ""

    def mark(self, res: Reservation, status: str = "submitted", **fields) -> dict:
        """An intermediate row (e.g. the provider accepted a job); the call still counts at its estimate."""
        return self.append(self._base(res) | {"status": status, "cost_usd": 0.0, **fields})

    def settle(self, res: Reservation, status: str, cost_usd: float, **fields) -> dict:
        return self.append(self._base(res) | {"status": status, "cost_usd": round(_money(cost_usd), 6), **fields})

    @staticmethod
    def _base(res: Reservation) -> dict:
        return {"id": res.id, "project": res.project, "tool": res.tool, "provider": res.provider,
                "est_usd": res.est_usd, **res.fields}


def spent_usd(project) -> float:
    """Paid spend recorded for a project (for the runner's report and the assets listing)."""
    from .config import context
    ctx = context(project)
    return Ledger(ctx.ledger_path).spent(ctx.project_key)
