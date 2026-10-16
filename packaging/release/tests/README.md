# Disposable role-installation integration fixture

This harness is preparation for a separately authorized campaign. No guest has
been installed by creating these files. A successful run tests installer decisions
on one explicitly supplied disposable QEMU guest; it is not release promotion,
independent operator acceptance, arbitrary-media crash proof or physical proof.

Use a **new disposable** exact Debian 13.7 QEMU guest for each role. There are no
SSH endpoint/port/key defaults and no VM creation, downloads, package installation,
module loading or service startup. Never point this harness at the existing
kernel, manager, server or development guests. The operator independently checks
the original image SHA-512, guest host key, boot ID and machine ID. Caller-provided
image identity is an attestation; an in-guest check cannot rehash its parent image.

Prepare a complete real input specification using the release examples, with
independently selected hashes of actual binaries, assets, module, units, profile,
licenses and compiler/build provenance. Debug executables larger than the fixed
64 MiB per-file limit need an appropriately reviewed release build; the harness
will not strip or replace them. Selected tools must match the current release
scripts. Preparation never substitutes synthetic files for missing real inputs.

```sh
python3 -B -E -s packaging/release/tests/guest.py prepare \
  --spec COMPLETE_REAL_INPUTS.json --out NEW_PRIVATE_PREPARATION_DIRECTORY
```

Preparation verifies the selected input hashes, retains their manifest entries,
and stores **one** bounded payload archive. Five small manifest variants exercise
unsigned, signed-incomplete and signed host-mismatch rejection plus two complete
fixture tuples. The fixture tuples differ only in clearly marked test evidence;
no binary, module or selected input hash changes. A disposable Ed25519 key is
created under the private preparation directory; its name and evidence explicitly
say **integration fixture, NOT a release**. Its private key is never uploaded.
The test's `software-preview-qualified` manifest value exists only to exercise the
installer's signed-candidate path; it is not real qualification or a release key.
No artifact from this directory may be promoted or used on a non-disposable host.

The caller must inspect the preparation and separately authorize a real campaign:

```sh
python3 -B -E -s packaging/release/tests/guest.py run \
  --prepared NEW_PRIVATE_PREPARATION_DIRECTORY --output NEW_RESULT_DIRECTORY \
  --ssh-host EXPLICIT_GUEST_IP --ssh-port EXPLICIT_PORT \
  --ssh-key EXPLICIT_PRIVATE_SSH_KEY --known-hosts VERIFIED_KNOWN_HOSTS \
  --expected-boot-id EXPECTED_UUID --expected-machine-id EXPECTED_MACHINE_ID \
  --image-sha512 INDEPENDENTLY_VERIFIED_BASE_IMAGE_SHA512 \
  --fresh-disposable-guest I_CREATED_THIS_DISPOSABLE_GUEST
```

Before upload, the harness checks the authenticated SSH endpoint's root identity,
Debian version, architecture, running kernel, QEMU virtualization, exact supplied
boot/machine identity, absent prior Actryn installation/configuration, inactive
role services and absent authority module. The exact kernel/package artifacts
are then checked by the actual installer's `SystemPlatform`. Mismatch aborts;
there are no retries, alternate endpoints or automatic recovery of failed steps.
All guest paths are fixed beneath a unique private campaign directory or the
installer's fixed production paths. Failed campaign directories and diagnostics
are retained. Running the same campaign twice is rejected.

The explicit scenario creates clearly named state/evidence/secret sentinels before
installation, checks unsigned/incomplete/wrong-host/wrong-role rejection without
managed-state mutation, stages and activates the base tuple, then interrupts a
second activation **after its durable pointer publication** using the installer's
existing test callback and process exit. It checks a complete retained tuple,
explicitly completes recovery, then explicitly rolls back to the retained base.
Sentinel hashes, persistent inhibition, inactive services and absent module are
checked throughout. No operation is proposed, no grant/rearm/recovery of runtime
authority is requested, and no runtime database is restored. Failure aborts and
preserves the actual failing phase; the planned explicit recovery after the
injected exit is a distinct test step, never a silent retry.

The scenario deliberately finishes inhibited. It checks that preflight and resume
reject before missing local bootstrap configuration can clear the gate. Full
successful startup needs separate reviewed sysusers, valid local configuration,
verified server artifact import or robot module/DTB setup, explicit resume and
explicit unit starts. This harness does not perform those actions or claim that
acceptance. Keep the independently trusted external bootstrap scripts available
when initial publication has no working installed CLI/current pointer.

Host-only preparation/probe regressions reuse existing synthetic release-test
fixtures and disposable test keys, without SSH or guest state:

```sh
TMPDIR=/dev/shm PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s packaging/release/tests -v
```
