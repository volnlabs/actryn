import contextlib
import copy
import hashlib
import json
import os
import socket
import socketserver
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import guest_robot_debit as campaign
from debit_gate import ConnectionGate


def fixture(*, active=False, crashed=False):
    attempt, binding = 'a' * 32, {'attempt_id': 'a' * 32, 'namespace': 'b' * 32}
    handle = {'attempt': attempt, 'namespace': 'b' * 32, 'key': 'c' * 64}
    observer = {'ready': True, 'lost': 0, 'collector_epoch': 'original-epoch',
                'coverage': list(campaign.common.REQUIRED_COVERAGE)}
    intent = {'request_key': 'preview-1', 'handle': handle, 'robot_epoch': 'd' * 32,
              'observation_digest': 'sha256:' + 'e' * 64, 'proposal_digest': 'sha256:' + 'f' * 64,
              'artifact_digest': 'sha256:' + '1' * 64,
              'runtime_binding': {'boot_id': 'original-boot', 'observer': observer}}
    logs = {'stdout.log': 'one original agent reply\n', 'stderr.log': ''}
    state, outcome = ('running', 'pending') if active else ('reaped', 'unknown' if crashed else 'cancelled')
    values = {
        'attempt': {'id': attempt, 'state': state, 'outcome': outcome, 'artifact_digest': intent['artifact_digest']},
        'runtime_binding': intent['runtime_binding'],
        'broker': {'attempt_state': state, 'attempt_outcome': outcome,
                   'calls': [{'request_key': 'preview-1', 'state': 'settled', 'consumed_tokens': 0,
                              'publication_closed': not active}], 'policy_denials': [],
                   'policy_denials_retained': 0, 'evidence_gaps': []},
        'robot': {'classification': 'trusted_peer_delegation_metadata', 'binding': binding,
                  'outstanding_debits': 1, 'requests_retained': 1,
                  'requests': [{**{key: intent[key] for key in ('request_key', 'handle', 'robot_epoch',
                                  'observation_digest', 'proposal_digest')},
                                'outstanding_debit': True, 'cancellation_requested': not active,
                                'phase': 'accepted' if active else 'unknown'}]}}
    omissions = []
    if active or crashed:
        omissions.append({'artifact': 'runtime_facts', 'reason': 'final_resource_snapshot_unavailable', 'omitted_records': 1})
    else:
        values['runtime_facts'] = {'observer_health_unavailable': False, 'observer': observer,
            'resources': {'classification': 'observed_cgroup_v2_counters',
                          'stage': 'after_descendants_empty_before_runtime_delete',
                          'counters': {key: '0\n' for key in campaign.common.RESOURCE_COUNTERS}, 'unavailable': []}}
    if crashed:
        omissions.append({'artifact': 'runtime_facts', 'reason': 'log_incomplete', 'omitted_records': 1})
    for name in ('stdout', 'stderr'):
        raw = logs[name + '.log'].encode()
        values[name] = {'classification': 'untrusted_agent_output_not_policy_attribution',
                        'retained_bytes': len(raw), 'retained_sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                        'file_complete': not active and not crashed, 'source_truncated': False,
                        'tail_encoding': 'hex', 'tail': raw.hex(), 'tail_omitted_bytes': 0}
    bundle = {'schema': 'actryn.server.evidence.v1', 'attempt_id': attempt,
              'execution_replay_eligible': False, 'omissions': omissions,
              'artifacts': [{'name': name, 'content': copy.deepcopy(content)} for name, content in values.items()]}
    rehash(bundle)
    return bundle, attempt, binding, intent, logs


def rehash(bundle):
    for item in bundle['artifacts']:
        item['bytes'] = len(campaign.common.compact(item['content']))
        item['sha256'] = campaign.common.digest(item['content'])


def wait(predicate):
    until = time.monotonic() + 1
    while not predicate():
        if time.monotonic() >= until: raise AssertionError('host predicate timeout')
        time.sleep(.005)


IDENTITY = {'device': [1] * 16, 'boot': 1, 'session': 2, 'runtime_nonce': [2] * 16,
            'grant': 3, 'instance': 4, 'operation': 5, 'stream': 6}


