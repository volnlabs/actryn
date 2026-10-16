# Paused implementation checkpoint — 2026-10-16

The user requested **push the work and stop for now**. Pause the persistent goal;
the full v0.0.1 release is incomplete. Resume only on a new user instruction.
The approved scope remains [the full plan](../superpowers/plans/2026-10-16-actryn-v0.0.1.md).
[Progress](progress.md) and [acceptance gaps](acceptance-gaps.md) retain the evidence.
Earlier checkpoints and failed attempts remain preserved.

## Repository and execution state

- Integration branch: `feat/v0.0.1`; implementation HEAD before this handoff:
  `ec2dfde`. The user authorized pushing this branch to `origin`. Recheck the
  remote head on resume. Every task commit carries
  `Signed-off-by: Utkarsh Maurya <projects.utkarshMaurya@gmail.com>`.
- All three agent lanes stopped. All QEMU and controller-fixture processes are
  absent. No new native build, guest or campaign was started for this pause.
  `artifacts/server-a08-import-failure01/pause-result.json` verifies the original
  Server PID absent and its unit inactive/MainPID0 after one graceful poweroff.
  Receipt SHA256: `86e8eee0fe4d760c958627e8057c09d244f737acff51ea8507dc4b3d9451fe8d`.
- Both Server stores retain exactly eight reaped attempts with zero open calls
  or Robot debits. No container tasks, child cgroups, fault shim or drop-in exist.
  Source, failed import, disks, seed and SSH trust remain preserved. Raw artifacts
  and VM state are ignored local files; a Git push does not back them up.
- Host boot: `7f875223-b4cf-421e-b04d-81e3c1f19460`. Prior fixture processes did
  not survive the host reboot and none was restarted. No physical device used.
- All linked worktrees were inspected. Existing Cargo.lock changes remain
  untouched in `.worktrees/{fixture,observer-install,robot,server,source-gap}`.
  The new `.worktrees/artifact-modes` branch is clean and integrated.
- Original userspace: Apache-2.0; kernel/BPF: GPL-2.0-only. No global Git identity
  or provider/signing credentials changed. Account quota telemetry is unavailable.

## Server pressure campaign: import defect fixed in source, not deployed

`cd9d551` contains the pressure harness; 43 integration host checks passed.
`1293676` corrects the installed command to `actryn server import`. Plans01–05
and their failures remain preserved. Plan06 passes seven host checks, then actual
boot, staging, preflight and toolchain simulation against all 14 runtime pins.

Toolchain install01 failed because the preparation helper's inherited 8 MiB file
limit interrupted an apt download; all 328 installed package rows stayed unchanged.
Reviewed plan02 caps output without limiting downloaded files. Six host checks pass,
including reproduction of the earlier failure. Actual install02 passes with exactly
35 additions, no change to existing packages/runtime pins, and clean dpkg audit.
Evidence: `artifacts/server-a08-toolchain-{plan,install}02`.

Native pressure-agent and fault-library compilation and OCI assembly then pass.
Actual import fails with `rootfs file mode changed`: process umask 077 filtered
requested file modes to 0500/0400. The invalid sealed artifact remains at
`/var/lib/actryn-artifacts/443737b73904317b1ca87741eee2582997dcd1ab9c9fef4f833de7a06b647110`.
It was not allowlisted, and no pressure attempt, shim or campaign was launched.
The original approved artifact/configuration remains unchanged. Raw build/import,
capture and shutdown evidence is under `artifacts/server-a08-pressure-run06` and
`artifacts/server-a08-import-failure01`.

`ec2dfde` integrates the shared writer fix: apply the requested permissions on the
exclusively created descriptor after writing and before syncing. RED reproduced
artifact verification and config-mode failures; all ten Server library tests,
strict all-target Server Clippy and formatting pass. Subprocess regressions cover
umasks 027/077 and retain existing-file/symlink rejection. Logs:
`artifacts/artifact-modes01`. The installed importer remains unchanged. This fix
neither repairs nor overwrites an existing invalid sealed slot.

Next: rebuild/package the importer from the integrated source and record a new
coherent candidate. Review explicit recovery of the retained failed slot before
any new import; do not delete, chmod or silently retry it. Preserve cohort01 and
prepare a new numbered campaign with fresh lifetime bindings.

