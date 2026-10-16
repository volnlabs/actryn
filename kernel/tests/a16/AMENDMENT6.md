# Selected production module16

Amendment6 replaces only the measured authority module, before any
instrumentation pilot or comparison run. Module16 adds native serdev shutdown
closure; its UAPI, workload and configured limits are unchanged. The userspace
gateway, workload, controller fixture, QEMU commands, kernel image, DTBs and
instrumentation4/5 retain their frozen bytes. No timing superiority or physical
qualification is established by this amendment.

The selected module SHA-256 is
`a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112`.
It was built against Debian `6.12.111-1` ARM64 headers. Source, configuration,
symbol versions, compiler/package records and its complete ELF GNU build-ID
note are pinned in [amendment6.toml](amendment6.toml). The native shutdown
source originated in `d3f48e8694faac2ae4f360e8d4d010824d50ec0a`, integrated as
`8802e97`. A real ARM shutdown/poweroff sequence remains NOT_RUN.

The wrapper requires the immutable aggregate
`artifacts/kernel-module16-acceptance01/manifest.json`, SHA-256
`00120810d6e385e32fe4d915852fbed819b9182cbf013aee668538dcb8d9a298`.
It verifies the aggregate's three actual-campaign hash inventories and their
raw files, all sixteen selected scenario markers/exit codes, the module identity,
the genuine same-numeric-PID reuse and surviving-sibling evidence, and the
separate seventeen-case plain/lockdep/KASAN/KCSAN archive. This is bounded
software acceptance, not full release acceptance. Original failed attempts and
the old module15 correctness pilots remain historical records; they are not
relabeled as module16 results.

`campaign6.py` delegates execution to the unchanged `campaign.py`. It stages
byte-identical pinned helpers under `.cache/qemu/a16/amendment6/host/`, with the
new manifest named `campaign.toml` only inside that new input directory. During
the call it selects that directory, the new guest build directory and a remote
wrapper. All original trial logic, ordering, retirement fences, denominators,
timeouts and failure handling remain in the frozen runner. The runner's
`campaign_sha256` consequently identifies amendment6; its `runner_sha256`
continues to identify the original runner. Separate wrapper attempt records bind
both identities and the original completed-record hash. Each attempt consumes
its label even if verification fails; the wrapper never retries or launches a VM.

After the runner's kernel-only `insmod` succeeds, the remote wrapper compares
the selected on-disk object SHA and every byte of
`/sys/module/actryn_authority/notes/.note.gnu.build-id` with the pinned ELF note.
Missing or different notes fail the attempt before a workload starts. This is
a trusted-Linux identity check, not protection against a compromised kernel.
The userspace arm never loads the authority module or reads that sysfs note.

## Host staging and guest input preparation

Run from the integrated repository. These first commands inspect local files
and create only a new host input directory; they do not contact any guest:

```sh
python3 kernel/tests/a16/campaign6.py verify "$PWD/.cache/qemu/a16"
python3 kernel/tests/a16/campaign6.py stage "$PWD/.cache/qemu/a16"
python3 kernel/tests/a16/campaign6.py commands "$PWD/.cache/qemu/a16"
```

The six QEMU command JSON records are unchanged, SHA-256
`bf785c5ea500cee47b4da74eabf3b765769fad492b68933eb400faabe7d8c8b7`.
The integrator controls their launch and all VM resource coordination.

On the dedicated A16 guest only, upload the selected module from
`artifacts/kernel-module16-build02/evidence/kernel/actryn_authority.ko` and the
committed `amendment6.toml` into a new `/opt/actryn-a16/module16-input/` directory.
Check the uploaded manifest SHA against the host verifier's reported
`manifest_sha256`. Preserve the original build directories. The following
fixed staging snippet performs no module load or package installation:

```python
import hashlib, pathlib, platform, shutil, socket, tomllib
assert socket.gethostname() == 'actryn-a16'
assert platform.machine() == 'aarch64'
assert platform.release() == '6.12.111+deb13-arm64'
base = pathlib.Path('/opt/actryn-a16/build-amendment2')
inputs = pathlib.Path('/opt/actryn-a16/module16-input')
target = pathlib.Path('/opt/actryn-a16/build-amendment6')
manifest = tomllib.loads((inputs / 'amendment6.toml').read_text())
assert manifest['amendment']['revision'] == 6
assert manifest['amendment']['guest_build'] == str(target)
files = {name: base / name for name in ('a16-gateway', 'a16-workload')}
files['kernel/actryn_authority.ko'] = inputs / 'actryn_authority.ko'
for name, source in files.items():
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['guest_binaries'][name]
assert (base / 'AMENDMENT2').is_file()
target.mkdir()  # Existing/partial attempt is retained, never overwritten.
(target / 'kernel').mkdir()
for name, source in files.items():
    shutil.copyfile(source, target / name)
    shutil.copymode(source, target / name)
shutil.copyfile(base / 'AMENDMENT2', target / 'AMENDMENT2')
shutil.copyfile(inputs / 'amendment6.toml', target / 'amendment6.toml')
(target / 'AMENDMENT6').write_text(hashlib.sha256((target / 'amendment6.toml').read_bytes()).hexdigest() + '\n')
```

The copied AMENDMENT2 marker denotes the unchanged workload/gateway lineage;
AMENDMENT6 and the new manifest identify the selected module. The campaign
preflight checks all three deployed binaries and the new manifest again.
Instrumentation deployment remains exactly the files and module specified in
`CAMPAIGN.md`; this amendment adds no probe or capture change.

## Explicit target execution, still pending

After each integrator-controlled boot, use the wrapper instead of the original
runner. The two instrumentation pilots are excluded from comparison:

```sh
python3 kernel/tests/a16/campaign6.py trace-pilot "$PWD/.cache/qemu/a16" kernel
python3 kernel/tests/a16/campaign6.py trace-pilot "$PWD/.cache/qemu/a16" userspace
```

After both pass, use `block ... 1`, `block ... 2`, `block ... 3` and `block ... 4`
on their respective distinct boots. The order remains kernel/userspace/userspace/
kernel, with one untraced then one traced run per boot: eight comparison runs,
ten fixed trials each. Keep failed attempts and all issued-request denominators.
Neither instrumentation pilots nor the comparison have run under amendment6.
