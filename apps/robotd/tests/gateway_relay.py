"""One bounded opaque TLS relay for explicit A10 capture/replay or delayed send.

This never decrypts TLS, reconnects, or retries a failed write. Only one complete
post-handshake application record may be captured; a second record fails closed.
"""
import hashlib
import select
import socket
import threading
import time


def tls_record_count(data):
    offset, count = 0, 0
    while offset < len(data):
        if len(data) - offset < 5:
            return 0
        assert data[offset:offset+3] == b'\x17\x03\x03', 'application TLS record required'
        size = int.from_bytes(data[offset+3:offset+5], 'big')
        assert 0 < size <= 18432, 'TLS record capacity'
        if len(data) - offset < size + 5:
            return 0
        offset += size + 5
        count += 1
    return count


class CipherGate:
    def __init__(self, upstream_port, *, capture_limit=18437):
        assert 0 < upstream_port <= 65535 and 0 < capture_limit <= 18437
        self.upstream_port, self.limit = upstream_port, capture_limit
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(.05)
        self.port = self.listener.getsockname()[1]
        self.lock, self.stop, self.forwarded = threading.Lock(), threading.Event(), threading.Event()
        self.connections, self.captured = [], bytearray()
        self.mode, self.sealed, self.pending = None, False, False
        self.stats = {'connections': 0, 'total_bytes': 0, 'explicit_writes': 0, 'post_seal_dropped_bytes': 0,
                      'armed_ns': None, 'first_capture_ns': None, 'write_started_ns': None,
                      'write_finished_ns': None, 'error': None}
        self.worker = threading.Thread(target=self._run, name='a10-cipher-gate', daemon=True)

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, *_):
        self.close()

    def arm(self, mode):
        with self.lock:
            assert mode in ('capture', 'hold') and self.mode is None and not self.stop.is_set()
            self.mode = mode
            self.stats['armed_ns'] = time.monotonic_ns()

    def wait_record(self, timeout=.5):
        assert 0 < timeout <= .5
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                assert self.stats['error'] is None and not self.stop.is_set(), self.stats
                if tls_record_count(self.captured) == 1:
                    return
            assert time.monotonic() < deadline, 'ciphertext did not arrive within bound'
            time.sleep(.002)

    def seal(self):
        with self.lock:
            assert self.mode is not None and not self.sealed and self.stats['error'] is None
            assert tls_record_count(self.captured) == 1, 'exactly one complete TLS record required'
            self.sealed = True

    def forward_once(self):
        with self.lock:
            assert self.sealed and self.stats['explicit_writes'] == 0 and not self.stop.is_set()
            # Charge the only permitted malicious replay/release before doing I/O.
            self.stats['explicit_writes'] = 1
            self.pending = True
        assert self.forwarded.wait(.75), 'explicit ciphertext write outcome unknown; never retry'
        with self.lock:
            assert self.stats['error'] is None and self.stats['write_finished_ns'] is not None, self.stats

    def report(self):
        with self.lock:
            try:
                records = tls_record_count(self.captured)
            except AssertionError:
                records = None  # Keep malformed/partial data diagnostics inspectable.
            return dict(self.stats, mode=self.mode, sealed=self.sealed, captured_bytes=len(self.captured),
                        captured_sha256=hashlib.sha256(self.captured).hexdigest(),
                        captured_records=records, capture_limit=self.limit,
                        tls_terminated=False, automatic_reconnects=0, automatic_retries=0)

    def _run(self):
        deadline = time.monotonic() + 20
        try:
            client = None
            while client is None and not self.stop.is_set():
                assert time.monotonic() < deadline, 'relay lifetime'
                try:
                    client, _ = self.listener.accept()
                except TimeoutError:
                    continue
            if client is None:
                return
            self.connections.append(client)
            upstream = socket.create_connection(('127.0.0.1', self.upstream_port), timeout=1)
            self.connections.append(upstream)
            for connection in self.connections:
                connection.settimeout(.25)
            with self.lock:
                self.stats['connections'] = 1
            while not self.stop.is_set():
                assert time.monotonic() < deadline, 'relay lifetime'
                with self.lock:
                    if self.pending:
                        self.pending = False
                        self.stats['write_started_ns'] = time.monotonic_ns()
                        upstream.sendall(self.captured)
                        self.stats['write_finished_ns'] = time.monotonic_ns()
                        self.forwarded.set()
                for source in select.select(self.connections, [], [], .005)[0]:
                    data = source.recv(4096)
                    if not data:
                        return
                    destination = upstream if source is client else client
                    with self.lock:
                        assert self.stats['total_bytes'] + len(data) <= 262144, 'relay total capacity'
                        self.stats['total_bytes'] += len(data)
                        if source is client and self.mode:
                            if self.sealed:
                                # TLS may send its own fatal alert after the malicious replay.
                                # No second client record may reach the actual gateway.
                                self.stats['post_seal_dropped_bytes'] += len(data)
                                assert self.stats['post_seal_dropped_bytes'] <= self.limit, 'post-seal capacity'
                                continue
                            assert len(self.captured) + len(data) <= self.limit, 'capture capacity'
                            self.captured.extend(data)
                            self.stats['first_capture_ns'] = self.stats['first_capture_ns'] or time.monotonic_ns()
                            assert tls_record_count(self.captured) <= 1, 'multiple client records'
                            if self.mode == 'hold':
                                continue
                        destination.sendall(data)
        except BaseException as error:
            if not self.stop.is_set():
                with self.lock:
                    self.stats['error'] = repr(error)
        finally:
            self.stop.set()
            self.forwarded.set()
            for connection in self.connections:
                connection.close()
            self.listener.close()

    def close(self):
        self.stop.set()
        for connection in self.connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        if self.worker.ident:
            self.worker.join(1)
            assert not self.worker.is_alive(), 'relay cleanup deadline'
