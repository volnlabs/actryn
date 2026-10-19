# A16 listener-credential derivative 10

The frozen comparison remains **FAILED79/80**. Its B3 evidence trial 6 stopped
during BIND without retaining the role, reply error or peer credentials. The
later diagnostic9 observation passed 10/10 and cannot identify or repair that
historical failure.

A host-only investigation found a real race in the frozen userspace gateway:
it enabled `SO_PASSCRED` on an accepted `SOCK_SEQPACKET` connection. A client
can send BIND after `accept4` and before that option is enabled. On the observed
Linux host, `recvmsg` then returned fallback credentials (PID 0, UID/GID 65534),
and the gateway rejected the valid BIND with `-EPERM`.

`passcred10.py` accepts only the exact frozen gateway SHA-256
`5ca065e12366c020987fb6670fed0dba7661b50f51f7198c29e5cbd0f066803c`.
It produces a separately numbered derivative that enables credential reception
on the bound listener before `listen`. The option is inherited by accepted
connections, so credentials are recorded even when a client sends during the
post-accept/pre-configuration window. The frozen source is not edited.

The host regression forces that window through the actual `receive_command`
and `dispatch` functions for all four roles:

```sh
python3 -B -m unittest discover -s kernel/tests/a16 -p passcred10_test.py
```

The test first failed with role 1 receiving PID 0, UID/GID 65534 and BIND
`-EPERM`; it passes with the derivative. An environment that denies private
abstract Unix-socket bind cannot run this check inside its sandbox.

This proves a source defect and host correction. It does **not** prove that the
race caused the historical B3 failure, qualify the pinned ARM guest, change the
original denominator, or pass A16. Before a successor measurement, build and
review the derivative on the pinned guest, retain exact source/binary hashes,
record any BIND role/error/credentials, pass the prescribed target pilots, and
freeze a new campaign identity. No replacement retry or pooling is permitted.
