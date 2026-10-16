"""Test-only bounded TCP relay. TLS stays end-to-end; held bytes are never replayed."""
import hashlib
import select
import socket
import threading
import time


class ReplyGate:
    def __init__(self, upstream_port, *, held_limit=65536, upstream_limit=73728):
        assert 0 < upstream_port <= 65535 and 0 < held_limit <= 65536 and 0 < upstream_limit <= 73728
        self.upstream_port = upstream_port
        self.held_limit, self.upstream_limit = held_limit, upstream_limit
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(.1)
        self.port = self.listener.getsockname()[1]
        self.connections = []
        self.gated = False
        self.digest = hashlib.sha256()
        self.stats = {'armed_ns': None, 'gated_upstream_bytes': 0, 'withheld_bytes': 0,
                      'gated_downstream_forwarded': 0, 'total_forwarded': 0,
                      'connections': 0, 'first_withheld_ns': None, 'error': None}
        self.worker = threading.Thread(target=self._run, name='a02-reply-gate', daemon=True)

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, *_):
        self.close()

    def arm(self):
        with self.lock:
            assert not self.gated and not self.stop.is_set(), 'reply gate cannot reopen or rearm'
            self.gated = True
            self.stats['armed_ns'] = time.monotonic_ns()

    def report(self):
        with self.lock:
            return dict(self.stats, withheld_sha256=self.digest.hexdigest(),
                        held_limit=self.held_limit, upstream_limit=self.upstream_limit,
                        tls_terminated=False, automatic_reconnects=0, withheld_replayed=False)

    def _run(self):
        deadline = time.monotonic() + 20
        try:
            client = None
            while client is None and not self.stop.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('relay lifetime')
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
                connection.settimeout(.5)
            with self.lock:
                self.stats['connections'] = 1
            while not self.stop.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('relay lifetime')
                readable, _, _ = select.select(self.connections, [], [], .05)
                for source in readable:
                    data = source.recv(4096)
                    if not data:
                        return
                    destination = upstream if source is client else client
                    with self.lock:
                        if self.gated and source is upstream:
                            self.stats['withheld_bytes'] += len(data)
                            self.digest.update(data)
                            self.stats['first_withheld_ns'] = self.stats['first_withheld_ns'] or time.monotonic_ns()
                            assert self.stats['withheld_bytes'] <= self.held_limit, 'withheld ciphertext capacity'
                            continue
                        if self.gated:
                            assert self.stats['gated_upstream_bytes'] + len(data) <= self.upstream_limit, 'proposal ciphertext capacity'
                            self.stats['gated_upstream_bytes'] += len(data)
                        assert self.stats['total_forwarded'] + len(data) <= 262144, 'relay total capacity'
                        destination.sendall(data)
                        self.stats['total_forwarded'] += len(data)
        except BaseException as error:
            if not self.stop.is_set():
                with self.lock:
                    self.stats['error'] = repr(error)
        finally:
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
            self.worker.join(2)
            assert not self.worker.is_alive(), 'relay worker did not terminate'
