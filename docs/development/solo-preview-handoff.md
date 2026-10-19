# Solo-maintainer v0.0.1 handoff

Approved 2026-10-19. Owner of every human step below: **Utkarsh Maurya**.
This is preparation, not a claim that keys or a personal installation exist.
The earlier off-host archive restore passed, and corrected live software evidence
is recorded in [the A13 successor receipt](live-observation-qualification.json).
Current attestation readiness is in [the v2 successor packet](solo-preview-qualification-v2.json);
the [predecessor packet](solo-preview-qualification.json) remains unchanged.
The [approved plan](../superpowers/plans/2026-10-19-actryn-solo-preview.md) is the
release contract. Original independent A14 remains DEFERRED.

After all required gates pass, describe this release as: **Qualified by the sole
maintainer; independent installation and physical qualification have not been
performed.** Before that, call it an incomplete candidate.

The historical [packaging instructions](../../packaging/release/README.md) are
hash-bound evidence and remain byte-identical. This amendment overrides only
their staffing/key-establishment language: the custodian may be the sole
maintainer, who may deliberately establish the first release key. "External"
means outside the build/installer, not another company. `server-independent-D2`
means Server independence from Robot, not an independent human review. Existing
manifest scopes, RPC, UAPI and runtime checks are unchanged.

## 1. Close software evidence before approval

Run from the repository root:

```sh
python3 -B ci/solo_qualification.py
python3 -B ci/solo_qualification.py --receipt-root .
```

The first command checks structure and reports zero bytes/receipts verified.
The second verifies small receipts, the immutable historical packet, historical
receipt bindings, both manifest projections and both payload archive hashes.
Neither command signs, approves, replays a campaign or substitutes for reading
the evidence. `--require-ready` exits nonzero until all required rows have valid
PASS associations, their local evidence is present and your review is recorded.
It still reports `release_qualified:false`: signatures and actual distribution
verification are separate.

The four nonhistorical gates A13, MAINTAINER-INSTALL, KEY-RECOVERY and
ARCHIVE-RESTORE require a dedicated JSON receipt in their evidence lists:
`format: actryn-solo-check-1`, the exact `gate`, `owner: Utkarsh Maurya`, selected
`subjects` copied from the packet, and `status: PASS` only after execution.
Gate-specific required fields are:

- A13: `standalone_receipt` and `composition_receipt`, naming the preserved
  standalone PASS and the bounded corrected-live/exact-package receipt in the gate
  evidence list. The checker rejects missing-credential/offline substitution and
  requires the exact two-binary Server identity, one provider call, reconciled
  operation closure, fresh-target lifecycle and explicit nonphysical boundaries.
- MAINTAINER-INSTALL: `execution: human`, `operator: Utkarsh Maurya`,
  `independent: false`, and ordered `completed_checks`: `install`, `diagnose`,
  `pair`, `offline-two-operations`, `cancel`, `restart-recover`, `export`.
- KEY-RECOVERY: equal `public_key_spki_sha256` and `restored_spki_sha256`, and
  true `encrypted_key`, `challenge_verified`, `tamper_rejected` results.
- ARCHIVE-RESTORE: true `off_host` and `all_entries_verified`, designated
  `filesystem_uuid`, `archive_sha256` and `restored_inventory_sha256`.

These records are declarations backed by reviewed receipts, not independent
authentication of a human's actions. Never generate a human PASS from agent work.
Your separate review receipt uses `format: actryn-solo-maintainer-review-1`,
`owner`, exact `subjects`, `decision: approve-for-attestation`, a `dispositions`
map of every gate ID to status, and `inputs_sha256`. Compute that digest with
`ci/solo_qualification.py`'s `review_input_digest(packet)` after setting the review
reference: it binds all packet inputs except the review record and its own
receipt entry, preventing a hash cycle. The review must not serve as gate evidence.
Changing inputs or dispositions invalidates the review; an unrelated historical
packet cannot substitute for any of these records.

Each gate's PASS must name evidence and a source/configuration association to
both selected subjects. Changing a selected payload requires renewed affected
associations. The predecessor packet remains bound to Server9f/Robotda6; v2 binds
the corrected Server CLI/serverd pair and retains the same Robot subject.
Do not edit the historical packet to make it green. A09 sync faults, packaged
automatic restart, and live A13 must not be closed by unrelated happy-path tests.

