"""Command-line interface for dstcron."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from . import __version__
from .analyze import SEVERITY, analyze
from .dst import transitions
from .sources import Job, parse_file


def _render_text(findings, show_info):
    lines = []
    for f in findings:
        if f.severity == "info" and not show_info:
            continue
        loc = f"{f.source}:{f.line}"
        if f.effect == "error":
            lines.append(f"[{f.severity.upper()}] {loc} {f.label}: {f.message}")
            continue
        lines.append(f"[{f.severity.upper()}] {loc} '{f.schedule}' ({f.tz}) {f.label}")
        lines.append(f"    {f.transition_local} {f.kind}: {f.effect} -> {f.message} "
                     f"[{', '.join(f.affected[:6])}{' ...' if len(f.affected) > 6 else ''}]")
    return "\n".join(lines) or "no DST hazards found"


def _render_md(findings, show_info):
    rows = ["| severity | where | schedule | tz | transition | effect | runs |",
            "|---|---|---|---|---|---|---|"]
    for f in findings:
        if f.severity == "info" and not show_info:
            continue
        rows.append(f"| {f.severity} | `{f.source}:{f.line}` {f.label} | `{f.schedule}` | {f.tz} | "
                    f"{f.transition_local} {f.kind} | {f.effect} | {', '.join(f.affected[:6])} |")
    return "\n".join(rows) if len(rows) > 2 else "No DST hazards found."


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dstcron", description=__doc__ or
                                "Find cron schedules that skip, shift, or double-fire across DST changes.")
    p.add_argument("paths", nargs="*", help="crontab files or Kubernetes CronJob YAML ('-' for stdin)")
    p.add_argument("-e", "--expr", action="append", default=[], help="check a single cron expression")
    p.add_argument("--tz", default=os.environ.get("TZ") or "UTC",
                   help="default IANA zone when a file sets no CRON_TZ/timeZone (default: $TZ or UTC)")
    p.add_argument("--year", type=int, default=date.today().year)
    p.add_argument("--years", type=int, default=1, help="number of years to scan (default 1)")
    p.add_argument("--semantics", choices=["wallclock", "vixie"], default="wallclock",
                   help="wallclock: naive local-time matching; vixie: cronie's fixed-time catch-up rules")
    p.add_argument("--system", action="store_true", help="crontab has a user column (/etc/crontab, cron.d)")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--all", action="store_true", help="also show info-level findings")
    p.add_argument("--fail-on", choices=["low", "medium", "high"], help="exit 1 at or above this severity")
    p.add_argument("--transitions", action="store_true", help="just list the zone's DST transitions")
    p.add_argument("--version", action="version", version=f"dstcron {__version__}")
    a = p.parse_args(argv)
    years = [a.year + i for i in range(a.years)]

    if a.transitions:
        for y in years:
            for tr in transitions(a.tz, y):
                print(f"{tr.wall_start:%Y-%m-%d %H:%M} {tr.kind} {int(tr.delta.total_seconds()//60)}min "
                      f"({a.tz})")
        return 0

    jobs: list[Job] = [Job(e, None, "<expr>", i + 1, "") for i, e in enumerate(a.expr)]
    for path in a.paths:
        text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        jobs += parse_file(text, path, None, a.system)
    if not jobs:
        p.error("give at least one path or --expr")

    findings = analyze(jobs, years, a.semantics, a.tz)
    if a.format == "json":
        print(json.dumps([f.to_dict() for f in findings], indent=2))
    elif a.format == "md":
        print(_render_md(findings, a.all))
    else:
        print(_render_text(findings, a.all))
    if a.fail_on and any(SEVERITY[f.severity] >= SEVERITY[a.fail_on] for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
