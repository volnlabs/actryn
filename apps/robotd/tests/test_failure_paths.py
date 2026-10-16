import contextlib
import copy
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from reply_gate import ReplyGate
from sqlite_contention import writer_lease, wait_release, clock_ns
from failure_paths import Campaign, OneProposal, durable_cancel, operation_id, validate_capture
from guest import RequestHandle
from actryn import OutcomeUnknown
from actryn import RpcError
from guest import wire


@contextlib.contextmanager
def echo_peer():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(2)
    received = bytearray()
    def serve():
        connection = None
        try:
            connection, _ = listener.accept()
            connection.settimeout(2)
            while data := connection.recv(4096):
                received.extend(data)
                connection.sendall(data)
        except (OSError, TimeoutError):
            pass
        finally:
            if connection:
                connection.close()
    worker = threading.Thread(target=serve)
    worker.start()
    try:
        yield listener.getsockname()[1], received
    finally:
        listener.close()
        worker.join(3)
        assert not worker.is_alive()


class ReplyGateTests(unittest.TestCase):
    def test_transparent_then_withholds_without_replay_on_close(self):
        with echo_peer() as (port, received), ReplyGate(port) as relay:
            with socket.create_connection(('127.0.0.1', relay.port), timeout=1) as client:
                client.sendall(b'handshake-and-observe')
                self.assertEqual(client.recv(4096), b'handshake-and-observe')
                relay.arm()
                client.sendall(b'one-proposal')
                client.settimeout(.1)
                with self.assertRaises(TimeoutError):
                    client.recv(4096)
                self.assertEqual(bytes(received), b'handshake-and-observeone-proposal')
                relay.close()
                self.assertEqual(client.recv(4096), b'')
            report = relay.report()
            self.assertEqual(report['gated_upstream_bytes'], len(b'one-proposal'))
            self.assertEqual(report['withheld_bytes'], len(b'one-proposal'))
            self.assertEqual(report['gated_downstream_forwarded'], 0)
            self.assertIsNone(report['error'])

    def test_response_limit_closes_and_never_flushes(self):
        with echo_peer() as (port, _), ReplyGate(port, held_limit=2) as relay:
            with socket.create_connection(('127.0.0.1', relay.port), timeout=1) as client:
                relay.arm()
                client.sendall(b'oversized')
                self.assertEqual(client.recv(32), b'')
            self.assertIn('withheld ciphertext capacity', relay.report()['error'])
            self.assertEqual(relay.report()['gated_downstream_forwarded'], 0)

    def test_upstream_limit_rejects_before_forwarding_and_cannot_rearm(self):
        with echo_peer() as (port, received), ReplyGate(port, upstream_limit=2) as relay:
            with socket.create_connection(('127.0.0.1', relay.port), timeout=1) as client:
                relay.arm()
                with self.assertRaises(AssertionError):
                    relay.arm()
                client.sendall(b'oversized')
                self.assertEqual(client.recv(32), b'')
            self.assertEqual(bytes(received), b'')
            self.assertIn('proposal ciphertext capacity', relay.report()['error'])

    def test_exception_finally_stops_worker(self):
        relay = None
        with self.assertRaises(RuntimeError), echo_peer() as (port, _):
            with ReplyGate(port) as relay:
                raise RuntimeError('campaign stopped')
        self.assertFalse(relay.worker.is_alive())


