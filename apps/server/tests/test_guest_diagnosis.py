import copy
import errno
import json
import os
import stat
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import guest_capacity as common
import guest_diagnosis as diagnosis
from test_guest_capacity import complete_export, rehash


def node():
    return {'mode': stat.S_IFCHR | 0o666, 'uid': 0, 'gid': 0, 'nlink': 1,
            'major': 1, 'minor': 7, 'ino': 123, 'dev': 456}


def trace_fixture():
    binding = complete_export()[3]
    parent = binding['snapshot']['pid']
    child = parent + 1
    events = [{'kind': 4, 'pid': parent, 'tid': parent, 'related_pid': parent,
               'syscall': -1, 'result': 0, 'classification': 'observed'},
              {'kind': 3, 'pid': parent, 'tid': parent, 'related_pid': child,
               'syscall': -1, 'result': 0, 'classification': 'observed'}]
    for result in (3, -errno.ENOENT, -errno.EPERM):
        events.extend([{'kind': 1, 'pid': child, 'tid': child, 'related_pid': 0,
                        'syscall': 257, 'result': 0, 'classification': 'observed'},
                       {'kind': 2, 'pid': child, 'tid': child, 'related_pid': 0,
                        'syscall': 257, 'result': result,
                        'classification': 'access_failed' if result < 0 else 'observed'}])
    events.append({'kind': 5, 'pid': child, 'tid': child, 'related_pid': 0,
                   'syscall': -1, 'result': 0, 'classification': 'observed'})
    events.append({'kind': 5, 'pid': parent, 'tid': parent, 'related_pid': 0,
                   'syscall': -1, 'result': 0, 'classification': 'observed'})
    rows = []
    for sequence, event in enumerate(events, 1):
        event.update(sequence=sequence, monotonic_ns=100 + sequence,
                     cgroup_id=binding['cgroup_id'], origin='linux.tracepoint', comm='agent')
        rows.append({'attempt_id': 'b'*32, 'boot_id': binding['boot_id'],
                     'collector_epoch': binding['observer']['collector_epoch'], 'event': event})
    return binding, rows


