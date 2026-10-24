"""A provider-neutral agent loop over Chat Completions tool calling.

Agent.run() calls the model, runs every tool call it makes, feeds the results back and stops when the model answers
without a tool call or a limit is reached. Tool images go back as one user message of JPEG parts after the tool
messages (most providers take no images in a tool message). History is append-only except when the prompt grows past
`context_tokens`: then the oldest tool outputs and images are replaced by short stubs.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
import time
import uuid
from pathlib import Path

from ..guard import brief_input

NUDGE = "(runner) continue, or say you are done."
STUB = "[older output elided: {what}]"
IMAGE_STUB = "[older images elided: {names}]"
# max_images: per tool turn (a preview is 24 stills and a contact sheet); max_context_images: per request
DEFAULT_LIMITS = {"max_turns": None, "budget_usd": None, "wall_s": None, "context_tokens": None,
                  "max_image_edge": 1280, "max_images": 25, "max_context_images": 30}
ELIDE_TO = 0.6                  # after an elision the prompt should be this share of context_tokens
IMAGE_TOKENS = 1500             # rough cost of one image part, for choosing what to elide
CHARS_PER_TOKEN = 3.0


def _flat(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _text_of(content) -> str:
    """Assistant content as plain text (a string, or a list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _usage_row(usage) -> dict:
    u = usage if isinstance(usage, dict) else {}
    row = {}
    for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens"):
        try:
            row[key] = int(u.get(key) or 0)
        except (TypeError, ValueError):
            row[key] = 0
    cost = u.get("cost_usd")
    row["cost_usd"] = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    return row


def encode_image(path, max_edge: int = 1280) -> str:
    """A data URL of the image downscaled to max_edge, as JPEG q85 (alpha flattened on white)."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
            im = flat
        else:
            im = im.convert("RGB")
        if max_edge and max(im.size) > max_edge:
            im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class Agent:
    """One model, its tools, a system prompt and limits. run() never raises (KeyboardInterrupt aside)."""

    def __init__(self, client, tools: list, system: str, limits: dict | None = None, log=None, price=None, *,
                 on_turn=None, clock=None, session_id: str | None = None):
        self.client = client
        self.tools = {}
        for tool in tools or []:
            if tool.name in self.tools:
                raise ValueError(f"two tools are named {tool.name}")
            self.tools[tool.name] = tool
        self.system = system
        self.limits = {**DEFAULT_LIMITS, **{k: v for k, v in (limits or {}).items() if v is not None}}
        self.log = log
        self.price = price
        self.on_turn = on_turn
        self.clock = clock or time.monotonic
        self.session_id = session_id or uuid.uuid4().hex
        self._ids: set[str] = set()
        self.specs = [{"type": "function", "function": {
            "name": t.name, "description": t.description or t.name,
            "parameters": t.parameters or {"type": "object", "properties": {}}}} for t in self.tools.values()]
        if getattr(client, "on_retry", "absent") is None:
            client.on_retry = lambda attempt, wait, why: self._line(
                f"retry {attempt} in {wait:.1f} s: {_flat(why)[:200]}")

    # ------------------------------------------------------------ logging
    def _event(self, kind: str, **data) -> None:
        try:
            if hasattr(self.log, "event"):
                self.log.event(kind, **data)
            elif callable(self.log):
                self.log(kind, data)
        except Exception:  # noqa: BLE001 - logging never stops the run
            pass

    def _line(self, text: str) -> None:
        try:
            if hasattr(self.log, "line"):
                self.log.line(text)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ the loop
    def run(self, prompt: str, history: list[dict] | None = None) -> dict:
        started = self.clock()
        messages: list[dict] = []
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0}
        out = {"result": None, "turns": 0, "usage": totals, "cost_usd": 0.0, "cost_estimated": False,
               "aborted": None, "error": None, "messages": messages, "session_id": self.session_id}
        nudged = False
        no_price_warned = False
        try:
            # a copy: elision rewrites old messages, and the caller's history stays as it was
            messages += copy.deepcopy([m for m in history or [] if isinstance(m, dict)])
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": self.system})
            if prompt:
                messages.append({"role": "user", "content": prompt})
            # some servers reuse ids like call_0 every turn; others refuse a repeated id anywhere in the history
            self._ids = {str(c.get("id")) for m in messages for c in m.get("tool_calls") or []
                         if isinstance(c, dict) and c.get("id")}
            self._event("start", session_id=self.session_id, prompt=prompt, resumed=bool(history),
                        tools=list(self.tools), limits=self.limits)
            while True:
                sent = len(messages)
                try:
                    reply = self.client.complete(messages, self.specs)
                except Exception as exc:  # noqa: BLE001
                    out["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
                    self._event("error", error=out["error"], turn=out["turns"] + 1)
                    self._line(f"model error {out['error'][:300]}")
                    break
                out["turns"] += 1
                usage = _usage_row(reply.get("usage"))
                for key in totals:
                    totals[key] += usage[key]
                cost = usage["cost_usd"]
                if cost is None:
                    out["cost_estimated"] = True
                    cost = self._priced(reply.get("usage"))
                    if cost is None:
                        cost = 0.0
                        if self.limits["budget_usd"] is not None and not no_price_warned:
                            no_price_warned = True
                            self._line("warning: the provider reports no cost and there is no price table; "
                                       "the budget cannot be enforced")
                out["cost_usd"] = round(out["cost_usd"] + cost, 6)

                message = self._keep(reply.get("message"))
                calls = message.get("tool_calls") or []
                text = _text_of(message.get("content"))
                self._event("turn", turn=out["turns"], finish_reason=reply.get("finish_reason"),
                            model=reply.get("model"), provider=reply.get("provider"), usage=usage,
                            cost_usd=out["cost_usd"], message=message)
                if text.strip():
                    self._line("say " + _flat(text)[:200])
                if calls:
                    nudged = False
                    messages.append(message)
                    names = self._run_calls(calls, messages)
                elif text.strip():
                    messages.append(message)
                    out["result"] = text
                    self._turned(out, usage, reply, [])
                    break
                elif not nudged:
                    # an empty answer is not an answer: ask once, then give up
                    nudged = True
                    names = []
                    messages.append({"role": "user", "content": NUDGE})
                    self._line("empty reply: nudged")
                else:
                    out["aborted"] = "the model gave two empty replies"
                    self._turned(out, usage, reply, [])
                    break
                self._fit(messages, usage["prompt_tokens"], sent)
                self._turned(out, usage, reply, names)
                out["aborted"] = self._over(out, started)
                if out["aborted"]:
                    self._event("abort", reason=out["aborted"], turn=out["turns"])
                    self._line(f"abort: {out['aborted']}")
                    break
        except Exception as exc:  # noqa: BLE001 - the outcome says what happened
            out["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            self._event("error", error=out["error"], turn=out["turns"])
            self._line(f"loop error {out['error'][:300]}")
        out["cost_usd"] = round(out["cost_usd"], 6)
        self._event("end", turns=out["turns"], cost_usd=out["cost_usd"], usage=totals, aborted=out["aborted"],
                    error=out["error"], result=out["result"])
        return out

    def _priced(self, usage) -> float | None:
        if self.price is None:
            return None
        try:
            value = self.price(usage if isinstance(usage, dict) else {})
            return float(value) if value is not None else None
        except Exception as exc:  # noqa: BLE001
            self._line(f"price failed ({type(exc).__name__}: {exc})")
            return None

    def _over(self, out: dict, started: float) -> str | None:
        lim = self.limits
        if lim["max_turns"] and out["turns"] >= int(lim["max_turns"]):
            return f"reached the {int(lim['max_turns'])} turn limit"
        if lim["budget_usd"] is not None and out["cost_usd"] >= float(lim["budget_usd"]):
            return f"the ${out['cost_usd']:.2f} spent reached the ${float(lim['budget_usd']):.2f} budget"
        if lim["wall_s"] and self.clock() - started >= float(lim["wall_s"]):
            return f"over the {float(lim['wall_s']) / 60:g} minute limit"
        return None

    def _turned(self, out: dict, usage: dict, reply: dict, names: list[str]) -> None:
        if self.on_turn is None:
            return
        info = {"turn": out["turns"], "session_id": self.session_id, "usage": usage, "totals": dict(out["usage"]),
                "cost_usd": out["cost_usd"], "finish_reason": reply.get("finish_reason"), "tools": names,
                "messages": out["messages"]}
        try:
            self.on_turn(info)
        except Exception as exc:  # noqa: BLE001
            self._line(f"on_turn failed ({type(exc).__name__}: {exc})")

    @staticmethod
    def _keep(message) -> dict:
        """The assistant message as returned, minus null fields a provider may refuse on the way back."""
        msg = copy.deepcopy(message) if isinstance(message, dict) else {}
        msg = {k: v for k, v in msg.items() if v is not None or k == "content"}
        msg["role"] = "assistant"
        msg.setdefault("content", None)
        calls = msg.get("tool_calls")
        if calls is not None and not (isinstance(calls, list) and calls):
            msg.pop("tool_calls")
        return msg

    # ------------------------------------------------------------ tools
    def _run_calls(self, calls: list, messages: list[dict]) -> list[str]:
        images: list[tuple[str, Path]] = []
        names = []
        for i, call in enumerate(calls):
            if not isinstance(call, dict):
                call = {}
                calls[i] = call
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(fn.get("name") or "")
            cid = str(call.get("id") or "")
            if not cid or cid in self._ids:
                cid = f"call_{uuid.uuid4().hex[:12]}"
                call["id"] = cid            # the tool message must answer an id the assistant message carries
            call.setdefault("type", "function")
            self._ids.add(cid)
            names.append(name or "?")
            text, error, pics = self._call(name, fn.get("arguments"))
            if error and not text.lower().startswith("error"):
                text = "error: " + text
            messages.append({"role": "tool", "tool_call_id": cid, "content": text or "(no output)"})
            images += [(name, p) for p in pics]
        if images:
            messages.append(self._image_message(images))
        return names

    def _call(self, name: str, raw_args) -> tuple[str, bool, list]:
        """(text, error, images) for one tool call; nothing it does escapes as an exception."""
        args, text, error, pics = raw_args, "", True, []
        t0 = time.monotonic()
        tool = self.tools.get(name)
        if tool is None:
            text = f"error: there is no tool named {name!r}. The tools are: {', '.join(self.tools) or 'none'}."
        else:
            args, why = _arguments(name, raw_args)
            if why:
                text = why
            else:
                self._line(f"-> {name} {brief_input(name, args)}")
                try:
                    result = tool.run(args)
                    if isinstance(result, str) or result is None:
                        text, error = result or "", False
                    else:
                        text = str(getattr(result, "text", "") or "")
                        error = bool(getattr(result, "error", False))
                        pics = [Path(p) for p in (getattr(result, "images", None) or [])]
                except Exception as exc:  # noqa: BLE001
                    text = f"error: {name} failed with {type(exc).__name__}: {str(exc)[:1000]}"
        self._event("tool", name=name, input=args, error=error, text=text, images=[str(p) for p in pics],
                    seconds=round(time.monotonic() - t0, 2))
        if error:
            self._line(f"<- {name or '?'} " + ("" if text.lower().startswith("error") else "error ")
                       + _flat(text)[:200])
        return text, error, pics

    def _image_message(self, images: list[tuple[str, Path]]) -> dict:
        cap = int(self.limits.get("max_images") or 0)
        edge = int(self.limits.get("max_image_edge") or 0)
        shown, parts = images[:cap] if cap else images, []
        for tool, path in shown:
            try:
                url = encode_image(path, edge)
            except Exception as exc:  # noqa: BLE001
                parts.append({"type": "text", "text": f"({tool}) could not attach {path.name}: {type(exc).__name__}"})
                continue
            parts.append({"type": "text", "text": f"({tool}) {path.name}"})
            parts.append({"type": "image_url", "image_url": {"url": url}})
        names = ", ".join(p.name for _, p in shown)
        head = f"(runner) Images from the tool calls above: {names}."
        if len(images) > len(shown):
            head += (f" {len(images) - len(shown)} more were not attached: "
                     + ", ".join(p.name for _, p in images[len(shown):]))
        return {"role": "user", "content": [{"type": "text", "text": head}, *parts]}

    # ------------------------------------------------------------ context
    def _fit(self, messages: list[dict], prompt_tokens: int, sent: int) -> None:
        """Stub the oldest image messages past max_context_images, and the oldest tool outputs and images once the
        last prompt passed context_tokens; the newest turn always stays."""
        limit = self.limits.get("context_tokens")
        cap = self.limits.get("max_context_images")
        over = bool(limit) and prompt_tokens > limit
        pictures = sum(_images(m) for m in messages)
        if not over and not (cap and pictures > cap):
            return
        weights = [_weight(m) for m in messages]
        scale = prompt_tokens / max(1.0, sum(weights[:sent])) if prompt_tokens else 1.0
        expected = (prompt_tokens or sum(weights[:sent])) + scale * sum(weights[sent:])
        newest = max((i for i, m in enumerate(messages) if m.get("role") == "assistant"), default=len(messages))
        names = _call_names(messages)
        freed, count = 0.0, 0

        def elide(i: int, stub: str) -> None:
            nonlocal freed, count, pictures
            freed += scale * (weights[i] - _weight({"content": stub}))
            pictures -= _images(messages[i])
            messages[i]["content"] = stub
            count += 1

        # providers cap the images in one request: the oldest go first
        for i in range(newest):
            if not cap or pictures <= cap:
                break
            if _images(messages[i]):
                elide(i, _stub(messages[i], names))
        if over:
            goal = ELIDE_TO * limit
            for i in range(newest):
                if expected - freed <= goal:
                    break
                stub = _stub(messages[i], names)
                if stub is not None and weights[i] > _weight({"content": stub}):
                    elide(i, stub)
        if count:
            self._event("elided", count=count, prompt_tokens=prompt_tokens, context_tokens=limit,
                        images_left=pictures, expected_after=round(expected - freed))
            self._line(f"context: elided {count} older outputs (prompt {prompt_tokens} tokens, "
                       f"~{round(expected - freed)} next, {pictures} images left)")
        elif over:
            self._line(f"context: prompt {prompt_tokens} > {limit} tokens and nothing older is left to elide")


def _arguments(name: str, raw) -> tuple[dict | None, str]:
    """(arguments, '') or (None, the error the model gets back)."""
    if isinstance(raw, dict):
        return raw, ""
    text = str(raw or "").strip()
    try:
        args = json.loads(text) if text else {}
    except ValueError as exc:
        return None, (f"error: the arguments of {name} are not valid JSON ({exc}): {text[:200]!r}. "
                      "Call it again with one JSON object.")
    if not isinstance(args, dict):
        return None, f"error: the arguments of {name} must be a JSON object, not {type(args).__name__}."
    return args, ""


def _weight(message: dict) -> float:
    """Rough tokens of a message: text by characters, each image part at a flat rate."""
    content = message.get("content")
    if isinstance(content, list):
        total = 0.0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                total += IMAGE_TOKENS
            elif isinstance(part, dict):
                total += len(str(part.get("text") or "")) / CHARS_PER_TOKEN
        return total + 4
    total = len(str(content or "")) / CHARS_PER_TOKEN
    if message.get("tool_calls"):
        total += len(json.dumps(message["tool_calls"], ensure_ascii=False)) / CHARS_PER_TOKEN
    return total + 4


def _images(message: dict) -> int:
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    return sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")


def _call_names(messages: list[dict]) -> dict:
    names = {}
    for m in messages:
        for call in m.get("tool_calls") or []:
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                names[call.get("id")] = call["function"].get("name") or "?"
    return names


def _stub(message: dict, names: dict) -> str | None:
    """The stub that replaces an old tool output or image message, or None when it is not one (or already is)."""
    content = message.get("content")
    if message.get("role") == "tool" and isinstance(content, str):
        if content.startswith("[older output elided"):
            return None
        first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
        return STUB.format(what=" ".join(x for x in (names.get(message.get("tool_call_id"), "tool"), first[:120]) if x))
    if message.get("role") == "user" and _images(message):
        labels = [p.get("text") for p in content[1:] if isinstance(p, dict) and p.get("type") == "text"]
        return IMAGE_STUB.format(names=", ".join(str(t) for t in labels)[:300] or "images")
    return None
