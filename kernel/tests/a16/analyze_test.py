import unittest
import analyze


class AnalyzerTests(unittest.TestCase):
    def manifest(self):
        return {"type": "manifest", "revision": 1, "planned_trials": 10, "arm": "kernel", "boot": "test"}

    def test_failed_and_missing_trials_stay_in_denominator(self):
        rows = [self.manifest(), {"type": "trial_begin", "trial": 0, "lost_baseline": 8},
                {"type": "trial_end", "trial": 0, "pass": False, "lost_final": 10}]
        r = analyze.summarize(rows)
        self.assertEqual((r["planned_trials"], r["failed_trials"], r["unfinished_or_unstarted_trials"]), (10, 1, 9))
        self.assertEqual(r["new_event_loss_in_ended_trials"], 2)
        self.assertFalse(r["event_loss_complete"])
        self.assertFalse(r["complete_marker"])

    def test_deadline_equality_is_not_timely(self):
        rows = [self.manifest(), {"type": "request", "trial": 0, "opcode": 8, "before_ns": 10,
                "after_ns": 12, "rc": 0, "operation": 1, "sequence": 1, "deadline_ns": 30},
                {"type": "event", "trial": 0, "kind": 0x20008, "captured_ns": 30,
                 "operation": 1, "sample": 1, "sequence": 2}]
        r = analyze.summarize(rows)
        self.assertEqual((r["sample_requests"], r["timely_applied"], r["no_timely_applied"]), (1, 0, 1))
        self.assertEqual(r["metrics"]["admission"]["median_ns"], 2)
        self.assertEqual(r["metrics"]["sample_to_applied"]["count"], 0)

    def test_duplicate_trial_is_rejected(self):
        r = {"type": "trial_begin", "trial": 0, "lost_baseline": 0}
        with self.assertRaises(ValueError):
            analyze.summarize([self.manifest(), r, r])

    def test_maximum_remains_observed(self):
        self.assertEqual(analyze.distribution([9, 1, 3]),
                         {"count": 3, "median_ns": 3, "p95_ns": 9, "observed_max_ns": 9})

    def test_observation_age_uses_acquisition_not_ioctl_return(self):
        rows = [self.manifest(), {"type": "request", "trial": 0, "opcode": 6, "before_ns": 7,
                "after_ns": 9, "rc": 0, "observation": 2, "acquired_earliest_ns": 3},
                {"type": "request", "trial": 0, "opcode": 8, "before_ns": 10, "after_ns": 12,
                 "rc": 0, "operation": 1, "sequence": 1, "deadline_ns": 30, "observation": 2}]
        self.assertEqual(analyze.summarize(rows)["metrics"]["observation_age_at_sample"]["median_ns"], 7)

    def test_loss_regression_is_not_reported_as_zero(self):
        rows = [self.manifest(), {"type": "trial_begin", "trial": 0, "lost_baseline": 8},
                {"type": "trial_end", "trial": 0, "pass": False, "lost_final": 7}]
        with self.assertRaises(ValueError):
            analyze.summarize(rows)

    def test_baseline_cpu_is_separate(self):
        rows = [self.manifest(), {"type": "baseline_cpu", "phase": "begin", "pid": 8,
                "user_ticks": 10, "system_ticks": 30}, {"type": "baseline_cpu", "phase": "end",
                "pid": 8, "user_ticks": 12, "system_ticks": 35}]
        r = analyze.summarize(rows)
        self.assertIsNone(r["cpu"])
        self.assertEqual(r["baseline_process_cpu_ticks"], {"user_ticks": 2, "system_ticks": 5})


if __name__ == "__main__":
    unittest.main()