## 2. Establish the dedicated signing identity

Perform this yourself in a private terminal outside the agent transcript. Use
the installed OpenSSL; enter passphrases at its prompt, never in flags, files in
the repo, environment variables, or chat. Do not reuse any fixture/SSH key.
The commands refuse an existing key destination. Public key material is shareable.

```sh
set -euo pipefail
umask 077
ACTRYN_KEY_DIR="$HOME/.local/share/actryn-release"
install -d -m 700 "$ACTRYN_KEY_DIR"
test ! -e "$ACTRYN_KEY_DIR/release-ed25519.pem"
openssl genpkey -algorithm ED25519 -aes-256-cbc \
  -out "$ACTRYN_KEY_DIR/release-ed25519.pem"
openssl pkey -in "$ACTRYN_KEY_DIR/release-ed25519.pem" -pubout \
  -out "$ACTRYN_KEY_DIR/release-public.pem"
openssl pkey -pubin -in "$ACTRYN_KEY_DIR/release-public.pem" -outform DER | sha256sum
```

Record owner, creation date, public key and SPKI fingerprint in a public custody
receipt. Verify a challenge signature and rejection after changing the challenge
or public key using the existing release signature tests as the interface guide.
Keep the encrypted key outside CI and guest images. Publish its fingerprint in a
maintainer-controlled trust record; a key downloaded beside a candidate is not
itself a trust anchor. Do not sign release manifests until their evidence review.

Loss/compromise: stop signing, record affected releases, establish a replacement
identity and announce its independently verified fingerprint. Never silently
replace the old trust pin or rewrite published signatures.

## 3. External-drive backup and restore

Supply the drive's filesystem UUID and mount path; no formatting is required.
Confirm `findmnt --target DRIVE_PATH` reports the expected external filesystem,
not the workstation root filesystem. Use a new private directory on that drive.

Prepare an explicit allowlisted archive inventory with relative paths, lengths
and SHA-256 hashes. Include exact payloads, build/dependency inputs, fixture and
nonsecret configuration, qualification receipts and the raw evidence supporting
their claims. Include original failed campaigns. Existing preservation01/02
archives are useful inputs, but selected receipts alone are not the complete raw
evidence archive. Do not recursively archive `.cache`, credential directories or
whole guest disks containing keys. Preserve required data selectively.

Use GnuPG's interactive symmetric encryption for the evidence archive:

```sh
gpg --symmetric --cipher-algo AES256 --output "$ACTRYN_ENCRYPTED_ARCHIVE" \
  "$ACTRYN_PLAINTEXT_ARCHIVE"
```

These two paths must be explicitly selected new files in a protected staging
directory. Copy the ciphertext to the verified drive; compare its SHA-256 after
copy. Decrypt the **drive copy** into a new protected restore directory. Verify
every inventory entry and run the successor checker against the restored tree.
Archive the repository material needed by that checker as well as ignored files.
Do not report restoration from checking the workstation's original archive.

Separately copy the encrypted Ed25519 key and public fingerprint to the drive.
Restore that encrypted copy into a protected temporary directory, unlock it
interactively, derive its public fingerprint and verify a challenge signature.
Keep recovery passphrases separately accessible to you; do not store them beside
the backup. Record public results only, then disconnect the drive. Retain release
evidence for the project lifetime with no automatic deletion. A single external
drive remains a single backup failure domain.

## 4. Bounded live acceptance

**Consumed 2026-10-19: do not rerun this campaign.** The standalone call passed;
the combined call consumed 33 tokens and failed closed because its original
one-second observation expired during inference. No operation was allocated,
outputs stayed zero, local recovery preserved the uncertain debit, and stopped
custody passed. Later Robot clock warnings are retained as separate post-failure
facts. The two-call budget is exhausted. A new attempt requires qualification of
the reviewed execution-observation correction, a new numbered campaign and an
explicitly renewed budget.

Provision a dedicated provider key yourself through the documented
`/etc/actryn/credentials/openai-api-key` server-only `LoadCredential` route.
Neither agent nor launcher receives it. No key or passphrase belongs in a report.

