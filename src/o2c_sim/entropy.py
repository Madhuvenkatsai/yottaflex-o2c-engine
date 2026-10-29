from datetime import date, datetime, timedelta, timezone

import numpy as np


class StreamedEntropy:
    """Single-stream RNG so a rerun with the same seed replays every draw."""

    def __init__(self, seed: int) -> None:
        self.seed = int(seed)
        self._rng = np.random.default_rng(self.seed)

    def integers(self, low: int, high: int, size: int | None = None) -> int | np.ndarray:
        return self._rng.integers(low, high, size=size)

    def pick(self, items: tuple | list, size: int | None = None):
        idx = self._rng.integers(0, len(items), size=size)
        if size is None:
            return items[int(idx)]
        return [items[int(i)] for i in idx]

    def chance(self, probability: float) -> bool:
        return bool(self._rng.random() < probability)

    def unit(self) -> float:
        return float(self._rng.random())

    def cents(self, low: int, high: int) -> int:
        return int(self._rng.integers(low, high))

    def stamp_between(self, start: date, end: date, hour_low: int = 8, hour_high: int = 19) -> datetime:
        span = (end - start).days
        if span < 0:
            raise ValueError("calendar window is inverted")
        offset = int(self._rng.integers(0, span + 1))
        hour = int(self._rng.integers(hour_low, hour_high))
        minute = int(self._rng.integers(0, 60))
        second = int(self._rng.integers(0, 60))
        return datetime.combine(start + timedelta(days=offset), datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=hour, minute=minute, second=second
        )

    def later_than(self, origin: datetime, min_hours: int, max_hours: int, ceiling: datetime) -> datetime:
        if origin >= ceiling:
            return ceiling
        hours = int(self._rng.integers(min_hours, max_hours + 1))
        minutes = int(self._rng.integers(0, 60))
        candidate = origin + timedelta(hours=hours, minutes=minutes)
        if candidate > ceiling:
            slack = (ceiling - origin).total_seconds()
            if slack <= 1:
                return ceiling
            bump = int(self._rng.integers(1, max(2, int(slack))))
            return origin + timedelta(seconds=bump)
        return candidate
