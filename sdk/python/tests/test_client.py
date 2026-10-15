import json
import socket
import struct
import threading
import time
import unittest
from actryn import Client, RequestHandle, OutcomeUnknown, RpcError
from actryn import robot_v1_pb2 as wire

class ClientTests(unittest.TestCase):
    def client(self):
        client=Client.__new__(Client)
        client._socket,peer=socket.socketpair()
        client._socket.settimeout(.2)
        client._epoch=b'e'*16
        client._timeout=.2
        self.addCleanup(client.close);self.addCleanup(peer.close)
        return client,peer

    def test_handle_survives_roundtrip_and_cannot_change(self):
        handle=RequestHandle.create(b'a'*16,b'n'*16)
        self.assertEqual(RequestHandle.from_json(json.loads(json.dumps(handle.json()))),handle)
        with self.assertRaises(AttributeError): handle.key=b'x'*32
        with self.assertRaises(ValueError): RequestHandle(b'a',b'n',b'k')

    def test_lost_proposal_reply_never_resends_or_replaces_handle(self):
        client,peer=self.client();handle=RequestHandle.create(b'a'*16,b'n'*16)
        original=handle.json()
        with self.assertRaises(OutcomeUnknown):
            client.propose(handle,observation_id=1,left_delta_ticks=10,right_delta_ticks=10,duration_ms=1000,parent_digest=b'd'*32)
        size,=struct.unpack('!I',peer.recv(4));request=wire.Request.FromString(peer.recv(size))
        self.assertEqual(request.propose.handle.key,handle.key)
        self.assertEqual(peer.recv(1),b'')
        self.assertEqual(handle.json(),original)

    def test_readonly_query_retains_original_key(self):
        client,peer=self.client();handle=RequestHandle.create(b'a'*16,b'n'*16)
        def reply():
            size,=struct.unpack('!I',peer.recv(4));request=wire.Request.FromString(peer.recv(size))
            assert request.query.key==handle.key
            response=wire.Response(version=1,request_id=request.request_id,robot_epoch=b'e'*16,
                report=wire.Report(json=b'{"phase":"OutcomeUnknown"}'))
            data=response.SerializeToString(deterministic=True);peer.sendall(struct.pack('!I',len(data))+data)
        worker=threading.Thread(target=reply);worker.start()
        self.assertEqual(client.query(handle),{'phase':'OutcomeUnknown'});worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_invalid_targets_do_not_send(self):
        client,peer=self.client();handle=RequestHandle.create(b'a'*16,b'n'*16)
        with self.assertRaises(ValueError):
            client.propose(handle,observation_id=1,left_delta_ticks=101,right_delta_ticks=0,duration_ms=1,parent_digest=b'd'*32)
        peer.settimeout(.05)
        with self.assertRaises(TimeoutError):peer.recv(1)

    def test_evidence_read_rejects_paths_before_transport_and_retains_identity(self):
        client,peer=self.client();handle=RequestHandle.create(b'a'*16,b'n'*16)
        with self.assertRaises(ValueError):client.evidence_read(handle,file='../key.pem')
        with self.assertRaises(ValueError):client.evidence_read(handle,offset=67108865)
        def reply():
            size,=struct.unpack('!I',peer.recv(4));request=wire.Request.FromString(peer.recv(size))
            assert request.evidence_read.handle.key==handle.key
            assert request.evidence_read.file=='checkpoints.sqlite'
            response=wire.Response(version=1,request_id=request.request_id,robot_epoch=b'e'*16,
                report=wire.Report(json=b'{"data_hex":"61","next_offset":1}'))
            data=response.SerializeToString(deterministic=True);peer.sendall(struct.pack('!I',len(data))+data)
        worker=threading.Thread(target=reply);worker.start()
        self.assertEqual(client.evidence_read(handle,file='checkpoints.sqlite')['data_hex'],'61')
        worker.join(1);self.assertFalse(worker.is_alive())

    def test_forged_reply_correlation_is_unknown_for_cancel(self):
        client,peer=self.client();handle=RequestHandle.create(b'a'*16,b'n'*16)
        response=wire.Response(version=1,request_id=b'wrong'*3,robot_epoch=b'e'*16,report=wire.Report(json=b'{}'))
        data=response.SerializeToString(deterministic=True);peer.sendall(struct.pack('!I',len(data))+data)
        with self.assertRaises(OutcomeUnknown):client.cancel(handle)

    def test_malformed_mutation_result_is_unknown_and_closes(self):
        for result in [None, wire.Observation(id=1), wire.Failure(code=99)]:
            client,peer=self.client();handle=RequestHandle.create(b'a'*16,b'n'*16)
            def reply():
                size,=struct.unpack('!I',peer.recv(4));request=wire.Request.FromString(peer.recv(size))
                response=wire.Response(version=1,request_id=request.request_id,robot_epoch=b'e'*16)
                if isinstance(result, wire.Observation):response.observation.CopyFrom(result)
                if isinstance(result, wire.Failure):response.failure.CopyFrom(result)
                data=response.SerializeToString(deterministic=True);peer.sendall(struct.pack('!I',len(data))+data)
            worker=threading.Thread(target=reply);worker.start()
            with self.assertRaises(OutcomeUnknown):client.cancel(handle)
            worker.join(1);self.assertEqual(client._socket.fileno(),-1)

    def test_slow_bytes_cannot_extend_absolute_request_deadline(self):
        client,peer=self.client();client._timeout=.08
        handle=RequestHandle.create(b'a'*16,b'n'*16)
        def reply():
            size,=struct.unpack('!I',peer.recv(4));request=wire.Request.FromString(peer.recv(size))
            response=wire.Response(version=1,request_id=request.request_id,robot_epoch=b'e'*16,report=wire.Report(json=b'{}'))
            data=response.SerializeToString(deterministic=True)
            try:
                for byte in struct.pack('!I',len(data))+data:
                    peer.sendall(bytes([byte]));time.sleep(.025)
            except OSError:pass
        worker=threading.Thread(target=reply);worker.start();started=time.monotonic()
        with self.assertRaises(OutcomeUnknown):client.cancel(handle)
        self.assertLess(time.monotonic()-started,.35)
        worker.join(1);self.assertFalse(worker.is_alive())

if __name__=='__main__':unittest.main()
