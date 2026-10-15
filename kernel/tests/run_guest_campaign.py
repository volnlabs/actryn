#!/usr/bin/env python3
"""Run one labeled actual ARM64 fixture campaign; preserve and stop on failure."""
import argparse
import contextlib
import json
import pathlib
import shlex
import socket
import subprocess
import tempfile

import fixture_bridge

SCENARIOS = {
    "selftest", "inhibited-revoke", "dup", "rights", "owner-exit",
    "unbind-rebind", "event-capacity", "late-sample", "late-barrier",
    "delayed-handoff", "controller-restart", "ready-recovery", "repeated-revoke", "cancel-revoke",
}
CONTROLLED = {"late-sample", "late-barrier", "delayed-handoff", "controller-restart",
              "repeated-revoke", "cancel-revoke"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--admin", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--build", default="/root/actryn-kernel-build12")
    parser.add_argument("--port", type=int, default=26221)
    parser.add_argument("--trace", action="store_true", help="diagnostic error kprobes in the guest")
    parser.add_argument("scenarios", nargs="+")
    args = parser.parse_args()
    if any(case not in SCENARIOS for case in args.scenarios):
        parser.error("unknown scenario")
    output = pathlib.Path(args.output).resolve()
    output.mkdir()  # Never overwrite an earlier attempt.
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o",
           "UserKnownHostsFile=" + str(pathlib.Path(args.known_hosts).resolve()),
           "-i", str(pathlib.Path(args.identity).resolve()), "-p", str(args.port),
           "root@127.0.0.1"]
    build = shlex.quote(args.build)

    def remote(command, filename, check=True):
        result = subprocess.run(ssh + [command], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=30)
        (output / filename).write_bytes(result.stdout)
        (output / (filename + ".exit")).write_text(str(result.returncode) + "\n")
        if check and result.returncode:
            raise RuntimeError(f"{filename}: remote exit {result.returncode}")
        return result

    with tempfile.TemporaryDirectory(prefix="actryn-campaign-control-") as directory:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as control:
            control.settimeout(2)
            control.bind(str(pathlib.Path(directory) / "reply"))
            control.connect(str(pathlib.Path(args.admin).resolve()))

            def admin(command):
                control.send(command.encode())
                response = control.recv(512).decode()
                with (output / "fixture.log").open("a") as log:
                    log.write(json.dumps({"command": command, "response": response}) + "\n")
                if command != "status" and response != "OK\n":
                    raise RuntimeError(f"fixture rejected {command}: {response!r}")
                return response

            tracing = False
            try:
                remote("set -eu; test \"$(uname -r)\" = 6.12.111+deb13-arm64; "
                       "test \"$(uname -m)\" = aarch64; "
                       "tr '\\0' '\\n' < /proc/device-tree/compatible | grep -qx linux,dummy-virt; "
                       "test ! -e /dev/ttyAMA1; "
                       "if systemctl is-active --quiet actryn-robotd; then exit 70; fi; "
                       "if systemctl is-active --quiet actryn-gatewayd; then exit 70; fi; "
                       "uname -a; cat /proc/sys/kernel/random/boot_id; "
                       f"sha256sum {build}/kernel/actryn_authority.ko", "environment.log")
                admin("status")
                for index, case in enumerate(args.scenarios, 1):
                    prefix = f"{index:02}-{case}"
                    remote("set -eu; if grep -q '^actryn_authority ' /proc/modules; "
                           "then rmmod actryn_authority; fi", prefix + ".unload.log")
                    for command in ("delay 0", "drop 0", "pause-rx 0", "restart", "status"):
                        admin(command)
                    remote(f"insmod {build}/kernel/actryn_authority.ko", prefix + ".load.log")
                    if args.trace:
                        remote(f"sh {build}/kernel/tests/arm_trace.sh start", prefix + ".trace-start.log")
                        tracing = True
                    executable = "authority-selftest" if case == "selftest" else "authority-adversarial"
                    command = f"{build}/{executable}"
                    if case != "selftest":
                        command += " " + shlex.quote(case)
                    if case == "unbind-rebind":
                        command += " serial0-0"
                    if case in CONTROLLED:
                        with (output / (prefix + ".log")).open("w") as log, contextlib.redirect_stdout(log):
                            fixture_bridge.run(str(pathlib.Path(args.admin).resolve()), ssh + [command], 30)
                        (output / (prefix + ".log.exit")).write_text("0\n")
                    else:
                        remote(command, prefix + ".log")
                    if tracing:
                        remote(f"sh {build}/kernel/tests/arm_trace.sh stop", prefix + ".trace.log")
                        tracing = False
                    admin("status")
                    remote("dmesg", prefix + ".kernel.log")
                    (output / (prefix + ".PASS")).write_text("PASS " + case + "\n")
                    print("PASS", prefix, flush=True)
            except BaseException as error:
                marker = "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED"
                (output / marker).write_text(repr(error) + "\n")
                if tracing:
                    remote(f"sh {build}/kernel/tests/arm_trace.sh stop", "failure.trace.log", check=False)
                remote("dmesg", "failure.kernel.log", check=False)
                raise


if __name__ == "__main__":
    main()
