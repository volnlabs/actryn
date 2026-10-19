# Host checks

Run `python3 ci/check.py rust --output artifacts/ci/local-rust01` and repeat
with `python` and `kernel-host`, using a new output directory each time.
Results contain the Git revision, dirty-state flag, exact commands, exit codes
and per-command logs. A failed command does not suppress later checks. Partial
or interrupted reports stay `passed: false`. CI has a 30-minute job limit.

Prerequisites: the repository Rust toolchain, C compiler/make, pkg-config,
libelf/zlib development headers, protoc, Python >=3.11, OpenSSL, and the pinned
protobuf wheel in `requirements.txt`. CI uses Python 3.13.5. Host OS packages
and the Ubuntu runner are **not** the qualified Debian release tuple; these
jobs establish source regressions, not binary reproducibility or guest evidence.
The Rust suite also runs the isolated [SQLite sync fault regression](../tests/storage/README.md)
with a process-local interceptor. It records actual journal sync stall/EIO and
urgent closure with the host authority stub; it does not exercise the ARM kernel
or prove physical-media durability. The explicit runner is necessary because
the injected Rust case is ignored in ordinary `cargo test`.

The workflow uses ordinary pull-request events, read-only contents permission,
no retained checkout credential and full-SHA action pins, following the
[GitHub secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
There are no model credentials, privileged guests, device access, signing,
release promotion or installation actions. CI's 30-day logs are not the durable
release evidence archive. Target/kernel diagnostic campaigns remain explicit,
separately recorded qualification work.

`python3 ci/qualification.py` checks the historical incomplete packet's gates
and reference structure. It reports **zero receipt files verified** on CI, where
ignored evidence is absent. On the custody workstation, add `--receipt-root .`
to verify all selected small receipt bytes and exact manifest projections.
Neither mode approves the packet or replaces custodian review. A successor
qualified packet needs its own explicit review; do not relabel this checkpoint.

`python3 ci/solo_qualification.py` validates the approved solo-preview successor
without changing that checkpoint. Only original A14 is deferred; maintainer
installation, key recovery and off-host restoration are separate required gates.
`--receipt-root .` checks successor and historical receipts, exact manifest
projections and streams both selected payload archive hashes. `--require-ready`
fails unless all required gates pass and a maintainer review is recorded with
locally verified evidence. It never approves/signs a release; hosted structure
checks alone cannot make it ready. Raw guest traces and large source archives
are not recursively decoded by this checker; their review/custody remains an
explicit qualification responsibility.
