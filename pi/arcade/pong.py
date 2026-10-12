#!/usr/bin/env python3
"""Two-player Pong on the head unit.

  left knob  (E1)  moves the left paddle    (clockwise = up)
  right knob (E2)  moves the right paddle   (clockwise = up)
  either button    serves; after a win it starts a new game
  both buttons     hold for a second to go back

The ball is served toward the player who just conceded. First to WIN_SCORE wins. The ball
speeds up on every paddle hit, and where it strikes the paddle sets its angle.
"""

import math
import os
import random
import select
import shutil
import struct
import subprocess
import tempfile
import time
import wave

import runner

BACKGROUND = (0, 0, 0)
PADDLE = (190, 190, 190)       # kept below full white: bright static shapes can ghost
BALL = (190, 190, 190)
NET = (70, 70, 70)
SCORE = (120, 120, 120)

PADDLE_W, PADDLE_H, PADDLE_MARGIN = 10, 64, 24
BALL_SIZE = 10

# Pixels per knob step. The left knob gives 2 steps per turn cycle and the right one 4,
# so the left step is twice as long and both paddles move the same distance per turn.
STEP_LEFT = 10
STEP_RIGHT = 5

SERVE_SPEED = 280.0            # pixels per second
SPEED_UP = 1.06                # per paddle hit
MAX_SPEED = 900.0
MAX_ANGLE = 0.8                # sideways share of the speed for a hit at the paddle's edge
WIN_SCORE = 7
FPS = 60
EXIT_HOLD = 1.0                # seconds both buttons must be held
AUDIO_DEVICE = os.environ.get("HU_AUDIO", "plughw:CARD=Device")

# 5x7 digits, drawn at DIGIT_SCALE pixels per dot
DIGIT_SCALE = 8
FONT = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}

SOUNDS = {                      # name -> [(frequency Hz, milliseconds), ...]
    "paddle": [(880, 45)],
    "wall": [(440, 35)],
    "score": [(220, 280)],
    "win": [(523, 130), (659, 130), (784, 130), (1047, 320)],
}


