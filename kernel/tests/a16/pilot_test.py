import unittest
import copy
import pathlib
import tempfile
import os
import subprocess

import pilot


class PilotGateTests(unittest.TestCase):
    def test_unknown_start_stops_owned_unit_without_retry(self):
        calls = []
        def remote(command, filename):
            calls.append(filename)
            if filename == 'gateway-start.log':
                raise TimeoutError('unit created but SSH reply lost')
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(TimeoutError):
                with pilot.gateway_session(remote, pathlib.Path(path)):
                    self.fail('unknown startup must not enter workload')
        self.assertEqual(calls, ['gateway-start.log', 'gateway-final.log'])

    def test_delayed_start_cannot_overtake_completed_cleanup(self):
        commands = []
        with tempfile.TemporaryDirectory() as path:
            root = pathlib.Path(path)
            with pilot.gateway_session(lambda command, name: commands.append(command), root):
                pass
            for name, body in [('systemd-run', 'echo started >> "$A16_STARTED"'),
                               ('systemctl', '[ "$1" != is-active ]'), ('journalctl', 'exit 0')]:
                script = root / name
                script.write_text('#!/bin/sh\n' + body + '\n')
                script.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], A16_STARTED=str(root / 'started'))
            run = lambda command: subprocess.run(command.replace('/run/actryn-a16-pilot01', str(root / 'pilot01')),
                                                  shell=True, env=env, capture_output=True, timeout=3)
            self.assertEqual(run(commands[1]).returncode, 0)
            self.assertNotEqual(run(commands[0]).returncode, 0)
            self.assertFalse((root / 'started').exists())

    def rows(self):
        rows = [{'type': 'manifest', 'revision': 1, 'amendment': 2, 'arm': 'userspace', 'planned_trials': 10}]
        for trial, scenario in enumerate(pilot.SCENARIOS):
            rows += [{'type': 'trial_begin', 'trial': trial, 'scenario': scenario, 'lost_baseline': 0}]
            if scenario in ('normal', 'cancel'):
                rows += [{'type': 'terminal', 'trial': trial, 'state': 2, 'operation_state': 4,
                          'reason': 1 if scenario == 'normal' else 2, 'flags': 9, 'left': 0, 'right': 0,
                          'grant': 3, 'expected_grant': 3, 'operation': 4, 'expected_operation': 4,
                          'stream': 5, 'expected_stream': 5}]
            rows += [{'type': 'trial_end', 'trial': trial, 'pass': True, 'lost_final': 0}]
        return rows + [{'type': 'complete', 'trials': 10, 'failures': 0}]

    def test_all_fixed_trials_required(self):
        pilot.qualify_workload(self.rows())
        rows = self.rows()
        del rows[1:3]
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)

    def test_failed_trial_cannot_be_hidden_by_complete_marker(self):
        rows = self.rows()
        next(r for r in rows if r['type'] == 'trial_end')['pass'] = False
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
        next(r for r in rows if r['type'] == 'trial_end')['lost_final'] = 1
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)

    def test_wrong_terminal_reason_or_lost_grant_blocks_qualification(self):
        for field, value in [('reason', 2), ('flags', 1), ('left', 1), ('right', -1),
                             ('grant', 4), ('operation', 5), ('stream', 6)]:
            rows = copy.deepcopy(self.rows())
            next(r for r in rows if r['type'] == 'terminal')[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                pilot.qualify_workload(rows)
        rows = self.rows()
        next(r for r in rows if r['type'] == 'terminal' and r['trial'] == 1)['reason'] = 1
        with self.assertRaises(ValueError):
            pilot.qualify_workload(rows)
        with self.assertRaises(ValueError):
            pilot.qualify_workload([r for r in self.rows() if r['type'] != 'terminal'])


if __name__ == '__main__':
    unittest.main()
