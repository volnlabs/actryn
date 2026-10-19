# Actryn v0.0.1 solo-maintainer implementation plan

Approved in conversation 2026-10-19; supersedes only the staffing and independent
installation requirements of the 2026-10-16 plan. Integration: `feat/v0.0.1`, PR #1.

Goal: a maintainer-qualified, signed software developer preview with the actual
kernel path, offline demonstration and pinned live-model integration. Utkarsh
Maurya owns credential provisioning, signing, evidence retention and manual
installation. Independent A14 is DEFERRED, never PASS. Physical qualification
and live actuation remain outside scope. Publication/merge/tagging are separate.

## Tasks and exits

1. Amend the current specification and completion checklist; preserve original
   plans and immutable qualification checkpoints. Record the sole maintainer and
   exact release claim, and a separate manual installation requirement.
2. Create a successor qualification packet and fail-closed validator covering all
   16 acceptance cases and 17 D2 predicates, exact selected subjects, receipts,
   source associations and remaining tests. Only A14 may be deferred. Preserve
   FAILED79/80 and the independently numbered passing A16 successor.
3. Prepare a custody runbook: dedicated encrypted local Ed25519 key, public SPKI
   fingerprint, interactive passphrases, separate encrypted key recovery and
   evidence copies on an existing external drive, inventory/hash restore test,
   no formatting or automatic retention deletion. Utkarsh supplies the drive.
4. Extend existing combined acceptance helpers to exercise the live profile;
   keep offline behavior unchanged. Budget at most two provider calls across
   the standalone and combined campaign, no retries, original one-second
   observation lifetime. Failure/staleness is retained, not positive acceptance.
5. Prepare one manual installation/recovery route through existing instructions.
   Utkarsh executes it on fresh guests. Then freeze the packet, review/attest,
   sign canonical manifests and verify actual signed bundles on fresh guests.
   Record post-sign distribution checks separately to avoid circular hashes.
6. Run host regressions and packet verification; require actual CI on the pushed
   head. Commit with `Signed-off-by: Utkarsh Maurya <projects.utkarshMaurya@gmail.com>`.
   Update PR #1; ready-for-review only when all agreed candidate work is complete.

## Validation

Reject missing/duplicate gates, unsupported passes, missing or altered receipts,
wrong subject bindings, unexpected deferrals and fabricated independent results.
Host checks report zero local raw receipts verified unless explicitly supplied.
Keep signature/wrong-key/wrong-role tests. Live validation checks provider/model,
request/observation/operation lineage, bounds, accounted cleanup and evidence;
mocked tests cannot close A13. No runtime/UAPI/RPC changes are planned.

## Execution ledger

- Baseline: clean `9d19be4`; user approved solo scope, retained live run, external
  drive backup and personal manual rehearsal. No key/drive/credential supplied.
- Ruling: the goal tool retains the historical paused objective and has no
  objective-edit/resume operation. User continuation and this amendment govern
  current work; do not falsely mark the old independent-install goal complete.
- Ruling: use the requested feature checkout; no need for another worktree.
- Preflight: successor validation consumes existing evidence references; live
  campaign reuses offline lineage/export logic with an explicit profile. Neither
  checker nor test-key fixture can provide human custody or independent evidence.
- Usage telemetry unavailable; bounded execution, no assumed quota reset.
- Task 1: contract/ownership amendment implemented; original A14 deferred.
- Task 2: successor checker and 30 source-bound software associations implemented.
  142 successor receipt references, 107 historical receipts and two payload
  archives verify locally. A12/A13 and three human/custody gates remain open.
- Task 3: custody instructions prepared. Actual key/recovery and external-drive
  restore await Utkarsh; no keys generated or credentials inspected.
- Task 4: explicit one-call combined live mode and host regressions implemented.
  Actual provider run awaits provisioning and fresh guests after evidence backup.
- Task 5: manual rehearsal/signing/distribution route prepared; human execution
  and actual signed bundles are not fabricated. Packaged automatic restart needs
  a fresh target campaign after backup, without Restart=no qualification overrides.
- Ruling: preserve packaging/release/README.md byte-for-byte because the immutable
  historical packet hashes it. The linked solo handoff is the current amendment;
  changing the old file would invalidate retained installer-source evidence.
- Ruling: A12's pre-sign qualification covers mechanical installer/restart
  behavior. Genuine signed-distribution verification lives in a separate post-sign
  receipt, avoiding a circular dependency on the packet's own future signature.
- A09 RED without interceptor correctly failed; actual journal fsync stall/EIO
  passed twice per campaign with exact selected production-source association.
  Only test code changed. No database-file sync/fdatasync/media-power-loss claim.
- Validation: Python host suite passed. Initial Rust/kernel-host runs failed at
  socket bind under sandbox restrictions; retained those failures and reran with
  authorized host-test access. Rust format/Clippy/workspace/storage and kernel-host
  suites passed under artifacts/solo-preview-host03. No guest or provider started.
- Fresh scoped review found unrelated receipts could fabricate readiness.
  Reproduction failed as expected; fix requires dedicated live/human/custody
  receipts and exact-input/disposition-bound maintainer review. Nine validator
  tests pass, including rejection of unrelated historical approval evidence.
  Eighteen combined live/offline harness checks pass. No reviewer minor deferred.
- Final Python host checks pass under artifacts/solo-preview-host05/python after
  sandbox socket denials in host04 were preserved and the suite rerun with
  authorized host-test access. Ten checks (eight test components plus two packet
  validators) passed. Local `--require-ready` correctly exits 1 for the five
  remaining required gates; this is expected incomplete readiness, not a test failure.
