"""Common start-up and clean-up for games.

  def play(fb, events): ...      # draw on fb, read events, return to quit
  runner.run(play)

run() connects to the daemon's event stream, opens the framebuffer, switches the daemon
to the `raw` profile so the knobs only reach the game, and stops the console drawing
over the picture. When play() returns (or the program is interrupted or its SSH session
closes) it blanks the screen and puts everything back.
"""

import signal
import sys

from fb import Framebuffer, console_graphics
from hu import Events, control


def run(play):
    # A closed SSH session (SIGHUP) or `kill` would otherwise skip the cleanup below and
    # leave the knobs dead in the `raw` profile.
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        events = Events()
        fb = Framebuffer()  # open before switching profile, so a failure can't strand it
        control("profile raw")
        console_graphics(True)
        try:
            play(fb, events)
        finally:
            fb.fill((0, 0, 0))
            console_graphics(False)
            try:
                control("profile system")
            except OSError:
                pass
    except KeyboardInterrupt:
        pass