class DiagnosisTests(unittest.TestCase):
    def test_existing_cancelled_export_stays_strict(self):
        args = list(complete_export())
        for item in args[0]['artifacts']:
            if item['name'] == 'attempt': item['content']['outcome'] = 'exited:137'
            if item['name'] == 'broker': item['content']['attempt_outcome'] = 'exited:137'
        args[4]['attempt']['outcome'] = 'exited:137'
        rehash(args[0])
        with self.assertRaises(AssertionError): common.validate_export(*args)
        common.validate_export(*args, expected_outcome='exited:137')

    def test_oom_requires_actual_limit_events_not_just_sigkill(self):
        initial = 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n'
        final = 'low 0\nhigh 0\nmax 24\noom 1\noom_kill 1\n'
        diagnosis.validate_oom(initial, final, 'exited:137', '268435456', '0')
        for bad in (initial, final.replace('oom_kill 1', 'oom_kill 0'),
                    final.replace('oom 1', 'oom 0'), final.replace('max 24', 'max 0')):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                diagnosis.validate_oom(initial, bad, 'exited:137', '268435456', '0')
        for outcome, limit, swap in [('cancelled', '268435456', '0'),
                                     ('exited:0', '268435456', '0'),
                                     ('exited:137', '536870912', '0'),
                                     ('exited:137', '268435456', 'max')]:
            with self.subTest(outcome=outcome, limit=limit, swap=swap), self.assertRaises(AssertionError):
                diagnosis.validate_oom(initial, final, outcome, limit, swap)
        with self.assertRaises(AssertionError):
            diagnosis.validate_oom(final, final, 'exited:137', '268435456', '0')
        with self.assertRaises(AssertionError):
            diagnosis.validate_oom(initial, final + 'oom_kill 0\n', 'exited:137', '268435456', '0')

    def test_existing_char_node_is_not_namespace_or_dac_failure(self):
        diagnosis.validate_node(node())
        for field, value in [('mode', stat.S_IFREG | 0o666), ('mode', stat.S_IFCHR | 0o600),
                             ('minor', 3), ('major', 8), ('uid', 65532), ('nlink', 2)]:
            bad = node(); bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                diagnosis.validate_node(bad)

    def test_kernel_sequence_binds_child_and_distinguishes_failures(self):
        binding, rows = trace_fixture()
        result = diagnosis.validate_trace(rows, 'b'*32, binding)
        self.assertEqual(result['results'], [3, -2, -1])
        self.assertEqual(result['classification'], 'access_failed_not_policy_origin_event')
        for index, field, value in [(7, 'result', -2), (7, 'pid', 999),
                                    (7, 'classification', 'policy_denied'),
                                    (7, 'cgroup_id', 999), (7, 'sequence', 4)]:
            bad = copy.deepcopy(rows); bad[index]['event'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                diagnosis.validate_trace(bad, 'b'*32, binding)
        reordered = [rows[1], rows[0], *rows[2:]]
        self.assertEqual(diagnosis.validate_trace(reordered, 'b'*32, binding), result)
        with self.assertRaises(AssertionError): diagnosis.validate_trace(rows, 'b'*32, binding, len(rows)+1)
        for bad in (rows[:-1], rows[:3] + rows[5:], rows + rows[-1:]):
            with self.subTest(length=len(bad)), self.assertRaises(AssertionError):
                diagnosis.validate_trace(bad, 'b'*32, binding)

    def test_trace_ignores_parent_tgid_thread_exits_around_agent_exec(self):
        binding, rows = trace_fixture()
        parent = binding['snapshot']['pid']
        thread_exits = []
        for offset in range(2, 8):
            thread = copy.deepcopy(rows[-1])
            thread['event']['tid'] = parent + offset
            thread_exits.append(thread)
        # The runtime can exec and retire its INIT threads before the agent's
        # final exec; a later non-leader exit is not the agent leader's exit.
        rows = [copy.deepcopy(rows[0]), *thread_exits[:5], rows[0],
                thread_exits[5], *rows[1:]]
        for sequence, row in enumerate(rows, 1):
            row['event'].update(sequence=sequence, monotonic_ns=100 + sequence)
        proof = diagnosis.validate_trace(rows, 'b'*32, binding, len(rows))
        self.assertEqual(proof['child_host_pid'], parent + 1)
        self.assertEqual(proof['results'], [3, -2, -1])

    def test_trace_requires_parent_leader_exit_even_with_late_thread_exit(self):
        binding, rows = trace_fixture()
        rows[-1]['event']['tid'] = binding['snapshot']['pid'] + 2
        with self.assertRaises(AssertionError):
            diagnosis.validate_trace(rows, 'b'*32, binding)

    def test_trace_requires_one_parent_leader_exit_after_exec_and_child(self):
        binding, rows = trace_fixture()
        cases = {'missing': rows[:-1],
                 'duplicate': rows + [copy.deepcopy(rows[-1])],
                 'before_exec': [rows[-1], *rows[:-1]],
                 'before_child_exit': [*rows[:-2], rows[-1], rows[-2]]}
        for label, events in cases.items():
            events = copy.deepcopy(events)
            for sequence, row in enumerate(events, 1):
                row['event'].update(sequence=sequence, monotonic_ns=100 + sequence)
            with self.subTest(label=label), self.assertRaises(AssertionError):
                diagnosis.validate_trace(events, 'b'*32, binding)

    def test_old_rows_and_no_work_are_preserved_in_both_stores(self):
        old = {name: {table: [] for table in diagnosis.TABLES} for name in ('launcher', 'broker')}
        for name, tables in old.items():
            tables['attempts'] = [{'id': name, 'state': 'reaped', 'outcome': 'cancelled'}]
            tables['runtime_evidence'] = [{'attempt_id': name, 'data': 'old-evidence'}]
        after = copy.deepcopy(old)
        for table in after.values():
            table['attempts'].append({'id': 'b'*32, 'state': 'reaped', 'outcome': 'exited:137'})
        after['launcher']['runtime_evidence'].append({'attempt_id': 'b'*32, 'data': 'new-evidence'})
        diagnosis.validate_history(old, after, 'b'*32)
        for name in after:
            bad = copy.deepcopy(after); bad[name]['attempts'][0]['outcome'] = 'unknown'
            with self.assertRaises(AssertionError): diagnosis.validate_history(old, bad, 'b'*32)
        bad = copy.deepcopy(after); bad['broker']['calls'] = [{'attempt_id': 'b'*32, 'state': 'unknown'}]
        with self.assertRaises(AssertionError): diagnosis.validate_history(old, bad, 'b'*32)
        bad = copy.deepcopy(after); bad['launcher']['runtime_evidence'] = bad['launcher']['runtime_evidence'][1:]
        with self.assertRaises(AssertionError): diagnosis.validate_history(old, bad, 'b'*32)

    def test_real_sqlite_snapshot_preserves_full_rows_and_empty_launcher_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {name: Path(directory)/name for name in ('launcher', 'broker')}
            for name, path in paths.items():
                with sqlite3.connect(path) as db:
                    db.execute('CREATE TABLE attempts(id TEXT,state TEXT,outcome TEXT)')
                    db.execute("INSERT INTO attempts VALUES('old','reaped','cancelled')")
                    db.execute('CREATE TABLE calls(attempt_id TEXT,output BLOB)')
                    if name == 'broker': db.execute("INSERT INTO calls VALUES('old',?)", (b'\x00\xff',))
                    for table in diagnosis.TABLES[2:]: db.execute(f'CREATE TABLE {table}(attempt_id TEXT,data TEXT)')
                db.close()
                before = path.read_bytes()
                got = diagnosis.snapshot({name: path})[name]
                self.assertEqual(got['attempts'], [{'id': 'old', 'state': 'reaped', 'outcome': 'cancelled'}])
                self.assertEqual(got['calls'], [] if name == 'launcher' else
                                 [{'attempt_id': 'old', 'output': {'blob_hex': '00ff'}}])
                self.assertEqual(got['robot_requests'], [])
                self.assertEqual(path.read_bytes(), before)

    def test_cleanup_never_repeats_cancel_after_unknown_reply(self):
        run = diagnosis.Campaign(None, 'sha256:' + 'a'*64)
        run.known = ['b'*32]
        records = []
        with patch.object(run, 'record', side_effect=lambda *args: records.append(args)), \
                patch.object(run, 'status', return_value={'attempt': {'state': 'running'}}), \
                patch.object(run, 'cli', side_effect=TimeoutError('lost reply')) as cli, \
                patch.object(run, 'retired'):
            run.cleanup_failure()
            run.cleanup_failure()
        self.assertEqual(cli.call_count, 1)
        self.assertTrue(any(label == 'cleanup-unconfirmed' for label, _ in records))

    def test_prepared_pid_guard_checks_actual_exit_start_and_cgroup(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.2)'])
        fd = os.pidfd_open(process.pid)
        try:
            proc = Path('/proc', str(process.pid))
            snapshot = {'pid': process.pid,
                        'start_ticks': int((proc/'stat').read_text().rsplit(')', 1)[1].split()[19]),
                        'cgroup': (proc/'cgroup').read_text().strip().removeprefix('0::')}
            diagnosis.task_alive(fd, snapshot)
            for key, value in [('start_ticks', snapshot['start_ticks'] + 1), ('cgroup', '/wrong')]:
                with self.subTest(key=key), self.assertRaises(AssertionError):
                    diagnosis.task_alive(fd, {**snapshot, key: value})
            process.wait(timeout=2)
            with self.assertRaises(AssertionError): diagnosis.task_alive(fd, snapshot)
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=2)
            os.close(fd)

    def test_agent_stages_require_probe_success_before_memory(self):
        rows = [{'event': 'device_probe', 'results': [3, -2, -1], 'major': 1, 'minor': 7, 'mode': 438},
                {'event': 'memory_begin', 'bytes': 536870912, 'page_bytes': 4096}]
        def logs(values): return {'stdout': b''.join(json.dumps(v).encode()+b'\n' for v in values), 'stderr': b''}
        self.assertEqual(diagnosis.validate_agent(logs(rows), {'calls': []}), [3, -2, -1])
        for bad in (rows[:1], list(reversed(rows)), rows + rows[:1]):
            with self.assertRaises((AssertionError, KeyError)):
                diagnosis.validate_agent(logs(bad), {'calls': []})
        with self.assertRaises(AssertionError): diagnosis.validate_agent(logs(rows), {'calls': [{'state': 'unknown'}]})


if __name__ == '__main__': unittest.main()
