#!/usr/bin/env python3
"""A10: bounded forged traffic, encrypted replay/delay, and saturated local closure."""
import base64
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import ssl
import struct
import time

from failure_paths import OneProposal, durable_cancel, operation_id, same_operation
from gateway_campaign import GatewayCampaign, main
from gateway_relay import CipherGate
from guest import phase, wire, write_json
from actryn import OutcomeUnknown, RpcError
from source_gap import require


def request(epoch, method, payload):
    result = wire.Request(version=1, request_id=secrets.token_bytes(16), robot_epoch=epoch)
    getattr(result, method).CopyFrom(payload)
    return result


def unchanged_authority(before, after):
    names = ('runtime_nonce', 'instance', 'grant', 'deadline_ns', 'state', 'operation', 'stream',
             'operation_state', 'left_permille', 'right_permille')
    require(all(before['runtime']['kernel'][name] == after['runtime']['kernel'][name] for name in names)
            and after['clock_healthy'] and after['runtime']['health']['healthy']
            and after['runtime']['event_stream_healthy'], 'authority changed or independent fault during negative traffic')


def rejected_frame(peer, encoded, expected):
    """One malicious application frame. Timeout is inconclusive, never rejection."""
    peer.settimeout(.75)
    peer.sendall(struct.pack('!I', len(encoded)) + encoded)
    raw = bytearray()
    try:
        head = peer.recv(4)
        if not head:
            return {'rejected': True, 'eof': True}
        while len(head) < 4:
            part = peer.recv(4 - len(head))
            require(part, 'partial response header')
            head += part
        size = struct.unpack('!I', head)[0]
        require(0 < size <= 65536, 'negative response capacity')
        deadline = time.monotonic() + .75
        while len(raw) < size:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'negative response deadline')
            peer.settimeout(remaining)
            part = peer.recv(size - len(raw))
            require(part, 'partial negative reply')
            raw.extend(part)
    except (ConnectionResetError, ssl.SSLError) as error:
        return {'rejected': True, 'transport_error': repr(error), 'partial_bytes': len(raw)}
    response = wire.Response.FromString(raw)
    response.DiscardUnknownFields()
    require(response.SerializeToString(deterministic=True) == raw and response.version == 1
            and response.request_id == expected.request_id and response.robot_epoch == expected.robot_epoch
            and response.HasField('failure') and response.failure.code in
            (wire.Failure.REJECTED, wire.Failure.CAPACITY, wire.Failure.UNAVAILABLE), 'negative request admitted/unknown')
    return {'rejected': True, 'code': response.failure.code, 'message': response.failure.message}


def no_pending_tcp(peer):
    # MSG_PEEK on a duplicate descriptor never consumes TLS bytes or changes flags.
    with socket.socket(fileno=os.dup(peer.fileno())) as raw:
        try:
            data = raw.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
        except BlockingIOError:
            return
        raise AssertionError({'holder_closed_or_unexpected_ciphertext': data.hex()})


