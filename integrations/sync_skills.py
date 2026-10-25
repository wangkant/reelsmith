"""Copy skills/reelsmith/SKILL.md into the integrations that ship it (a plugin cannot reference files outside its
own folder). `python integrations/sync_skills.py` writes the copies; `--check` exits 1 when one has drifted."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "skills" / "reelsmith" / "SKILL.md"
COPIES = [ROOT / "integrations" / "claude-code" / "skills" / "reelsmith" / "SKILL.md"]


def drifted() -> list[Path]:
    want = SOURCE.read_bytes()
    return [p for p in COPIES if not p.is_file() or p.read_bytes() != want]


def main(argv: list[str]) -> int:
    stale = drifted()
    if "--check" in argv:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)} (run python integrations/sync_skills.py)")
        return 1 if stale else 0
    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(SOURCE.read_bytes())
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
