#!/usr/bin/env python3
"""
Head unit input daemon.

Reads front-panel events from the Pico (USB CDC serial, one text line per event):
  E1 +1 / E1 -1      volume knob, one step
  E2 +1 / E2 -1      tuning knob, one step (4 per turn cycle; the volume knob gives 2)
  B1 down / B1 up    volume knob pushbutton
  B2 down / B2 up    tuning knob pushbutton
and turns them into actions according to the active *profile* from profiles.json.

Actions are either built-in (system volume, backlight, shutdown) or virtual input
devices created through uinput (a keyboard and a mouse), so games see ordinary input
hardware and need no per-game code.

The active profile is switched at runtime with `headunitctl profile NAME`, which talks
to this daemon over a Unix socket (SOCKET_PATH). The daemon always starts in the
`system` profile.

Must run as root (uinput, shutdown).
"""

import asyncio
import glob
import json
import os
import shutil
import subprocess
import termios
import tty

from evdev import UInput, ecodes as e

try:
    import RPi.GPIO as GPIO
except ImportError:  # lets the profile logic be exercised off the Pi
    GPIO = None

BLON_PIN = 26  # backlight enable (YS-DZ-3.1 BLON)
SERIAL_GLOB = "/dev/serial/by-id/*Head_unit_controls*"
SOCKET_PATH = "/run/headunit.sock"
PROFILES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json")
DEFAULT_PROFILE = "system"
LONG_PRESS_MS = 2000

# `amixer` controls to try for volume, first one that works is remembered.
VOLUME_CMDS = [
    ["-c", "1", "sset", "Speaker"],
    ["-c", "1", "sset", "PCM"],
    ["sset", "Speaker"],
    ["sset", "Master"],
    ["sset", "PCM"],
]


