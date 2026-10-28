# dstcron

Find cron schedules that silently **skip**, **shift**, or **double-fire** when a time zone changes clocks for daylight saving time.

A job at `30 2 * * *` in `America/Chicago` has no 2:30 AM to run at on the second Sunday of March, and a job at `15 1 * * *` sees 1:15 AM twice on the first Sunday of November. Whether that means a lost nightly backup, a late run, or a double-charged invoice batch depends on the scheduler. dstcron computes the real transitions for each job's zone and tells you exactly which runs are at risk, before the weekend it happens.

## What's novel

Existing cron tools explain an expression or list its next run times. dstcron instead works backwards from the zone's actual DST transitions (via the IANA tz database in Python's `zoneinfo`) and checks every wall-clock minute that does not exist or exists twice against every job:

- Reads **per-job zones**: `CRON_TZ=` / `TZ=` lines in crontabs, Kubernetes CronJob `spec.timeZone`, and `CRON_TZ=` prefixes inside a CronJob schedule.
- Models **two scheduler semantics**. `wallclock` is naive local-time matching (gap minutes are skipped, repeated minutes fire twice), which is how many app-level schedulers behave. `vixie` follows the rules documented in the cronie/Vixie `cron(8)` man page: fixed-time jobs in a skipped hour run right after the jump, fixed-time jobs in a repeated hour run once, and wildcard jobs follow the new clock.
- Grades severity by how much it hurts. A daily or weekly job that never runs (or runs twice) is high; a `*/20` poller losing three runs is low.
- Handles non-hour shifts, such as `Australia/Lord_Howe`'s 30-minute DST, and multi-year scans.
- Stdlib only, offline, CI-friendly (`--fail-on`, JSON and Markdown output).

## Install

```bash
pip install git+https://github.com/rashedhasan090/dstcron
# or, from a clone, no install needed:
python3 -m dstcron --help
```

Requires Python 3.9+ with tz data (on minimal images, `pip install tzdata`).

## Usage

```bash
dstcron /etc/crontab --system                      # system crontab with a user column
crontab -l | dstcron - --tz America/Chicago        # default zone when no CRON_TZ is set
dstcron k8s/*.yaml --format md --fail-on high      # CronJob manifests in CI
dstcron -e "30 2 * * *" --tz Europe/Berlin --years 3
dstcron examples/crontab --semantics vixie --all   # what cronie will actually do
dstcron --transitions --tz America/Chicago         # list this year's DST changes
```

## Demo

`examples/crontab` and `examples/cronjobs.yaml` hold a few realistic jobs:

```text
$ dstcron examples/crontab examples/cronjobs.yaml --year 2026
[HIGH] examples/crontab:3 '30 2 * * *' (America/Chicago) /usr/local/bin/nightly-backup.sh
    2026-03-08 02:00 gap: skipped -> never runs on this date: 1 scheduled minute(s) fall in the 60-minute spring-forward gap [02:30]
[HIGH] examples/crontab:4 '15 1 * * *' (America/Chicago) /usr/local/bin/rotate-invoices.sh
    2026-11-01 01:00 overlap: doubled -> 1 run(s) fall in the 60-minute repeated window and fire twice [01:15]
[LOW] examples/crontab:5 '*/20 * * * *' (America/Chicago) /usr/local/bin/poll-queue.sh
    2026-03-08 02:00 gap: skipped -> loses 3 run(s) that fall in the 60-minute spring-forward gap [02:00, 02:20, 02:40]
[LOW] examples/crontab:5 '*/20 * * * *' (America/Chicago) /usr/local/bin/poll-queue.sh
    2026-11-01 01:00 overlap: doubled -> 3 run(s) fall in the 60-minute repeated window and fire twice [01:00, 01:20, 01:40]
[HIGH] examples/crontab:8 '0 1 * * 0' (Europe/London) /usr/local/bin/weekly-report.sh
    2026-03-29 01:00 gap: skipped -> never runs on this date: 1 scheduled minute(s) fall in the 60-minute spring-forward gap [01:00]
[HIGH] examples/crontab:8 '0 1 * * 0' (Europe/London) /usr/local/bin/weekly-report.sh
    2026-10-25 01:00 overlap: doubled -> 1 run(s) fall in the 60-minute repeated window and fire twice [01:00]
[HIGH] examples/cronjobs.yaml:6 '30 2 * * *' (America/New_York) CronJob/billing-close
    2026-03-08 02:00 gap: skipped -> never runs on this date: 1 scheduled minute(s) fall in the 60-minute spring-forward gap [02:30]
```

The `0 9 * * 1-5` standup reminder, the `CRON_TZ=UTC` job, and the 6 AM New York `cache-warm` CronJob are correctly left alone.

## Fixes it nudges you toward

Move fixed-time jobs out of the 1 AM to 3 AM local window, schedule in UTC, or make the job idempotent and guarded against overlapping runs.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
