# Existing-device refusal and actual cgroup OOM

Run04 failed because the existing 1:7 node opened successfully; its parent exited
105 before the memory stage. That failure remains preserved. Target acceptance
of the corrected fixed-filter cohort is **NOT_RUN** until the integration owner
schedules a separately numbered disposable installed Server campaign. Host tests validate the harness;
compiling the workload does not establish either target result. Do not execute
`diagnosis_agent` on the host.

This is one credential-free static agent, one approved offline OCI artifact and
one attempt. It fills two gaps in the platform contract: an open of an **existing**
forbidden harmless character device, and an actual memory-limit kill retained in
the exported evidence. It does not repeat the existing unauthorized-broker test,
run inference, bind Robot authority, or claim complete A08/physical qualification.

## Fixed test and evidence

After normal Prepare, the root harness pins PID/start ticks, cgroup identity and
the stopped task's `/dev` tmpfs. It opens that exact process root using the kernel
procfs reference, then uses directory-relative operations with no-follow checks
to create only `/dev/actryn-denied-full`: root-owned char **1:7**, mode 0666.
Mode is set explicitly despite the harness's umask 077. This is the nonphysical
Linux `/dev/full` device; the test only opens/reads it, never writes. A same-UID
65532 subprocess outside the attempt cgroup must open the exact node through the
retained directory FD and read one zero byte. The forbidden path and the unrelated
missing path must both be absent before creation. No existing node is replaced.
All proc-root/device/PID FDs close before Start.

This is a test-only addition to the existing mounted `/dev` tmpfs, **not an extra
bind mount**. The production OCI/device policy, signed rootfs, units, capabilities,
limits and startup checks remain unchanged during the campaign. OCI rules request
char 1:3/5/8/9 only, but runc adds virtual-device defaults. The corrected launcher
also installs its own fixed filter, which permits only those four devices for
read/write and denies 1:7. Acceptance requires its pinned instruction hash and
program ID in both the direct and effective inventories, with `ALLOW_MULTI`.
Seccomp permits `openat`. An extra mount would be
rejected by the ordinary Start verifier and is not a fallback. If the prepared
namespace cannot be inspected or the control open fails, stop and preserve that
failure rather than changing the sandbox.

The agent forks one child after exec. That child verifies the existing node and
makes exactly three direct `openat` calls: `/dev/null` succeeds, an unrelated
missing path returns `ENOENT`, and the existing 1:7 node returns `EPERM`. The child
prints one bounded JSON record and exits. The parent waits for success, prints
the memory-stage marker, then maps at most 512 MiB and writes one byte per 4096-byte
page. The touch loop stops with a failure exit after ten seconds or after touching
the complete mapping. Allocation failure and ordinary exit are failures, not OOM
success. There is no retry, fork loop or host-pressure workload.

The installed profile remains `memory.max=268435456`, `memory.swap.max=0`.
Success sends **no Cancel**. Within the existing twenty-second read-only retirement
poll, both stores must report `reaped`. Export must retain the natural
`exited:137` result, fresh positive `memory.events` `max`, `oom` and `oom_kill`
counters from an initial zero baseline, complete counter/log/observer evidence,
and no gaps. The ordinary launcher snapshots counters after descendants are empty
and before deleting the runtime/cgroup. SIGKILL or counter presence alone is
insufficient.

Observer JSONL must cover the complete sequence set through the final summary
with zero source/local loss. Cross-CPU ring delivery can differ from sequence
assignment order; the validator checks uniqueness/completeness, then orders by
source sequence. A retained exec and fork bind the three child syscall entry/exit
pairs and child exit to the exact attempt/cgroup/boot/collector. The observer
records `access_failed`, **not a device-policy-specific denial event**; it does not
record path arguments. Device attribution combines that kernel-observed sequence,
the reviewed agent, independently verified node/control, and installed isolation
inventory. Agent stdout remains labelled untrusted.