class Daemon:
    def __init__(self):
        self.profiles = {}
        self.current = DEFAULT_PROFILE
        self.load_profiles()

        # Two virtual devices: a keyboard (all keys) and a relative mouse.
        self.kbd = UInput({e.EV_KEY: list(range(1, 249))}, name="headunit-keyboard")
        self.mouse = UInput(
            {
                e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
                e.EV_REL: [e.REL_X, e.REL_Y],
            },
            name="headunit-mouse",
        )

        self.backlight_on = True
        if GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(BLON_PIN, GPIO.OUT)
            GPIO.output(BLON_PIN, GPIO.HIGH)

        self.volume_cmd = None  # index into VOLUME_CMDS once one works
        self.held = {}          # key code -> asyncio timer handle (auto-release)
        self.down = {}          # button id -> pressed-state info for B1/B2
        self.long_timers = {}   # button id -> asyncio timer handle

    # ── profiles ─────────────────────────────────────────────────────────
    def load_profiles(self):
        with open(PROFILES_PATH) as f:
            self.profiles = json.load(f)
        if self.current not in self.profiles:
            self.current = DEFAULT_PROFILE

    def set_profile(self, name):
        if name not in self.profiles:
            return False
        self.release_all()
        self.current = name
        print(f"Profile: {name}", flush=True)
        return True

    def release_all(self):
        """Let go of anything held so nothing stays stuck across a profile switch."""
        for code, handle in list(self.held.items()):
            handle.cancel()
            self.kbd.write(e.EV_KEY, code, 0)
        self.held.clear()
        self.kbd.syn()
        for btn in (e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE):
            self.mouse.write(e.EV_KEY, btn, 0)
        self.mouse.syn()
        for handle in self.long_timers.values():
            handle.cancel()
        self.long_timers.clear()
        self.down.clear()

    # ── event dispatch ───────────────────────────────────────────────────
    def handle_line(self, line):
        parts = line.split()
        if len(parts) != 2:
            return
        name, arg = parts
        spec = self.profiles[self.current].get(name)
        if not spec:
            return
        if name.startswith("E") and arg in ("+1", "-1"):
            self.turn(spec, 1 if arg == "+1" else -1)
        elif name.startswith("B") and arg in ("down", "up"):
            self.button(name, spec, arg == "down")

    def turn(self, spec, direction):
        action = spec["action"]
        n = direction * spec.get("scale", 1)
        if action == "volume":
            self.change_volume(direction, spec.get("step", 5))
        elif action == "mouse_x":
            self.mouse.write(e.EV_REL, e.REL_X, n)
            self.mouse.syn()
        elif action == "mouse_y":
            self.mouse.write(e.EV_REL, e.REL_Y, n)
            self.mouse.syn()
        elif action == "hold_keys":
            # Hold the "plus" or "minus" key while the knob keeps turning; release shortly
            # after the last step. Turning the other way swaps which key is held.
            keys = spec["plus"], spec["minus"]
            pressed, other = (keys[0], keys[1]) if direction > 0 else (keys[1], keys[0])
            self.hold_key(e.ecodes[other], release_now=True)
            self.hold_key(e.ecodes[pressed], hold_ms=spec.get("hold_ms", 150))

    def hold_key(self, code, hold_ms=0, release_now=False):
        handle = self.held.pop(code, None)
        if release_now:
            if handle:
                handle.cancel()
                self.kbd.write(e.EV_KEY, code, 0)
                self.kbd.syn()
            return
        if handle:
            handle.cancel()
        else:
            self.kbd.write(e.EV_KEY, code, 1)
            self.kbd.syn()
        loop = asyncio.get_running_loop()
        self.held[code] = loop.call_later(hold_ms / 1000, self.release_key, code)

    def release_key(self, code):
        self.held.pop(code, None)
        self.kbd.write(e.EV_KEY, code, 0)
        self.kbd.syn()

    def button(self, name, spec, is_down):
        if "short" in spec or "long" in spec:
            # Tap/long-press button: short fires on release, long fires after LONG_PRESS_MS.
            if is_down:
                self.down[name] = True
                loop = asyncio.get_running_loop()
                self.long_timers[name] = loop.call_later(
                    spec.get("long_ms", LONG_PRESS_MS) / 1000, self.long_press, name, spec
                )
            elif self.down.pop(name, None):
                timer = self.long_timers.pop(name, None)
                if timer:
                    timer.cancel()
                    self.run_action(spec.get("short"))
        else:
            # Pass-through button: mirror down/up to a key or mouse button.
            if "key" in spec:
                self.kbd.write(e.EV_KEY, e.ecodes[spec["key"]], 1 if is_down else 0)
                self.kbd.syn()
            elif "mouse_button" in spec:
                self.mouse.write(e.EV_KEY, e.ecodes[spec["mouse_button"]], 1 if is_down else 0)
                self.mouse.syn()

    def long_press(self, name, spec):
        self.long_timers.pop(name, None)
        self.down.pop(name, None)  # consumed, so the release doesn't also fire "short"
        self.run_action(spec.get("long"))

    # ── built-in actions ─────────────────────────────────────────────────
    def run_action(self, action):
        if action == "backlight_toggle":
            self.backlight_on = not self.backlight_on
            if GPIO:
                GPIO.output(BLON_PIN, GPIO.HIGH if self.backlight_on else GPIO.LOW)
            print(f"Backlight: {'on' if self.backlight_on else 'off'}", flush=True)
        elif action == "shutdown":
            print("Long press: shutting down", flush=True)
            subprocess.run(["shutdown", "-h", "now"])

    def change_volume(self, direction, step):
        delta = f"{step}%{'+' if direction > 0 else '-'}"
        order = range(len(VOLUME_CMDS))
        if self.volume_cmd is not None:
            order = [self.volume_cmd]
        for i in order:
            res = subprocess.run(["amixer", "-q", *VOLUME_CMDS[i], delta], check=False)
            if res.returncode == 0:
                self.volume_cmd = i
                return

    # ── Pico serial link ─────────────────────────────────────────────────
    async def serial_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            paths = glob.glob(SERIAL_GLOB)
            if not paths:
                await asyncio.sleep(1)
                continue
            try:
                fd = os.open(paths[0], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                tty.setraw(fd, termios.TCSANOW)
            except OSError:
                await asyncio.sleep(1)
                continue
            print(f"Pico connected: {paths[0]}", flush=True)
            queue = asyncio.Queue()
            loop.add_reader(fd, self.on_readable, fd, queue)
            try:
                buf = b""
                while True:
                    chunk = await queue.get()
                    if chunk is None:  # device went away
                        break
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        self.handle_line(line.decode(errors="ignore").strip())
            finally:
                loop.remove_reader(fd)
                os.close(fd)
                print("Pico disconnected", flush=True)

    @staticmethod
    def on_readable(fd, queue):
        try:
            data = os.read(fd, 256)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        queue.put_nowait(data or None)

    # ── control socket (headunitctl) ─────────────────────────────────────
    async def control_client(self, reader, writer):
        line = (await reader.readline()).decode().strip()
        cmd, _, arg = line.partition(" ")
        if cmd == "status":
            reply = self.current
        elif cmd == "list":
            reply = "\n".join(("* " if n == self.current else "  ") + n for n in self.profiles)
        elif cmd == "profile":
            reply = f"ok {arg}" if self.set_profile(arg) else f"error: unknown profile '{arg}'"
        elif cmd == "reload":
            try:
                self.load_profiles()
                reply = "ok"
            except (OSError, ValueError) as exc:
                reply = f"error: {exc}"
        else:
            reply = "error: commands are status, list, profile NAME, reload"
        writer.write((reply + "\n").encode())
        await writer.drain()
        writer.close()

    async def run(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        server = await asyncio.start_unix_server(self.control_client, SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o660)
        try:
            shutil.chown(SOCKET_PATH, group="pi")
        except (LookupError, PermissionError):
            pass
        async with server:
            await self.serial_loop()


if __name__ == "__main__":
    print("Head unit daemon starting", flush=True)
    daemon = Daemon()
    try:
        asyncio.run(daemon.run())
    finally:
        if GPIO:
            GPIO.cleanup()
