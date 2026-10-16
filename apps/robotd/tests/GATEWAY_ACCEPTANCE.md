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
  A valid PendingIntent reply need not contain an operation ID. Before replay,
  one preconnected observer queries the original handle and checks the full
  RUNNING kernel identity within one second. The original encrypted stream stays
  idle during this check. The lifetime case uses the same bounded read-only
  confirmation before process interruption. Unknown/terminal replies, changed
  identities and expired confirmation deadlines fail without another proposal.
* Three authenticated observation connections hold the three ordinary request
  slots using incomplete next-frame headers. Two incomplete TLS handshakes occupy
  the handshake permits; an additional handshake must be rejected. The test
  verifies that the original sockets remain open, then a guest helper records an
  ordinary local Describe rejection and issues one Cancel on the reserved socket.
  Holder ages must remain below 1.8 seconds, within the unchanged two-second
  ordinary read deadline. This is a bounded decoder/handshake saturation test,
  not a bulk observation stream or arbitrary sustained-load qualification.

The saturation helper starts over one owned SSH child and returns `READY` before
the original operation is proposed. It waits at most ten seconds for one `run`
line; EOF, an expired wait or an invalid trigger aborts without calling Cancel.
The host sends the trigger once after saturation and never resends an unknown
outcome. Cleanup closes or terminates only that owned child. Preloading does not
enter the fault interval: the unchanged probe records CLOCK_BOOTTIME immediately
around the local Describe and Cancel calls. Operation targets, production
deadlines, holder-age checks and test leases are unchanged.

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

## Installed gateway lifetime with retained descriptors

`gateway_lifetime.py` is a separate opt-in campaign with the same arguments and
fresh output requirement. It uses `gateway_fds.py` as a root test helper on the
explicit disposable guest. The helper never impersonates the installed gateway.
Before recovery, preparation or grant, it pins the installed gateway PID with a
pidfd, checks its executable hash and unprivileged UID, and duplicates candidate
socket descriptors with Linux `pidfd_getfd`. It requires exactly one control
socket and one relay socket whose peer is the exact root manager PID, plus one
accepted TCP socket on port 7443. It checks source/duplicate inode identity,
rejects ambiguity and closes every duplicate after this nonmutating preflight.
Only diagnostic files are created. Permission denial stops the campaign; there
is no ptrace setting, capability, service policy or production API workaround.

After one acknowledged proposal reaches RUNNING, a fresh helper retains those
three real sockets again. Its command lease accepts one `kill` line, then sends
SIGKILL once through the pinned pidfd. It confirms process death while all three
duplicate descriptors remain open and attempts one nonblocking `H` heartbeat on
the retained control socket. That single write may already fail because the
manager detected death; the failure is recorded. The helper never reads payloads
or changes shared descriptor flags. Its fd retention lease is eight seconds,
with explicit success checks against the guest CLOCK_BOOTTIME duration; this is
a measured test limit, not a scheduler or storage WCET guarantee.

The host requires reason-3 GRANT_REVOKED closure and reconciliation, observed
within the existing three-second liveness interval, with exact retained operation
identity. Only a secondary recorder `WriterStopped` issue is allowed; clock,
storage, pending-age and source faults fail the test. The helper keeps its
duplicates across the installed systemd gateway's automatic replacement. A fresh
pinned mTLS connection must inspect the old operation with `live_authority=false`.
One separately saved negative key in the old namespace must be rejected for the
gateway/binding generation mismatch (`principal mismatch`), not for stale
observation data; it must have no registry entry or allocation. Only then does
the host release the duplicates.

The campaign stops the fixed gateway service once, establishes MainPID zero,
and performs explicit local retirement/recovery while the gateway is offline.
It starts that same service once for authenticated export. Service actions are
fenced before I/O, so an unknown start response cannot be retried by cleanup.
On failure, a distinct reserved local Revoke is attempted once; test-owned FDs
are always closed and a previously requested service stop gets at most one
restoration attempt. Unknown cleanup remains an explicit failure.

The production-reader proof requires one allocation/START/accepted execution and
an actual closure event kind `0x30003` with reason 3 inside the bounded death
interval. The prior traffic case instead requires `0x30002` with reason 2;
inconsistent synthetic kind/reason combinations cannot pass. Exact original/new
PIDs, socket inodes/peer endpoints, pidfd death, helper/lease timestamps,
replacement inspection and offline recovery reports are retained alongside the
capture. This checks the trusted-Linux gateway lifetime contract; it does not
claim isolation from a hostile root process.