The harness snapshots all seven common SQLite tables in **both** stores through
`mode=ro`, `query_only`, finite reads. Every old full row must remain byte-for-byte
equal as a logical field value, including BLOB contents. Each store gains exactly
one attempt; only the launcher gains its new resource-evidence row. No calls,
Robot bindings/debits, policy-denial rows or gaps are introduced. Final tasks,
cgroup children and broker directories must be absent. This preserves the actual
post-debit baseline; it does not assume an old fixed attempt count.

## Scheduled guest-only steps

Use the existing guarded host lifetime/SSH recorder. Observe the future boot,
machine, QEMU lifetime, installed manifest/CLI, runtime package pins and original
unit properties. Require all retained debits settled and enough retained-attempt
capacity before this campaign. Schedule after the retained-debit window.

Stage new, protected, numbered paths without overwriting earlier artifacts.
Required sibling sources are `diagnosis_agent.c`, `guest_diagnosis.py`,
`guest_capacity.py`, `pressure_fixture.py`, plus the reviewed OCI builder and
offline input/schema. The pressure helper is imported only for its read-only
installed-state/property checks and bounded file helpers; **never run its
install/restore actions**. No LD_PRELOAD shim may be mapped or armed.

The owner separately records one native compile with the already installed pinned
toolchain, compiler output/ELF/hash, one OCI construction and one import while
launcher/serverd are stopped. Commands below are structured guest argv examples,
not host shell commands:

```text
["cc","-std=c11","-O2","-static","-Wall","-Wextra","-Werror","-o","/root/actryn-diagnosis01/agent","/root/actryn-diagnosis01/diagnosis_agent.c"]
["python3","/root/actryn-diagnosis01/build_oci.py","--agent","/root/actryn-diagnosis01/agent","--out","/root/actryn-diagnosis01/agent.oci"]
["/usr/bin/actryn","server","import","--layout","/root/actryn-diagnosis01/agent.oci","--digest","sha256:OBSERVED_OCI_DIGEST"]
```

Preserve old config/registry entries. Import adds exactly one approved artifact and
one charged slot (capacity 8); the test does not delete them afterward. Require the
installed service UID's `actryn-serverd --check-config` to succeed before starting
the unchanged installed services. Use existing reviewed service startup handling;
the campaign itself does not install, import, start, stop or restart services.

```text
["python3","/root/actryn-diagnosis01/guest_diagnosis.py","--manifest","OBSERVED_MANIFEST_SHA256","--boot-id","OBSERVED_BOOT_UUID","--artifact","sha256:OBSERVED_OCI_DIGEST","--agent-sha256","OBSERVED_AGENT_SHA256","--output","/root/actryn-diagnosis01/campaign"]
```

Bound this single invocation externally to 180 seconds; retain stdout/stderr/status
even on preflight failure. Never automatically repeat it. The output directory
must be absent. Success requires a final `PASS` **and no `FAILED`**, the installed
state unchanged, both subresults PASS and final quiescence. Preserve the exported
bundle, copied raw stdout/stderr/observer JSONL+summary, hashes, SQLite snapshots,
source/native/OCI provenance and installed state. A stopped final raw-database
capture and service shutdown use the existing separately reviewed owner procedure.

On any failure the original failure record remains. For each known still-live
attempt, cleanup sends Cancel at most once, records a lost reply as uncertainty,
and only polls for convergence. It does not overwrite natural outcomes, retry
Prepare/Start/Cancel, remove history or claim an uncertain cleanup succeeded.
An unknown Prepare reply may leave an unidentified reservation; the owner must
inspect it separately. The private tmpfs device disappears with runtime teardown;
no host device node or mount needs restoration. Partial device/OOM results stay
separate from the overall failed campaign.

Host checks (no target contact, do not run the compiled agent):

```text
["python3","-m","unittest","discover","-s","apps/server/tests","-p","test_*.py"]
["cc","-std=c11","-O2","-static","-Wall","-Wextra","-Werror","-o","NEW_PRIVATE_OUTPUT/diagnosis-agent","apps/server/tests/diagnosis_agent.c"]
```
