import copy
import socket
import struct
import threading
import unittest

from gateway_traffic import no_pending_tcp, rejected_frame, request, unchanged_authority
from guest import wire


class HostileFrameTests(unittest.TestCase):
    def test_only_correlated_explicit_rejection_or_eof_counts(self):
        message = request(b'e' * 16, 'grant', wire.Grant(duration_ms=60000))
        for outcome in ('eof', 'rejected', 'admitted', 'wrong-id', 'unknown'):
            left, right = socket.socketpair()
            sent = []
            response = wire.Response(version=1, request_id=message.request_id, robot_epoch=b'e' * 16)
            response.failure.code = wire.Failure.REJECTED
            if outcome == 'wrong-id':
                response.request_id = b'x' * 16
            if outcome == 'admitted':
                response.report.json = b'{}'
            if outcome == 'unknown':
                response.failure.code = wire.Failure.OUTCOME_UNKNOWN
            encoded = response.SerializeToString(deterministic=True)
            def serve():
                with right:
                    sent.append(right.recv(4096))
                    if outcome != 'eof':
                        right.sendall(struct.pack('!I', len(encoded)) + encoded)
            worker = threading.Thread(target=serve); worker.start()
            try:
                if outcome in ('eof', 'rejected'):
                    self.assertTrue(rejected_frame(left, b'once', message)['rejected'])
                else:
                    with self.assertRaises(AssertionError):
                        rejected_frame(left, b'once', message)
                self.assertEqual(sent, [b'\x00\x00\x00\x04once'])
            finally:
                left.close(); worker.join(1)

    def test_peek_preserves_bytes_flags_and_rejects_closed_holder(self):
        left, right = socket.socketpair()
        try:
            no_pending_tcp(left)
            self.assertTrue(left.getblocking())
            right.sendall(b'a')
            with self.assertRaises(AssertionError):
                no_pending_tcp(left)
            self.assertEqual(left.recv(1), b'a')
            right.close()
            with self.assertRaises(AssertionError):
                no_pending_tcp(left)
        finally:
            left.close(); right.close()

    def test_negative_traffic_cannot_renew_deadline_or_hide_health_loss(self):
        before = {'clock_healthy': True, 'runtime': {'event_stream_healthy': True,
            'health': {'healthy': True}, 'kernel': dict.fromkeys(('runtime_nonce', 'instance', 'grant',
            'deadline_ns', 'state', 'operation', 'stream', 'operation_state', 'left_permille', 'right_permille'), 0)}}
        unchanged_authority(before, copy.deepcopy(before))
        for field in ('deadline_ns', 'grant', 'operation'):
            after = copy.deepcopy(before)
            after['runtime']['kernel'][field] += 1
            with self.assertRaises(AssertionError):
                unchanged_authority(before, after)
        after = copy.deepcopy(before); after['clock_healthy'] = False
        with self.assertRaises(AssertionError):
            unchanged_authority(before, after)


if __name__ == '__main__':
    unittest.main()
