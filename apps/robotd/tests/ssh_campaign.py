"""One owned SSH master for a disposable campaign; passengers cannot reconnect."""
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

from guest import write_json


def passenger_command(common, destination, control):
    # OpenSSH normally falls back to a new transport if the master disappears.
    # A fixed failing proxy makes that path fail before any network connection.
    return [*common, '-o', 'ControlMaster=no', '-o', 'ControlPersist=no',
            '-o', 'ControlPath=' + str(control), '-o', 'ProxyCommand=/usr/bin/false', destination]


class SharedSsh:
    def __init__(self, base, output):
        assert base[0] == 'ssh' and base[-1] == 'root@127.0.0.1'
        self.destination = base[-1]
        self.common = ['ssh', '-F', '/dev/null', *base[1:-1], '-o', 'ForwardAgent=no',
                       '-o', 'ForwardX11=no', '-o', 'ClearAllForwardings=yes',
                       '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes']
        self.output = output
        self.process = self.directory = self.log = None

    def __enter__(self):
        try:
            self.directory = tempfile.TemporaryDirectory(prefix='actryn-ssh-')
            root = Path(self.directory.name)
            meta = root.stat()
            assert meta.st_uid == os.getuid() and meta.st_mode & 0o077 == 0
            self.control = root / 'control'
            assert len(os.fsencode(self.control)) < 100
            self.command = passenger_command(self.common, self.destination, self.control)
            self.log = (self.output / 'ssh-master.stderr').open('xb')
            started = time.monotonic_ns()
            self.process = subprocess.Popen([*self.common, '-o', 'ControlMaster=yes',
                '-o', 'ControlPersist=no', '-o', 'ControlPath=' + str(self.control), '-N', self.destination],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.log)
            deadline = time.monotonic() + 8
            while True:
                assert self.process.poll() is None, 'SSH master exited before readiness; no retry'
                if self.control.exists():
                    meta = self.control.lstat()
                    assert stat.S_ISSOCK(meta.st_mode) and meta.st_uid == os.getuid() and meta.st_mode & 0o077 == 0
                    result = subprocess.run([*self.command[:-1], '-O', 'check', self.destination],
                                            capture_output=True, timeout=1)
                    if result.returncode == 0:
                        match = re.search(rb'pid=(\d+)', result.stderr)
                        assert match and int(match[1]) == self.process.pid, 'master PID mismatch'
                        break
                assert time.monotonic() < deadline, 'SSH master readiness deadline; no retry'
                time.sleep(.025)
            write_json('ssh-master.json', {'pid': self.process.pid, 'control_path': str(self.control),
                'started_at_host_ns': started, 'ready_at_host_ns': time.monotonic_ns(),
                'master_starts': 1, 'automatic_reconnect': False, 'network_fallback': False})
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        process, self.process = self.process, None
        result = {'automatic_retry': False, 'master_exited': process is None}
        try:
            if process is not None:
                if process.poll() is None:
                    # The foreground Popen child is owned by this invocation.
                    # Never signal a PID merely read from a control socket.
                    process.terminate()
                    result['owned_master_sigterm'] = True
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        result['owned_master_sigkill'] = True
                        process.wait(timeout=1)
                result['master_exited'] = process.poll() is not None
                result['returncode'] = process.returncode
        finally:
            write_json('ssh-master-cleanup.json', result)
            if self.log is not None:
                self.log.close()
                self.log = None
            if self.directory is not None:
                self.directory.cleanup()
                self.directory = None

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as cleanup_error:
            write_json('ssh-master-cleanup-error.json', {'error': repr(cleanup_error), 'automatic_retry': False})
            if kind is None:
                raise
