# A16 comparison: completed, FAILED

Saved-evidence checkpoint, 2026-10-18. The preceding verified push is
`79910ea9982db04db87e19ac722c1c7dd75b3fbe`; [push17](../../artifacts/reconciliation-checkpoint-push17/result.json)
records zero CI runs, not a CI pass. Local ignored evidence is not backed up by Git.

The frozen kernel/userspace/userspace/kernel matrix completed all eight runs:
**80 planned, begun and ended trials; 79 PASS, 1 FAILED, 0 unstarted**. Both passing
10-trial pilots remain excluded. B1/B2/B4 each pass 20/20. B3 evidence passes 9/10
and its later traced run passes 10/10. Evidence trial 6 aborts during a BIND reply
error assertion before RECOVER/first request/eligibility; exact bind role, errno
and underlying rejection cause are unobserved. The missing eligibility record is
a consequence of that real child failure. Traced success does not repair it.

The unchanged C03 runner permits a complete failed comparison block with known
cleanup in its next-block history. Numbered [Root adapter02](../../artifacts/a16-abba-window-plan02/README.md)
adds only an exact 19-receipt B3 exception for block4, with 14 focused host checks
and independent review. It changes no frozen runner, workload, binary, limit,
label or denominator. No block3 retry occurred. The final report and independent
audit preserve comparison status FAILED; successful report production is not
workload acceptance.

Six distinct boots pass the separate original-K11 cohort equality gate: all
before/after catalog, provider and artifact fields match the newly approved K11
baseline, with the four frozen binaries unchanged. This does not infer a
historical provider-byte baseline or turn failed workload qualification into PASS.

## Recorded runs

All runs below began and ended ten planned trials. `Samples` is successful SAMPLE
requests/timely applied/no timely applied. The fixed delayed-reply scenarios
intentionally exercise expiry; these misses are not silently removed or treated
as latency zero. Admission p95 includes all recorded request calls, including
rejected calls; its sample count is in parentheses.

| Block | Arm / mode | Trial PASS/FAIL | Samples | Admission p95 (µs; n) | Guest busy CPU (s) | Gateway CPU (s) | Journal+intent bytes |
|---|---|---|---|---|---|---|---|
| 1 | kernel / evidence | 10/0 | 62/60/2 | 1173.504 (272) | 1.76 | N/A | 442,646 |
| 1 | kernel / trace | 10/0 | 62/60/2 | 925.555 (272) | 1.33 | N/A | 478,099 |
| 2 | userspace / evidence | 10/0 | 62/60/2 | 1256.462 (272) | 6.13 | 3.76 | 447,623 |
| 2 | userspace / trace | 10/0 | 62/60/2 | 1206.846 (272) | 5.72 | 3.69 | 480,673 |
| 3 | userspace / evidence | 9/1 | 61/60/1 | 1560.141 (261) | 5.17 | 3.57 | 431,687 |
| 3 | userspace / trace | 10/0 | 62/60/2 | 1908.427 (272) | 5.93 | 4.34 | 490,875 |
| 4 | kernel / evidence | 10/0 | 62/60/2 | 622.553 (272) | 1.20 | N/A | 442,646 |
| 4 | kernel / trace | 10/0 | 62/60/2 | 735.155 (272) | 1.00 | N/A | 471,479 |

Values come from the eight-row [resource/acceptance CSV](../../artifacts/a16-abba-final-analysis01/resource-acceptance.csv)
and 64-row [per-run metrics CSV](../../artifacts/a16-abba-final-analysis01/metrics-long.csv).
Each metric retains its own count, median, nearest-rank p95 and observed maximum
in nanoseconds; displayed µs are ns/1000 rounded to three decimals. Empty metrics
remain null, not zero. Admission is request entry to ioctl/typed-IPC return, not
UART dispatch. Other metric boundaries are sample-to-timely-applied, observation
age at sample, cancel-to-closure/quiescence, finish-to-quiescence,
Recover-to-baseline and owner-exit-to-closure; their different denominators must
remain visible. All eight ended-trial loss totals, sequence discontinuities and
reversed-clock counts are zero, with complete loss coverage and no saturation.