Use newly prepared, exact supported non-actuating guests after evidence backup.
Import the separately pinned live OCI profile following the
[live profile instructions](../../packaging/agent/README.md#separately-pinned-live-profile).
Freeze artifact/model-policy digests and guest identities first. The configured
model remains `gpt-5.4-mini-2026-03-17`; unavailable model/access is a failed input,
not permission to substitute a model or silently change the profile.

The consumed budget was at most two provider calls total, one standalone live
check and one combined check. The standalone harness ran once with
`--expect completed`. The combined invocation used the exact named arguments
from [combined acceptance](../../packaging/agent/ROBOT_ACCEPTANCE.md), the live
artifact digest and `--allow-one-live-provider-call` in a new output directory.
That option ran only the combined case, avoiding the extra unbound-agent call in
the default offline campaign. No automatic retries occurred.

Keep 1,024 output tokens, 64 KiB response and the 30-second transport bound. The
model-input and execution observations each retain the one-second Robot freshness
ceiling. The first remains immutable model lineage; after inference the broker
captures exactly one newer execution observation and requires unchanged encoder
values and context revision before dispatch. These are not an invoice cap. The
harness checks the real model, both observation roles, bounded target, settled
token count, kernel completion, reconciliation and final exports. Never widen the
bound, retry a mismatch, relabel offline output or start another campaign until
its failed/unknown predecessor is inspected and explicitly closed. Record every
provider dispatch, including uncertain ones.

## 5. Your manual rehearsal

Use fresh supported Server and Robot guests and the selected exact payloads,
initially through clearly labelled disposable test signatures. Record base-image
hashes, boot/machine IDs, software tuples and candidate hashes. Do not reuse the
retained qualification guests or reset their histories. Host package preparation
is separate from Actryn installation.

Follow this one route through shipped instructions, executing commands yourself:

1. [Host prerequisites](../../packaging/release/README.md#host-prerequisites-and-maintenance),
   then [stage/activate/recover/rollback](../../packaging/release/README.md#stage-switch-recover-and-rollback).
2. [Server bootstrap](../../packaging/release/README.md#fresh-independent-server-explicit-local-bootstrap),
   then [Robot bootstrap](../../packaging/release/README.md#fresh-robot-explicit-local-bootstrap).
3. [Enrollment/readiness](../../packaging/release/README.md#robot-enrollment-and-read-only-readiness),
   then [delegated offline execution](../../packaging/release/README.md#delegated-offline-agent-execution).
4. Repeat a natural operation under the retained valid grant only after explicit
   reconciliation; retain both operation IDs. Follow the existing lifecycle
   instructions for cancellation, restart/recovery and evidence export.
5. Diagnose one injected failure using the documented evidence. Record elapsed
   time, exact failed step, confusing wording and every instance of assistance.

Create a report containing your name, date, exact subjects, ordered commands and
results, operation/grant identities, cancellation/recovery outcomes, export hashes,
friction and assistance. State `independent:false`, `operator:Utkarsh Maurya` and
`execution:human` only if you actually performed the steps. Agent execution is
not your manual rehearsal. No report template pre-populates PASS.

## 6. Final signing and distribution verification

Resolve all required packet rows, then record your review as a separate referenced
receipt. Freeze the packet bytes and hash before adding its `qualification-bundle`
reference and existing role-scoped attestations to new candidate input specs.
Build with `packaging/release/release.py build --spec ... --out ...`; verify unchanged
payload bytes, then sign each exact canonical manifest with your dedicated key.
Use the existing `inspect` interface and your externally pinned SPKI fingerprint.

On fresh guests verify the actual signed bundles, installation, bootstrap,
inhibited initial state and bounded workflow. Do not replace retained test manifests
or invent a genuine signature from test evidence. Put post-sign checks in a separate
distribution receipt referencing manifests, signatures and the frozen packet; do
not add it back into the already signed qualification hash. Archive and restore
the final distribution set and receipt too.

Run final host checks and actual hosted CI on the pushed head. Update PR #1 with
the limited release claim and observed results. Merge, tagging and publication
remain separate. When another human joins, execute original A14 and publish a
new additive qualification record identifying exactly what they tested.
