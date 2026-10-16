# Instrumented server call pressure and directory failure

`guest_pressure.py` is an opt-in, server-only A08 campaign for the selected
disposable installed Debian guest. Actual guest execution is **NOT_RUN** until
the integration owner schedules and records it. Host tests exercise the native
workload over Unix sockets and the real linked-libc interception; they do not
establish production broker or containerd acceptance.

The three results are separate:

1. A reviewed static fixture agent A completes four `diagnostic.echo` calls,
   then releases eight children together to send eight further approved calls
   while the parent sends one reserved `Cancel(base-0)`. The twelve call keys
   stay within the existing sixteen-key bound. Every request has one frame
   write and no retry. Four settled zero-token debits, a durable key cancellation
   and at least one exact call-budget refusal are required. EOF/reset after a
   complete burst write remains explicit uncertainty, never a denial inferred
   from silence. All eight burst requests must be accounted for, with no extra
   debit. This is finite concurrent call pressure, not an arrival-rate/WCET or
   proof that every request overlapped inside the broker.
2. While A remains active, exactly one broker-directory `mkdir` for newly
   allocated B returns `ENOSPC`. The launcher has already retained its binding
   and registered the observer, but has not created a task or output directory.
   The latched B must match the returned error and launcher database. B must
   become cancelled/reaped without broker adoption. Its root-helper export must
   contain the three available artifacts plus exactly the two expected
   `retained_log_unavailable` omissions; no fabricated application log is used.
3. C is prepared normally. Its final broker-directory `rmdir` returns `EBUSY`
   under a maximum ten-second monotonic lease. One Cancel must return that exact
   failure, both stores must keep C retiring, the cgroup must be gone and the
   empty broker directory must remain. A new Prepare must fail without a new
   row. Removing the fault lets the existing launcher cleanup tick converge;
   the harness does not resend Cancel. A fresh D then proves preparation
   capacity was reclaimed. A keeps the same PID, start time, binding and output
   throughout both faults. A, C and D are cancelled at most once and exported
   with the existing resource/observer/raw-log validator.

Unknown cleanup, source loss, unrelated failures, expired injection before an
assertion, missing counters or unexpected output fail the campaign. A behavior
observed before final export is labelled pending evidence, not PASS. This does
not inject heap allocation failure, kernel reclaim/OOM, storage stalls, external
provider work or physical motion, and does not close all of A08.

## Fixed fault scope

`directory_fault.c` interposes only libc `mkdir` and `rmdir`. Production-mode
paths are compiled constants: `/run/actryn/a08-pressure` and
`/run/actryn/brokers/<32 lowercase hex>`. The root-owned mode-0700 control
directory and mode-0600 regular files use no-follow, nonblocking bounded access.
Active A is excluded. An exclusive retained latch permits one allocation fault;
reclaim affects only C. Controls expire after at most ten seconds. A timer and
`finally` remove only the owned control inode. The shim also checks time on
every call, so a killed test process cannot leave an indefinite fault. Its
event ledger is bounded to 64 records/8192 bytes; an invalid control or exhausted
ledger is inert and cannot satisfy the campaign's required fault observation.
Latched identity and event records are never removed by the harness.

These points correspond to `Launcher::prepare_runtime`'s broker `create_dir`
after durable observer binding, and `Launcher::cleanup`'s broker `remove_dir`
immediately before `mark_reaped`. The empty cgroup itself is deliberately not
the rmdir target: containerd/runc can remove it earlier. No production source,
injection API, limit or dependency is added.

`pressure_fixture.py install` installs one fixed **runtime-only** drop-in under
`/run/systemd/system/actryn-launcher.service.d/90-a08-pressure.conf`. It prefixes
only the launcher's ExecStart with `/usr/bin/env LD_PRELOAD=...`. This is
**instrumented production-path evidence**, not unchanged installed-unit
qualification. The normal installed ExecStartPre gate, ExecStopPost, signed
files, `/etc` unit/drop-in files, capabilities and limits remain intact. A
preflight rejection stops setup and is retained; it is never bypassed.
The fixture records the effective unit text/commands and inherited security
properties, plus selected immutable executable hashes. A bounded process-map
inventory must find the shim in exactly the current launcher, not the server,
observer or agent. `restore` requires every attempt reaped, removes only the
owned runtime drop-in, restarts normally, and requires exact original effective
configuration, unchanged public config and no remaining shim mappings. Library,
event, imported-artifact and attempt history remain retained.

