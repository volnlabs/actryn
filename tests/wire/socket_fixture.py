#!/usr/bin/env python3
"""Independent Python socket/process contract checks; no physical target involved."""
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from generate import cobs

OFFSETS = {'boot':24,'session':32,'grant':56,'operation':64,'stream':72,
           'sequence':80,'transaction':88,'expiry':96,'time':104,'context':136}

def encode(kind, epoch=None, **fields):
    body = bytearray(152)
    struct.pack_into('<HH', body, 0, 2, kind)
    if epoch:
        body[8:56] = epoch[8:56]
    for name, value in fields.items():
        if name == 'nonce':
            body[40:56] = value
        elif name in ('left','right'):
            struct.pack_into('<i', body, 112 if name == 'left' else 116, value)
        else:
            struct.pack_into('<Q', body, OFFSETS[name], value)
    return cobs(body + struct.pack('<I', zlib.crc32(body)))

def decode(encoded):
    out = bytearray()
    i = 0
    while i < len(encoded):
        code = encoded[i]
        assert code and i + code <= len(encoded)
        out += encoded[i+1:i+code]
        i += code
        if code < 255 and i < len(encoded):
            out.append(0)
    assert len(out) == 156
    assert zlib.crc32(out[:152]) == struct.unpack_from('<I', out, 152)[0]
    return bytes(out)

def field(body, name):
    return struct.unpack_from('<Q', body, OFFSETS[name])[0]

class Peer:
    def __init__(self, sock):
        self.sock, self.pending = sock, bytearray()
    def receipt(self, kind, transaction, timeout=2):
        until = time.monotonic() + timeout
        while True:
            while 0 in self.pending:
                stop = self.pending.index(0)
                raw = bytes(self.pending[:stop])
                del self.pending[:stop+1]
                if not raw:
                    continue
                body = decode(raw)
                if struct.unpack_from('<H', body, 2)[0] == kind and field(body, 'transaction') == transaction:
                    return body
            remaining = until - time.monotonic()
            assert remaining > 0, (kind, transaction)
            self.sock.settimeout(remaining)
            data = self.sock.recv(4096)
            assert data, 'unexpected fixture disconnect'
            self.pending.extend(data)