Guest busy CPU is the aggregate `/proc/stat` tick delta excluding idle and iowait,
divided by the recorded 100 ticks/s. It includes whole-guest activity, not isolated
authority CPU. Gateway CPU is its same-PID user+system ticks/100; the kernel arm
has no corresponding process measurement (N/A, not zero). Child CPU and observation
intervals remain in the CSV. Owner host counters are supporting observations.
Byte counts cover only workload JSONL plus intent files, not total capture/storage.
B3 evidence has 261 request calls and 61 samples rather than 272/62; it is not an
equal-work CPU/latency observation. No pooling of quantiles, significance test,
superiority conclusion, physical measurement or WCET bound is inferred.

## Diagnostic UART correlation

All four traced runs retain 78/78 eligible/matched accepted-dispatch requests,
98 capture entries/returns and zero reported capture loss/error/gap counters.
There are no unmatched/ambiguous or excluded failed-dispatch calls in these traces.
Evidence-mode runs have no diagnostic dispatch-latency measurement.

| Block / arm | Matched/eligible | Entry→frame median (µs) | p95 (µs) | Observed max (µs) |
|---|---|---|---|---|
| 1 / kernel | 78/78 | 1595.844 | 3221.895 | 4540.668 |
| 2 / userspace | 78/78 | 1314.186 | 2783.097 | 3230.630 |
| 3 / userspace | 78/78 | 1792.384 | 3136.792 | 4613.588 |
| 4 / kernel | 78/78 | 1447.391 | 2478.061 | 3348.625 |

The [four-row dispatch CSV](../../artifacts/a16-abba-final-analysis01/traced-dispatch.csv)
also retains write-entry-to-complete distributions and every capture counter.
The boundary is external request entry to a complete immutable frame accepted
into Linux serial buffers. Exact internal admission, physical UART drain,
controller response and physical actuation are not measured. The primary
analyzer's own dispatch field remains NOT_RUN; this separate correlation report
supplies the stated trace-only measurement.

## Custody and receipt identities

All 80 intent files remain present, including B3's empty trial 6 intent. The final
independent audit verifies 8 resource rows, 64 metric rows, 4 dispatch rows and 589
public hash-bookend leaves. B4's normal VM poweroff and supported fixture shutdown
complete within original 970 seconds; its stopped custody records 24 units inactive/PID0/
empty cgroups/NRestarts0, no repository actors and journal boot 144/2904 bytes.
A16 disk SHA256 is `b039bcc9b842e66d89b81f52af0d9969fd693f4ffc3600543dd764e656621772`;
other eight public records and three private-key metadata records are unchanged.
Custody checks inspected only private-key metadata. Earlier failures remain unchanged.

The following SHA-256 values are copied from saved receipt/hash JSON, not inferred
from filenames. Original and retained raw inventories remain linked by the audit.

| Receipt | SHA-256 |
|---|---|
| [Final FAILED comparison result](../../artifacts/a16-abba-final-analysis01/result.json) | `d4f3ef18f85a43995da6dbb451861f3c8099dba7aba8f4f75f8260aeb89c1b8e` |
| [Unchanged primary analyzer output](../../artifacts/a16-abba-final-analysis01/analyzer.json) | `5843282ba98973397914e093c8e3a42c9b0c8abba66b53ead8da25a148bf0494` |
| [Six-boot equality and workload boot links](../../artifacts/a16-abba-final-analysis01/cohort-gate.json) | `1bcfd6809ae42fddf2528b34a99d5a1657dc6e74f1de3f2fff1e28cba491aba7` |
| [Eight run/resource rows](../../artifacts/a16-abba-final-analysis01/resource-acceptance.csv) | `9cb53ffb58b7dbfd159357afc2491f689c7c3e67f47c3da98e39e59e665fc0b1` |
| [64 per-run metric rows](../../artifacts/a16-abba-final-analysis01/metrics-long.csv) | `f80cc9d5bf54605ae0af60208732b87b6d44854e741640e93dadb47f62c48e96` |
| [Four trace-only dispatch rows](../../artifacts/a16-abba-final-analysis01/traced-dispatch.csv) | `271df43da4ff7ea8234370edd9c3c0a00c5065b8468bb0e950edfefb6bf5c587` |
| [B3 independent failure audit](../../artifacts/a16-block7b03-actual-review01/review.json) | `f78046ae005493a4daac242ae85b793dd4d56acb1c9432f4bd731b8ac01dfeac` |
| [B4 independent review](../../artifacts/a16-block7b04-actual-review01/review.json) | `09eda2e2a49af201fef7ab3d04bb19da960b39afa16b5cd90f0e7a15f4c87928` |
| [B4 full stopped custody](../../artifacts/a16-block7b04-final-stopped-custody01/result.json) | `a1c19a5bd9a2190bb3d41a63ff8df0e22cb47008a7a12189c314553d0e0349dd` |
| [Independent final saved-output audit](../../artifacts/a16-abba-final-analysis-actual-review01/review.json) | `4257e0458a9e4d94e7f316b1f3bbea36e8d040d18a8430e4787c122114ef0865` |

