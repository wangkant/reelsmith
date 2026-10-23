"""Who serves the runner's session: the backend's key, the CLI env that points Claude Code at it, and its prices."""
from __future__ import annotations

import dataclasses
import re

from .workspace import WorkspaceError

LONG_CONTEXT = "[1m]"          # Claude Code's suffix for a 1M-token context window
DEEPSEEK_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_COMPACT_WINDOW = 786432


@dataclasses.dataclass(frozen=True)
class Price:
    """$ per million tokens by kind; `search` is $ per web search."""
    miss: float
    hit: float
    write: float
    out: float
    search: float = 0.0


def _claude(inp: float, out: float) -> Price:
    return Price(miss=inp, hit=inp * 0.1, write=inp * 1.25, out=out, search=0.01)


@dataclasses.dataclass(frozen=True)
class Backend:
    name: str
    model: str                      # the default model; for deepseek also the small and subagent model
    key: str                        # the API key's name: workspace .env first, then the environment
    prices: dict
    cli_cost: bool                  # the CLI's own cost figure (a Claude price table) is right for it
    base_url: str | None = None
    long_context: frozenset = frozenset()
    blind: frozenset = frozenset()  # models that take no images


BACKENDS = {
    "anthropic": Backend("anthropic", "claude-opus-5-5", "ANTHROPIC_API_KEY", {
        "claude-opus-5-5": _claude(4.0, 20.0), "claude-sonnet-5-5": _claude(2.0, 10.0),
        "claude-haiku-5-5": _claude(1.0, 5.0)}, cli_cost=True),
    # peak prices (off-peak is half); cache writes bill as misses; web search is free until 2026-11-01, counted anyway
    "deepseek": Backend("deepseek", "deepseek-flash", "DEEPSEEK_API_KEY", {
        "deepseek-flash": Price(miss=0.30, hit=0.006, write=0.30, out=1.20, search=0.00075),
        "deepseek-v4-pro": Price(miss=1.32, hit=0.044, write=1.32, out=3.96, search=0.00075)},
        cli_cost=False, base_url=DEEPSEEK_URL, long_context=frozenset({"deepseek-flash", "deepseek-v4-pro"}),
        blind=frozenset({"deepseek-v4-pro"})),
}


def get(name=None) -> Backend:
    key = str(name or "anthropic").strip().lower()
    if key not in BACKENDS:
        raise WorkspaceError(f'unknown runner backend "{name}": use {" or ".join(BACKENDS)}')
    return BACKENDS[key]


def plain(model) -> str:
    """deepseek-flash[1m] -> deepseek-flash."""
    return re.sub(r"\[[^\]]*\]$", "", str(model or "")).strip()


def cli_model(backend: Backend, model: str) -> str:
    """The model string the CLI gets: a 1M-context model without a suffix gets [1m]."""
    if model != plain(model) or plain(model).lower() not in backend.long_context:
        return model
    return model + LONG_CONTEXT


def can_see(backend: Backend, model: str) -> bool:
    return plain(model).lower() not in backend.blind


def cli_env(backend: Backend, model: str, key: str, workspace_id: str = "") -> dict:
    """The env that sends the CLI to this backend with this key and no other credential."""
    if not backend.base_url:
        # a host env set up for another endpoint must not carry the Anthropic key there ("" reads as unset)
        env = {"ANTHROPIC_API_KEY": key, "ANTHROPIC_BASE_URL": "", "ANTHROPIC_AUTH_TOKEN": ""}
        if workspace_id:
            env["ANTHROPIC_CUSTOM_HEADERS"] = f"anthropic-workspace-id: {workspace_id}"
        return env
    main, small = cli_model(backend, model), backend.model
    return {
        "ANTHROPIC_BASE_URL": backend.base_url, "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_API_KEY": key,
        "ANTHROPIC_MODEL": main, "ANTHROPIC_DEFAULT_OPUS_MODEL": main, "ANTHROPIC_DEFAULT_SONNET_MODEL": main,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": small, "ANTHROPIC_SMALL_FAST_MODEL": small,
        "CLAUDE_CODE_SUBAGENT_MODEL": small, "CLAUDE_CODE_AUTO_COMPACT_WINDOW": str(DEEPSEEK_COMPACT_WINDOW),
        # the SDK passes the host env through: blank any Anthropic credential or header it carries
        "ANTHROPIC_CUSTOM_HEADERS": "", "ANTHROPIC_WORKSPACE_ID": "", "CLAUDE_CODE_OAUTH_TOKEN": "",
    }


def price(backend: Backend, model, fallback=None) -> Price:
    """The model's price, else the fallback model's, else the backend's dearest."""
    for name in (model, fallback):
        found = backend.prices.get(plain(name).lower()) if name else None
        if found:
            return found
    return max(backend.prices.values(), key=lambda p: (p.out, p.miss))


def _n(usage: dict, key: str) -> int:
    try:
        return int(usage.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def cost(backend: Backend, rows: dict, model: str) -> float:
    """$ for usage rows {key: {"model", "usage"}} with Anthropic-style counters, at the backend's prices."""
    total = 0.0
    for row in rows.values():
        p = price(backend, row.get("model"), model)
        u = row.get("usage") or {}
        tool = u.get("server_tool_use") if isinstance(u.get("server_tool_use"), dict) else {}
        total += (_n(u, "input_tokens") * p.miss + _n(u, "cache_creation_input_tokens") * p.write
                  + _n(u, "cache_read_input_tokens") * p.hit + _n(u, "output_tokens") * p.out) / 1e6
        total += _n(tool, "web_search_requests") * p.search
    return total


def model_usage_rows(model_usage) -> dict:
    """The CLI's per-model totals (ResultMessage.model_usage, camelCase) as usage rows."""
    rows = {}
    for name, mu in (model_usage or {}).items():
        if isinstance(mu, dict):
            rows[name] = {"model": name, "usage": {
                "input_tokens": mu.get("inputTokens"), "output_tokens": mu.get("outputTokens"),
                "cache_read_input_tokens": mu.get("cacheReadInputTokens"),
                "cache_creation_input_tokens": mu.get("cacheCreationInputTokens"),
                "server_tool_use": {"web_search_requests": mu.get("webSearchRequests")}}}
    return rows
