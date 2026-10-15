from dataclasses import dataclass
import hashlib
import json
import secrets
import socket
import ssl
import struct
import time
from . import robot_v1_pb2 as wire

MAX_MESSAGE = 65536

class RpcError(Exception):
    pass

class OutcomeUnknown(RpcError):
    """Delivery/reply is uncertain. Query the original handle on a new connection."""

@dataclass(frozen=True)
class RequestHandle:
    attempt: bytes
    namespace: bytes
    key: bytes

    def __post_init__(self):
        if not all(isinstance(value, bytes) for value in (self.attempt, self.namespace, self.key)):
            raise TypeError('handle fields must be immutable bytes')
        if (len(self.attempt), len(self.namespace), len(self.key)) != (16, 16, 32):
            raise ValueError('invalid stable request handle')

    @classmethod
    def create(cls, attempt: bytes, namespace: bytes):
        return cls(attempt, namespace, secrets.token_bytes(32))

    def json(self):
        return {name: getattr(self, name).hex() for name in ('attempt', 'namespace', 'key')}

    @classmethod
    def from_json(cls, document):
        if set(document) != {'attempt', 'namespace', 'key'}:
            raise ValueError('invalid handle fields')
        return cls(*(bytes.fromhex(document[name]) for name in ('attempt', 'namespace', 'key')))

    def _wire(self):
        return wire.Handle(attempt=self.attempt, namespace=self.namespace, key=self.key)

class Client:
    def __init__(self, host, *, server_name, ca, certificate, key, paired_fingerprint, port=7443, timeout=5.0):
        if not 0 < timeout <= 30:
            raise ValueError('timeout must be in (0, 30] seconds')
        if len(paired_fingerprint) != 64 or any(c not in '0123456789abcdef' for c in paired_fingerprint):
            raise ValueError('a locally verified certificate fingerprint is required')
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.options |= ssl.OP_NO_TICKET
        context.set_alpn_protocols(['actryn-rpc/1'])
        context.load_cert_chain(certificate, key)
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            self._socket = context.wrap_socket(raw, server_hostname=server_name)
            if self._socket.selected_alpn_protocol() != 'actryn-rpc/1':
                raise RpcError('unsupported Robot protocol')
            if hashlib.sha256(self._socket.getpeercert(binary_form=True)).hexdigest() != paired_fingerprint:
                raise RpcError('paired device fingerprint changed')
        except BaseException:
            raw.close()
            if hasattr(self, '_socket'):
                self._socket.close()
            raise
        self._epoch = b''
        self._timeout = timeout
        try:
            self.describe()
        except BaseException:
            self.close()
            raise

    def close(self):
        self._socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('RPC absolute deadline expired')
        self._socket.settimeout(remaining)

    def _read(self, size, deadline):
        data = bytearray()
        while len(data) < size:
            self._remaining(deadline)
            part = self._socket.recv(size - len(data))
            if not part:
                raise EOFError('reply ended early')
            data.extend(part)
        return bytes(data)

    def _call(self, method, payload, *, mutation=False):
        request = wire.Request(version=1, request_id=secrets.token_bytes(16), robot_epoch=self._epoch)
        getattr(request, method).CopyFrom(payload)
        data = request.SerializeToString(deterministic=True)
        if not 0 < len(data) <= MAX_MESSAGE:
            raise ValueError('RPC request exceeds bounded frame')
        deadline = time.monotonic() + self._timeout
        try:
            self._remaining(deadline)
            self._socket.sendall(struct.pack('!I', len(data)) + data)
            size, = struct.unpack('!I', self._read(4, deadline))
            if not 0 < size <= MAX_MESSAGE:
                raise RpcError('invalid RPC reply size')
            raw = self._read(size, deadline)
            response = wire.Response.FromString(raw)
            response.DiscardUnknownFields()
            if response.SerializeToString(deterministic=True) != raw:
                raise RpcError('noncanonical RPC reply')
            if response.version != 1 or response.request_id != request.request_id or len(response.robot_epoch) != 16:
                raise RpcError('RPC reply identity mismatch')
            if method != 'describe' and response.robot_epoch != self._epoch:
                raise RpcError('robot epoch retired; query retained identities after reconnecting')
            result = response.WhichOneof('result')
            if result == 'failure':
                if response.failure.code not in (wire.Failure.REJECTED, wire.Failure.CAPACITY,
                                                wire.Failure.UNAVAILABLE, wire.Failure.OUTCOME_UNKNOWN):
                    raise RpcError('unknown failure status')
                decoded = None
            elif method == 'observe' and result == 'observation':
                value = response.observation
                decoded = {field.name: getattr(value, field.name) for field in value.DESCRIPTOR.fields}
            elif method != 'observe' and result == 'report':
                decoded = json.loads(response.report.json)
                if not isinstance(decoded, dict):
                    raise RpcError('inspection report must be an object')
            else:
                raise RpcError('missing or unexpected result kind')
            if method == 'describe':
                self._epoch = response.robot_epoch
        except Exception as error:
            self.close()
            if mutation:
                raise OutcomeUnknown('query the original stable handle; no retry was sent') from error
            raise RpcError('read-only request failed; no execution was sent') from error
        if result == 'failure':
            if response.failure.code == wire.Failure.OUTCOME_UNKNOWN:
                raise OutcomeUnknown(response.failure.message)
            raise RpcError(f'{wire.Failure.Code.Name(response.failure.code)}: {response.failure.message}')
        return decoded

    def describe(self):
        return self._call('describe', wire.Empty())

    def observe(self, attempt: bytes, namespace: bytes):
        if len(attempt) != 16 or len(namespace) != 16:
            raise ValueError('invalid attempt namespace')
        return self._call('observe', wire.Handle(attempt=attempt, namespace=namespace))

    def propose(self, handle: RequestHandle, *, observation_id: int, left_delta_ticks: int,
                right_delta_ticks: int, duration_ms: int, parent_digest: bytes):
        if (type(observation_id) is not int or observation_id <= 0 or
            not all(type(n) is int and -100 <= n <= 100 for n in (left_delta_ticks, right_delta_ticks)) or
            type(duration_ms) is not int or not 1 <= duration_ms <= 10000 or
            not isinstance(parent_digest, bytes) or len(parent_digest) != 32):
            raise ValueError('proposal outside fixed wheel skill envelope')
        return self._call('propose', wire.Proposal(handle=handle._wire(), observation_id=observation_id,
            target=wire.Target(left_delta_ticks=left_delta_ticks, right_delta_ticks=right_delta_ticks, duration_ms=duration_ms),
            parent_digest=parent_digest), mutation=True)

    def query(self, handle: RequestHandle):
        return self._call('query', handle._wire())

    def evidence_read(self, handle: RequestHandle, *, file='', offset=0):
        """Read a retired capture page or bounded file chunk; never starts work."""
        if (not isinstance(file, str) or len(file) > 64 or
            any(not (c.isascii() and (c.isalnum() or c in '-.')) for c in file) or
            type(offset) is not int or not 0 <= offset <= 67108864):
            raise ValueError('invalid evidence read bounds')
        return self._call('evidence_read', wire.EvidenceRead(handle=handle._wire(), file=file, offset=offset))

    def cancel(self, handle: RequestHandle):
        return self._call('cancel', handle._wire(), mutation=True)
