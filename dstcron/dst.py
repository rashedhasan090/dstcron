"""Find DST transitions for an IANA zone and the wall-clock minutes they break."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Transition:
    utc: datetime            # first instant with the new offset
    before: timedelta        # utcoffset just before
    after: timedelta         # utcoffset at/after
    tz: str

    @property
    def kind(self) -> str:
        return "gap" if self.after > self.before else "overlap"

    @property
    def delta(self) -> timedelta:
        return abs(self.after - self.before)

    @property
    def wall_start(self) -> datetime:
        """Naive local wall time where the affected window begins."""
        if self.kind == "gap":
            return (self.utc + self.before).replace(tzinfo=None)
        return (self.utc + self.after).replace(tzinfo=None)

    def wall_minutes(self):
        """Naive wall-clock minutes that do not exist (gap) or occur twice (overlap)."""
        start = self.wall_start
        n = int(self.delta.total_seconds() // 60)
        for i in range(n):
            yield start + timedelta(minutes=i)


def _offset(z: ZoneInfo, t: datetime) -> timedelta:
    return t.astimezone(z).utcoffset()


def transitions(tz: str, year: int) -> list[Transition]:
    z = ZoneInfo(tz)
    start = datetime(year, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) + timedelta(days=1)
    out: list[Transition] = []
    t = start
    prev = _offset(z, t)
    step = timedelta(hours=1)
    while t < end:
        nt = t + step
        cur = _offset(z, nt)
        if cur != prev:
            lo, hi = t, nt  # binary search to the minute
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                mid = mid.replace(second=0, microsecond=0)
                if mid <= lo:
                    mid = lo + timedelta(minutes=1)
                if _offset(z, mid) == prev:
                    lo = mid
                else:
                    hi = mid
            tr = Transition(utc=hi, before=prev, after=cur, tz=tz)
            local_year = (hi + cur).year
            if local_year == year:
                out.append(tr)
            prev = cur
        t = nt
    return out
