import unittest

import pilot


class PilotGateTests(unittest.TestCase):
    def rows(self):
        rows = [{'type': 'manifest', 'revision': 1, 'arm': 'userspace', 'planned_trials': 10}]
        for trial, scenario in enumerate(pilot.SCENARIOS):
            rows += [{'type': 'trial_begin', 'trial': trial, 'scenario': scenario, 'lost_baseline': 0},
                     {'type': 'trial_end', 'trial': trial, 'pass': True, 'lost_final': 0}]
        return rows + [{'type': 'complete', 'trials': 10, 'failures': 0}]

    def test_all_fixed_trials_required(self):
        pilot.qualify_workload(self.rows())
        rows = self.rows()
        del rows[1:3]
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)

    def test_failed_trial_cannot_be_hidden_by_complete_marker(self):
        rows = self.rows()
        rows[2]['pass'] = False
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)

    def test_wrong_order_or_missing_completion_blocks_comparison(self):
        rows = self.rows()
        rows[1]['scenario'] = 'cancel'
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)
        with self.assertRaises(ValueError):
            pilot.qualify_workload(self.rows()[:-1])

    def test_event_loss_blocks_qualification(self):
        rows = self.rows()
        rows[2]['lost_final'] = 1
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)


if __name__ == '__main__':
    unittest.main()
