"""Extract (schedule, timezone, label) jobs from crontabs and Kubernetes CronJob YAML."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .cronexpr import MACROS


@dataclass
class Job:
    schedule: str
    tz: str | None
    source: str
    line: int
    label: str


_ENV = re.compile(r"^\s*(CRON_TZ|TZ)\s*=\s*['\"]?([^'\"\s]+)['\"]?\s*$")
_HINT = re.compile(r"#\s*dstcron:\s*tz\s*=\s*(\S+)")


def parse_crontab(text: str, source: str, default_tz: str | None, system: bool = False) -> list[Job]:
    jobs: list[Job] = []
    tz = default_tz
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        hint = _HINT.search(line)
        if line.startswith("#"):
            if hint:
                tz = hint.group(1)
            continue
        m = _ENV.match(line)
        if m:
            tz = m.group(2)
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
            continue  # other env assignment
        toks = line.split()
        if toks[0].startswith("@"):
            if toks[0].lower() == "@reboot":
                continue
            sched, rest = toks[0], toks[1:]
        else:
            if len(toks) < 6:
                jobs.append(Job(" ".join(toks[:5]), tz, source, n, "(no command)"))
                continue
            sched, rest = " ".join(toks[:5]), toks[5:]
        if system and rest:
            rest = rest[1:]
        cmd = " ".join(rest)
        jobs.append(Job(sched, tz, source, n, cmd[:60] or "(no command)"))
    return jobs


def parse_k8s(text: str, source: str, default_tz: str | None) -> list[Job]:
    jobs: list[Job] = []
    offset = 0
    for doc in re.split(r"(?m)^---\s*$", text):
        lines = doc.splitlines()
        if not re.search(r"(?m)^kind:\s*CronJob\s*$", doc):
            offset += len(lines) + 1
            continue
        name = re.search(r"(?m)^\s{2}name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", doc)
        sched_line, sched, tz = None, None, default_tz
        for i, l in enumerate(lines):
            m = re.match(r"^\s{2}schedule:\s*['\"]?([^'\"#]+?)['\"]?\s*(#.*)?$", l)
            if m and sched is None:
                sched, sched_line = m.group(1).strip(), i
            m = re.match(r"^\s{2}timeZone:\s*['\"]?([^'\"\s#]+)['\"]?", l)
            if m:
                tz = m.group(1)
        if sched:
            s = sched
            tzm = re.match(r"^(?:CRON_TZ|TZ)=(\S+)\s+(.*)$", s)
            if tzm:
                tz, s = tzm.group(1), tzm.group(2)
            jobs.append(Job(s, tz, source, offset + sched_line + 1,
                            f"CronJob/{name.group(1) if name else '?'}"))
        offset += len(lines) + 1
    return jobs


def parse_file(text: str, source: str, default_tz: str | None, system: bool = False) -> list[Job]:
    if re.search(r"(?m)^kind:\s*CronJob\s*$", text):
        return parse_k8s(text, source, default_tz)
    return parse_crontab(text, source, default_tz, system)


__all__ = ["Job", "parse_crontab", "parse_k8s", "parse_file", "MACROS"]
