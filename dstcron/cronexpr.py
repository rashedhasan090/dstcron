"""Minimal 5-field cron expression parser (Vixie/cronie dialect)."""
from __future__ import annotations

from dataclasses import dataclass

MONTHS = {n: i for i, n in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAYS = {n: i for i, n in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


class CronError(ValueError):
    pass


def _value(tok: str, names: dict | None) -> int:
    t = tok.lower()
    if names and t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(f"bad value {tok!r}")
    return int(t)


def parse_field(field: str, lo: int, hi: int, names: dict | None = None) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        if not part:
            raise CronError(f"empty list item in {field!r}")
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) == 0:
                raise CronError(f"bad step in {field!r}")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            x, y = part.split("-", 1)
            a, b = _value(x, names), _value(y, names)
        else:
            a = _value(part, names)
            b = hi if step != 1 else a
        if a < lo or b > hi or a > b:
            raise CronError(f"value out of range in {field!r} ({lo}-{hi})")
        out.update(range(a, b + 1, step))
    return out


@dataclass(frozen=True)
class CronSpec:
    expr: str
    minutes: frozenset
    hours: frozenset
    doms: frozenset
    months: frozenset
    dows: frozenset
    dom_star: bool
    dow_star: bool
    wildcard: bool  # cronie: minute or hour field starts with '*'

    def matches(self, month: int, day: int, weekday_sun0: int, hour: int, minute: int) -> bool:
        if minute not in self.minutes or hour not in self.hours or month not in self.months:
            return False
        dom_ok = day in self.doms
        dow_ok = weekday_sun0 in self.dows
        if self.dom_star or self.dow_star:
            return dom_ok and dow_ok
        return dom_ok or dow_ok  # classic Vixie OR rule

    @property
    def runs_per_day_hint(self) -> int:
        return len(self.minutes) * len(self.hours)


def parse(expr: str) -> CronSpec:
    raw = expr.strip()
    e = MACROS.get(raw.lower(), raw)
    if e.startswith("@"):
        raise CronError(f"unsupported macro {raw!r}")
    f = e.split()
    if len(f) != 5:
        raise CronError(f"expected 5 fields, got {len(f)}: {raw!r}")
    m, h, dom, mon, dow = f
    dows = parse_field(dow, 0, 7, DAYS)
    if 7 in dows:
        dows = (dows - {7}) | {0}
    return CronSpec(
        expr=raw,
        minutes=frozenset(parse_field(m, 0, 59)),
        hours=frozenset(parse_field(h, 0, 23)),
        doms=frozenset(parse_field(dom, 1, 31)),
        months=frozenset(parse_field(mon, 1, 12, MONTHS)),
        dows=frozenset(dows),
        dom_star=dom.startswith("*"),
        dow_star=dow.startswith("*"),
        wildcard=m.startswith("*") or h.startswith("*"),
    )
