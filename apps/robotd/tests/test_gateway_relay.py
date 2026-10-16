import socket
import time
import unittest

from test_failure_paths import echo_peer
from gateway_relay import CipherGate, tls_record_count


def record(payload):
    return b'\x17\x03\x03' + len(payload).to_bytes(2, 'big') + payload


class CipherGateTests(unittest.TestCase):
    def test_fragmented_record_is_not_complete_or_unbounded(self):
        data = record(b'opaque')
        for end in range(len(data)):
            self.assertEqual(tls_record_count(data[:end]), 0)
        self.assertEqual(tls_record_count(data), 1)
        self.assertEqual(tls_record_count(data * 2), 2)
        with self.assertRaises(AssertionError):
            tls_record_count(b'\x17\x03\x03\xff\xff')

    def test_capture_then_one_explicit_replay_never_reconnects(self):
        with echo_peer() as (port, received), CipherGate(port) as gate:
            with socket.create_connection(('127.0.0.1', gate.port), timeout=1) as client:
                client.sendall(b'handshake')
                self.assertEqual(client.recv(64), b'handshake')
                gate.arm('capture')
                data = record(b'one-proposal')
                client.sendall(data)
                self.assertEqual(client.recv(64), data)
                gate.seal()
                gate.forward_once()
                self.assertEqual(client.recv(64), data)
                with self.assertRaises(AssertionError):
                    gate.forward_once()
                self.assertEqual(bytes(received), b'handshake' + data * 2)
            report = gate.report()
            self.assertEqual(report['explicit_writes'], 1)
            self.assertEqual(report['captured_records'], 1)
            self.assertFalse(report['tls_terminated'])
            self.assertEqual(report['automatic_reconnects'], 0)

    def test_hold_requires_complete_record_then_forwards_exactly_once(self):
        with echo_peer() as (port, received), CipherGate(port) as gate:
            with socket.create_connection(('127.0.0.1', gate.port), timeout=1) as client:
                gate.arm('hold')
                data = record(b'delayed-proposal')
                client.sendall(data[:4])
                time.sleep(.02)
                with self.assertRaises(AssertionError):
                    gate.seal()
                self.assertEqual(bytes(received), b'')
                client.sendall(data[4:])
                gate.wait_record(.5)
                gate.seal()
                self.assertEqual(bytes(received), b'')
                gate.forward_once()
                self.assertEqual(client.recv(64), data)
                with self.assertRaises(AssertionError):
                    gate.forward_once()

    def test_capacity_or_exception_closes_without_flushing_held_bytes(self):
        with echo_peer() as (port, received), CipherGate(port, capture_limit=8) as gate:
            with socket.create_connection(('127.0.0.1', gate.port), timeout=1) as client:
                gate.arm('hold')
                client.sendall(record(b'over-capacity'))
                self.assertEqual(client.recv(64), b'')
            self.assertEqual(bytes(received), b'')
            self.assertEqual(gate.report()['explicit_writes'], 0)
            self.assertIn('capacity', gate.report()['error'])
        with self.assertRaises(RuntimeError), echo_peer() as (port, received):
            with CipherGate(port) as gate:
                raise RuntimeError('abort')
        self.assertFalse(gate.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