class SQLiteLeaseTests(unittest.TestCase):
    def test_real_writer_contention_releases_after_exception_without_data_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'intent.sqlite'
            with contextlib.closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE records(value INTEGER)')
            with self.assertRaises(RuntimeError):
                with writer_lease(path):
                    with contextlib.closing(sqlite3.connect(path, timeout=0)) as writer, writer:
                        with self.assertRaises(sqlite3.OperationalError):
                            writer.execute('INSERT INTO records VALUES(1)')
                    raise RuntimeError('host disconnected')
            with contextlib.closing(sqlite3.connect(path, timeout=0)) as db, db:
                self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 0)
                db.execute('INSERT INTO records VALUES(2)')

    def test_lease_eof_timeout_and_invalid_release_are_failures(self):
        for data, expected in ((b'', EOFError), (b'wrong\n', AssertionError)):
            left, right = socket.socketpair()
            try:
                if data:
                    left.sendall(data)
                else:
                    left.close()
                with self.assertRaises(expected):
                    wait_release(right, clock_ns() + 50_000_000)
            finally:
                left.close(); right.close()
        left, right = socket.socketpair()
        try:
            with self.assertRaises(TimeoutError):
                wait_release(right, clock_ns() + 10_000_000)
        finally:
            left.close(); right.close()

    def test_rollback_error_still_closes_but_close_error_never_claims_release(self):
        for rollback_error, close_error, released in ((True, False, True), (False, True, False)):
            db, confirm = Mock(), Mock()
            db.execute.return_value.fetchone.return_value = ['delete']
            if rollback_error:
                db.rollback.side_effect = sqlite3.OperationalError('rollback failed')
            if close_error:
                db.close.side_effect = sqlite3.OperationalError('close failed')
            with patch('sqlite_contention.sqlite3.connect', return_value=db):
                with self.assertRaises(sqlite3.OperationalError):
                    with writer_lease('/unused', confirm):
                        pass
            db.close.assert_called_once()
            self.assertEqual(confirm.call_count, int(released))


class NoRetryTests(unittest.TestCase):
    def test_explicit_rejection_is_retained_without_claiming_unknown_outcome(self):
        campaign = Campaign(SimpleNamespace(ssh_key='unused', ssh_port=26221, known_hosts='unused'))
        request_id = bytes([1]*16)
        reply = wire.Response(version=1, request_id=request_id, robot_epoch=bytes([2]*16),
                              failure=wire.Failure(code=wire.Failure.REJECTED, message='denied'))
        campaign.run = Mock(return_value=reply.SerializeToString(deterministic=True))
        with patch('failure_paths.secrets.token_bytes', return_value=request_id), patch('failure_paths.write_json') as save:
            with self.assertRaises(RpcError) as error:
                campaign.local('activate', label='once')
            self.assertNotIsInstance(error.exception, OutcomeUnknown)
            self.assertFalse(any('unknown' in call.args[0] for call in save.call_args_list))
            campaign.run.assert_called_once()

    def test_unknown_first_proposal_invokes_sdk_once_and_cannot_restart(self):
        rpc = Mock()
        rpc.propose.side_effect = OutcomeUnknown('reply withheld')
        call = OneProposal(rpc, RequestHandle.create(bytes([1]*16), bytes([2]*16)), {'id': 7})
        call.start()
        result = call.finish()
        with self.assertRaises(AssertionError):
            call.start()
        rpc.propose.assert_called_once()
        self.assertTrue(result['outcome_unknown'])
        self.assertEqual(result['calls'], 1)
        self.assertNotIn('reply', result)

    def test_unknown_reserved_cancel_is_recorded_and_never_reissued(self):
        campaign = Campaign(SimpleNamespace(ssh_key='unused', ssh_port=26221, known_hosts='unused'))
        campaign.cancel_attempted = False
        campaign.local = Mock(side_effect=TimeoutError('lost closure reply'))
        handle = RequestHandle.create(bytes([1]*16), bytes([2]*16))
        with patch('failure_paths.write_json') as save:
            self.assertIsNone(campaign.cancel_once(handle))
            with self.assertRaises(AssertionError):
                campaign.cancel_once(handle)
        campaign.local.assert_called_once()
        self.assertEqual(save.call_args.args[0], 'cancel-reply-unknown.json')