## Reviewed execution stages (guest only)

Do not execute documentation commands on the host. Schedule one quiet VM window;
pin its boot, machine identity, installed manifest, compiler/package versions and
all test sources before mutations. Require no outstanding attempts/tasks,
capacity for four retained launcher attempts and three broker attempts, and one
free approved-artifact slot. Use a new root-owned mode-0700 staging directory,
for example `/root/actryn-a08-pressure01`. The control path must not already exist.

Copy the four campaign Python/C sources and `guest_capacity.py` unchanged, plus
the pinned `packaging/agent/build_oci.py`, `input.json` and `input.schema.json`.
Keep compiler output, ELF/readelf details and SHA-256 provenance. Compile without
`NDEBUG` or the host-test macros:

```text
["cc","-std=c11","-O2","-static","-Wall","-Wextra","-Werror","-o","/root/actryn-a08-pressure01/agent","/root/actryn-a08-pressure01/pressure_agent.c"]
["cc","-std=c11","-O2","-shared","-fPIC","-Wall","-Wextra","-Werror","-o","/root/actryn-a08-pressure01/fault.so","/root/actryn-a08-pressure01/directory_fault.c"]
["python3","/root/actryn-a08-pressure01/build_oci.py","--agent","/root/actryn-a08-pressure01/agent","--out","/root/actryn-a08-pressure01/agent.oci"]
```

Stop the quiescent server/launcher normally, retain the old public config, and
import this layout once with installed `/usr/bin/actryn-artifact import --layout
... --digest sha256:ACTUAL_BUILDER_DIGEST`. Preserve the new public config and
restart the unchanged services. The importer, not an edited allowlist, approves
the artifact. Its fixed offline profile permits echo but no live model, network
access, credential or Robot delegation. Existing installed builder files are
not assumed to exist. This test approval consumes a finite registry slot and is
not silently deleted after the campaign.

Run these structured invocations in order, replacing the explicit pins. Each
output directory must be absent. Bound setup/restore externally to 150 seconds
and the campaign to 180 seconds; retain stdout/stderr/exit status before any
follow-up. A failed or timed-out stage stops the sequence for inspection; never
restart a mutation automatically.

```text
["python3","pressure_fixture.py","install","--manifest","MANIFEST_SHA256","--library","/root/actryn-a08-pressure01/fault.so","--library-sha256","LIBRARY_SHA256","--output","/root/actryn-a08-pressure01/setup"]
["python3","guest_pressure.py","--manifest","MANIFEST_SHA256","--artifact","sha256:OCI_MANIFEST_SHA256","--agent-sha256","AGENT_SHA256","--fixture-record","/root/actryn-a08-pressure01/setup/fixture.json","--output","/root/actryn-a08-pressure01/campaign"]
["python3","pressure_fixture.py","restore","--manifest","MANIFEST_SHA256","--fixture-record","/root/actryn-a08-pressure01/setup/fixture.json","--output","/root/actryn-a08-pressure01/restoration"]
```

Retain all numbered intents/replies, phase results, B's latched identity, the
bounded fault ledger, root-helper and operator exports, raw logs, observer
traces/summaries, service journals, public config/unit comparisons and source /
binary / OCI hashes. Any unknown Prepare identity requires separate read-only
inspection. A failed run remains failed after cleanup. Final handoff must report
both stores' counts and states, absent cgroups/broker directories, effective unit
restoration and the imported fixture slot still retained.

Host checks (no guest contact):

```text
["python3","-m","unittest","discover","-s","apps/server/tests","-p","test_*.py","-v"]
```
