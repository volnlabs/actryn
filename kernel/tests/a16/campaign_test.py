# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

import campaign


class CampaignTests(unittest.TestCase):
    def test_frozen_four_boots_eight_ordered_runs(self):
        self.assertEqual(campaign.ARMS, ('kernel', 'userspace', 'userspace', 'kernel'))
        root = pathlib.Path('/test/.cache/qemu/a16')
        commands = campaign.commands(root)
        self.assertEqual(len(commands), 6)  # Two excluded pilots plus four blocks.
        for block, arm in enumerate(campaign.ARMS, 1):
            command = commands[f'block{block:02d}']
            dt = command[command.index('-dtb') + 1]
            self.assertTrue(dt.endswith('protected.dtb' if arm == 'kernel' else 'raw-compact-amendment3.dtb'))

    def test_missing_or_reused_boot_history_blocks_later_block(self):
        record = {'boot': 'one', 'runner_sha256': 'sha', 'completed_runs': 2, 'campaign_sha256': 'manifest'}
        campaign.check_history(2, [record], 'two', 'sha', 'manifest')
        for rows, boot, source in (([], 'two', 'sha'), ([record], 'one', 'sha'),
                                   ([record], 'two', 'changed')):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                campaign.check_history(2, rows, boot, source, 'manifest')
        with self.assertRaises(ValueError):
            campaign.check_history(2, [record], 'two', 'sha', 'changed-manifest')

    def test_workload_failure_stays_visible_and_cannot_qualify_pilot(self):
        summary = {'planned_trials': 10, 'begun_trials': 10, 'ended_trials': 10,
                   'passed_trials': 9, 'failed_trials': 1, 'unfinished_or_unstarted_trials': 0,
                   'complete_marker': True, 'new_event_loss_in_ended_trials': 0,
                   'event_sequence_discontinuities': 0, 'reversed_clock_pairs': 0,
                   'loss_counter_saturated': False}
        self.assertFalse(campaign.successful_summary(summary))
        summary['passed_trials'] = 10; summary['failed_trials'] = 0
        self.assertTrue(campaign.successful_summary(summary))
        summary['new_event_loss_in_ended_trials'] = 1
        self.assertFalse(campaign.successful_summary(summary))

    def test_terminal_counterexamples_cannot_pass_by_setting_trial_pass(self):
        rows = [{'type': 'manifest', 'revision': 1, 'amendment': 2, 'arm': 'kernel', 'planned_trials': 10},
                {'type': 'complete', 'trials': 10, 'failures': 0}]
        for trial, scenario in enumerate(campaign.SCENARIOS):
            rows += [{'type': 'trial_begin', 'trial': trial, 'scenario': scenario},
                     {'type': 'trial_end', 'trial': trial, 'pass': True}]
            if scenario in ('normal', 'cancel'):
                rows.append({'type': 'terminal', 'trial': trial, 'state': 2, 'operation_state': 4,
                    'reason': 1 if scenario == 'normal' else 2, 'flags': 9, 'left': 0, 'right': 0,
                    'grant': 1, 'operation': trial + 1, 'stream': trial + 2, 'expected_grant': 1,
                    'expected_operation': trial + 1, 'expected_stream': trial + 2})
        campaign.qualify_trials(rows, 'kernel')
        terminal = next(row for row in rows if row['type'] == 'terminal')
        for key, value in [('reason', 2), ('state', 4), ('flags', 1), ('grant', 0), ('stream', 999), ('left', 1)]:
            original = terminal[key]; terminal[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                campaign.qualify_trials(rows, 'kernel')
            terminal[key] = original
        with self.assertRaises(ValueError):
            campaign.qualify_trials(rows, 'userspace')

    def test_delayed_start_cannot_outlive_retirement_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = str(pathlib.Path(directory) / 'actryn-a16-')
            def invoke(script, close=False):
                command = campaign.guarded('test', script, close).replace('/run/actryn-a16-', prefix)
                return subprocess.run(['sh', '-c', command], capture_output=True, timeout=10)
            self.assertEqual(invoke('true', close=True).returncode, 0)
            target = pathlib.Path(directory) / 'should-not-exist'
            self.assertNotEqual(invoke('touch ' + str(target)).returncode, 0)
            self.assertFalse(target.exists())

    def test_prerequisite_failure_never_stops_a_foreign_gateway(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(campaign, 'sha', return_value='sha'), \
                mock.patch.object(campaign, 'prerequisites', side_effect=ValueError('pilot missing')), \
                mock.patch.object(campaign, 'Remote') as remote:
            root = pathlib.Path(directory)
            with self.assertRaises(RuntimeError):
                campaign.execute(root, 'traceuserspace01', 'userspace', 0)
            remote.return_value.run.assert_not_called()
            record = json.loads((root / 'qualification/instrumentation-userspace01/attempt.json').read_text())
            self.assertEqual(record['unstarted_or_unreturned_runs'], ['traceuserspace01trace'])
            self.assertEqual(record['completed_runs'], 0)

    def test_unknown_start_is_retired_and_both_exports_attempted(self):
        names = []
        def run(command, output, name, **kwargs):
            names.append(name)
            if name == 'capture-start.log':
                raise TimeoutError('start reply lost')
            if name == 'retire.log':
                self.assertIn('.closed', command)
                self.assertIn('capture_guest5.py stop', command)
            if name.endswith('.tar.gz'):
                raise RuntimeError('no remote archive')
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(campaign.fixture_bridge, 'run') as workload:
            root = pathlib.Path(directory)
            remote = mock.Mock(); remote.run.side_effect = run
            result = campaign.one_run(root, remote, root, 'unknown', 'kernel', True)
            workload.assert_not_called()
            self.assertEqual(result['status'], 'FAILED')
            self.assertIsNone(result['cleanup_error'])
            self.assertEqual(names, ['capture-start.log', 'retire.log', 'workload.tar.gz', 'capture.tar.gz', 'kernel.log'])

    def test_workload_export_failure_does_not_discard_valid_raw_capture(self):
        capture = b'raw retained capture'
        def run(command, output, name, **kwargs):
            if name == 'workload.tar.gz':
                raise RuntimeError('workload export lost')
            if name == 'capture.tar.gz':
                files = {'capture.bin': capture,
                    'result.json': json.dumps({'module_unloaded': True, 'start_failed': False,
                        'capture_sha256': hashlib.sha256(capture).hexdigest(), 'boot_id': 'boot'}).encode(),
                    'instrumentation5.json': json.dumps({'instrumentation4_sha256': campaign.sha(campaign.HERE / 'instrumentation4.toml'),
                        'instrumentation5_sha256': campaign.sha(campaign.HERE / 'instrumentation5.toml')}).encode()}
                with tarfile.open(output / name, 'w:gz') as archive:
                    for filename, data in files.items():
                        info = tarfile.TarInfo('actryn-a16-capture-partial/' + filename); info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(campaign.fixture_bridge, 'run'), \
                mock.patch.object(campaign.dispatch, 'decode_capture', return_value={'frames': []}):
            root = pathlib.Path(directory)
            remote = mock.Mock(); remote.run.side_effect = run
            result = campaign.one_run(root, remote, root, 'partial', 'kernel', True)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual((root / 'partial/capture/capture.bin').read_bytes(), capture)
            self.assertIsNone(json.loads((root / 'partial/dispatch.json').read_text())['correlation'])
            self.assertEqual(len(result['evidence_errors']), 1)

    def test_cleanup_failure_blocks_remaining_paired_run_but_exports_evidence(self):
        names = []
        def run(command, output, name, **kwargs):
            names.append(name)
            if name == 'retire.log' or name.endswith('.tar.gz'):
                raise RuntimeError('retirement unknown or export failed')
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(campaign.fixture_bridge, 'run'):
            root = pathlib.Path(directory); remote = mock.Mock(); remote.run.side_effect = run
            with self.assertRaisesRegex(RuntimeError, 'unknown cleanup'):
                campaign.one_run(root, remote, root, 'unknowncleanup', 'kernel', True)
            self.assertIn('capture.tar.gz', names)
            self.assertTrue((root / 'unknowncleanup/FAILED').exists())


if __name__ == '__main__':
    unittest.main()
