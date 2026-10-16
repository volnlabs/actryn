# Amendment 7 source preparation — not frozen for target execution

The first module 16 tracing pilot is preserved as FAILED at
`artifacts/a16-execution01/tracekernel01`. Its ten trials ended with nine PASS and
one first-SAMPLE failure. Every HELLO also exceeded instrumentation 4's 158-byte
capture cap: the production driver writes one synchronization delimiter plus a
158-byte frame. Those missing captured bytes cannot be reconstructed afterward.
The clock evidence supports a premature first sample but does not identify the
exact private transmit-check predicate. No comparison run has occurred.

This amendment changes only the common test workload's first-sample eligibility,
test instrumentation's bounded prefix capacity/format, and the required numbered
adapters. It changes no production driver, gateway, fixture or authority limit.
Both arms receive the identical new workload binary and new instrumentation.

`first_sample7.h` retains the actual matching HELLO_ACK and STARTED records. It
requires the same nonce, device/controller epoch and allocated operation identity;
a poll alone cannot establish receipt. The lower clock uses the manager's
`Mapping::controller_lower` rule: HELLO event host time, a 10 ms conservative sent
bound, and 100 ppm drift rounded outward. HELLO capture minus 10 ms is a synthetic
conservative anchor, not a captured actual send timestamp. SAMPLE1 waits for at
least 100 ms of mapped
controller credit after STARTED. A mere 100 ms host sleep is insufficient at the
boundary. Faults, event loss/gaps, epoch changes, reversed/overflowed time and
mapping expiry fail the trial. The unchanged 10 s scenario alarm bounds the wait.

Once eligible, the existing sample schedule starts: offsets 0..900 ms for ten zero
duty samples, with 100 ms spacing. Cancel/owner exit remain after sample 5 at nominal
offset 400 ms. Delayed-applied still uses 600 ms reply delay and 150 ms sample expiry.
The normal 400 ms sample expiry, 5 s operation, 15 s grant, 900 ms observation and 1500 ms
health remain unchanged. Health/observation are refreshed immediately before each
sample as before. The measured settling interval and its CPU cost are retained;
no operation deadline is extended. A new raw record ties eligibility to the actual
HELLO/STARTED sequence numbers and timestamps. Independent Python validation
recomputes the lower bound and checks every sample's identity/count/schedule.

Capture ABI 7 keeps the 128-byte header, 4096 records of 256 bytes and maxactive 64.
It changes magic to A16UART7, version to 7, accepted-prefix cap to 159 and reserved
record bytes from 26 to 25. The encoded-frame bound remains 158. Counts above 159,
loss, failed reads, invalid returns, overlapping calls, missed/in-flight returns,
malformed COBS/CRC, partial final frames and ambiguous duplicates still invalidate
complete dispatch evidence. ABI 4 is rejected by the ABI 7 decoder; old evidence
is never reinterpreted under the new format.

## Derived sources without overwriting frozen inputs

`amendment7.py NEW_DIRECTORY` verifies exact frozen hashes and makes a new source
tree. Only six derived files differ: workload, capture prefix/header implementation,
decoder, capture lifecycle metadata and campaign adapter. `DERIVATION7.json`
records every input/output hash and exact unified diff. All original tracked
files and old source/build directories remain unchanged. Existing/partial output
directories are refused. This helper never builds, deploys or launches anything.

The derived campaign reuses the original lifecycle, start/retirement fence,
request denominators, timeouts and fail-stop policy. It selects new
`/opt/actryn-a16/build-amendment7` and `/opt/actryn-a16/instrumentation7` directories,
pilot labels `tracekernel07`/`traceuserspace07`, and `comparison7/block7b01` through
`block7b04`. The same four-boot ABBA order and two runs per boot remain. It verifies
module 16's actual acceptance aggregate and loaded GNU note through the frozen
campaign6 helper. Only serial log labels differ in newly emitted QEMU commands.
Environment3 continues to validate amendment 2's original source bytes in the
integration repository, never the deliberately changed amendment 7 derivatives;
its original path is restored even on validation failure. The original manifest
still pins each of those source files independently.

## Verification and freeze still required

Original target failure is the meaningful RED evidence. New parser tests cover
whole 159-byte writes and every split, short/zero/error writes, over-cap 160-byte
writes, old ABI rejection,
malformed frames/CRC, padding, loss and duplicates. C tests cover the actual
first-receipt identity, clock-credit boundary and prefix accounting. Compile the
common workload and capture module against the same exact ARM headers into new
directories; retain the complete source derivation, toolchain, config, symbol
exports, object hashes and GNU note. No target load is implied by compilation.

After those checks, freeze new `instrumentation7.toml`, `amendment7.toml` and the
derived `campaign.toml` with exact new binary/source hashes. Retain module 16's
selected hash and the original gateway hash. Unfrozen source preparation is not
executable qualification: the derived runner requires those manifests and thus
fails closed until the build/provenance freeze is complete. Two separately
numbered instrumentation pilots must pass before the eight comparison runs.
No retry, target run, performance claim, WCET or physical qualification is implied.

The later binary freeze must provide these concrete inputs, with no old-format
aliasing: `instrumentation7.toml` revision 7 pins the exact new capture module and
its sources; `amendment7.toml` revision 7 pins that manifest plus the new helper
sources; the derived `campaign.toml` revision 1 keeps the four-boot matrix and pins
all derived/transitive helpers, both new manifests and the selected three guest
binaries. Capture lifecycle state uses `instrumentation7_sha256`; passive-guard
metadata is `amendment7.json` with both `instrumentation7_sha256` and
`amendment7_sha256`. The runner expects exactly those names. It records a new
derived runner hash and campaign manifest hash. Missing freeze manifests reject
preflight before a module load or workload start.
Both capture manifests require the exact `CAPTURE_SOURCES` inventory in
`capture_guest7.py`. Amendment 7 additionally requires its exact `WORKLOAD_SOURCES`
inventory and `workload_sha256`; the campaign must include every
`EXECUTION_SOURCES` pin. Missing/wrong new hashes reject before original-baseline
verification. Remote preflight then checks all three actual guest binaries and
capture sources/module before loading anything. Original environment3 checks do
not substitute for these independent derived-execution checks.

Deployment must retain the derived hierarchy for workload includes and host
source checks. `/opt/actryn-a16/instrumentation7` needs the new exact `.ko`, derived
`capture_guest.py` and `dispatch.py`, unchanged `capture_guest5.py` (only its
passive guard is reused), unchanged `uart_trace.py`, new `capture_guest7.py`, both
new manifests and every source file those manifests enumerate. No helper may
refer to an undeployed input. The new build directory receives the same original
gateway, same selected module 16, new common workload, and its new AMENDMENT7
marker/provenance. The original integration source tree remains required for
environment3's independently pinned amendment 2 validation.