class TrafficCampaign(GatewayCampaign):
    def forged(self, denied):
        phase('A10 bounded forged metadata and unauthorized methods')
        before = self.local('describe', label='before-forged')
        with socket.create_connection(('127.0.0.1', self.args.tcp_port), timeout=.75) as peer:
            peer.sendall(b'ACTRYN-GW1\nprincipal=root\n')
            peer.shutdown(socket.SHUT_WR)
            try:
                data = peer.recv(4096)  # A TLS alert is permitted; it is never an RPC identity.
            except ConnectionResetError:
                data = b''
            write_json('forged-plaintext.json', {'bytes_sent': len(b'ACTRYN-GW1\nprincipal=root\n'), 'reply_bytes': len(data),
                'reply_sha256': hashlib.sha256(data).hexdigest(), 'tls_terminated': False})
        for name in ('unknown-identity-field', 'remote-grant', 'widened-target'):
            with self.connection() as rpc:
                if name == 'remote-grant':
                    message = request(self.epoch, 'grant', wire.Grant(duration_ms=60000))
                elif name == 'widened-target':
                    observation = rpc.observe(self.handle.attempt, self.handle.namespace)
                    message = request(self.epoch, 'propose', wire.Proposal(handle=denied._wire(),
                        observation_id=observation['id'], parent_digest=b'\x30' * 32,
                        target=wire.Target(left_delta_ticks=101, right_delta_ticks=0, duration_ms=1000)))
                else:
                    message = request(self.epoch, 'describe', wire.Empty())
                encoded = message.SerializeToString(deterministic=True)
                if name == 'unknown-identity-field':
                    encoded += b'\xa2\x06\x04root'  # Unknown field 100 cannot become an authenticated identity.
                write_json(name + '-intent.json', {'request_hex': encoded.hex(), 'automatic_retry': False})
                write_json(name + '-result.json', rejected_frame(rpc._socket, encoded, message))
            after = self.local('describe', label='after-' + name)
            unchanged_authority(before, after)
        with self.connection() as rpc:
            require(rpc.query(denied)['snapshot'] is None, 'out-of-policy proposal retained or allocated')

    def delayed(self, handle):
        phase('A10 one delayed valid record after durable absent-key cancellation')
        with CipherGate(self.args.tcp_port) as gate, self.connection(gate.port) as sender, self.connection() as observer:
            observation = sender.observe(handle.attempt, handle.namespace)
            call = OneProposal(sender, handle, observation)
            self.read_pre_send(sender, handle, 'delayed-pre-send')
            write_json('delayed-proposal-intent.json', {'handle': handle.json(), 'observation': observation,
                'target': [100, -100, 10000], 'automatic_retry': False})
            gate.arm('hold'); call.start()
            try:
                gate.wait_record(); gate.seal()
                require(not call.done.is_set(), 'delayed proposal already completed')
                try:
                    self.local('cancel', handle._wire(), label='absent-key-cancel', closure=True)
                except BaseException as error:
                    if isinstance(error, RpcError) and not isinstance(error, OutcomeUnknown):
                        raise
                    write_json('absent-cancel-unknown.json', {'error': repr(error), 'automatic_retry': False})
                def absent(value):
                    s = value['snapshot']
                    return (s is not None and s['operation'] is None and s['phase'] == 'CancelledDurable'
                        and s['terminal'] and s['cancellation_durable'] and not s['persistence_failed']
                        and s['revision'] == s['durable_revision'] > 0 and s['closure'] == 'NotAllocated')
                cancelled = self.poll_read('absent-durable', lambda: observer.query(handle), absent, .5)
                before = observer.describe()
                require(before['runtime']['kernel']['now_ns'] < observation['valid_until_ns'],
                        'observation expired before delayed record release')
                gate.forward_once()
                result = call.finish()
                write_json('delayed-proposal-result.json', result)
                require('reply' in result and result['reply']['operation'] is None
                        and result['reply']['phase'] == 'CancelledDurable', 'delayed key was not terminal')
                after = observer.describe()
                unchanged_authority(before, after)
                require(after['runtime']['kernel']['now_ns'] < observation['valid_until_ns'],
                        'delayed request crossed freshness deadline; cannot claim fresh cancellation race')
                write_json('delayed-proof.json', {'cancelled_before_forward': cancelled,
                    'description_after': after, 'gate': gate.report()})
            finally:
                gate.close()
                write_json('delayed-proposal-result.json', call.finish())
                write_json('delayed-gate.json', gate.report())

    def replay(self):
        phase('A10 one acknowledged proposal followed by one malicious ciphertext replay')
        with CipherGate(self.args.tcp_port) as gate, self.connection(gate.port) as sender:
            observation = sender.observe(self.handle.attempt, self.handle.namespace)
            call = OneProposal(sender, self.handle, observation)
            write_json('proposal-intent.json', {'handle': self.handle.json(), 'observation': observation,
                       'target': [100, -100, 10000], 'automatic_retry': False})
            self.start_checked(sender, self.handle, call, lambda: gate.arm('capture'))
            try:
                result = call.finish()
                require('reply' in result and result['reply']['operation'] is not None, 'proposal was not acknowledged')
                gate.seal()
                # The SDK response proves the captured record reached the manager once.
                gate.forward_once()
                sender._socket.settimeout(.75)
                try:
                    data = sender._socket.recv(1)
                    require(data == b'', 'replayed TLS application record produced application data')
                    rejection = {'eof': True}
                except (ssl.SSLError, ConnectionResetError) as error:
                    rejection = {'transport_error': repr(error)}
                write_json('replay-rejection.json', rejection)
            finally:
                gate.close()
                call.worker.join(1)
                require(not call.worker.is_alive(), 'proposal worker did not stop after relay close')
                write_json('replay-gate.json', gate.report())
        with self.connection() as rpc:
            running = self.poll_read('running-after-replay', rpc.describe, lambda d:
                d['runtime']['kernel']['operation_state'] == 2 and d['runtime']['kernel']['flags'] & 8, 1)
            operation = operation_id(running['runtime']['kernel'])
            require(result['reply']['operation'] == operation, 'acknowledged/running operation mismatch')
            write_json('replay-query.json', rpc.query(self.handle))
            return operation

    def saturation(self):
        phase('A10 three ordinary slots and two slow handshakes; reserved local cancellation')
        description = request(self.epoch, 'describe', wire.Empty())
        cancel = request(self.epoch, 'cancel', self.handle._wire())
        with ExitStack() as stack:
            holders = [stack.enter_context(self.connection()) for _ in range(3)]
            times, observations = [], []
            for rpc in holders:
                observations.append(rpc.observe(self.handle.attempt, self.handle.namespace))
                times.append(time.monotonic_ns())
                rpc._socket.sendall(b'\x00\x00\x01')  # Deliberately incomplete next frame length.
            slow = []
            for _ in range(2):
                peer = stack.enter_context(socket.create_connection(('127.0.0.1', self.args.tcp_port), timeout=.5))
                peer.sendall(b'\x16\x03\x01\x00\x05')  # Two bounded incomplete TLS handshakes.
                slow.append(peer)
            with socket.create_connection(('127.0.0.1', self.args.tcp_port), timeout=.5) as excess:
                excess.sendall(b'\x16\x03\x01\x00\x05')
                try:
                    require(excess.recv(1) == b'', 'extra handshake admitted')
                except ConnectionResetError:
                    pass
            for rpc in holders:
                no_pending_tcp(rpc._socket)
            for peer in slow:
                no_pending_tcp(peer)
            write_json('saturation-intent.json', {'observation_connections': 3, 'partial_plaintext_bytes_each': 3,
                'slow_handshakes': 2, 'extra_handshake_rejected': True, 'observations': observations,
                'cancel_request_hex': cancel.SerializeToString(deterministic=True).hex(), 'automatic_retry': False})
            self.cancel_attempted = True
            helper = Path(__file__).with_name('gateway_closure.py').read_text()
            command = 'python3 -c ' + shlex.quote(helper) + ' ' + ' '.join(shlex.quote(base64.b64encode(
                r.SerializeToString(deterministic=True)).decode()) for r in (description, cancel))
            try:
                result = json.loads(self.run(command, timeout=4))
            except BaseException as error:
                write_json('saturation-cancel-unknown.json', {'error': repr(error), 'automatic_retry': False})
                raise
            result['holder_age_ns'] = [time.monotonic_ns() - t for t in times]
            write_json('saturation-result.json', result)
            require(result['ordinary_rejected'] and result['cancel_sends'] == 1
                    and max(result['holder_age_ns']) < 1_800_000_000, 'saturation/cancel timing not established')
            for rpc in holders:
                no_pending_tcp(rpc._socket)
            if 'reply_hex' in result:
                raw = bytes.fromhex(result['reply_hex'])
                response = wire.Response.FromString(raw)
                response.DiscardUnknownFields()
                require(response.SerializeToString(deterministic=True) == raw and response.version == 1
                        and response.request_id == cancel.request_id and response.robot_epoch == self.epoch,
                        'reserved response identity')
                require(response.HasField('report') or (response.HasField('failure')
                    and response.failure.code == wire.Failure.OUTCOME_UNKNOWN), 'reserved cancellation denied')
            else:
                require(result.get('cancel_outcome_unknown'), 'reserved cancellation not sent')
            return result

    def run_campaign(self):
        self.setup()
        delayed, denied = self.save_other_handle('delayed'), self.save_other_handle('denied')
        complete = False
        try:
            self.activate()
            self.forged(denied)
            self.delayed(delayed)
            operation = self.replay()
            interval = self.saturation()
            with self.connection() as rpc:
                self.poll_read('durable-cancel', lambda: rpc.query(self.handle),
                    lambda value: durable_cancel(value['snapshot'], self.handle, operation))
                description = rpc.describe()
                write_json('before-retirement.json', description)
                kernel = description['runtime']['kernel']
                require(description['clock_healthy'] and description['runtime']['health']['healthy']
                    and description['runtime']['event_stream_healthy'] and same_operation(kernel, operation)
                    and kernel['operation_state'] == 4 and kernel['reason'] == 2
                    and kernel['left_permille'] == kernel['right_permille'] == 0, 'independent fault or unreconciled cancel')
            self.retire_recover()
            self.export(operation, interval)
            complete = True
        finally:
            if not complete:
                try:
                    self.local('revoke', label='failure-cleanup-revoke', closure=True)
                except BaseException as error:
                    write_json('cleanup-unknown.json', {'error': repr(error), 'automatic_retry': False})


if __name__ == '__main__':
    main('traffic', TrafficCampaign)
