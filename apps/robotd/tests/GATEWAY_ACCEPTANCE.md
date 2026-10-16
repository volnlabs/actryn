# A10 actual gateway campaigns

`gateway_traffic.py` is an opt-in production manager, gateway, kernel and deterministic
fixture campaign. Host tests validate the bounded test mechanisms; they do not
close A10. No actual guest run is claimed by this source change.

The entry point accepts the same supplied SSH, mTLS, CLI, reader, principal and
manager/module pins as `failure_paths.py`, plus `--gateway-sha256`. `--help` is
read-only. Execution requires a separately scheduled disposable ARM64 QEMU guest
with kernel `6.12.111+deb13-arm64`, existing enrollment and no current preparation
or authority. Output must be a new directory. It uses one owned SSH master and
never reconnects through a fallback transport. It neither installs credentials
nor changes the installed services or security policy.

The traffic campaign explicitly recovers, rearms, prepares and authorizes once.
Every failed/unknown mutation ends the relevant phase; no proposal or closure is
retried. A one-shot Recover can fail during an existing clock checkpoint. That
failure remains a failed campaign, rather than a reason to infer readiness.

The bounded cases are:

* Forged plaintext identity metadata, one unknown protobuf identity field, one
  remote Grant, and one out-of-envelope target cannot change grant identity,
  deadline, operation or health. Explicit decoder rejection/EOF counts; a timeout
  does not. The out-of-envelope key must have no registry entry.
* A second saved key has one valid encrypted Propose record withheld. The reserved
  local endpoint cancels the absent key once. Only after its terminal revision is
  durable is that exact ciphertext forwarded once. The terminal key remains
  unallocated while the original observation is still fresh. No observation is
  refreshed, replaced or given a wider validity interval.
* One accepted SDK Propose is acknowledged. Its exact opaque TLS application
  record is replayed once on the same connection. TLS must reject it and the
  original operation must still be the only allocated operation. This is an
  intentional malicious replay, never a client retry.
* Three authenticated observation connections hold the three ordinary request
  slots using incomplete next-frame headers. Two incomplete TLS handshakes occupy
  the handshake permits; an additional handshake must be rejected. The test
  verifies that the original sockets remain open, then a guest helper records an
  ordinary local Describe rejection and issues one Cancel on the reserved socket.
  Holder ages must remain below 1.8 seconds, within the unchanged two-second
  ordinary read deadline. This is a bounded decoder/handshake saturation test,
  not a bulk observation stream or arbitrary sustained-load qualification.

After releasing only test-owned sockets, read-only inspection must establish
durable cancellation and kernel reconciliation with no independent clock,
recorder or source fault. The campaign retires and recovers once, exports through
the production CLI, and invokes the existing production-reader adapter
`failure_capture`. The whole capture must contain exactly one allocation, START
and accepted execution, contiguous external kernel sequence, unchanged loss
counter, and a complete durable recorder prefix. The cancellation receipt must
fall inside the guest CLOCK_BOOTTIME interval recorded by the reserved-endpoint
helper. Extra allocations, expiry instead of cancellation, source gaps, incomplete
capture, or an ambiguous successful result cannot pass.

The opaque relay has one connection, a 20-second lifetime, one complete captured
TLS record (at most 18,437 bytes), 262,144 total observed bytes, and one explicit
forward/replay action charged before I/O. Held bytes are never flushed on abort.
It parses only public TLS record framing and does not terminate TLS, read private
keys or synthesize authenticated replies. Post-seal client alerts are dropped and
counted; no additional client application record is forwarded.

Artifacts retain immutable handles, mutation intents, raw bounded RPC replies,
unknown outcomes, source/binary hashes, TLS ciphertext hashes and byte counts,
guest PID/unit/boot identity, phase times, exported evidence and decoded capture.
Metadata-only capture remains ineligible for full execution replay. Nothing here
qualifies physical actuation, hostile-root isolation, or a hard timing bound.

Host verification: run Python unittest discovery for `test_gateway_*.py` with
`ResourceWarning` treated as an error. These use real local TCP/Unix sockets and
the capture predicates; they do not connect to a guest or issue robot commands.
