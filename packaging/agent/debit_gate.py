"""Test-only finite TCP admission gate; ciphertext is neither decoded nor replayed."""
import hashlib
import copy
import select
import socket
import threading
import time


class ConnectionGate:
    def __init__(self, port, upstream_port, *, lifetime=1200, connections=64,
                 active=8, per_connection=262144, total_bytes=8 * 1024 * 1024):
        assert 0 <= port <= 65535 and 0 < upstream_port <= 65535
        assert 0 < lifetime <= 1200 and 0 < connections <= 64 and 0 < active <= 8
        assert 0 < per_connection <= 262144 and 0 < total_bytes <= 8 * 1024 * 1024
        self.upstream_port = upstream_port
        self.deadline = time.monotonic() + lifetime
        self.maximum, self.active_max = connections, active
        self.per_connection, self.total_max = per_connection, total_bytes
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', port)); self.listener.listen(active)
        self.listener.settimeout(.05)
        self.port = self.listener.getsockname()[1]
        self.closed = False
        self.sockets, self.workers = set(), []
        self.stats = {'connections': 0, 'active': 0, 'blocked_active': 0,
                      'bytes_observed': 0, 'bytes_forwarded': 0, 'blocked_bytes': 0,
                      'arms': [], 'error': None}
        self.digest = hashlib.sha256()
        self.thread = threading.Thread(target=self._accept, daemon=True)

    def __enter__(self):
        self.thread.start(); return self

    def __exit__(self, *_):
        self.close()

    def arm(self, identity):
        assert set(identity) == {'device', 'boot', 'session', 'runtime_nonce',
                                 'grant', 'instance', 'operation', 'stream'}
        assert len(identity['device']) == len(identity['runtime_nonce']) == 16
        assert any(identity['device']) and any(identity['runtime_nonce'])
        assert all(type(identity[k]) is int and identity[k] > 0 for k in
                   ('boot', 'session', 'grant', 'instance', 'operation', 'stream'))
        with self.lock:
            assert not self.closed and len(self.stats['arms']) < 5 and not self.stop.is_set()
            self.closed = True
            self.stats['arms'].append({'at_monotonic_ns': time.monotonic_ns(),
                                       'operation': copy.deepcopy(identity)})

    def pass_future(self):
        with self.lock:
            assert self.closed and self.stats['blocked_active'] == 0 and not self.stop.is_set()
            self.closed = False  # Old blocked sockets are never reopened or replayed.

    def report(self):
        with self.lock:
            return dict(self.stats, arms=copy.deepcopy(self.stats['arms']), future_connections_blocked=self.closed,
                        port=self.port, remaining_s=max(0, self.deadline - time.monotonic()),
                        ciphertext_sha256=self.digest.hexdigest(), tls_terminated=False,
                        withheld_replayed=False, automatic_reconnects=0)

    def _accept(self):
        try:
            while not self.stop.is_set():
                assert time.monotonic() < self.deadline, 'gate lifetime exceeded'
                try: client, _ = self.listener.accept()
                except TimeoutError: continue
                with self.lock:
                    if self.stats['connections'] >= self.maximum or self.stats['active'] >= self.active_max:
                        client.close(); raise AssertionError('gate connection capacity')
                    blocked = self.closed
                    self.stats['connections'] += 1; self.stats['active'] += 1
                    self.stats['blocked_active'] += int(blocked)
                    self.sockets.add(client)
                worker = threading.Thread(target=self._copy, args=(client, blocked), daemon=True)
                self.workers.append(worker); worker.start()
        except BaseException as error:
            if not self.stop.is_set(): self._fail(error)

    def _fail(self, error):
        with self.lock:
            self.stats['error'] = self.stats['error'] or repr(error)
        self.stop.set()

    def _copy(self, client, blocked):
        pair = [client]
        used = 0
        deadline = min(self.deadline, time.monotonic() + (6 if blocked else 15))
        try:
            if not blocked:
                upstream = socket.create_connection(('127.0.0.1', self.upstream_port), timeout=1)
                pair.append(upstream)
                with self.lock: self.sockets.add(upstream)
            for stream in pair: stream.settimeout(.2)
            while not self.stop.is_set() and time.monotonic() < deadline:
                readable, _, _ = select.select(pair, [], [], .05)
                for source in readable:
                    data = source.recv(4096)
                    if not data: return
                    with self.lock:
                        assert used + len(data) <= self.per_connection, 'gate per-connection bytes'
                        assert self.stats['bytes_observed'] + len(data) <= self.total_max, 'gate total bytes'
                        used += len(data); self.stats['bytes_observed'] += len(data)
                        self.digest.update(data)
                        if blocked: self.stats['blocked_bytes'] += len(data)
                    if not blocked:
                        pair[1 if source is client else 0].sendall(data)
                        with self.lock: self.stats['bytes_forwarded'] += len(data)
        except BaseException as error:
            if not self.stop.is_set(): self._fail(error)
        finally:
            with self.lock:
                for stream in pair: self.sockets.discard(stream)
                self.stats['active'] -= 1; self.stats['blocked_active'] -= int(blocked)
            for stream in pair: stream.close()

    def close(self):
        self.stop.set(); self.listener.close()
        with self.lock: streams = list(self.sockets)
        for stream in streams:
            try: stream.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        deadline = time.monotonic() + 2
        for worker in [self.thread, *self.workers]:
            if worker.ident: worker.join(max(0, deadline - time.monotonic()))
        assert not any(worker.is_alive() for worker in [self.thread, *self.workers]), 'gate cleanup unknown'