def main(binary):
    with tempfile.TemporaryDirectory(prefix='actryn-fixture-') as d:
        d = pathlib.Path(d)
        command = [str(binary),'--socket',str(d/'wire'),'--state',str(d/'state'),'--admin',str(d/'admin')]
        process = subprocess.Popen(command, stderr=subprocess.PIPE)
        try:
            until = time.monotonic()+3
            while not (d/'admin').exists():
                assert process.poll() is None, process.stderr.read().decode()
                assert time.monotonic()<until
                time.sleep(.005)
            admin = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            admin.bind(str(d/'client'));admin.settimeout(1)
            def control(text):
                admin.sendto(text.encode(),str(d/'admin'))
                return admin.recv(1024).decode()
            for bad in ['delay -1','delay 2000000001','drop 33','status extra','x'*128]:
                assert control(bad) == 'ERROR\n'
            other = subprocess.run(command, capture_output=True, timeout=2)
            assert other.returncode != 0 and b'locked' in other.stderr
            wire = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            wire.connect(str(d/'wire'));peer = Peer(wire)
            wire.sendall(encode(1,nonce=b'X'*16,transaction=1))
            epoch = peer.receipt(2,1);assert field(epoch,'boot') == 1
            wire.sendall(encode(3,epoch,transaction=2,context=1));peer.receipt(4,2)
            expiry = field(epoch,'time')+1_500_000_000
            wire.sendall(encode(5,epoch,grant=1,operation=1,stream=1,transaction=3,context=1,expiry=expiry))
            started = peer.receipt(6,3)
            time.sleep(.11)
            assert control('delay 600000000') == 'OK\n'
            sample = encode(7,epoch,grant=1,operation=1,stream=1,sequence=1,
                            transaction=4,context=1,expiry=field(started,'time')+350_000_000,left=100,right=-100)
            wire.sendall(sample)
            time.sleep(.30)  # Host/guest does no RX progress; independent controller poll expires.
            status = control('status')
            assert 'state=Faulted' in status and 'duties=(0, 0, false)' in status, status
            applied = peer.receipt(8,4)
            assert struct.unpack_from('<ii',applied,112) == (100,-100)
            assert field(applied,'time') < field(started,'time')+350_000_000
            assert control('delay 0') == 'OK\n'
            assert control('restart') == 'OK\n'
            status = control('status');assert 'state=Inhibited' in status and 'boot=2' in status
            wire.sendall(sample)  # Old UART bytes do not adopt a reset.
            stale = peer.receipt(11,4)
            assert struct.unpack_from('<I',stale,144)[0] == 3
            # A new session must explicitly rearm, and quiesce retires delayed START.
            wire.sendall(encode(1,nonce=b'Y'*16,transaction=1));epoch2=peer.receipt(2,1)
            assert field(epoch2,'boot') == 2
            wire.sendall(encode(3,epoch2,transaction=2,context=1));peer.receipt(4,2)
            wire.sendall(encode(9,epoch2,grant=1,operation=9,stream=9,transaction=4,context=1))
            closed=peer.receipt(10,4)
            wire.sendall(encode(5,epoch2,grant=1,operation=9,stream=9,transaction=3,context=1,
                                expiry=field(closed,'time')+500_000_000))
            assert struct.unpack_from('<I',peer.receipt(11,3),144)[0] == 3
            # Drop and replay are separate local controls, never protocol commands.
            assert control('drop 1') == 'OK\n'
            wire.sendall(encode(9,epoch2,grant=1,operation=10,stream=10,transaction=5,context=1))
            time.sleep(.01)
            assert control('replay') == 'OK\n'
            peer.receipt(10,5)
            # A timed-out immutable prefix cannot be spliced into a new command.
            wire.sendall(b'\x02')
            time.sleep(.55)
            wire.sendall(b'\x02\0')
            wire.sendall(b'\x01'*10000+b'\0')
            wire.sendall(encode(9,epoch2,grant=1,operation=11,stream=11,transaction=6,context=1))
            peer.receipt(10,6)
            # With held receipts, a finite output queue overflows closed, never grows.
            assert control('delay 2000000000') == 'OK\n'
            start=encode(5,epoch2,grant=1,operation=12,stream=12,transaction=7,context=1,
                         expiry=field(closed,'time')+1_000_000_000)
            wire.sendall(start*40)
            until=time.monotonic()+1
            while 'state=Faulted' not in control('status'):
                assert time.monotonic()<until
                time.sleep(.005)
            assert 'queued=0' in control('status')
            wire.close()
            until=time.monotonic()+1
            while 'state=Faulted' not in control('status'):
                assert time.monotonic()<until
                time.sleep(.005)
            admin.sendto(b'shutdown',str(d/'admin'))
            assert process.wait(timeout=2)==0
            process=subprocess.Popen(command,stderr=subprocess.PIPE)
            until=time.monotonic()+2
            while not (d/'admin').exists():
                assert process.poll() is None
                assert time.monotonic()<until
                time.sleep(.005)
            status=control('status')
            assert 'boot=3' in status and 'state=Inhibited' in status,status
            wire3=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            wire3.connect(str(d/'wire'));peer3=Peer(wire3)
            wire3.sendall(encode(1,nonce=b'Z'*16,transaction=1));epoch3=peer3.receipt(2,1)
            assert control('sink-fail') == 'OK\n'
            wire3.sendall(encode(3,epoch3,transaction=2,context=1))
            failure=peer3.receipt(11,2)
            assert struct.unpack_from('<I',failure,144)[0] == 7
            assert 'state=Faulted' in control('status')
            wire3.close()
            admin.sendto(b'shutdown',str(d/'admin'))
            assert process.wait(timeout=2)==0
            # Corrupt/ambiguous persistence never serves a socket or resets its identity.
            with (d/'state').open('ab') as f:
                f.write(b'\x00')
            broken=subprocess.run(command,capture_output=True,timeout=2)
            assert broken.returncode != 0 and b'ambiguous' in broken.stderr
            assert not (d/'wire').exists()
            admin.close()
        finally:
            if process.poll() is None:
                process.kill();process.wait()
    print('independent socket/process expiry, replay, retirement, restart, lock and corrupt-state checks passed')

if __name__ == '__main__':
    main(pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'target/debug/controller-fixture').resolve())
