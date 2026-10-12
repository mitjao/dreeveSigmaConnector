"""Minimal 5-field cron expression parser (stdlib only).

  minute hour day-of-month month day-of-week

Each field supports `*`, numbers, ranges `a-b`, lists `a,b` and steps `*/n`,
`a-b/n`. Day-of-week is 0-7 (0 and 7 = Sunday). As in classic cron, when both
day-of-month and day-of-week are restricted, a day matches if EITHER does.
Times are evaluated in the process' local time zone (set `TZ`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

_FIELDS = (  # (name, min, max)
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 7),
)


def _parse_field(spec: str, name: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        rng, _, step_s = part.partition("/")
        step = int(step_s) if step_s else 1
        if step < 1:
            raise ValueError(f"cron {name}: step must be >= 1 in {part!r}")
        if rng == "*":
            start, end = lo, hi
        elif "-" in rng:
            a, b = rng.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(rng)
            end = hi if step_s else start
        if not (lo <= start <= hi and lo <= end <= hi and start <= end):
            raise ValueError(f"cron {name}: {part!r} out of range {lo}-{hi}")
        values.update(range(start, end + 1, step))
    return values


class CronSchedule:
    def __init__(self, expr: str):
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron expression needs 5 fields, got {len(parts)}: {expr!r}")
        self.expr = expr
        try:
            (self.minutes, self.hours, self.days, self.months, dows) = (
                _parse_field(p, n, lo, hi) for p, (n, lo, hi) in zip(parts, _FIELDS)
            )
        except ValueError as e:
            if "cron" in str(e):
                raise
            raise ValueError(f"invalid cron expression {expr!r}: {e}") from None
        self.dows = {d % 7 for d in dows}  # 7 -> 0 (Sunday)
        self._dom_any = parts[2] == "*"
        self._dow_any = parts[4] == "*"

    def _day_matches(self, dt: datetime) -> bool:
        dow = (dt.weekday() + 1) % 7  # Python: Mon=0 -> cron: Sun=0
        dom_ok = dt.day in self.days
        dow_ok = dow in self.dows
        if self._dom_any or self._dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def next_after(self, now: datetime) -> datetime:
        """First matching minute strictly after `now` (naive local datetime)."""
        dt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = dt + timedelta(days=366 * 5)
        while dt < limit:
            if dt.month not in self.months or not self._day_matches(dt):
                dt = (dt + timedelta(days=1)).replace(hour=0, minute=0)
            elif dt.hour not in self.hours:
                dt = (dt + timedelta(hours=1)).replace(minute=0)
            elif dt.minute not in self.minutes:
                dt += timedelta(minutes=1)
            else:
                return dt
        raise ValueError(f"cron expression {self.expr!r} never matches")
