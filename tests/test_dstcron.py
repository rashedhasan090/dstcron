import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from dstcron.analyze import analyze
from dstcron.cli import main
from dstcron.cronexpr import CronError, parse
from dstcron.dst import transitions
from dstcron.sources import Job, parse_crontab, parse_k8s


def run(*argv):
    buf = StringIO()
    with redirect_stdout(buf):
        code = main(list(argv))
    return code, buf.getvalue()


class CronParse(unittest.TestCase):
    def test_fields(self):
        s = parse("*/15 9-17 * jan-mar mon-fri")
        self.assertEqual(sorted(s.minutes), [0, 15, 30, 45])
        self.assertEqual(sorted(s.months), [1, 2, 3])
        self.assertEqual(sorted(s.dows), [1, 2, 3, 4, 5])
        self.assertTrue(s.wildcard)

    def test_sunday_seven_and_macro(self):
        self.assertEqual(parse("0 0 * * 7").dows, frozenset({0}))
        self.assertEqual(sorted(parse("@daily").hours), [0])

    def test_dom_dow_or_rule(self):
        s = parse("0 0 1 * 1")
        self.assertTrue(s.matches(5, 1, 3, 0, 0))   # 1st, a Wednesday
        self.assertTrue(s.matches(5, 4, 1, 0, 0))   # a Monday
        self.assertFalse(s.matches(5, 5, 2, 0, 0))

    def test_errors(self):
        for bad in ["* * * *", "60 * * * *", "*/0 * * * *", "@reboots"]:
            with self.assertRaises(CronError):
                parse(bad)


class Transitions(unittest.TestCase):
    def test_chicago_2026(self):
        trs = transitions("America/Chicago", 2026)
        self.assertEqual([(t.kind, t.wall_start.strftime("%m-%d %H:%M")) for t in trs],
                         [("gap", "03-08 02:00"), ("overlap", "11-01 01:00")])

    def test_utc_and_half_hour_zone(self):
        self.assertEqual(transitions("UTC", 2026), [])
        lh = transitions("Australia/Lord_Howe", 2026)
        self.assertTrue(lh and all(t.delta.total_seconds() == 1800 for t in lh))


class Analysis(unittest.TestCase):
    def one(self, expr, tz="America/Chicago", sem="wallclock"):
        return analyze([Job(expr, tz, "x", 1, "j")], [2026], sem)

    def test_daily_in_gap_is_high_skip(self):
        f = self.one("30 2 * * *")
        self.assertEqual([(x.kind, x.effect, x.severity) for x in f], [("gap", "skipped", "high")])

    def test_daily_in_overlap_doubles(self):
        f = self.one("15 1 * * *")
        self.assertEqual([(x.kind, x.effect, x.severity) for x in f], [("overlap", "doubled", "high")])

    def test_vixie_semantics(self):
        f = self.one("30 2 * * *", sem="vixie")
        self.assertEqual(f[0].effect, "shifted")
        f = self.one("15 1 * * *", sem="vixie")
        self.assertEqual((f[0].effect, f[0].severity), ("once", "info"))
        f = self.one("*/30 * * * *", sem="vixie")
        self.assertEqual({x.effect for x in f}, {"skipped", "doubled"})

    def test_safe_schedules(self):
        self.assertEqual(self.one("0 9 * * *"), [])
        self.assertEqual(self.one("30 2 * * *", tz="UTC"), [])
        self.assertEqual(self.one("30 2 * * 1-5"), [])  # DST changes land on Sunday

    def test_bad_inputs(self):
        self.assertEqual(self.one("nope")[0].effect, "error")
        self.assertIn("unknown time zone", self.one("0 2 * * *", tz="Mars/Base")[0].message)


class Sources(unittest.TestCase):
    def test_crontab_tz_switch(self):
        jobs = parse_crontab("CRON_TZ=Europe/Paris\n0 2 * * * a\nTZ=UTC\n@hourly b\n@reboot c\n",
                             "ct", None)
        self.assertEqual([(j.schedule, j.tz) for j in jobs],
                         [("0 2 * * *", "Europe/Paris"), ("@hourly", "UTC")])

    def test_system_crontab_user_column(self):
        jobs = parse_crontab("0 2 * * * root /bin/backup\n", "ct", "UTC", system=True)
        self.assertEqual(jobs[0].label, "/bin/backup")

    def test_k8s(self):
        y = ("kind: CronJob\nmetadata:\n  name: a\nspec:\n  schedule: \"30 2 * * *\"\n"
             "  timeZone: Europe/Berlin\n---\nkind: Deployment\n")
        jobs = parse_k8s(y, "k.yaml", None)
        self.assertEqual((jobs[0].schedule, jobs[0].tz, jobs[0].label, jobs[0].line),
                         ("30 2 * * *", "Europe/Berlin", "CronJob/a", 5))


class Cli(unittest.TestCase):
    def test_json_and_fail_on(self):
        code, out = run("-e", "30 2 * * *", "--tz", "America/Chicago", "--year", "2026",
                        "--format", "json", "--fail-on", "high")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["effect"], "skipped")

    def test_clean_and_md(self):
        code, out = run("-e", "0 12 * * *", "--tz", "America/Chicago", "--format", "md", "--fail-on", "low")
        self.assertEqual((code, out.strip()), (0, "No DST hazards found."))

    def test_transitions_listing(self):
        code, out = run("--transitions", "--tz", "Europe/London", "--year", "2026")
        self.assertIn("2026-03-29 01:00 gap 60min", out)


if __name__ == "__main__":
    unittest.main()