The [audit hash inventory](../../artifacts/a16-abba-final-analysis-actual-review01/artifact-hashes.json)
binds the remaining output/approval/custody inputs. The primary analyzer and outer
owner return 0 and the owner is inactive with an empty cgroup; that establishes
known report completion, while the workload result remains FAILED. A16 and whole
release qualification remain open for an explicit failure disposition.

## Separate diagnostic9 observation, 2026-10-19

[Observation02](release-cohort.md#diagnostic9-observation02-ten-trials) executes
one separately instrumented userspace diagnostic and passes10/10 under the
original kernel111 cohort and timing limits. It records no BIND failures; the
original trial6 role/errno/cause remains unobserved. Its ten trials are excluded
from this frozen80-trial comparison and the two prior pilots. The eight
comparison rows remain unchanged; the aggregate comparison and acceptance
remain FAILED.
Normal shutdown and stopped custody complete; this gives no physical or UART
trace qualification and does not establish that the earlier failure is fixed.

## Passcred10 successor comparison: PASS, 2026-10-19

The original comparison above remains FAILED79/80. A separately numbered
successor addresses the supported listener-credential race without replaying or
backfilling the failed trial. Source `7858e1674bacb1f8f67455cf42955e762a54a70254ddbba089f8de7abe0b273e`
enables `SO_PASSCRED` on the bound gateway listener before `listen`; the exact
pinned ARM64 target build is `18fc58610ffbfe37c8eeebc583cc55d8fbc3c08fa3c885e253cc3b4cc0ac3835`.
The common workload `40f75fe9…2398`, production module `a49fd1a…1112`, timing,
scenario order, limits and amendment7 instrumentation remain unchanged.

Two excluded trace pilots pass 10/10 on distinct kernel/userspace boots with
78/78 eligible requests correlated in each. The new four-boot ABBA campaign then
passes all eight fixed runs: **80 planned, begun, ended and passed trials; 0
failed or unstarted**. Every traced run correlates 78/78 eligible requests. All
eight summaries report complete event-loss coverage, zero new loss, zero sequence
discontinuities, zero reversed clock pairs and no saturation. Block 3 evidence
and trace both pass 10/10, including the position corresponding to the original
failure.

Independent local analysis receipt
[`27104456…d9e8`](../../artifacts/a16-passcred10-final-analysis01/result.json)
reparses raw events and verifies the six distinct boot identities, denominators,
trace correlations, source pins and preservation of original receipt
`d4f3ef18…1b8e`. Final custody
[`216e3586…d7a8`](../../artifacts/a16-passcred10-final-stopped-custody01/result.json)
records both successor units inactive/PID0/empty cgroups, ports 26226/27448 free,
and no repository QEMU or fixture actor. The original parent disk remains
`cf7b67ab…87de`; successor overlay is `20e63d6a…c2f4`.

This establishes the successor software comparison only. Raw evidence remains
in ignored local artifacts and `.cache`, is not durably archived off-host and is
not a release signature. It measures host request admission and immutable UART
frame acceptance, not physical UART drain, controller response, actuation or
hard WCET, and supports no superiority claim.