Historical run06: unit `actryn-server-a08-pressure06.service`, PID 226766,
start ticks 686142, invocation `79c8a4c9216b49d698f50625a775b6d4`, guest boot
`73a11031-bf36-4858-8c97-38a0ff74a91f`. These identities are now dead.
The retained disk is `.cache/qemu/install-server03/disk.qcow2`, device 56,
inode 27349874, size 2126446592, mtime_ns 1792174467145588725. Its contents changed
through compiler installation and the failed import; no full disk hash is claimed.

## A16: reviewed build-only plan, execution not run

Excluded pilot07 remains FAILED: the first HELLO faults before grant/START/SAMPLE;
nine other trials pass. Exact rejected predicate and cause remain unproven.
No repeat pilot, userspace pilot or comparison ran. Original evidence remains in
`artifacts/a16-execution07/tracekernel07`.

`e9b2bd8` integrates five diagnostic files; all 24 focused host checks passed.
The unchanged HELLO predicate and timestamp sample remain authoritative. Event
loss, gaps and nonzero/unknown RECOVER results prevent diagnostic success.
This admin-only diagnostic cannot replace production module 16 or qualify release.

`artifacts/a16-hello8-native-plan01` is now complete and reviewed for compile-only
execution. Its 24-file inventory SHA256 is
`8c94877a1aef432c048b6d48f2db6474073e17f141ef36418db30b9c661fc47b`;
source archive SHA256 is
`9cad135e205f0eea39f6e2c3a1573119b04f615ab02d8e2115f3f12927f5a0d7`.
Syntax, eleven source members, ten package pins and five tool pins were checked.
It uses a disconnected second UART and one bounded native build. No execution
window was released: disk hashing, VM launch, native compilation, module loading
and the target diagnostic are NOT_RUN. Revalidate gates before any future launch.

## Source, notices and unsigned candidates

- `artifacts/release-cohort01` remains unchanged, unsigned, qualification incomplete
  and `promotable=false`. Root independently verifies all 55 inventory files
  (115,773,094 bytes) and all 44 payload entries/modes. Manifests:
  Server `f3018c58da0f2687cfaf54d52244589078ae24d8bd1d83263a141e20feaeb484`;
  Robot `878732d88c534a87388c35aff7a6e2b35ef9192fb50210d045b77cd053536800`.
  Source revision is `cc530d2`; component origins are separately recorded.
  This candidate predates the importer fix. No candidate was installed or signed.
- `artifacts/release-source-materials01` binds 250 files/86,498,309 bytes to those
  manifests, including ten Git archives and 234 public source/receipt copies.
  Root independently verifies every file and 2691 Git leaves, including symlinks
  and executable bits. Material manifest SHA256:
  `9b3edb584823732c5d8760b02bb818d17441fe8d1ada82d9e14b1e1ff5b65581`.
  Receipts: `artifacts/release-cohort-root-review01/{source-materials-result,git-source-result}.json`.
- Exact offline agent/OCI bytes were reproduced in `offline-oci-matching-build03`.
  Complete exact glibc source and all 74 inventory entries were verified in
  `glibc-source-complete01`; all 16 selected notice slices pass independent review
  in `release-notices02`. These are retained `artifacts/` directories.
  Full GCC source and broader dependency/toolchain source closure remain explicit
  gaps; no hermetic-build or legal-completeness claim follows from these checks.
- Replacement fixture ELF imports match the actual Server runtime libraries;
  its installed Server execution is NOT_RUN. Installed binaries are unchanged.

## Remaining integration and external gates

`artifacts/robot-retained-debit-plan02` amendment03 remains prepared, NOT_RUN;
11 host checks previously passed. Its null template must not execute. Future
execution needs fresh boot/process/controller identities, post-A08 catalogs and
a new workload principal under the existing lifecycle03 issuer. The old principal
is revoked. Preserve namespaces/history; six preparations project 9 to 15 of 16.

Resume with this handoff and current ledgers, then verify branch/worktree state,
resources and retained evidence. Rebuild/reconcile the importer and resolve its
failed-slot recovery before another pressure campaign. Run only a reviewed,
numbered campaign with fresh identities and evidence paths. A16 has no allocated
window. Authorized live-provider credentials, a release signing custodian and
an independent developer remain external inputs. Final coherent qualification
is unfinished. Live motion stays inhibited; no result is physical qualification.
