#!/usr/bin/env python3
"""Test script for two EC11 rotary encoders.

Wiring (BCM pins):
  Encoder 1 (X): CLK=17, DT=27
  Encoder 2 (Y): CLK=22, DT=23
  Both GNDs to GND rail.
"""

import RPi.GPIO as GPIO

CLK_X, DT_X, SW_X = 17, 27, 24
CLK_Y, DT_Y, SW_Y = 22, 23, 25

# Half-step state table (Ben Buxton)
_S  = 0x00
_CW = 0x10
_CC = 0x20
_SM = 0x03
_CWB= 0x02
_CCB= 0x01
_CWBM = 0x04
_CCBM = 0x05

HALF_TAB = [
    [_SM,      _CWB,  _CCB,  _S ],   # 0 start
    [_SM|_CC,  _S,    _CCB,  _S ],   # 1 ccw begin
    [_SM|_CW,  _CWB,  _S,    _S ],   # 2 cw begin
    [_SM,      _CCBM, _CWBM, _S ],   # 3 start_m
    [_SM,      _SM,   _CWBM, _S|_CW],# 4 cw_begin_m
    [_SM,      _CCBM, _SM,   _S|_CC],# 5 ccw_begin_m
]

class Encoder:
    def __init__(self, clk, dt, name):
        self.name = name
        self.clk = clk
        self.dt = dt
        self.state = 0
        self.steps = 0
        GPIO.setup(clk, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(dt,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(clk, GPIO.BOTH, callback=self._cb)
        GPIO.add_event_detect(dt,  GPIO.BOTH, callback=self._cb)

    def _cb(self, _channel):
        clk = GPIO.input(self.clk)
        dt  = GPIO.input(self.dt)
        self.state = HALF_TAB[self.state & 0x0f][(clk << 1) | dt]
        result = self.state & 0x30
        if result == _CW:
            self.steps += 1
            print(f"{self.name}: {self.steps:+d}")
        elif result == _CC:
            self.steps -= 1
            print(f"{self.name}: {self.steps:+d}")

def setup_button(pin, name):
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(pin, GPIO.FALLING, callback=lambda _: print(f"{name} pressed"), bouncetime=200)

GPIO.setmode(GPIO.BCM)

enc_x = Encoder(CLK_X, DT_X, "X")
enc_y = Encoder(CLK_Y, DT_Y, "Y")

setup_button(SW_X, "X")
setup_button(SW_Y, "Y")

print("Listening for encoder input. Ctrl+C to quit.")
try:
    input()
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
