# Instrumentation amendment 5: passive tracefs guard

Before any target capture load, a read-only inspection of the exact original
Robot kernel found `buffer_size_kb` equal to `7 (expanded: 1408)`, `current_tracer`
equal to `nop`, CPU mask `3`, and clock list
`[local] global counter uptime perf mono mono_raw boot tai`. Retained evidence:
`artifacts/robot-source-gap-postrun01/read-only-tracefs.txt` in the integration
checkout. The frozen amendment-4 helper rejected this legitimate lazy-allocation
display because it inherited the optional pointer tracer's numeric restoration
precondition. No amendment-4 target capture or comparison had run.

Amendment 5 adds `capture_guest5.py` as the required start/stop entrypoint. It
verifies the unchanged amendment-4 manifest and its own source pins, then delegates
to the unchanged amendment-4 lifecycle. That lifecycle still verifies every
amendment-4 source, the exact compiled module, hostname, kernel/config, architecture,
CPU profile and boot identity. The module binary, capture ABI and decoder do not
change; no recompilation is required.

The replacement callback checks idle `nop`, all events disabled, no foreign
dynamic/kprobe definitions, no PID filters and no existing trace records. It reads
and retains the raw clock, buffer, tracing, options and CPU mask strings without
requiring a numeric buffer value: it never writes or restores tracefs controls.
Before the unchanged helper can load the module, the callback durably writes
`instrumentation5.json` with both manifest hashes and the passive snapshot. Stop
requires matching amendment provenance before using the original freeze/export/
unload path. Original start failures and frozen state remain separate and intact.

Deploy the two new Python files and `instrumentation5.toml` beside the complete,
unchanged instrumentation-4 package and `.ko` in
`/opt/actryn-a16/instrumentation4/`. Invoke `capture_guest5.py start|stop OUTPUT`;
do not invoke `capture_guest.py` directly for the campaign. The revised campaign
runner must retain both manifest hashes and require both matching target pilots.

The optional pointer/count tracer remains frozen and rejects this lazy buffer
state. Its mutation/restoration of lazy allocation has not been qualified. It is
not part of the required matched instrumentation and is not run concurrently.

Host verification reproduced the original rejection without writes (RED), then
passed five regression tests (GREEN): exact lazy display and raw clock retention,
foreign trace controls/records rejection, provenance before load, blocked-load
failure retention, and changed-amendment stop rejection. All module operations in
these host tests were mocked. Target capture pilots and the eight-run comparison
remain **NOT_RUN**.
