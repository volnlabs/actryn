# Observer retirement under delayed persistence

`delayed_retirement.py` runs the actual installed observer and BPF object in the
disposable Debian `6.12.111+deb13-amd64` guest. Stop the server, launcher, and
observer services first, after all attempts have reaped; retire the stale observer
socket. The script refuses active services or an existing socket. It does not
replace installed files or restart services.

Run with an unused output directory, keeping the adjacent C source available:

```sh
python3 delayed_retirement.py --disposable-guest \
  --output /var/tmp/actryn-observer-retirement-01
```

The test-only `LD_PRELOAD` library intercepts the first JSONL `fsync` for one
generated attempt. A barrier holds that call beyond the existing IPC deadline;
then it returns `EIO` exactly once. Eight registrations remain charged, so a ninth
registration must fail until the original retirement identity completes durable
recovery. Afterwards exactly one slot becomes available. The barrier has a finite
15-second fail-safe, and all other sync calls use the kernel's real `fsync`.
No production timeout is widened. The regression catches premature slot release,
false successful durability acknowledgement, and loss of recoverable retirement
state. It does not claim a storage latency bound.

Every request/reply, binary/object/fixture hash, stderr and result is retained in
the output directory. Observer evidence stays under its original epoch. An
operator cancellation is never retried: observer retirement retries reuse the
same immutable identity, matching the existing launcher cleanup loop.

The offline OCI acceptance harness separately preserves its one cancellation
reply (including an unknown outcome), then polls read-only status until both
stores are reaped and the cgroup is gone. It requires zero evidence gaps and a
healthy final observer summary before declaring cleanup complete.
