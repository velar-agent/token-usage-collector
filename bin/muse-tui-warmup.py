#!/usr/bin/env python3
"""Open the muse TUI in a pseudo-terminal, send one prompt, and kill it after N seconds.

Usage: muse-tui-warmup.py [seconds]   (default 10)
A headless `muse exec` call can leave the 5-hour usage window unopened
(server_sent_no_usage); an interactive TUI session opens it.
"""
import fcntl, os, pty, select, signal, struct, sys, termios, time

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 10
wd = "/tmp/muse-warm"
os.makedirs(wd, exist_ok=True)
os.environ.setdefault("TERM", "xterm-256color")
pid, fd = pty.fork()
if pid == 0:
    os.chdir(wd)
    os.execvp("muse", ["muse", "--trust-workspace", "--model", "muse-ember-1.0", "--effort", "minimal", "hi"])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
end = time.time() + secs
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.5)
    if r:
        try:
            d = os.read(fd, 65536)
        except OSError:
            break
        if not d:
            break
        if b"\x1b[6n" in d:  # answer cursor-position query so the TUI starts
            os.write(fd, b"\x1b[1;1R")
for sig in (signal.SIGTERM, signal.SIGKILL):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        break
    time.sleep(1)
try:
    os.waitpid(pid, 0)
except ChildProcessError:
    pass
