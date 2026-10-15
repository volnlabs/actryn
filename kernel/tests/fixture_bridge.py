#!/usr/bin/env python3
"""Coordinate actual guest tests with the external, non-actuating fixture."""
import argparse
import os
import pathlib
import selectors
import socket
import subprocess
import tempfile
import time

ALLOWED = {"delay 0", "delay 250000000", "delay 600000000", "replay", "restart"}


def run(admin, command, timeout):
    with tempfile.TemporaryDirectory(prefix="actryn-fixture-bridge-") as directory:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as control:
            control.bind(str(pathlib.Path(directory) / "reply.sock"))
            control.connect(admin)
            control.settimeout(2)
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=0,
            )
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = b""
            deadline = time.monotonic() + timeout
            total = 0
            try:
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("guest scenario exceeded its deadline")
                    for key, _ in selector.select(min(remaining, 1)):
                        data = os.read(key.fileobj.fileno(), 4096)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(data)
                        if total > 1024 * 1024:
                            raise RuntimeError("guest scenario output exceeded 1 MiB")
                        pending += data
                        while b"\n" in pending:
                            raw, pending = pending.split(b"\n", 1)
                            line = raw.decode("utf-8", errors="replace").rstrip("\r")
                            print(line, flush=True)
                            if line.startswith("CONTROL "):
                                instruction = line.removeprefix("CONTROL ")
                                if instruction not in ALLOWED:
                                    raise ValueError(f"unsupported fixture instruction: {instruction}")
                                control.send(instruction.encode())
                                answer = control.recv(128)
                                if answer != b"OK\n":
                                    raise RuntimeError(f"fixture rejected {instruction}: {answer!r}")
                                process.stdin.write(b"Y")
                                process.stdin.flush()
                if pending:
                    print(pending.decode("utf-8", errors="replace"), flush=True)
                result = process.wait(timeout=max(0.01, deadline - time.monotonic()))
                if result:
                    raise RuntimeError(f"guest scenario exited {result}")
                return 0
            finally:
                selector.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                process.stdin.close()
                process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or not 1 <= args.timeout <= 60:
        parser.error("provide a guest command and a timeout between 1 and 60 seconds")
    return run(os.path.abspath(args.admin), command, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
