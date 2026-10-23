"""One shape for every problem the platform reports."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning" | "advice"
    where: str
    msg: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.where}: {self.msg}"


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]
