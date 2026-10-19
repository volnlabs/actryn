# Host SQLite sync-boundary regression

Run from the repository root, selecting a new output directory:

```sh
python3 tests/storage/qualify.py --output artifacts/solo-a09-host02
```

This builds the existing `robot-intent` unit-test executable and a small Linux
`LD_PRELOAD` interceptor, then starts two separate test processes. It needs the
locked Cargo dependencies already cached, a C compiler, and Linux `/proc`.
The ignored test is intentionally excluded from ordinary `cargo test`; running
it without the interceptor must fail, rather than count an uninjected case.

The interceptor matches only the exact temporary `intent.sqlite` or its DELETE
journal in the selected case directory. After namespace setup, an explicit
marker arms one interception of an actual SQLite `fsync`/`fdatasync` call. Other
files and later syncs use the original libc function. Nothing is installed in a
service, guest, production process, or system configuration. Existing output
directories are refused and failed logs are preserved.

Both cases hold the real sync call until the Rust test has observed urgent
allocated cancellation completing, a nondurable cancellation result, and no
new authority submission. The stall case releases the real sync and checks the
terminal cancellation becomes durable. The EIO case returns `EIO` at that sync
and requires SQLite's specific `SQLITE_IOERR_FSYNC`, failed persistence, closed
admission, and no new submission. A separately committed operation in that case
becomes `OutcomeUnknown` on restart; its old namespace cannot replay it. Both
cases reopen the actual SQLite database and prove zero recovered allocations
or submissions. The Rust test uses the existing deterministic authority stub.

The interceptor has an eight-second fail-stop limit; urgent cancellation must
return within one second while sync is still blocked; each test process has a
20-second external timeout. These are regression timeouts, not latency or WCET
measurements. The result records the exact interrupted file and syscall, test
and interceptor hashes, source hashes and each result. The common Linux SQLite
path reaches journal `fsync`; database-file sync and `fdatasync` are not claimed
unless the receipt actually records them.

This is host software storage-fault evidence. It does not execute the ARM
manager binary or real kernel gate, simulate media power loss, or establish
physical durability. Associate unchanged production source with the selected
build and retain real-kernel SQLite-contention evidence separately. A successful
run does not qualify the whole release.
