# A16 amendment 7: native compilation freeze

The common workload and ABI 7 capture module compiled successfully on the
dedicated `actryn-a16` guest using Debian GCC 14.2.0-19 and Linux headers/image
6.12.111-1 (`6.12.111+deb13-arm64`). The one native build, retrieval and independent
archive/source/ELF/hash verification are retained under
`artifacts/a16-amendment7-native-build01/`. This establishes compilation only.
Both new instrumentation pilots and the eight comparison runs remain NOT_RUN.

| Input | SHA-256 |
| --- | --- |
| Verified native evidence archive | `887124e9c3fab35bde1d3bf422fff87c389b1d27e28aa2d71f7142aeb1fa91c8` |
| Original amendment 7 source archive | `2f8d1f5c3c8e4dfb14c70d73caec245ecfda2fa8524916a32b6d48f693a401ce` |
| Source derivation record | `880f7acf8b2e9205e3ed1bf474c965562fdb0f3285cb667e6f740d875297983c` |
| New common workload | `40f75fe9d898bcd2320f97e70257426f3ca71cdddffe562a25f7581ccba42398` |
| New capture module | `fae8eccb64cbe586f55a5c92c4b0521173dc2c4308fd5fa60f0c6cb3f646b403` |

Workload GNU build ID: `a868382dc485265d69f67061157383fbca387578`.
Capture module GNU build ID: `e8c3965072ce9c9a3f1c04681598a5576b302aa5`.
The exact kernel config and Module.symvers, three required GPL exports, package
versions and all 42 derived source hashes were checked. Neither binary was
executed or loaded during the build. No production driver, gateway, limit,
deadline or original frozen input changed.

## Immutable originals and named manifest copy

`AMENDMENT7.md` is itself in the frozen source inventory, so its historical
pre-build text remains unchanged. This separate document records the completed
compile freeze. The three new tracked manifests form this dependency chain:

1. `instrumentation7.toml` pins the actual capture module and native evidence,
   exact ABI 7 bounds and eight capture source files.
2. `amendment7.toml` pins that manifest, actual workload and the exact capture and
   workload source sets.
3. `campaign7.toml` pins both manifests, all 42 derived source files and the
   three selected guest binaries. Authority module 16 and the gateway retain
   their prior hashes. The four-boot ABBA matrix, two runs per boot, ten trials
   per run and no-automatic-retry policy remain unchanged.

Use `amendment7.py` to create a fresh derived hierarchy, and verify its
`DERIVATION7.json` against the hash above. Exclusively create these copies:

| Tracked source | Path relative to fresh derived root |
| --- | --- |
| `instrumentation7.toml` | `kernel/tests/a16/instrumentation7.toml` |
| `amendment7.toml` | `kernel/tests/a16/amendment7.toml` |
| `campaign7.toml` | `kernel/tests/a16/campaign.toml` |

The destination campaign manifest is absent from the source derivation; copying
does not replace an existing file. Retain the mapping and verify byte identity.
Never overwrite the original tracked `campaign.toml`. Its original inputs remain
available for the existing environment3 checks. The verified local freeze is
`artifacts/a16-amendment7-freeze01/source7/`; `freeze-map.json` records the mapping.

The derived runner's source checks use the new manifests. Its environment3
redirection separately verifies the originals under the integration repository,
using that repository's `.cache/qemu/a16` state argument. The exact derived
capture module may be copied beside the derived capture helper for read-only
`capture_guest.verify_inputs()`; this does not load it. Existing
`campaign.verify_campaign_inputs()`, capture verifiers and
`campaign.prerequisites(state_root, 0)` passed on this freeze without SSH, a
fixture command or consuming a pilot label. Eleven existing derivation/capture
freeze tests passed, including missing/wrong source and binary pins and failure
restoration of the original-source verifier path.

## Deployment and excluded-pilot boundary

The retained compile boot may receive the reviewed new files into fresh
directories. Staging must verify its actual boot identity, unchanged selected
module/gateway, complete new source/manifests, and absence of modules/workloads;
it must preserve all earlier source/build and failed-pilot directories. A full
derived source hierarchy is kept separately from the capture helper's runtime
directory so relative workload/header paths retain their meaning. Capture helper
verification uses its exact runtime source inventory. Staging does not load a
module, execute a workload, change a service or reset the fixture.

The compile boot cannot run either pilot: its serial/QMP argv intentionally names
the native-build attempt, and the frozen runner requires the exact pilot argv.
After staging and graceful shutdown, use the derived runner's `commands` output
for a fresh `tracekernel07` boot. Preserve its result and shut it down before the
separate raw `traceuserspace07` boot. Record each actual boot/process identity and
the same finite host limits (TasksMax 256, MemoryMax 3 GiB, Restart=no).

If the emitted QMP path still contains a stale socket, retain its inode/type and
prior process identity, require no live holder/listener or dedicated QEMU, then
perform only the reviewed stale-path removal. Never silently replace a live
socket or overwrite a serial log, output directory or failed attempt.

Run the unchanged derived pilot entry points only on those respective exact
boots, with the original integration state directory as the final argument:

```text
python3 -B DERIVED/kernel/tests/a16/campaign.py trace-pilot kernel ROOT/.cache/qemu/a16
python3 -B DERIVED/kernel/tests/a16/campaign.py trace-pilot userspace ROOT/.cache/qemu/a16
```

Both are excluded qualification pilots. Matching pilot PASS records are required
before any comparison block. Retain every attempted workload and failure; a
failed pilot blocks comparison rather than authorizing another attempt. Neither
host verification nor a future fixture result establishes physical qualification,
hard WCET, or superiority over the userspace baseline.