class CapturePredicateTests(unittest.TestCase):
    def fixture(self, mode='a09'):
        handle = RequestHandle(bytes([1]*16), bytes([2]*16), bytes([3]*32))
        prepared = {'configuration_digest': [4]*32}
        status = {'device_identity': [5]*16, 'controller_boot': 6, 'controller_session': 7,
                  'runtime_nonce': [8]*16, 'grant': 9, 'instance': 10, 'operation': 11, 'stream': 12,
                  'operation_state': 6, 'events_lost': 0, 'reason': 0, 'left_permille': 0, 'right_permille': 0}
        operation = operation_id(status)
        transitions = [(0x1000e, 6, 0)]
        if mode == 'a02':
            transitions.append((0x10007, 1, 0))
        transitions += [(0x30002, 3, 2), (0x2000b, 4, 2)]
        records = [{'producer': 0, 'record_ordinal': 4, 'origin': 'Runtime', 'kind': 'Execution',
                    'value': [list(handle.key), [9]*32, {}, 20]}]
        for index, (kind, state, reason) in enumerate(transitions):
            records.append({'producer': 1, 'record_ordinal': index+1, 'origin': 'Kernel', 'kind': 'Transition',
                'value': {'sequence': 100+index, 'captured_ns': 110+index*10, 'kind': kind,
                          'status': dict(status, operation_state=state, reason=reason)}})
        decoded = {'format': 'actryn-failure-capture-1', 'attempt': list(handle.attempt), **prepared,
            'policy': 'MetadataOnly', 'issues': [], 'raw_remnants': [], 'volatile_tail_unknown': True,
            'execution_replay_eligible': False, 'records': records,
            'frontiers': [{'gap_count': 0, 'read': n, 'durable': n} for n in (4, len(transitions))],
            'sources': [{'missing_record_ordinals': [], 'source_gap_record_ordinals': [],
                         'last_record_ordinal': n, 'durable_frontier': n} for n in (4, len(transitions))]}
        lease = {'locked_ns': 100, 'released_ns': 200, 'released': True, 'within_lease': True}
        return decoded, handle, prepared, operation, mode, lease

    def test_actual_identity_and_kernel_times_distinguish_both_campaigns(self):
        for mode in ('a02', 'a09'):
            proof = validate_capture(*self.fixture(mode))
            self.assertEqual(proof['start_count'], int(mode == 'a02'))
            self.assertEqual(proof['allocation_sequence'], 100)

    def test_wrong_identity_gap_duplicate_proposal_or_outside_lock_cannot_pass(self):
        changes = [lambda d, lease: d['records'][1]['value']['status'].update(operation=999),
                   lambda d, lease: d['records'][2]['value'].update(sequence=999),
                   lambda d, lease: d['records'].append(copy.deepcopy(d['records'][0])),
                   lambda d, lease: d['records'][2]['value']['status'].update(events_lost=1),
                   lambda d, lease: lease.update(released_ns=115),
                   lambda d, lease: lease.update(error='lease expired'),
                   lambda d, lease: d['frontiers'][1].update(durable=2),
                   lambda d, lease: d.update(execution_replay_eligible=True)]
        for change in changes:
            data = self.fixture()
            change(data[0], data[-1])
            with self.assertRaises(AssertionError):
                validate_capture(*data)

    def test_start_during_writer_lock_or_missing_start_in_reply_case_fails(self):
        data = list(self.fixture('a02'))
        data[-2] = 'a09'
        with self.assertRaises(AssertionError):
            validate_capture(*data)
        data = list(self.fixture('a09'))
        data[-2] = 'a02'
        with self.assertRaises(AssertionError):
            validate_capture(*data)

    def test_terminal_revision_itself_must_be_durable_with_exact_retained_identity(self):
        _, handle, _, operation, _, _ = self.fixture()
        snapshot = {'namespace': list(handle.namespace), 'key': list(handle.key), 'operation': operation,
                    'phase': 'CancelledDurable', 'terminal': True, 'cancellation_durable': True,
                    'persistence_failed': False, 'revision': 3, 'durable_revision': 3,
                    'verdict': 'Cancelled', 'reconciled': True}
        self.assertTrue(durable_cancel(snapshot, handle, operation))
        for change in ({'durable_revision': 2}, {'durable_revision': 4}, {'reconciled': False},
                       {'phase': 'OutcomeUnknown'}, {'operation': None}, {'key': [0]*32}):
            self.assertFalse(durable_cancel(dict(snapshot, **change), handle, operation))


if __name__ == '__main__':
    unittest.main()
