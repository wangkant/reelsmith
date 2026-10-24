"""Who serves the api engine: an OpenAI-compatible Chat Completions endpoint, its key, request extras and prices.

Built in: openrouter (the default; it reports each call's cost), deepseek (priced from backends.py's peak table),
openai, and custom (workspace.json runner.base_url and runner.key_env, for any compatible gateway or local server).
"""
from __future__ import annotations

import copy
import dataclasses
import re

from .. import backends
from ..workspace import WorkspaceError

DEFAULT = "openrouter"
REASONING = ("low", "medium", "high")
OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_URL = "https://api.deepseek.com"
OPENAI_URL = "https://api.openai.com/v1"
PROJECT_URL = "https://github.com/wangkant/reelsmith"


def _name(model) -> str:
    return backends.plain(model).lower()


def _n(usage: dict, key: str) -> int:
    try:
        return max(0, int((usage or {}).get(key) or 0))
    except (TypeError, ValueError):
        return 0


@dataclasses.dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key: str | None                     # the key's name: workspace .env first, then the environment; None: no key
    default_model: str | None
    extra_body: dict = dataclasses.field(default_factory=dict)
    headers: dict = dataclasses.field(default_factory=dict)
    vision: frozenset = frozenset()     # models known to take images
    blind: frozenset = frozenset()      # models known to take none
    prices: dict | None = None          # model -> backends.Price
    reports_cost: bool = False          # every response carries its own $ cost
    reasoning_style: str = "openai"     # "openrouter": {"reasoning": {"effort"}}; "openai": reasoning_effort
    dearest_fallback: bool = False      # an unlisted model is priced at the dearest, so an estimate errs high

    def can_see(self, model) -> bool | None:
        """True or False when the model is known to take images or not; None when unknown."""
        name = _name(model)
        if name in self.vision:
            return True
        if name in self.blind:
            return False
        return None

    def _price_row(self, model):
        table = {_name(k): v for k, v in (self.prices or {}).items()}
        found = table.get(_name(model))
        if found is None and self.dearest_fallback and table:
            found = max(table.values(), key=lambda p: (p.out, p.miss))
        return found

    def price(self, model, usage: dict) -> float | None:
        """$ for one call's usage ({prompt_tokens, completion_tokens, cached_tokens}), or None with no price."""
        p = self._price_row(model)
        if p is None:
            return None
        prompt = _n(usage, "prompt_tokens")
        cached = min(_n(usage, "cached_tokens"), prompt)
        return ((prompt - cached) * p.miss + cached * p.hit + _n(usage, "completion_tokens") * p.out) / 1e6

    def pricer(self, model):
        """The Agent's price callable for calls that report no cost, or None when nothing prices this model."""
        if self._price_row(model) is None:
            return None
        return lambda usage: self.price(model, usage) or 0.0

    def body(self, reasoning: str | None = None) -> dict:
        """The extra request fields: the provider's own plus the reasoning effort in its dialect."""
        out = copy.deepcopy(self.extra_body)
        if reasoning:
            if self.reasoning_style == "openrouter":
                out["reasoning"] = {**(out.get("reasoning") or {}), "effort": reasoning}
            else:
                out["reasoning_effort"] = reasoning
        return out


PROVIDERS = {
    # usage.include returns usage.cost in dollars; require_parameters keeps routing to hosts that take tools
    "openrouter": Provider(
        "openrouter", OPENROUTER_URL, "OPENROUTER_API_KEY", "deepseek/deepseek-v4.1-flash",
        extra_body={"usage": {"include": True}, "provider": {"require_parameters": True}},
        headers={"HTTP-Referer": PROJECT_URL, "X-Title": "reelsmith"},
        vision=frozenset({"deepseek/deepseek-v4.1-flash"}), blind=frozenset({"deepseek/deepseek-v4-pro"}),
        reports_cost=True, reasoning_style="openrouter"),
    "deepseek": Provider(
        "deepseek", DEEPSEEK_URL, "DEEPSEEK_API_KEY", "deepseek-flash",
        vision=frozenset({"deepseek-flash"}), blind=frozenset({"deepseek-v4-pro"}),
        prices=dict(backends.BACKENDS["deepseek"].prices), dearest_fallback=True),
    "openai": Provider("openai", OPENAI_URL, "OPENAI_API_KEY", None),
    "custom": Provider("custom", "", None, None),
}


def _prices(raw) -> dict:
    """workspace.json runner.prices {model: [input, output, cached_input]} in $ per million tokens."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkspaceError('workspace.json runner.prices must be an object {"model": [input, output, cached_input]}')
    out = {}
    for model, row in raw.items():
        vals = row if isinstance(row, (list, tuple)) else None
        if not vals or len(vals) not in (2, 3) or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in vals):
            raise WorkspaceError(f'runner.prices["{model}"] must be [input, output] or [input, output, cached_input] '
                                 "in $ per million tokens")
        inp, outp = float(vals[0]), float(vals[1])
        hit = float(vals[2]) if len(vals) == 3 else inp
        out[str(model)] = backends.Price(miss=inp, hit=hit, write=inp, out=outp)
    return out


def _merged(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = _merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def get(name=None, cfg: dict | None = None) -> Provider:
    """The named provider with the workspace's runner settings applied: base_url and key_env (custom only), prices
    (any provider; they price calls that report no cost) and extra_body (merged into every request)."""
    key = str(name or DEFAULT).strip().lower()
    if key not in PROVIDERS:
        raise WorkspaceError(f'unknown runner provider "{name}": use {", ".join(PROVIDERS)}')
    p, cfg = PROVIDERS[key], cfg or {}
    changes: dict = {}
    if key == "custom":
        url = str(cfg.get("base_url") or "").strip().rstrip("/")
        if not re.match(r"^https?://[^/\s]+", url, re.I):
            raise WorkspaceError('the custom provider needs workspace.json runner.base_url: the http(s) URL of an '
                                 'OpenAI-compatible API, like "http://localhost:8000/v1"')
        env = str(cfg.get("key_env") or "").strip() or None
        if env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
            raise WorkspaceError(f'runner.key_env must name an environment variable, not "{env}"')
        changes.update(base_url=url, key=env)
    table = _prices(cfg.get("prices"))
    if table:
        changes["prices"] = {**(p.prices or {}), **table}
    extra = cfg.get("extra_body")
    if extra is not None:
        if not isinstance(extra, dict):
            raise WorkspaceError("workspace.json runner.extra_body must be an object")
        changes["extra_body"] = _merged(p.extra_body, extra)
    return dataclasses.replace(p, **changes) if changes else p


def make_client(provider: Provider, model: str, api_key: str, reasoning: str | None = None, timeout_s: float = 600,
                proxy: str | None = None):
    """A ChatClient for this provider and model; `proxy` (runner.proxy or REELSMITH_PROXY) replaces HTTP(S)_PROXY."""
    import urllib.request

    from .client import ChatClient, _loopback
    client = ChatClient(provider.base_url, api_key, model, headers=dict(provider.headers) or None,
                        extra_body=provider.body(reasoning) or None, timeout_s=timeout_s)
    if proxy and not _loopback(client.host):
        client._opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return client
