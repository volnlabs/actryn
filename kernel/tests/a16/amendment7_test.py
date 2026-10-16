# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import tempfile
import types
import unittest
from unittest import mock
import amendment7


class Derivation7Tests(unittest.TestCase):
    def test_only_six_frozen_derivatives_change_and_all_originals_stay_intact(self):
        before = {p: p.read_bytes() for p in amendment7.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        files, changes = amendment7.sources()
        self.assertEqual(set(changes), {'workload.c', 'campaign.py', 'capture/prefix.h',
                         'capture/actryn_a16_capture.c', 'dispatch.py', 'capture_guest.py'})
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        self.assertEqual(files['engine.h'], (amendment7.HERE / 'engine.h').read_bytes())
        self.assertEqual(files['../../actryn_wire.c'], (amendment7.HERE / '../../actryn_wire.c').read_bytes())

    def test_schedule_count_and_deadline_literals_remain_identical(self):
        old = (amendment7.HERE / 'workload.c').read_text(); new = amendment7.workload(old)
        for fragment in ('for(unsigned i=1;i<=10;i++)', 'start+(i-1)*100*A16_MS',
                         'a16_now()+15000*A16_MS', 'a16_now()+5000*A16_MS',
                         'a16_now()+400*A16_MS', 'a16_now()+150*A16_MS',
                         'a16_now()+1500*A16_MS', 'now+900*A16_MS', 'alarm(10)',
                         'if(i==5 &&', 'control("delay 600000000")'):
            self.assertEqual(old.count(fragment), new.count(fragment), fragment)
        self.assertIn('start=wait_first7(admin,events);', new)
        self.assertLess(new.index('first7_expect(&first7,&r)'), new.index('r.opcode=ACTRYN_START'))
        self.assertIn('first7.enabled=false; return now;', new)
        self.assertLess(new.index('v.status.events_lost,bytes);'), new.index('first7_event(&first7,&v)'))

    def test_new_labels_and_paths_preserve_all_failed_inputs(self):
        new = amendment7.campaign((amendment7.HERE / 'campaign.py').read_text())
        for fragment in ('tracekernel07', 'traceuserspace07', 'block7b', 'comparison7',
                         "'instrumentation-' + arm + '07'", 'module16-loaded.log',
                         'campaign6.verify_acceptance', 'first_sample7.qualify(rows)'):
            self.assertIn(fragment, new)
        self.assertNotIn('tracekernel01', new)
        for fragment in ('timeout --kill-after=2 55', 'control.settimeout(2)', 'flock -w 5',
                         "if not block:\n            raise RuntimeError('instrumentation pilot failed; comparison blocked')"):
            self.assertIn(fragment, new)

    def test_new_directory_only_and_derived_diff_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'source7'
            record = amendment7.derive(output)
            self.assertEqual(record['status'], 'SOURCE_ONLY; NOT_FROZEN_FOR_EXECUTION')
            self.assertIn('frozen/workload.c', record['changes']['workload.c']['diff'])
            with self.assertRaises(FileExistsError):
                amendment7.derive(output)

    def test_changed_expected_text_is_refused(self):
        with self.assertRaises(ValueError):
            amendment7.workload((amendment7.HERE / 'workload.c').read_text().replace('start=a16_now();', 'start=0;'))

    def test_environment_verifies_original_source_tree_and_restores_on_failure(self):
        module = types.ModuleType('derived_campaign7'); module.__file__ = str(amendment7.HERE / 'campaign.py')
        exec(compile(amendment7.campaign((amendment7.HERE / 'campaign.py').read_text()), module.__file__, 'exec'), module.__dict__)
        root = pathlib.Path('/example/repository/.cache/qemu/a16')
        old = module.environment3.HERE
        def inspect(directory):
            self.assertEqual(directory, root)
            self.assertEqual(module.environment3.HERE, pathlib.Path('/example/repository/kernel/tests/a16'))
            raise ValueError('retained original-source failure')
        with mock.patch.object(module, 'verify_campaign_inputs'), \
                mock.patch.object(module.campaign6, 'verify_acceptance'), \
                mock.patch.object(module.environment3, 'verify', side_effect=inspect):
            with self.assertRaisesRegex(ValueError, 'retained original-source failure'):
                module.prerequisites(root, 0)
        self.assertEqual(module.environment3.HERE, old)


if __name__ == '__main__':
    unittest.main()
