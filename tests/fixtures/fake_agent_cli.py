"""Stands in for `codex exec` and `dsh --profile headless` in tests: plays recorded JSON events, no model calls.

FAKE_CLI_SCRIPT names a JSON file {"runs": [{"events": [...], "exit": 0, "stderr": ""}], "env_keys": [...]}; the
n-th call plays runs[n] (the last one repeats). An event is a JSON object printed as one line, "deliver" (write a
passing out/film.mp4 in the cwd) or {"sleep": seconds}. Each call is appended to <script>.calls.jsonl. `--version`
prints FAKE_CLI_VERSION (default 0.2.1-rc.3) and is not recorded.
"""
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    if sys.argv[1:] == ["--version"]:
        print(os.environ.get("FAKE_CLI_VERSION", "0.2.1-rc.3"))
        return 0
    script = Path(os.environ["FAKE_CLI_SCRIPT"])
    spec = json.loads(script.read_text(encoding="utf-8"))
    calls = script.with_name(script.stem + ".calls.jsonl")
    n = len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0
    run = spec["runs"][min(n, len(spec["runs"]) - 1)]
    prompt = sys.stdin.read()
    with open(calls, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(),
                             "env": {k: os.environ.get(k) for k in spec.get("env_keys", [])}}) + "\n")
    for ev in run.get("events", []):
        if ev == "deliver":
            out = Path.cwd() / "out"
            out.mkdir(exist_ok=True)
            (out / "film.mp4").write_bytes(b"x")
            (out / "report.json").write_text('{"ok": true}', encoding="utf-8")
        elif isinstance(ev, dict) and "sleep" in ev:
            time.sleep(ev["sleep"])
        else:
            print(json.dumps(ev), flush=True)
    sys.stderr.write(run.get("stderr", ""))
    return int(run.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
