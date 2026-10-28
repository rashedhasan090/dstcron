"""Combine cron specs with DST transitions into findings."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

from .cronexpr import CronError, CronSpec, parse
from .dst import Transition, transitions
from .sources import Job

SEVERITY = {"info": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class Finding:
    source: str
    line: int
    label: str
    schedule: str
    tz: str
    transition_local: str
    kind: str        # gap | overlap
    effect: str      # skipped | shifted | doubled | once | error
    severity: str
    affected: list
    message: str

    def to_dict(self):
        return asdict(self)


def _weekday_sun0(d: datetime) -> int:
    return (d.weekday() + 1) % 7


def _hits(spec: CronSpec, tr: Transition) -> list[datetime]:
    return [w for w in tr.wall_minutes()
            if spec.matches(w.month, w.day, _weekday_sun0(w), w.hour, w.minute)]


def _classify(spec: CronSpec, kind: str, semantics: str) -> tuple[str, str]:
    """Return (effect, severity)."""
    daily_or_rarer = spec.runs_per_day_hint <= 1 or not spec.wildcard and len(spec.hours) <= 2
    if kind == "gap":
        if semantics == "vixie" and not spec.wildcard:
            return "shifted", "low"
        return "skipped", ("high" if daily_or_rarer else "medium" if not spec.wildcard else "low")
    if semantics == "vixie" and not spec.wildcard:
        return "once", "info"
    return "doubled", ("high" if daily_or_rarer else "medium" if not spec.wildcard else "low")


_TEXT = {
    "skipped": "never runs on this date: {n} scheduled minute(s) fall in the {d}-minute spring-forward gap",
    "lost": "loses {n} run(s) that fall in the {d}-minute spring-forward gap",
    "shifted": "{n} run(s) fall in the {d}-minute gap; cronie/Vixie runs them late, right after the jump",
    "doubled": "{n} run(s) fall in the {d}-minute repeated window and fire twice",
    "once": "{n} run(s) fall in the repeated window; cronie/Vixie runs fixed-time jobs once",
}


def analyze(jobs: list[Job], years: list[int], semantics: str = "wallclock",
            default_tz: str = "UTC") -> list[Finding]:
    out: list[Finding] = []
    cache: dict = {}
    for job in jobs:
        tz = job.tz or default_tz
        try:
            spec = parse(job.schedule)
        except CronError as e:
            out.append(Finding(job.source, job.line, job.label, job.schedule, tz, "", "", "error",
                               "medium", [], f"unparseable schedule: {e}"))
            continue
        for y in years:
            key = (tz, y)
            if key not in cache:
                try:
                    cache[key] = transitions(tz, y)
                except Exception as e:  # unknown zone
                    cache[key] = e
            trs = cache[key]
            if isinstance(trs, Exception):
                out.append(Finding(job.source, job.line, job.label, job.schedule, tz, "", "", "error",
                                   "medium", [], f"unknown time zone {tz!r}"))
                break
            for tr in trs:
                hits = _hits(spec, tr)
                if not hits:
                    continue
                effect, sev = _classify(spec, tr.kind, semantics)
                d = int(tr.delta.total_seconds() // 60)
                key_t = "lost" if (effect == "skipped" and spec.wildcard) else effect
                out.append(Finding(
                    job.source, job.line, job.label, job.schedule, tz,
                    tr.wall_start.strftime("%Y-%m-%d %H:%M"), tr.kind, effect, sev,
                    [h.strftime("%H:%M") for h in hits],
                    _TEXT[key_t].format(n=len(hits), d=d)))
    return out
