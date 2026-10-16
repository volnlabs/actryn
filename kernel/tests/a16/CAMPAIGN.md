# A16 instrumentation pilots and frozen comparison

This runner does not launch, stop, reboot or create a VM. The integration owner
selects each exact emitted QEMU command, keeps unrelated guests and host builds
quiet during a run, waits for SSH, and invokes one labeled attempt. Failed labels
cannot be reused. No instrumentation pilot or comparison has run at this freeze.

The preexisting correctness evidence is separate:
`qualification/protected01`, `userspace01` and `environment3-userspace01` all have
retained PASS markers. The failed raw boot01, original padded DTB, successful raw
boot02 and all original/amended source/build artifacts remain unchanged.

`campaign.toml` pins the runner/helpers, amendments and the actual three measured
ARM binaries from `qualification/userspace01/environment.log`. The authority
module is under `build-amendment2/kernel/`, while gateway and workload are under
`build-amendment2/`. These existing binaries are reused without a new build. Both
instrumentation manifests are required; the amendment-4 module SHA remains
`535b1e5c653993a7a1ba716da9d569501875198a668ac94747bf119c95805bc8`.

## Prepare instrumentation once

With the dedicated A16 guest running and no experiment active, the integration
owner copies all paths listed under `instrumentation4.toml` and
`instrumentation5.toml`, preserving relative paths, plus both manifest files and
the exact build04 `actryn_a16_capture.ko`, into new guest directory
`/opt/actryn-a16/instrumentation4/`. Do not replace either workload build or load
the module during staging. Run host `sh kernel/tests/a16/run.sh` before the first
target pilot. This performs no guest actions or module load.

Generate exact commands on the host (replace ROOT with the integration checkout):

```sh
python3 kernel/tests/a16/campaign.py commands ROOT/.cache/qemu/a16
```

The resulting JSON has `tracekernel01`, `traceuserspace01`, and `block01` through
`block04`. The expected host units are `actryn-a16-robot.service` and
`actryn-a16-fixture.service`; the runner verifies their actual process arguments,
identity and fixture executable. It records the processes before and after each
attempt. Raw mode uses only the separately pinned compact amendment-3 DTB.

## Two excluded instrumentation pilots

Boot `tracekernel01` using its emitted command, then run:

```sh
python3 kernel/tests/a16/campaign.py trace-pilot kernel ROOT/.cache/qemu/a16
```

After preserving the result and shutting down that guest, boot
`traceuserspace01` using its emitted command, then run:

```sh
python3 kernel/tests/a16/campaign.py trace-pilot userspace ROOT/.cache/qemu/a16
```

Each pilot runs the unchanged ten-trial workload once with accepted-prefix
capture. A PASS requires all ten correct scenarios and terminals, zero new event
loss/gaps or saturated counter, complete raw capture with all strict decoder
checks, correlation of every successful eligible dispatch request, matching boot
and amendment provenance, and successful capture export/unload. The kernel pilot
loads the existing authority module once; it stays loaded until guest shutdown.
The userspace pilot starts the fixed gateway unit and retires it before returning.
The tests do not run the optional pointer/count tracer.

A failed pilot consumes its directory and blocks comparison. Diagnose it and
agree a separately numbered amendment/attempt; this runner has no retry option.
Pilot samples never enter the comparison. Records live in
`qualification/instrumentation-{kernel,userspace}01`.

## Four boots, eight comparison runs

Only after both matching instrumentation pilots pass, boot each block's exact
command in order and invoke `block N` once for that boot:

```sh
python3 kernel/tests/a16/campaign.py block 1 ROOT/.cache/qemu/a16
python3 kernel/tests/a16/campaign.py block 2 ROOT/.cache/qemu/a16
python3 kernel/tests/a16/campaign.py block 3 ROOT/.cache/qemu/a16
python3 kernel/tests/a16/campaign.py block 4 ROOT/.cache/qemu/a16
```

These are separate operator invocations separated by preserved results and guest
shutdown/next boot, not a single shell batch. Arms are kernel, userspace,
userspace, kernel. Within each boot the runner executes evidence-only first and
then evidence plus capture, ten trials each. A block keeps the same gateway or
authority module installed across its two modes; each traced mode gets a fresh
one-shot capture module. The fixed workload independently restarts the fixture
and creates a new authority epoch per trial. Comparison totals are exactly four
boots, eight runs, eighty planned trials; the two pilots add twenty excluded
qualification trials.

Every attempt creates its directory before setup. A failed workload with known
retirement keeps its complete/partial evidence and FAILED status and is not
replaced; a later ordered block can proceed with that failure in the denominator.
Unknown cleanup, missing workload boot, changed process identity or failed setup
halts progression. Unstarted/unreturned run labels remain in `attempt.json`.
The start, workload and retirement share a per-run flock and closed fence, so a
late SSH start cannot revive a retired run. Cleanup makes no claim of success if
the bounded lock, remote command, capture export or unload fails. Workload and
capture exports are attempted independently even after an earlier failure.

## Read the evidence

Each run retains workload tar/JSONL/intents, raw capture when traced, both capture
manifests' provenance, kernel log, return codes, result and independently decoded
`dispatch.json`. `attempt.json` retains incomplete blocks. `completed.json`
means the planned run records returned with known cleanup; inspect its explicit
PASS/FAILED status rather than interpreting file existence as correctness.

Pass the eight `comparison/blockNN/blockNNevidence|trace/workload/events.jsonl`
paths, in order, to `analyze.py`. It summarizes admission-call duration,
observation age, APPLIED/deadline outcomes, closure/recovery, CPU and event loss.
Its legacy `dispatch_latency: NOT_RUN` field means that this analyzer itself has
no UART input; use each traced run's separate `dispatch.json` for the measured
request-entry to complete-frame-accepted interval. Never substitute ioctl/IPC
duration for UART dispatch. Preserve every issued request and explicit failed,
ambiguous, unmatched and successful-correlated cohort count.

When a run has no readable events file, retain its planned ten trials and failed
setup/partial evidence in the final report; do not drop it to make the eight-file
analyzer succeed. Report all eight planned run outcomes and uncertainty before
any descriptive distributions. Raw request opcodes also preserve reconciliation
call durations and other per-operation breakdowns without inventing a physical
measurement. Captured bytes represent acceptance into the Linux serial buffer,
not physical UART drain or actuator motion. Matched workload and logging do not
make the two enforcement mechanisms equivalent. Two boots per arm support only
descriptive software comparison, not superiority, hard deadlines or WCET.
