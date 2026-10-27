import base64
import copy
import io
import json
from dataclasses import dataclass, field

import pytest
from PIL import Image

from reelsmith.agent import loop
from reelsmith.agent.loop import NUDGE, Agent


# ------------------------------------------------------------------ fakes
@dataclass
class Res:
    text: str
    images: list = field(default_factory=list)
    error: bool = False


@dataclass
class T:
    name: str
    run: object
    description: str = "a tool"
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


class FakeClient:
    """Plays scripted replies; each may be a reply dict, an exception to raise, or callable(messages) -> reply."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.on_retry = None

    def complete(self, messages, tools):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r(messages) if callable(r) else r


class Log:
    def __init__(self):
        self.events, self.lines = [], []

    def event(self, kind, **data):
        self.events.append((kind, data))

    def line(self, text):
        self.lines.append(text)

    def kinds(self):
        return [k for k, _ in self.events]


def reply(content=None, calls=(), prompt=100, completion=10, cost=0.0, finish=None, **extra):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": cid, "type": "function",
                              "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}
                             for name, args, cid in calls]
    msg.update(extra)
    return {"message": msg, "finish_reason": finish or ("tool_calls" if calls else "stop"),
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "cached_tokens": 0,
                      "cost_usd": cost}}


def echo_tool(seen=None):
    def run(args):
        if seen is not None:
            seen.append(args)
        return Res(f"echo {args.get('x')}")
    return T("echo", run)


def agent(client, tools=(), limits=None, **kw):
    return Agent(client, list(tools), "you edit films", limits or {}, **kw)


# ------------------------------------------------------------------ basics
def test_a_text_reply_ends_the_run():
    c = FakeClient(reply("all done"))
    out = agent(c).run("make a film")
    assert out["result"] == "all done" and out["turns"] == 1
    assert out["aborted"] is None and out["error"] is None
    assert [m["role"] for m in out["messages"]] == ["system", "user", "assistant"]
    assert c.calls[0]["messages"] == [{"role": "system", "content": "you edit films"},
                                      {"role": "user", "content": "make a film"}]
    assert len(out["session_id"]) == 32 and int(out["session_id"], 16) >= 0


def test_a_tool_call_round_trip_keeps_history_append_only():
    seen = []
    c = FakeClient(reply(None, [("echo", {"x": 1}, "c1")]), reply("ok"))
    out = agent(c, [echo_tool(seen)]).run("go")
    assert seen == [{"x": 1}] and out["result"] == "ok" and out["turns"] == 2
    assert c.calls[0]["tools"] == [{"type": "function", "function": {
        "name": "echo", "description": "a tool", "parameters": {"type": "object", "properties": {}}}}]
    first, second = c.calls[0]["messages"], c.calls[1]["messages"]
    assert second[:len(first)] == first
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "echo 1"}
    assert second[-2]["tool_calls"][0]["id"] == "c1"


def test_several_calls_in_one_turn_answer_in_order():
    c = FakeClient(reply("two at once", [("echo", {"x": 1}, "a"), ("echo", {"x": 2}, "b")]), reply("ok"))
    out = agent(c, [echo_tool()]).run("go")
    tail = out["messages"][2:5]
    assert tail[0]["role"] == "assistant" and tail[0]["content"] == "two at once"
    assert [(m["tool_call_id"], m["content"]) for m in tail[1:]] == [("a", "echo 1"), ("b", "echo 2")]


def test_malformed_arguments_become_an_error_message():
    seen = []
    c = FakeClient(reply(None, [("echo", '{"x": 1', "c1"), ("echo", "[1, 2]", "c2")]), reply("ok"))
    out = agent(c, [echo_tool(seen)]).run("go")
    assert seen == [] and out["result"] == "ok"
    bad, notobj = out["messages"][3]["content"], out["messages"][4]["content"]
    assert bad.startswith("error: the arguments of echo are not valid JSON") and "'{\"x\": 1'" in bad
    assert notobj == "error: the arguments of echo must be a JSON object, not list."


def test_empty_arguments_mean_no_arguments():
    seen = []
    c = FakeClient(reply(None, [("echo", "", "c1")]), reply("ok"))
    agent(c, [echo_tool(seen)]).run("go")
    assert seen == [{}]


def test_unknown_tool():
    c = FakeClient(reply(None, [("render_all", {}, "c1")]), reply("ok"))
    out = agent(c, [echo_tool()]).run("go")
    assert out["messages"][3]["content"] == "error: there is no tool named 'render_all'. The tools are: echo."


def test_a_raising_tool_reports_its_exception():
    def boom(args):
        raise ValueError("bad input")
    c = FakeClient(reply(None, [("boom", {}, "c1")]), reply("ok"))
    out = agent(c, [T("boom", boom)]).run("go")
    assert out["messages"][3]["content"] == "error: boom failed with ValueError: bad input"
    assert out["error"] is None and out["result"] == "ok"


def test_a_tool_error_is_marked():
    c = FakeClient(reply(None, [("render", {}, "c1"), ("note", {}, "c2"), ("quiet", {}, "c3")]), reply("ok"))
    tools = [T("render", lambda a: Res("render failed at master", error=True)),
             T("note", lambda a: Res("Error: already said", error=True)), T("quiet", lambda a: Res(""))]
    out = agent(c, tools).run("go")
    assert [m["content"] for m in out["messages"][3:6]] == [
        "error: render failed at master", "Error: already said", "(no output)"]


def test_missing_or_repeated_call_ids_are_made_up():
    c = FakeClient(reply(None, [("echo", {"x": 1}, ""), ("echo", {"x": 2}, "same"), ("echo", {"x": 3}, "same")]),
                   reply("ok"))
    out = agent(c, [echo_tool()]).run("go")
    ids = [call["id"] for call in out["messages"][2]["tool_calls"]]
    assert ids[0].startswith("call_") and ids[1] == "same" and ids[2] not in ("same", ids[0])
    assert [m["tool_call_id"] for m in out["messages"][3:6]] == ids


def test_ids_reused_across_turns_or_from_history_are_renamed():
    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
               {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call_0", "type": "function", "function": {"name": "echo", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "call_0", "content": "echo None"}]
    c = FakeClient(reply(None, [("echo", {}, "call_0")]), reply(None, [("echo", {}, "call_0")]), reply("ok"))
    out = agent(c, [echo_tool()]).run("again", history=history)
    ids = [call["id"] for m in out["messages"] for call in m.get("tool_calls") or []]
    assert ids[0] == "call_0" and len(set(ids)) == 3
    answered = [m["tool_call_id"] for m in out["messages"] if m["role"] == "tool"]
    assert answered == ids


def test_reasoning_fields_go_back_and_nulls_do_not():
    details = [{"type": "reasoning.encrypted", "data": "abc"}]
    c = FakeClient(reply(None, [("echo", {}, "c1")], reasoning="let me look", reasoning_details=details,
                         refusal=None), reply("ok"))
    agent(c, [echo_tool()]).run("go")
    sent = c.calls[1]["messages"][2]
    assert sent["reasoning"] == "let me look" and sent["reasoning_details"] == details
    assert "refusal" not in sent and "content" in sent


def test_content_as_parts_is_text():
    c = FakeClient(reply([{"type": "text", "text": "done "}, {"type": "text", "text": "here"}]))
    assert agent(c).run("go")["result"] == "done here"


# ------------------------------------------------------------------ images
def png(path, size, mode="RGB"):
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (10, 20, 30)).save(path)
    return path


def decode(part):
    url = part["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_images_follow_the_tool_messages_as_one_user_message(tmp_path):
    big = png(tmp_path / "sheet.png", (3000, 2000), "RGBA")
    small = png(tmp_path / "still_01.png", (400, 300))
    c = FakeClient(reply(None, [("preview", {}, "c1"), ("echo", {"x": 1}, "c2")]), reply("ok"))
    tools = [T("preview", lambda a: Res("2 stills", [big, small])), echo_tool()]
    out = agent(c, tools).run("go")
    msgs = c.calls[1]["messages"]
    assert [m["role"] for m in msgs[2:]] == ["assistant", "tool", "tool", "user"]
    parts = msgs[-1]["content"]
    assert parts[0]["type"] == "text" and "sheet.png" in parts[0]["text"]
    images = [p for p in parts if p["type"] == "image_url"]
    assert len(images) == 2
    first, second = decode(images[0]), decode(images[1])
    assert first.format == "JPEG" and first.size == (1280, 853) and first.mode == "RGB"
    assert second.size == (400, 300)
    assert out["result"] == "ok"


def test_image_edge_and_count_limits(tmp_path):
    stills = [png(tmp_path / f"s{i}.png", (1080, 1920)) for i in range(3)]
    c = FakeClient(reply(None, [("preview", {}, "c1")]), reply("ok"))
    agent(c, [T("preview", lambda a: Res("3", stills))], {"max_image_edge": 640, "max_images": 2}).run("go")
    parts = c.calls[1]["messages"][-1]["content"]
    images = [decode(p) for p in parts if p["type"] == "image_url"]
    assert [im.size for im in images] == [(360, 640), (360, 640)]
    assert "1 more were not attached: s2.png" in parts[0]["text"]


# ------------------------------------------------------------------ limits
def test_turn_limit():
    c = FakeClient(*[reply(None, [("echo", {}, f"c{i}")]) for i in range(5)])
    out = agent(c, [echo_tool()], {"max_turns": 2}).run("go")
    assert out["turns"] == 2 and out["result"] is None
    assert out["aborted"] == "reached the 2 turn limit" and len(c.calls) == 2


def test_budget_from_the_provider_cost():
    c = FakeClient(*[reply(None, [("echo", {}, f"c{i}")], cost=0.3) for i in range(5)])
    out = agent(c, [echo_tool()], {"budget_usd": 0.5}).run("go")
    assert out["turns"] == 2 and out["cost_usd"] == pytest.approx(0.6) and "budget" in out["aborted"]
    assert out["cost_estimated"] is False


def test_budget_from_the_price_table_when_there_is_no_cost():
    c = FakeClient(*[reply(None, [("echo", {}, f"c{i}")], prompt=1000, cost=None) for i in range(5)])
    seen = []

    def price(usage):
        seen.append(usage)
        return usage["prompt_tokens"] * 0.0002
    out = agent(c, [echo_tool()], {"budget_usd": 0.5}, price=price).run("go")
    assert out["turns"] == 3 and out["cost_usd"] == pytest.approx(0.6) and out["cost_estimated"] is True
    assert seen[0]["prompt_tokens"] == 1000


def test_no_cost_and_no_price_warns_once():
    log = Log()
    c = FakeClient(*[reply(None, [("echo", {}, f"c{i}")], cost=None) for i in range(2)], reply("ok"))
    out = agent(c, [echo_tool()], {"budget_usd": 1.0}, log=log).run("go")
    assert out["result"] == "ok" and out["cost_usd"] == 0
    assert sum("budget cannot be enforced" in ln for ln in log.lines) == 1


def test_wall_limit_with_a_fake_clock():
    now = [0.0]

    def slow(args):
        now[0] += 50
        return Res("rendered")
    c = FakeClient(*[reply(None, [("render", {}, f"c{i}")]) for i in range(5)])
    out = agent(c, [T("render", slow)], {"wall_s": 120}, clock=lambda: now[0]).run("go")
    assert out["turns"] == 3 and out["aborted"] == "over the 2 minute limit"


def test_a_final_answer_wins_over_a_limit():
    c = FakeClient(reply("done", cost=5.0))
    out = agent(c, [], {"budget_usd": 1.0, "max_turns": 1}).run("go")
    assert out["result"] == "done" and out["aborted"] is None


# ------------------------------------------------------------------ context
def dump_tool():
    def run(args):
        n = args.get("n")
        return Res(f"chunk {n}\n" + "x" * 3000)
    return T("dump", run)


def test_old_tool_outputs_are_elided_past_the_context_limit():
    log = Log()
    c = FakeClient(reply(None, [("dump", {"n": 1}, "c1")], prompt=50),
                   reply(None, [("dump", {"n": 2}, "c2")], prompt=1100),
                   reply("done", prompt=200))
    out = agent(c, [dump_tool()], {"context_tokens": 1000}, log=log).run("go")
    before, after = c.calls[1]["messages"], c.calls[2]["messages"]
    assert before[3]["content"].startswith("chunk 1\nxxx")
    assert after[3] == {"role": "tool", "tool_call_id": "c1", "content": "[older output elided: dump chunk 1]"}
    assert after[5]["content"].startswith("chunk 2\nxxx")          # the newest stays whole
    assert len(after) == len(before) + 2                           # stubs replace, nothing is dropped
    assert "elided" in log.kinds() and any(ln.startswith("context: elided 1") for ln in log.lines)
    assert out["messages"][3]["content"].startswith("[older output elided")


def test_no_elision_under_the_limit():
    c = FakeClient(reply(None, [("dump", {"n": 1}, "c1")], prompt=50),
                   reply(None, [("dump", {"n": 2}, "c2")], prompt=900), reply("done"))
    agent(c, [dump_tool()], {"context_tokens": 1000}).run("go")
    assert c.calls[2]["messages"][3]["content"].startswith("chunk 1")


def test_old_images_are_elided_past_the_image_cap(tmp_path):
    a, b = png(tmp_path / "a.png", (64, 64)), png(tmp_path / "b.png", (64, 64))
    c = FakeClient(reply(None, [("snap", {}, "c1")]), reply(None, [("snap", {}, "c2")]),
                   reply(None, [("snap", {}, "c3")]), reply("done"))
    agent(c, [T("snap", lambda args: Res("2 stills", [a, b]))], {"max_context_images": 3}).run("go")
    third = c.calls[2]["messages"]
    image_msgs = [m for m in third if m["role"] == "user" and m is not third[1]]
    assert image_msgs[0]["content"] == "[older images elided: (snap) a.png, (snap) b.png]"
    assert isinstance(image_msgs[1]["content"], list)
    assert sum(loop._images(m) for m in c.calls[3]["messages"]) == 2


def test_images_are_elided_with_tool_outputs_past_the_context_limit(tmp_path):
    a = png(tmp_path / "a.png", (64, 64))

    def snap(args):
        return Res(f"chunk {args['n']}\n" + "y" * 3000, [a])
    c = FakeClient(reply(None, [("snap", {"n": 1}, "c1")], prompt=50),
                   reply(None, [("snap", {"n": 2}, "c2")], prompt=5000), reply("done"))
    agent(c, [T("snap", snap)], {"context_tokens": 2000}).run("go")
    msgs = c.calls[2]["messages"]
    assert msgs[3]["content"] == "[older output elided: snap chunk 1]"
    assert msgs[4]["content"] == "[older images elided: (snap) a.png]"
    assert isinstance(msgs[-1]["content"], list) and msgs[-2]["content"].startswith("chunk 2")


# ------------------------------------------------------------------ nudge, resume, failures
def test_an_empty_reply_is_nudged_once():
    c = FakeClient(reply(None, [("echo", {}, "c1")]), reply(""), reply("done"))
    out = agent(c, [echo_tool()]).run("go")
    assert out["result"] == "done" and out["turns"] == 3
    third = c.calls[2]["messages"]
    assert third[-1] == {"role": "user", "content": NUDGE}
    assert third[-2]["role"] == "tool"                           # the empty answer is not kept


def test_two_empty_replies_in_a_row_stop():
    c = FakeClient(reply(None, [("echo", {}, "c1")]), reply(""), reply(None, reasoning="hmm"), reply("never"))
    out = agent(c, [echo_tool()]).run("go")
    assert out["result"] is None and out["turns"] == 3 and out["aborted"] == "the model gave two empty replies"
    assert len(c.replies) == 1


def test_the_nudge_resets_after_work():
    c = FakeClient(reply(""), reply(None, [("echo", {}, "c1")]), reply(""), reply("done"))
    out = agent(c, [echo_tool()]).run("go")
    assert out["result"] == "done" and out["turns"] == 4


def test_resume_from_history():
    history = [{"role": "system", "content": "older system"}, {"role": "user", "content": "first"},
               {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c1", "content": "echo None"}]
    keep = copy.deepcopy(history)
    c = FakeClient(reply("resumed"))
    out = agent(c, [echo_tool()], {"context_tokens": 10}).run("(runner) carry on", history=history)
    assert c.calls[0]["messages"] == keep + [{"role": "user", "content": "(runner) carry on"}]
    assert history == keep and out["messages"][0]["content"] == "older system"


def test_history_without_a_system_message_gets_one():
    c = FakeClient(reply("ok"))
    agent(c).run("again", history=[{"role": "user", "content": "first"}, {"role": "assistant", "content": "hi"}])
    assert [m["role"] for m in c.calls[0]["messages"]] == ["system", "user", "assistant", "user"]
    assert c.calls[0]["messages"][0]["content"] == "you edit films"


def test_a_model_error_never_raises():
    c = FakeClient(reply(None, [("echo", {}, "c1")], cost=0.1), RuntimeError("HTTP 401 from openrouter.ai: bad key"))
    out = agent(c, [echo_tool()]).run("go")
    assert out["error"] == "RuntimeError: HTTP 401 from openrouter.ai: bad key"
    assert out["turns"] == 1 and out["result"] is None and out["cost_usd"] == pytest.approx(0.1)
    assert [m["role"] for m in out["messages"]] == ["system", "user", "assistant", "tool"]


def test_an_exhausted_script_is_an_error_not_a_raise():
    out = agent(FakeClient()).run("go")
    assert out["error"].startswith("IndexError") and out["turns"] == 0


def test_on_turn_and_the_log():
    log, turns = Log(), []

    def on_turn(info):
        turns.append((info["turn"], info["tools"], len(info["messages"])))
    c = FakeClient(reply("looking", [("echo", {"x": 7}, "c1")]), reply("done"))
    out = agent(c, [echo_tool()], log=log, on_turn=on_turn).run("go")
    assert out["result"] == "done"
    assert turns == [(1, ["echo"], 4), (2, [], 5)]
    assert log.kinds() == ["start", "turn", "tool", "turn", "end"]
    assert "say looking" in log.lines and any(ln.startswith("-> echo") for ln in log.lines)
    tool = dict(log.events)["tool"]
    assert tool["name"] == "echo" and tool["input"] == {"x": 7} and tool["text"] == "echo 7"


def test_a_callable_log_gets_events():
    seen = []
    agent(FakeClient(reply("ok")), log=lambda kind, data: seen.append(kind)).run("go")
    assert seen == ["start", "turn", "end"]


def test_the_agent_hooks_the_clients_retry_log():
    log, c = Log(), FakeClient(reply("ok"))
    agent(c, log=log)
    c.on_retry(1, 2.0, "HTTP 429 from openrouter.ai: slow down")
    assert log.lines == ["retry 1 in 2.0 s: HTTP 429 from openrouter.ai: slow down"]


def test_duplicate_tool_names_are_refused():
    with pytest.raises(ValueError):
        agent(FakeClient(), [echo_tool(), echo_tool()])


def test_the_real_tool_types_fit():
    from reelsmith.agent.tools import Tool, ToolResult
    tool = Tool(name="echo", description="echo", parameters={"type": "object", "properties": {}},
                run=lambda args: ToolResult(text="hi", error=True))
    c = FakeClient(reply(None, [("echo", {}, "c1")]), reply("ok"))
    out = agent(c, [tool]).run("go")
    assert out["messages"][3]["content"] == "error: hi"
