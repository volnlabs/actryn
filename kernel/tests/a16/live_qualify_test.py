import errno
import socket
import struct
import threading
import unittest

import live_qualify as q


class QualificationProtocolTests(unittest.TestCase):
    def test_request_layout_independent_offsets(self):
        data = q.request(13, nonce=b'N' * 16, deadline=123)
        self.assertEqual(len(data), 192)
        self.assertEqual(struct.unpack_from('<4I', data), (1, 13, 0, 0))
        self.assertEqual(data[16:32], b'N' * 16)
        self.assertEqual(struct.unpack_from('<Q', data, 80)[0], 123)
        self.assertEqual(data[88:], bytes(104))

    def test_status_layout_independent_offsets(self):
        data = bytearray(192)
        struct.pack_into('<III', data, 0, 1, 4, 5)
        struct.pack_into('<QQ', data, 48, 77, 2)
        struct.pack_into('<IIII', data, 176, 5, 9, 1, 0)
        status = q.decode_status(data)
        self.assertEqual((status['state'], status['operation_state']), (4, 5))
        self.assertEqual((status['boot'], status['session']), (77, 2))
        self.assertEqual((status['reason'], status['lost'], status['flags']), (5, 9, 1))

    def test_real_seqpacket_exchange_keeps_denial(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        def server():
            data = b.recv(201)
            self.assertEqual(data, struct.pack('<II', 3, 0) + bytes(192))
            b.send(struct.pack('<iI', -errno.EPERM, 0) + bytes(216))
        thread = threading.Thread(target=server)
        thread.start()
        try:
            error, payload = q.exchange(a, 3)
            self.assertEqual(error, -errno.EPERM)
            self.assertEqual(len(payload), 216)
        finally:
            thread.join(2)
            a.close()
            b.close()

    def test_malformed_reply_is_rejected(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            b.send(bytes(225))
            with self.assertRaises(ValueError):
                q.exchange(a, 3)
        finally:
            a.close()
            b.close()


if __name__ == '__main__':
    unittest.main()
