# Fixed wheel runtime

`Engine` is the trusted native robot manager library for the single reviewed
`wheel.index_step.v1` skill on `qemu-arm64-fixture/1`. It binds the actual kernel
ADMIN/RUNTIME/ACQUISITION/EVENTS roles through `authority-client`; there is no
userspace authority fallback or replay device route. Network authentication,
operator policy, TLS, gateway supervision and RPC belong to the embedding service.
The service supplies SHA-256 of its stable authorized principal identifier, not a
peer-provided identity header.

The root must be an owned directory with mode 0700. `open` obtains its exclusive
lock before device binding and installs process-wide synchronized exec denial.
Use `Arc<Engine>` directly: methods take `&self`. Preparation may wait for storage
and must run on the bounded preparation worker. It reserves the only slot before
construction and never holds the control lock over filesystem work. The service
must call `tick` at least every 100 ms on its control thread. Kernel health and
controller command expiry remain independent when that thread stops.

An explicit local sequence is `recover` (poll pending, at most 12 seconds),
`rearm` (poll until matched baseline), `prepare(binding, instance, digest)`,
`grant(deadline)`, `activate`. An expired or unacknowledged clock mapping never returns recovery-ready; explicit
recovery refreshes it even after a long inhibited enrollment/setup interval.
Preparation publishes its namespace asynchronously;
`grant` rejects until namespace durability. Use `configuration_digest()` and
`profile_digest()` for the compiled reviewed inputs. Configuration cannot change
on a live instance. Binding principal, attempt, namespace and session deadline
are immutable. Reauthentication cannot extend this binding; the service retires
it and explicitly prepares another generation instead.

Only one instance is charged, including staged, active and retiring states. A
rejected second preparation preserves the current one. Construction has a
5-second publication deadline; blocked work stays charged until it returns.
A staged instance expires after 60 seconds, session ceilings are at most 120
seconds, and grants at most 60 seconds. `retire`/`recover` cannot release writer
resources while a writer is blocked; callers see pending. A fresh preparation
after retirement requires explicit recovery/rearm. This is narrower than the
profile's separate active/staged/retiring maxima; concurrent replacement is not
implemented.

`observe` retains actual controller baseline/applied/quiesced/periodic encoder
facts copied from kernel wire events. A status poll never creates acquisition
freshness. Retention is 32 observations; older IDs reject. The kernel validates
the actual HELLO send/receive exchange against its 10 ms clock eligibility bound.
The library only sees the accepted event, so it conservatively derives the host
bracket `[captured-10ms,captured]`, then expands it with 100 ppm drift, up to the
60-second mapping lifetime. This derived observation interval can be wider than
10 ms (at most roughly 22 ms); it is not a new eligibility measurement. Dispatch
uses the earliest bound for the 1-second age ceiling and checks the original
kernel clock mapping too. The fixture emits periodic actual `OBSERVATION` frames;
missing frames produce stale data and closure, never fabricated refreshes. All
observations are explicitly marked simulated, with source kernel event sequence.
Kernel sequence gaps/loss close authority; recorder-local producer cursors are
separate and do not reset or conceal source gaps.

`propose` binds a stable key, parent digest, retained observation and relative
wheel targets. Each wheel is limited to 100 ticks, duration to 10 seconds, and
duty to 100 permille. A wheel stops permanently when its target is crossed;
there is no reversal after overshoot. Samples have 100 ms minimum cadence,
receipt-aware 100 ms slew credit (including STARTED, with conservative mapped
controller time rather than observed timestamps), finite <=300 ms horizons and the original
operation/session/grant/observation ceilings. Only one unknown sample can exist.
External snapshots withhold the allocated ID until its binding is durable;
the stable key remains available for pending queries/cancellation. The registry
allocates without transport, commits the immutable intent on its
writer thread, then performs a serialized fresh check before START. Duplicates
are lookups and cannot refresh deadlines or dispatch; changed digests conflict.

Target verdict and closure/reconciliation are separate. Target reached sends
normal FINISH and still occupies the group until a matched kernel reconciliation.
Only then can a second operation start under the same live grant. Failed or late
reconciliation does not erase the task verdict or imply safe handoff. Timeout
closes authority and needs recovery; it is not a successful completion.

`cancel` reads the immutable published context and enters the registry's short
ordering lock, bypassing the control mutex and storage. It invokes the existing
ADMIN cancellation path even before the proposal reply. Its result explicitly
separates pending tombstone, durable tombstone, local close and reconciliation.
`revoke` bypasses both registry and control mutexes, disables new submissions and
calls ADMIN directly; it does not wait for disk, worker teardown or receipt. It
permanently closes that prepared binding. Gateway death, credential revocation
and clock failure must call it. Ordinary session EOF policy belongs to the service
and cannot extend any existing ceiling.

Intent and evidence each have a dedicated storage thread. Metadata-only capture
retains typed trusted structural metadata (never model/input payloads) using
MCAP + SQLite; it is execution-replay ineligible. Recorder/registry health loss
revokes before another HEALTH renewal/sample, with zero authorized continuation
after detection. `health` exposes read/queued/durable frontiers and source-gap
counts independently. No storage executes on admission/cancel/revoke paths.

Preparation also syncs an immutable private principal binding artifact before
publication: <=1024 bytes per namespace, at most 16 namespaces, no overwrite or
silent repair. `Engine::inspect(path, principal, attempt, namespace, key)` works
without binding a kernel device, reads those artifacts and the registry read-only,
and validates the stored association. An absent record is distinct from missing
or malformed binding/namespace metadata. Unfinished historical work remains
`OutcomeUnknown`; no restart resubmits or restores a grant. Historical inspection
cannot request a new durable cancellation or claim downstream reconciliation.
Historical cancellation of already retired unknown operations remains a service
policy/reporting limitation, not an available live operation route. Exact past
task verdicts beyond the current operation require retained evidence; inspection
reports unknown rather than inferring target success from registry completion.

Finite defaults are inherited from the registry (1024 keys, 128 pending jobs,
32 closure jobs, 16 MiB DB) and recorder (1 MiB/4096 pending records, 2-second
maximum age, 64 MiB disk reservation, 2 MiB batch reservation). Sixteen retained
captures plus bindings/registry bound application logical files to about 1 GiB;
this is not a filesystem/RSS quota or storage-media qualification. The service
must provision/archive this finite history deliberately; no live identity is
silently evicted. Engine drop revokes and releases the owner role immediately;
it signals writers to stop without joining a stalled writer.

Checks:

```sh
cargo test -p robot-runtime
cargo clippy -p robot-runtime --all-targets -- -D warnings
cargo fmt -p robot-runtime -- --check
# Only inside an isolated ARM64 guest with the actual module and fixture:
cargo test -p robot-runtime --test guest -- --ignored --nocapture
```

Host tests exercise pure limits/overflow, monotone wheel stopping, deadline
precedence, clock intervals, immutable digests/bindings, private durable history
and thread-safe API shape. Registry and evidence tests separately exercise actual
SQLite stalls and crash-prefix recovery. The ignored guest test uses the actual
module for two natural completions under one grant, duplicate/change semantics,
pre-ID cancellation and principal-bound historical lookup. Its presence is not a
claim that it ran. No production service integration, race qualification, hard
scheduler/WCET bound, hardware interface, physical result or release acceptance
is established by these host checks.