class Sound:
    """Short beeps, played by `aplay` on the USB audio device. Silent if that's not available."""

    RATE = 22050

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="pong")
        self.enabled = not os.environ.get("HU_NO_SOUND") and shutil.which("aplay") is not None
        self.procs = []
        if self.enabled:
            for name, notes in SOUNDS.items():
                self.write(os.path.join(self.dir, name + ".wav"), notes)

    def write(self, path, notes):
        frames = bytearray()
        for freq, ms in notes:
            count = self.RATE * ms // 1000
            for i in range(count):
                fade = 1.0 - i / count                       # decay so the beep doesn't click
                value = int(9000 * fade * math.sin(2 * math.pi * freq * i / self.RATE))
                frames += struct.pack("<h", value)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.RATE)
            w.writeframes(bytes(frames))

    def play(self, name):
        if not self.enabled:
            return
        self.procs = [p for p in self.procs if p.poll() is None]   # reap finished players
        try:
            self.procs.append(subprocess.Popen(
                ["aplay", "-q", "-D", AUDIO_DEVICE, os.path.join(self.dir, name + ".wav")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            self.enabled = False

    def close(self):
        for p in self.procs:
            p.terminate()
        shutil.rmtree(self.dir, ignore_errors=True)


class Pong:
    def __init__(self, fb, sound):
        self.fb, self.sound = fb, sound
        self.w, self.h = fb.width, fb.height
        self.px = {name: fb.pixel(c) for name, c in
                   (("bg", BACKGROUND), ("paddle", PADDLE), ("ball", BALL), ("net", NET), ("score", SCORE))}
        self.left_x = PADDLE_MARGIN
        self.right_x = self.w - PADDLE_MARGIN - PADDLE_W
        self.scores = [0, 0]
        self.serve_dir = random.choice((-1, 1))
        self.new_game(first=True)

    # ── state ────────────────────────────────────────────────────────────
    def new_game(self, first=False):
        self.scores = [0, 0]
        self.left_y = self.right_y = (self.h - PADDLE_H) // 2
        self.state = "serve"
        self.winner = None
        self.reset_ball()
        self.fb.fill(BACKGROUND)
        self.draw_net()
        self.draw_scores()
        self.drawn = {}           # what is on screen: name -> rect, so it can be erased
        self.render(time.monotonic())

    def reset_ball(self):
        self.ball_x = (self.w - BALL_SIZE) / 2
        self.ball_y = (self.h - BALL_SIZE) / 2
        self.vx = self.vy = 0.0

    def serve(self):
        self.vx = self.serve_dir * SERVE_SPEED
        self.vy = random.choice((-1, 1)) * random.uniform(40, 140)
        self.state = "play"

    # ── input ────────────────────────────────────────────────────────────
    def turn(self, encoder, direction):
        if encoder == 1:
            self.left_y = self.clamp_paddle(self.left_y - direction * STEP_LEFT)
        else:
            self.right_y = self.clamp_paddle(self.right_y - direction * STEP_RIGHT)

    def clamp_paddle(self, y):
        return min(max(y, 0), self.h - PADDLE_H)

    def press(self):
        if self.state == "serve":
            self.serve()
        elif self.state == "won" and time.monotonic() - self.won_at > 1.0:
            self.new_game()

    # ── physics ──────────────────────────────────────────────────────────
    def update(self, dt, now):
        if self.state != "play":
            return
        self.ball_x += self.vx * dt
        self.ball_y += self.vy * dt
        if self.ball_y < 0:
            self.ball_y, self.vy = 0.0, abs(self.vy)
            self.sound.play("wall")
        elif self.ball_y > self.h - BALL_SIZE:
            self.ball_y, self.vy = float(self.h - BALL_SIZE), -abs(self.vy)
            self.sound.play("wall")
        if self.vx < 0 and self.hits(self.left_x, self.left_y):
            self.bounce(self.left_y, 1, self.left_x + PADDLE_W)
        elif self.vx > 0 and self.hits(self.right_x, self.right_y):
            self.bounce(self.right_y, -1, self.right_x - BALL_SIZE)
        if self.ball_x + BALL_SIZE < 0:
            self.point(scorer=1, now=now)
        elif self.ball_x > self.w:
            self.point(scorer=0, now=now)

    def hits(self, paddle_x, paddle_y):
        return (self.ball_x < paddle_x + PADDLE_W and self.ball_x + BALL_SIZE > paddle_x
                and self.ball_y + BALL_SIZE > paddle_y and self.ball_y < paddle_y + PADDLE_H)

    def bounce(self, paddle_y, direction, x):
        speed = min(math.hypot(self.vx, self.vy) * SPEED_UP, MAX_SPEED)
        offset = (self.ball_y + BALL_SIZE / 2 - (paddle_y + PADDLE_H / 2)) / (PADDLE_H / 2 + BALL_SIZE / 2)
        offset = min(max(offset, -1.0), 1.0)
        self.vy = offset * speed * MAX_ANGLE
        self.vx = direction * math.sqrt(speed * speed - self.vy * self.vy)
        self.ball_x = x
        self.sound.play("paddle")

    def point(self, scorer, now):
        self.scores[scorer] += 1
        self.serve_dir = -1 if scorer == 1 else 1      # toward the player who conceded
        self.reset_ball()
        self.draw_scores()
        if self.scores[scorer] >= WIN_SCORE:
            self.state, self.winner, self.won_at = "won", scorer, now
            self.sound.play("win")
        else:
            self.state = "serve"
            self.sound.play("score")

    # ── drawing ──────────────────────────────────────────────────────────
    def draw_net(self):
        x = (self.w - 4) // 2
        for y in range(8, self.h - 8, 28):
            self.fb.rect(x, y, 4, 14, self.px["net"])

    def draw_scores(self, hide=None):
        cell = DIGIT_SCALE
        width, height = 5 * cell, 7 * cell
        for side in (0, 1):
            x = self.w // 2 + (-70 - width if side == 0 else 70)
            self.fb.rect(x - 2, 18, width + 4, height + 4, self.px["bg"])
            if hide == side:
                continue
            for row, bits in enumerate(FONT[str(self.scores[side])]):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        self.fb.rect(x + col * cell, 20 + row * cell, cell, cell, self.px["score"])

    def render(self, now):
        fb, px = self.fb, self.px
        rects = {
            "left": (self.left_x, int(self.left_y), PADDLE_W, PADDLE_H),
            "right": (self.right_x, int(self.right_y), PADDLE_W, PADDLE_H),
            "ball": (int(self.ball_x), int(self.ball_y), BALL_SIZE, BALL_SIZE),
        }
        # the ball blinks at centre while waiting to be served
        ball_visible = self.state == "play" or (self.state == "serve" and int(now * 2.5) % 2 == 0)
        old_ball = self.drawn.get("ball")
        for name, rect in rects.items():
            if name == "ball" and not ball_visible:
                continue
            if self.drawn.get(name) != rect:
                if name in self.drawn:
                    fb.rect(*self.drawn[name], px["bg"])
                self.drawn[name] = rect
        if not ball_visible and "ball" in self.drawn:
            fb.rect(*self.drawn.pop("ball"), px["bg"])
        # erasing the ball may have wiped part of the net or a paddle
        net_x = (self.w - 4) // 2
        if any(r and r[0] < net_x + 4 and r[0] + r[2] > net_x for r in (old_ball, self.drawn.get("ball"))):
            self.draw_net()
        if any(r and r[1] < 18 + 7 * DIGIT_SCALE + 4 for r in (old_ball, self.drawn.get("ball"))):
            self.draw_scores()  # the ball is crossing the score band
        for name in ("left", "right"):
            fb.rect(*rects[name], px["paddle"])
        if "ball" in self.drawn:
            fb.rect(*self.drawn["ball"], px["ball"])
        if self.state == "won":
            self.draw_scores(hide=self.winner if int((now - self.won_at) * 4) % 2 else None)


def play(fb, events):
    sound = Sound()
    try:
        game = Pong(fb, sound)
        held = {}                                   # button -> time it went down
        last = time.monotonic()
        next_frame = last
        while True:
            now = time.monotonic()
            ready, _, _ = select.select([events], [], [], max(0.0, next_frame - now))
            if ready:
                for kind, number, value in events.read():
                    if kind == "E":
                        game.turn(number, value)
                    elif value:
                        held[number] = time.monotonic()
                        game.press()
                    else:
                        held.pop(number, None)
            now = time.monotonic()
            if now < next_frame:
                continue
            next_frame = max(next_frame + 1 / FPS, now)
            if len(held) == 2 and now - max(held.values()) >= EXIT_HOLD:
                return
            game.update(min(now - last, 0.05), now)
            last = now
            game.render(now)
    finally:
        sound.close()


def main():
    runner.run(play)


if __name__ == "__main__":
    main()
