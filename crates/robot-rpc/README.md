# Robot RPC foundation

`schemas/robot-v1.proto` is the shared Rust/Python request schema. The wire is
TLS 1.3 with mandatory client authentication and ALPN `actryn-rpc/1`, carrying
four-byte big-endian lengths and canonical Protobuf messages capped at 65,536
bytes. Unknown/duplicate/noncanonical fields reject; no decoder executes a
caller-supplied method, path or robot-local code. Typed proposals bind a stable
namespace/key, retained observation and fixed wheel target. Request correlation
IDs do not provide execution deduplication; the intent registry owns that.

Rustls validates certificate signatures/chains and time. Local policy maps the
verified leaf fingerprint to a principal and read/propose scopes; neither a
claimed principal nor gateway headers establish identity. Sessions use the
remaining certificate lifetime, capped at five minutes and converted once to
BOOTTIME. Renewal cannot extend an existing session or prepared binding.
Revocation/removal is checked on every authorization. Network methods cannot
issue grants, rearm or enroll. TLS early data and resumption are disabled.

`PeerLifetime` captures Linux `SO_PEERPIDFD` on the protected gateway control
connection, avoiding a PID lookup race. The service must poll it and close its
associated contexts even when a descendant retains stream descriptors. Ordinary
connection EOF is separate. `ClockGuard` latches clock discontinuities and checks
a durable wall-time floor. The daemon must supply that floor, update it durably,
and enforce session/gateway health against actual grants.

The codec itself does not schedule work or install service-wide quotas. Its
caller must bound connection/handshake counts, per-principal work, frame deadlines
and aggregate queued bytes, reserve local closure service, and invoke authority
closure when credential/lifetime/clock checks fail. These are daemon integration
requirements, not claims established by the library tests.

`cargo test -p robot-rpc` checks real mutual TLS, untrusted/missing certificates,
fixed session expiry/revocation, frame rejection and a live process exiting while
its child retains the socket. These are software component tests; full gateway
flooding/replay and robot execution acceptance are separate.

API references: [Rustls server authentication](https://docs.rs/rustls/0.23.46/rustls/server/struct.WebPkiClientVerifier.html),
[Tokio TLS](https://docs.rs/tokio-rustls/0.26.6/tokio_rustls/),
[Prost messages](https://docs.rs/prost/0.14.4/prost/trait.Message.html).
# Fenced publication

`PreparedRpc::connect` authenticates TLS, verifies the operator's device pin and
encrypts a bounded request without sending its application bytes. Call the
consuming, synchronous `try_send_once` inside the caller's publication locks.
It makes one nonblocking socket write; a short write, timeout or error closes the
connection and leaves delivery unknown. There is no retry or automatic flush on
drop. The returned `SentRpc` reads one canonical, identity-checked response under
the original five-second deadline. The ciphertext buffer is capped at 73,728
bytes. This transport does not create grants, durable request handles or fences;
the broker must establish those before publication.
