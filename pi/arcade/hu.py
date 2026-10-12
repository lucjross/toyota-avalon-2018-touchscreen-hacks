"""Client for the head unit daemon, for games.

  events = Events()            # subscribes to the raw front-panel event stream
  select.select([events], ...) # events has fileno(), so it works with select()
  for ev in events.read(): ... # ("E", 1, +1)  encoder 1 one step clockwise
                               # ("B", 2, True) button 2 pressed (False = released)

  control("profile raw")       # ask the daemon to stop acting on events itself
"""

import os
import socket

EVENTS_PATH = os.environ.get("HU_EVENTS", "/run/headunit-events.sock")
CONTROL_PATH = os.environ.get("HU_CONTROL", "/run/headunit.sock")


def control(command):
    """Send one command to the daemon's control socket and return its reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(CONTROL_PATH)
        s.sendall((command + "\n").encode())
        reply = b""
        while chunk := s.recv(4096):
            reply += chunk
    return reply.decode().strip()


class Events:
    def __init__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(EVENTS_PATH)
        self.sock.setblocking(False)
        self.buf = b""

    def fileno(self):
        return self.sock.fileno()

    def read(self):
        """Return the events that have arrived, as a list. Raises EOFError if the daemon went away."""
        try:
            data = self.sock.recv(4096)
        except BlockingIOError:
            return []
        if not data:
            raise EOFError("head unit daemon closed the event stream")
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        events = []
        for line in lines:
            parts = line.decode(errors="ignore").split()
            if len(parts) != 2 or parts[0][0] not in "EB":
                continue
            kind, number = parts[0][0], int(parts[0][1:])
            if kind == "E":
                events.append((kind, number, 1 if parts[1] == "+1" else -1))
            else:
                events.append((kind, number, parts[1] == "down"))
        return events

    def close(self):
        self.sock.close()
