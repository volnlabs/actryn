#!/usr/bin/env python3
"""Actual tracepoint acceptance; run as root only inside the disposable Debian test guest."""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid

SOCKET = Path('/run/actryn/observer.sock')

def exchange(request):
    data = json.dumps(request).encode()
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        s.connect(str(SOCKET))
        s.sendall(struct.pack('>I', len(data)) + data)
        header = s.recv(4)
        if len(header) != 4:
            return None
        size, = struct.unpack('>I', header)
        assert size <= 65536
        data = b''
        while len(data) < size:
            part = s.recv(size - len(data))
            assert part
            data += part
        return json.loads(data)

def main():
    assert os.geteuid() == 0
    assert os.uname().release == '6.12.111+deb13-amd64'
    assert not SOCKET.exists(), 'stop the existing observer through its service before testing'
    root = Path('/sys/fs/cgroup/actryn')
    root.mkdir(exist_ok=True)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    groups = []
    with tempfile.TemporaryDirectory() as tmp:
        with open(Path(tmp) / 'stderr', 'wb') as stderr:
            observer = subprocess.Popen(['/usr/bin/actryn-observer'], stderr=stderr)
            try:
                deadline = time.monotonic() + 10
                while not SOCKET.exists():
                    assert observer.poll() is None, Path(tmp, 'stderr').read_text()
                    assert time.monotonic() < deadline
                    time.sleep(.02)
                for exhaust in (False, True):
                    attempt = uuid.uuid4().hex
                    cg = root / attempt
                    cg.mkdir()
                    groups.append(cg)
                    request = dict(op='register', attempt_id=attempt, boot_id=boot,
                                   cgroup_id=cg.stat().st_ino, cgroup_path='/actryn/' + attempt)
                    status = exchange(request)
                    assert status['ready'] and status['lost'] == 0, status
                    assert exchange(dict(request, boot_id='wrong-boot')) is None
                    assert exchange(dict(request, cgroup_path='/system.slice')) is None
                    assert exchange(dict(request, attempt_id='b' * 32)) is None
                    def enter():
                        (cg / 'cgroup.procs').write_text(str(os.getpid()))
                    script = ("for _ in range(30000):\n with open('/dev/null','rb'): pass\n" if exhaust else
                              "import os, subprocess\nsubprocess.run(['/bin/cat','/dev/null'])\n"
                              "try: open('/actryn-absent-fixture')\nexcept OSError: pass\n")
                    subprocess.run(['/usr/bin/python3', '-c', script], preexec_fn=enter, check=True, timeout=30)
                    time.sleep(.2)
                    status = exchange(dict(request, op='health'))
                    assert status['sequence'] > 0
                    assert status['ready'] is not exhaust, status
                    assert (status['lost'] > 0) is exhaust, status
                    log = Path('/var/lib/actryn-observer') / status['collector_epoch'] / (attempt + '.jsonl')
                    deadline = time.monotonic() + 5
                    while exchange(dict(request, op='unregister')) is None:
                        assert time.monotonic() < deadline, Path(tmp, 'stderr').read_text()
                        time.sleep(.1)
                    assert log.stat().st_size <= 16 * 1024 * 1024
                    records = [json.loads(line) for line in log.read_text().splitlines()]
                    assert records and all(r['attempt_id'] == attempt and r['boot_id'] == boot for r in records)
                    assert all(r['event']['origin'] == 'linux.tracepoint' for r in records)
                    assert not any(r['event']['classification'] == 'policy_denied' for r in records)
                    if not exhaust:
                        assert {1, 2, 3, 4, 5} <= {r['event']['kind'] for r in records}
                        assert any(r['event']['classification'] == 'access_failed' for r in records)
                        assert any(r['event']['kind'] == 2 and r['event']['result'] >= 0 for r in records)
                    assert log.with_suffix('.summary.json').exists()
                    assert not exchange(dict(request, op='health'))['ready']
                print('actual BPF lifecycle/syscall attribution, malformed identity, finite retention and loss checks passed')
            finally:
                if sys.exc_info()[0]:
                    print(Path(tmp, 'stderr').read_text(), file=sys.stderr)
                observer.terminate()
                observer.wait(timeout=5)
                SOCKET.unlink(missing_ok=True)
                for cg in groups:
                    (cg / 'cgroup.kill').write_text('1')
                    cg.rmdir()

if __name__ == '__main__':
    main()
