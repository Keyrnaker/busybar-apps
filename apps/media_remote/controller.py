"""Dial seeking (accumulate detents, commit after a pause) and the BACK-button rule. Pure."""
from __future__ import annotations

BACK_RESTART_AFTER = 3.0   # seconds: BACK restarts the item past this, else goes to the previous one


class SeekAccumulator:
    def __init__(self, step: float = 10.0, settle: float = 0.8) -> None:
        self.step = step
        self.settle = settle
        self._total = 0.0
        self._last: float | None = None

    def add(self, delta: int, now: float) -> None:
        self._total += delta * self.step
        self._last = now

    def pending(self, now: float) -> float | None:
        """The not-yet-committed offset, or None when nothing is queued."""
        return self._total if self._last is not None else None

    def take_if_settled(self, now: float) -> float | None:
        if self._last is None or now - self._last < self.settle:
            return None
        total, self._total, self._last = self._total, 0.0, None
        return total

    @staticmethod
    def preview_text(total: float) -> str:
        sign = "+" if total >= 0 else "-"
        arrow = ">" if total >= 0 else "<"
        return f"{arrow} {sign}{abs(int(total))}s"


def clamp_target(pos: float, delta: float, duration: float) -> float:
    target = max(0.0, pos + delta)
    return min(target, duration) if duration > 0 else target


def back_action(pos: float) -> str:
    return "restart" if pos > BACK_RESTART_AFTER else "previous"
