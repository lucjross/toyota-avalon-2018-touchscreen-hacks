#!/usr/bin/env python3
"""Etch-a-Sketch on the head unit.

  left knob  (E1)  moves the line horizontally   (clockwise = right)
  right knob (E2)  moves the line vertically     (clockwise = up)
  right button (B2) shake: each press dissolves part of the drawing, the 3rd clears it
  left button  (B1) go back

The drawing is kept as a set of lit pixels so a shake can knock random ones loose, like
the powder falling off the glass. Presses more than SHAKE_RESET seconds apart start
the count over; a long idle wipes the screen so a static image doesn't linger on the panel.
"""

import random
import select
import time

import runner

BACKGROUND = (128, 128, 121)   # aluminium powder
INK = (38, 38, 42)
THICKNESS = 3                  # line width in pixels (odd)

# Pixels per knob step. The left knob gives 2 steps per turn cycle and the right one 4,
# so the left step is twice as long and both axes draw at the same speed per turn.
STEP_X = 6
STEP_Y = 3

SHAKE_FRACTIONS = (0.45, 0.70, 1.0)   # share of the remaining pixels each press removes
SHAKE_RESET = 3.0                            # seconds between presses before the count restarts
DISSOLVE_FRAMES = 24                         # a dissolve takes this many frames (~0.8 s)
IDLE_WIPE = 600.0                            # seconds without input before the screen wipes
FRAME = 1 / 30


class Etch:
    def __init__(self, fb):
        self.fb = fb
        self.bg = fb.pixel(BACKGROUND)
        self.ink = fb.pixel(INK)
        self.x, self.y = fb.width // 2, fb.height // 2
        self.lit = set()          # pixels currently inked, as y * width + x
        self.falling = []         # pixels queued to be erased by the dissolve animation
        self.fall_per_frame = 1
        self.presses = 0
        self.last_press = 0.0
        self.last_input = time.monotonic()
        fb.fill(BACKGROUND)
        self.stamp()

    def stamp(self):
        half = THICKNESS // 2
        for dy in range(-half, half + 1):
            for dx in range(-half, half + 1):
                px, py = self.x + dx, self.y + dy
                if 0 <= px < self.fb.width and 0 <= py < self.fb.height:
                    key = py * self.fb.width + px
                    if key not in self.lit:
                        self.lit.add(key)
                        self.fb.put(px, py, self.ink)

    def move(self, dx, dy):
        """Move the pen along one axis, drawing as it goes."""
        step_x = (dx > 0) - (dx < 0)
        step_y = (dy > 0) - (dy < 0)
        margin = THICKNESS // 2
        for _ in range(abs(dx) + abs(dy)):
            nx = min(max(self.x + step_x, margin), self.fb.width - 1 - margin)
            ny = min(max(self.y + step_y, margin), self.fb.height - 1 - margin)
            if (nx, ny) == (self.x, self.y):
                break  # hit the edge
            self.x, self.y = nx, ny
            self.stamp()

    def shake(self, now):
        if now - self.last_press > SHAKE_RESET:
            self.presses = 0
        self.last_press = now
        fraction = SHAKE_FRACTIONS[min(self.presses, len(SHAKE_FRACTIONS) - 1)]
        self.presses = 0 if fraction >= 1.0 else self.presses + 1
        self.dissolve(fraction)

    def dissolve(self, fraction):
        count = int(len(self.lit) * fraction)
        victims = random.sample(sorted(self.lit), count) if count < len(self.lit) else list(self.lit)
        self.lit.difference_update(victims)
        random.shuffle(victims)
        self.falling.extend(victims)
        self.fall_per_frame = max(1, len(self.falling) // DISSOLVE_FRAMES + 1)

    def tick(self, now):
        if self.falling:
            width = self.fb.width
            for _ in range(min(self.fall_per_frame, len(self.falling))):
                key = self.falling.pop()
                if key not in self.lit:  # skip pixels the pen has drawn over since
                    self.fb.put(key % width, key // width, self.bg)
        elif self.lit and now - self.last_input > IDLE_WIPE:
            self.dissolve(1.0)


def play(etch, events):
    while True:
        ready, _, _ = select.select([events], [], [], FRAME)
        now = time.monotonic()
        if ready:
            for kind, number, value in events.read():
                etch.last_input = now
                if kind == "E" and number == 1:
                    etch.move(value * STEP_X, 0)
                elif kind == "E" and number == 2:
                    etch.move(0, -value * STEP_Y)
                elif kind == "B" and number == 2 and value:
                    etch.shake(now)
                elif kind == "B" and number == 1 and value:
                    return
        etch.tick(now)


def main():
    runner.run(lambda fb, events: play(Etch(fb), events))


if __name__ == "__main__":
    main()
