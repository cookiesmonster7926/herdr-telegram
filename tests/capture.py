#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyte"]
# ///
"""Records real dialog screens for the fixtures: opens claude in its own pty, sends one prompt,
then walks through a list of steps and prints the screen at every "dump".

    uv run tests/capture.py --prompt "..." --steps "wait:Enter to select" "dump:q1" "key:1" "dump:q2"

Steps: wait:<text> (until the screen shows it, 60 s), key:<name> (1-9, enter, esc, tab, left,
right, up, down, space, or literal text), dump:<name>, sleep:<seconds>.

Not a herdr pane and HERDR_* removed, so no plugin fires and no Telegram message goes out. It does
run one real haiku turn. claude is ended with SIGTERM; SIGKILL only if it is still alive 5 s later
(a SIGKILL breaks the next claude started on this machine).
"""
import argparse
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

import pyte

KEYS = {"enter": b"\r", "esc": b"\x1b", "tab": b"\t", "space": b" ", "left": b"\x1b[D",
        "right": b"\x1b[C", "up": b"\x1b[A", "down": b"\x1b[B"}


class Child:
    def __init__(self, args, env, cwd, cols, rows):
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.eof, self.status = False, None
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            os.chdir(cwd)
            os.execvpe("claude", args, env)

    def exited(self):
        if self.status is None:
            done, st = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self.status = st
        return self.status is not None

    def pump(self, seconds, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if until is not None and until():
                return True
            if self.eof:
                time.sleep(0.05)
                continue
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if not r:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                data = b""
            if not data:
                self.eof = True
                continue
            self.stream.feed(data)
        return until is not None and until()

    def text(self):
        out = [line.replace("\xa0", " ").rstrip() for line in self.screen.display]
        while out and not out[-1]:
            out.pop()
        return "\n".join(out)

    def stop(self):
        for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)):
            if self.exited():
                return
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                pass
            self.pump(wait, self.exited)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--steps", nargs="+", required=True)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--cols", type=int, default=80)
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--cwd", default=os.getcwd(), help="a folder claude already trusts")
    ap.add_argument("--out", help="also write each dump to <out>/<name>.txt")
    a = ap.parse_args()
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}
    env["QMP_NO_REPORT"] = "1"
    c = Child(["claude", "--model", a.model, a.prompt], env, a.cwd, a.cols, a.rows)
    try:
        for step in a.steps:
            kind, _, arg = step.partition(":")
            if kind == "wait":
                if not c.pump(60, lambda: arg in c.text() or c.exited()) or c.exited():
                    print(f"===== 等不到「{arg}」\n{c.text()}", flush=True)
                    return 1
                c.pump(0.8)
            elif kind == "key":
                os.write(c.fd, KEYS.get(arg, arg.encode()))
                c.pump(1.2)
            elif kind == "sleep":
                c.pump(float(arg))
            elif kind == "dump":
                print(f"===== {arg}\n{c.text()}", flush=True)
                if a.out:
                    with open(os.path.join(a.out, f"{arg}.txt"), "w", encoding="utf-8") as f:
                        f.write(c.text() + "\n")
        return 0
    finally:
        c.stop()


if __name__ == "__main__":
    sys.exit(main())