@contextlib.contextmanager
def echo_server():
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            while True:
                data = self.request.recv(4096)
                if not data: return
                self.request.sendall(data)
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        def handle_error(self, *_): pass
    with Server(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        try: yield server.server_address[1]
        finally: server.shutdown(); thread.join(1)


class PartialEvidenceTests(unittest.TestCase):
    def test_launcher_crash_omissions_do_not_require_a_copied_broker_gap(self):
        # Launcher recovery owns log completeness. Broker startup can reap the
        # same attempt before tick has mirrored that separate store's gap.
        for gaps in ([], ['log_incomplete']):
            args = list(fixture(crashed=True))
            values = {v['name']: v['content'] for v in args[0]['artifacts']}
            values['broker']['evidence_gaps'] = gaps
            rehash(args[0])
            before = copy.deepcopy(args)
            with self.subTest(gaps=gaps):
                campaign.verify_partial(*args, crashed=True)
                self.assertEqual(args, before)

    def test_noncrash_cannot_claim_a_broker_log_gap(self):
        for active in (False, True):
            args = list(fixture(active=active))
            broker = next(v['content'] for v in args[0]['artifacts'] if v['name'] == 'broker')
            broker['evidence_gaps'] = ['log_incomplete']
            rehash(args[0])
            with self.subTest(active=active), self.assertRaises(AssertionError):
                campaign.verify_partial(*args, active=active)

    def test_actual_partial_shapes_preserve_distinct_states(self):
        for active, crashed in ((False, False), (True, False), (False, True)):
            campaign.verify_partial(*fixture(active=active, crashed=crashed), active=active, crashed=crashed)

    def settled_fixture(self, verdict='TargetReached'):
        args = list(fixture(crashed=True))
        remote = next(v['content'] for v in args[0]['artifacts'] if v['name'] == 'robot')
        remote['outstanding_debits'] = 0
        remote['requests'][0].update(outstanding_debit=False, phase='settled',
                                     reconciled=True, remote_verdict=verdict)
        args[3]['operation'] = copy.deepcopy(IDENTITY)
        args[3]['settlement'] = {
            'namespace': list(bytes.fromhex(args[3]['handle']['namespace'])),
            'key': list(bytes.fromhex(args[3]['handle']['key'])),
            'operation': copy.deepcopy(IDENTITY), 'phase': 'Completed',
            'terminal': True, 'revision': 3, 'durable_revision': 3,
            'persistence_failed': False, 'verdict': verdict, 'reconciled': True}
        rehash(args[0])
        return args

    def test_completed_unknown_task_settlement_preserves_verdict_and_crash_uncertainty(self):
        for verdict in ('TargetReached', 'TimedOut', 'Cancelled', 'OutcomeUnknown'):
            args = self.settled_fixture(verdict)
            before = copy.deepcopy(args)
            campaign.verify_partial(*args, crashed=True, settled=True)
            self.assertEqual(args, before)
            with self.assertRaises(AssertionError): campaign.verify_partial(*args, crashed=True)

    def test_unknown_task_without_exact_durable_completion_cannot_settle(self):
        for fault in ('unknown_work', 'cancelled', 'unreconciled', 'partial', 'persistence',
                      'zero', 'overdurable', 'absent', 'key', 'namespace', 'operation',
                      'nonterminal', 'summary_verdict', 'summary_reconciliation', 'missing_proof'):
            args = self.settled_fixture('OutcomeUnknown')
            proof = args[3]['settlement']
            remote = next(v['content'] for v in args[0]['artifacts'] if v['name'] == 'robot')['requests'][0]
            if fault == 'unknown_work': proof['phase'] = 'OutcomeUnknown'
            elif fault == 'cancelled': proof['phase'] = 'CancelledDurable'
            elif fault == 'unreconciled': proof['reconciled'] = False
            elif fault == 'partial': proof['durable_revision'] = 2
            elif fault == 'persistence': proof['persistence_failed'] = True
            elif fault == 'zero': proof.update(revision=0, durable_revision=0)
            elif fault == 'overdurable': proof['durable_revision'] = 4
            elif fault == 'absent': proof['operation'] = None
            elif fault == 'key': proof['key'] = [7] * 32
            elif fault == 'namespace': proof['namespace'] = [7] * 16
            elif fault == 'operation': proof['operation']['stream'] += 1
            elif fault == 'nonterminal': proof['terminal'] = False
            elif fault == 'summary_verdict': remote['remote_verdict'] = 'TargetReached'
            elif fault == 'summary_reconciliation': remote['reconciled'] = False
            else: args[3].pop('settlement')
            rehash(args[0])
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.verify_partial(*args, crashed=True, settled=True)

    def test_known_task_also_requires_durable_matching_reconciliation(self):
        for field, value in [('reconciled', False), ('durable_revision', 2),
                             ('persistence_failed', True), ('phase', 'OutcomeUnknown')]:
            args = self.settled_fixture()
            args[3]['settlement'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                campaign.verify_partial(*args, crashed=True, settled=True)

    def test_rehashed_wrong_debit_identity_publication_and_log_cannot_pass(self):
        for fault in ('debit', 'handle', 'binding', 'phase', 'closed', 'call_state',
                      'raw_hash', 'complete', 'resources', 'missing_artifact'):
            args = list(fixture())
            bundle = args[0]; values = {v['name']: v['content'] for v in bundle['artifacts']}
            if fault == 'debit': values['robot']['outstanding_debits'] = 0
            elif fault == 'handle': values['robot']['requests'][0]['handle']['key'] = '9' * 64
            elif fault == 'binding': values['robot']['binding']['namespace'] = '9' * 32
            elif fault == 'phase': values['robot']['requests'][0]['phase'] = 'settled'
            elif fault == 'closed': values['broker']['calls'][0]['publication_closed'] = False
            elif fault == 'call_state': values['broker']['calls'][0]['state'] = 'unknown'
            elif fault == 'raw_hash': values['stdout']['retained_sha256'] = 'sha256:' + '0' * 64
            elif fault == 'complete': values['stdout']['file_complete'] = False
            elif fault == 'resources': values['runtime_facts']['resources']['unavailable'] = ['io.stat']
            else: bundle['artifacts'].pop()
            rehash(bundle)
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.verify_partial(*args)

    def test_crash_uncertainty_cannot_disappear_or_be_called_complete(self):
        for gaps in ([], ['log_incomplete']):
            for fault in ('omission', 'resources_omission', 'complete', 'gap',
                          'duplicate_gap', 'invented_gap', 'outcome', 'debit'):
                args = list(fixture(crashed=True)); values = {v['name']: v['content'] for v in args[0]['artifacts']}
                values['broker']['evidence_gaps'] = gaps
                if fault == 'omission': args[0]['omissions'].pop()
                elif fault == 'resources_omission': args[0]['omissions'].pop(0)
                elif fault == 'complete': values['stdout']['file_complete'] = True
                elif fault == 'gap': values['broker']['evidence_gaps'] = ['observer_unavailable']
                elif fault == 'duplicate_gap': values['broker']['evidence_gaps'] = ['log_incomplete', 'log_incomplete']
                elif fault == 'outcome': values['attempt']['outcome'] = values['broker']['attempt_outcome'] = 'cancelled'
                elif fault == 'debit': values['robot']['outstanding_debits'] = 0
                else: args[0]['omissions'].append({'artifact': 'robot', 'reason': 'arbitrary', 'omitted_records': 1})
                rehash(args[0])
                with self.subTest(gaps=gaps, fault=fault), self.assertRaises(AssertionError):
                    campaign.verify_partial(*args, crashed=True)

    def test_missing_postcrash_log_requires_independent_absence_and_omission(self):
        args = list(fixture(crashed=True))
        args[0]['artifacts'] = [v for v in args[0]['artifacts'] if v['name'] != 'stdout']
        args[0]['omissions'].append({'artifact': 'stdout', 'reason': 'retained_log_unavailable', 'omitted_records': 1})
        with self.assertRaises(AssertionError): campaign.verify_partial(*args, crashed=True)
        args[4]['stdout.log'] = None
        campaign.verify_partial(*args, crashed=True)

    def test_empty_artifact_list_is_not_partial_evidence(self):
        bundle = {'schema': 'actryn.server.evidence.v1', 'attempt_id': 'a' * 32,
                  'execution_replay_eligible': False, 'artifacts': [], 'omissions': []}
        with self.assertRaises(AssertionError):
            campaign.verify_partial(bundle, 'a' * 32, {}, {}, {})

    def test_peer_digest_matches_typed_struct_order_not_configuration_file_order(self):
        keys = ('endpoint', 'dns_name', 'robot_leaf_sha256', 'principal',
                'robot_configuration_digest', 'robot_profile_digest', 'ca_pem', 'client_certificate_pem')
        original = {key: key for key in keys}
        reversed_file = {key: key for key in reversed(keys)}
        self.assertEqual(campaign.peer_digest(original), campaign.peer_digest(reversed_file))
        self.assertNotEqual(campaign.peer_digest(original), campaign.common.digest(original))

    def test_reviewed_source_limits_are_unchanged(self):
        self.assertEqual(campaign.source_limits()['GLOBAL_JOBS'], 4)

    def test_wrong_target_pin_fails_before_inherited_recovery_or_guest_output_creation(self):
        run = object.__new__(campaign.DebitCampaign)
        run.peer = {'endpoint': '10.0.2.2:1234'}
        run.gate = SimpleNamespace(port=1234)
        with (patch.object(run, 'mark'),
              patch.object(run, 'pin_platforms', side_effect=AssertionError('wrong machine')),
              patch.object(run, 'preflight') as inherited):
            with self.assertRaises(AssertionError): run.execute()
            inherited.assert_not_called()

    def test_running_gate_requires_matching_full_runtime_kernel_identity(self):
        binding = {'attempt': list(bytes.fromhex('a' * 32)), 'namespace': list(bytes.fromhex('b' * 32))}
        status = {'state': 2, 'operation_state': 2, 'flags': 8,
                  'device_identity': IDENTITY['device'], 'controller_boot': 1, 'controller_session': 2,
                  **{k: IDENTITY[k] for k in ('runtime_nonce', 'grant', 'instance', 'operation', 'stream')}}
        description = {'runtime': {'prepared': {'binding': binding}, 'kernel': status,
                                   'operation': {'operation': IDENTITY}}}
        self.assertEqual(campaign.operation_identity(description, 'a' * 32, 'b' * 32), IDENTITY)
        for field, value in [('operation', 99), ('controller_boot', 9), ('runtime_nonce', [9] * 16)]:
            changed = copy.deepcopy(description); changed['runtime']['kernel'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                campaign.operation_identity(changed, 'a' * 32, 'b' * 32)
        description['runtime']['kernel']['flags'] = 0
        self.assertIsNone(campaign.operation_identity(description, 'a' * 32, 'b' * 32))


class ContinuationTests(unittest.TestCase):
    @contextlib.contextmanager
    def pipe(self):
        reader, writer = os.pipe()
        try:
            yield reader, writer
        finally:
            os.close(reader)
            try: os.close(writer)
            except OSError: pass

    def test_partial_line_times_out_under_original_absolute_deadline(self):
        with self.pipe() as (reader, writer):
            os.write(writer, b'{')
            # Release the old blocking readline even when this regression fails.
            closer = threading.Timer(.2, os.close, args=(writer,))
            closer.start()
            started = time.monotonic()
            try:
                with self.assertRaisesRegex(AssertionError, 'continuation cutoff'):
                    campaign.read_continuation(reader, started + .04)
                self.assertLess(time.monotonic() - started, .15)
            finally:
                closer.join(1)

    def test_eof_without_a_complete_line_is_rejected(self):
        for partial in (b'', b'{'):
            with self.subTest(partial=partial), self.pipe() as (reader, writer):
                os.write(writer, partial); os.close(writer)
                with self.assertRaisesRegex(AssertionError, 'continuation EOF'):
                    campaign.read_continuation(reader, time.monotonic() + .2)

    def test_incremental_complete_line_and_exact_byte_boundary(self):
        with self.pipe() as (reader, writer):
            os.write(writer, b'{')
            complete = threading.Timer(.02, os.write, args=(writer, b'}\n'))
            complete.start()
            try:
                self.assertEqual(campaign.read_continuation(reader, time.monotonic() + .2), b'{}\n')
            finally:
                complete.join(1)
        with self.pipe() as (reader, writer):
            frame = b'x' * 1023 + b'\n'
            os.write(writer, frame)
            self.assertEqual(campaign.read_continuation(reader, time.monotonic() + .2), frame)

    def test_oversize_multiple_lines_and_trailing_bytes_are_rejected(self):
        for frame in (b'x' * 1024 + b'\n', b'{}\n{}\n', b'{}\nx'):
            with self.subTest(frame=frame[:16]), self.pipe() as (reader, writer):
                os.write(writer, frame)
                with self.assertRaises(AssertionError):
                    campaign.read_continuation(reader, time.monotonic() + .2)


class FinalGateTests(unittest.TestCase):
    def campaign(self):
        run = object.__new__(campaign.DebitCampaign)
        run.gate = MagicMock()
        run.gate.report.return_value = {'error': None, 'active': 0, 'blocked_active': 0,
            'remaining_s': 1, 'connections': 4, 'bytes_observed': 30,
            'bytes_forwarded': 20, 'blocked_bytes': 10}
        run.save = Mock()
        return run

    def test_late_gate_error_cannot_publish_pass(self):
        run = self.campaign()
        def execute():
            run.gate.report.return_value['error'] = 'late forwarding failure'
            return {'scope': 'test'}
        run.execute = execute
        with self.assertRaises(AssertionError): run.complete()
        run.gate.close.assert_called_once()
        run.save.assert_not_called()

    def test_gate_cleanup_failure_cannot_publish_pass(self):
        run = self.campaign()
        run.execute = lambda: {'scope': 'test'}
        run.gate.close.side_effect = AssertionError('gate cleanup unknown')
        with self.assertRaisesRegex(AssertionError, 'gate cleanup unknown'): run.complete()
        run.save.assert_not_called()

    def test_final_cutoff_counters_and_drained_workers_are_required(self):
        for field, value in [('remaining_s', 0), ('active', 1), ('blocked_active', 1),
                             ('connections', 65), ('bytes_observed', 8 * 1024 * 1024 + 1),
                             ('bytes_forwarded', 31)]:
            run = self.campaign()
            run.execute = lambda: {'scope': 'test'}
            run.gate.report.return_value[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): run.complete()
            run.save.assert_not_called()

    def test_pass_is_saved_only_after_gate_close_and_final_validation(self):
        run = self.campaign()
        events = []
        run.execute = lambda: events.append('execute') or {'scope': 'test'}
        run.gate.close.side_effect = lambda: events.append('closed')
        run.save.side_effect = lambda name, value: events.append(name)
        run.complete()
        self.assertEqual(events, ['execute', 'closed', 'PASS.json'])

    def test_main_retains_cleanup_failure_in_failed_record(self):
        run = self.campaign()
        run.phase, run.attempts, run.cases = 'test', [], []
        run.execute = lambda: {'scope': 'test'}
        run.abort_revoke = Mock()
        run.gate.close.side_effect = AssertionError('gate cleanup unknown')
        args = SimpleNamespace(server_port=1, robot_port=2, tcp_port=3, gate_port=4,
            artifact='sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45',
            server_manifest='a' * 64, robot_manager_sha256='b' * 64,
            robot_module_note_sha256='c' * 64, server_machine_id='d' * 32,
            robot_machine_id='e' * 32, server_qemu_unit='actryn-install-server03.service',
            server_ssh_key='unused')
        with (patch.object(campaign.argparse.ArgumentParser, 'parse_args', return_value=args),
              patch.object(campaign, 'ConnectionGate', return_value=run.gate),
              patch.object(campaign, 'DebitCampaign', return_value=run),
              patch.object(campaign, 'source_limits'), patch.object(campaign.os, 'umask')):
            with self.assertRaisesRegex(AssertionError, 'gate cleanup unknown'): campaign.main()
        name, record = run.save.call_args.args
        self.assertEqual(name, 'FAILED.json')
        self.assertIn('gate cleanup unknown', record['gate_cleanup_error'])
        self.assertEqual(run.save.call_count, 1)
        run.abort_revoke.assert_called_once()


class GateTests(unittest.TestCase):
    def test_existing_connection_keeps_flowing_but_new_connections_are_not_forwarded(self):
        with echo_server() as upstream, ConnectionGate(0, upstream, lifetime=3) as gate:
            with socket.create_connection(('127.0.0.1', gate.port)) as old:
                old.settimeout(.5); old.sendall(b'before'); self.assertEqual(old.recv(6), b'before')
                gate.arm(IDENTITY)
                with socket.create_connection(('127.0.0.1', gate.port)) as blocked:
                    blocked.settimeout(.05); blocked.sendall(b'held')
                    with self.assertRaises(TimeoutError): blocked.recv(4)
                    old.sendall(b'after'); self.assertEqual(old.recv(5), b'after')
                wait(lambda: gate.report()['blocked_active'] == 0)
                gate.pass_future()
                with socket.create_connection(('127.0.0.1', gate.port)) as fresh:
                    fresh.settimeout(.5); fresh.sendall(b'new'); self.assertEqual(fresh.recv(3), b'new')
                report = gate.report()
                self.assertEqual(report['blocked_bytes'], 4)
                self.assertEqual(report['automatic_reconnects'], 0)
                self.assertFalse(report['tls_terminated'])
                self.assertFalse(report['withheld_replayed'])

    def test_connection_byte_and_lifetime_caps_fail_closed(self):
        with echo_server() as upstream:
            with ConnectionGate(0, upstream, lifetime=3, connections=1) as gate:
                with socket.create_connection(('127.0.0.1', gate.port)) as first:
                    first.sendall(b'a'); self.assertEqual(first.recv(1), b'a')
                    with socket.create_connection(('127.0.0.1', gate.port)): pass
                    wait(lambda: gate.report()['error'] is not None)
                    self.assertLessEqual(gate.report()['connections'], 1)
            with ConnectionGate(0, upstream, lifetime=3, per_connection=4) as gate:
                with socket.create_connection(('127.0.0.1', gate.port)) as client:
                    client.sendall(b'12345'); wait(lambda: gate.report()['error'] is not None)
                self.assertEqual(gate.report()['bytes_forwarded'], 0)
            with ConnectionGate(0, upstream, lifetime=3, total_bytes=4) as gate:
                with socket.create_connection(('127.0.0.1', gate.port)) as client:
                    client.sendall(b'12345'); wait(lambda: gate.report()['error'] is not None)
                self.assertEqual(gate.report()['bytes_forwarded'], 0)
            with ConnectionGate(0, upstream, lifetime=.05) as gate:
                wait(lambda: gate.report()['error'] is not None)
                self.assertIn('lifetime', gate.report()['error'])

    def test_gate_configuration_cannot_raise_fixed_caps(self):
        for arguments in ({'connections': 65}, {'active': 9}, {'lifetime': 1201},
                          {'per_connection': 262145}, {'total_bytes': 8 * 1024 * 1024 + 1}):
            with self.subTest(arguments=arguments), self.assertRaises(AssertionError):
                ConnectionGate(0, 12345, **arguments)

    def test_gate_rejects_incomplete_or_zero_operation_identity(self):
        with echo_server() as upstream, ConnectionGate(0, upstream, lifetime=3) as gate:
            bad = dict(IDENTITY, operation=0)
            with self.assertRaises(AssertionError): gate.arm(bad)
            with self.assertRaises(AssertionError): gate.arm({'operation': 1})

    def test_retained_gate_identity_cannot_be_changed_by_caller_or_report(self):
        with echo_server() as upstream, ConnectionGate(0, upstream, lifetime=3) as gate:
            identity = copy.deepcopy(IDENTITY)
            gate.arm(identity)
            identity['device'][0] = 99
            report = gate.report()
            self.assertEqual(report['arms'][0]['operation'], IDENTITY)
            report['arms'][0]['operation']['device'][0] = 98
            self.assertEqual(gate.report()['arms'][0]['operation'], IDENTITY)


if __name__ == '__main__':
    unittest.main()
