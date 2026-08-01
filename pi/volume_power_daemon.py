#!/usr/bin/env python3
"""
Raspberry Pi Standalone Volume & Display Power Controller
Designed for Toyota Head Unit project.

Hardware Pinout (BCM):
  Encoder CLK = GPIO 10 (Physical Pin 19)
  Encoder DT  = GPIO 11 (Physical Pin 23)
  Button SW   = GPIO 18 (Physical Pin 12)
  Backlight   = GPIO 26 (Physical Pin 37) -> YS-DZ-3.1 BLON
  Ground      = System GND (Physical Pin 14 or 20)

Behavior:
- Rotate Knob CW/CCW: Adjust Volume (+5% / -5%) via ALSA `amixer` (Card 1 USB Audio Speaker / Card 0 PCM).
- Short Press Knob: Toggle LCD backlight display power ON/OFF (GPIO 26).
- Long Press Knob (> 2.0s): Trigger safe Linux system shutdown (`sudo shutdown -h now`).
"""

import time
import subprocess
import RPi.GPIO as GPIO

# Pin Definitions
CLK_PIN  = 11
DT_PIN   = 10
SW_PIN   = 18
BLON_PIN = 26

# Half-step quadrature decoder state machine table (Ben Buxton algorithm)
_S, _CW, _CC = 0x00, 0x10, 0x20
_SM, _CWB, _CCB, _CWBM, _CCBM = 0x03, 0x02, 0x01, 0x04, 0x05
HALF_TAB = [
    [_SM,      _CWB,  _CCB,  _S ],
    [_SM|_CC,  _S,    _CCB,  _S ],
    [_SM|_CW,  _CWB,  _S,    _S ],
    [_SM,      _CCBM, _CWBM, _S ],
    [_SM,      _SM,   _CWBM, _S|_CW],
    [_SM,      _CCBM, _SM,   _S|_CC],
]

class HeadUnitControl:
    def __init__(self):
        # Force hardware pull-ups on GPIO 10 and 11
        try:
            subprocess.run(["pinctrl", "set", "10,11", "ip", "pu"], check=False)
        except Exception:
            pass

        GPIO.setmode(GPIO.BCM)

        # 1. Setup Rotary Encoder Pins
        GPIO.setup(CLK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(DT_PIN,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(CLK_PIN, GPIO.BOTH, callback=self._encoder_cb)
        GPIO.add_event_detect(DT_PIN,  GPIO.BOTH, callback=self._encoder_cb)
        self.state = 0

        # 2. Setup Backlight Control Pin (Default ON)
        GPIO.setup(BLON_PIN, GPIO.OUT)
        GPIO.output(BLON_PIN, GPIO.HIGH)
        self.backlight_on = True

        # 3. Setup Push Button Input Pin
        GPIO.setup(SW_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(SW_PIN, GPIO.BOTH, callback=self._button_cb, bouncetime=50)
        self.press_start = 0

    def _change_volume(self, delta_str):
        # Explicitly target Card 1 (USB Audio Device Speaker) first
        for cmd in [
            ["amixer", "-c", "1", "-q", "sset", "Speaker", delta_str],
            ["amixer", "-c", "1", "-q", "sset", "PCM", delta_str],
            ["amixer", "-q", "sset", "Speaker", delta_str],
            ["amixer", "-q", "sset", "Master", delta_str],
            ["amixer", "-q", "sset", "PCM", delta_str],
        ]:
            res = subprocess.run(cmd, check=False)
            if res.returncode == 0:
                print(f"Volume adjusted: {' '.join(cmd)}", flush=True)
                return

    def _encoder_cb(self, _ch):
        c = GPIO.input(CLK_PIN)
        d = GPIO.input(DT_PIN)
        self.state = HALF_TAB[self.state & 0x0f][(c << 1) | d]
        res = self.state & 0x30
        if res == _CW:
            self._change_volume("5%+")
        elif res == _CC:
            self._change_volume("5%-")

    def _button_cb(self, channel):
        if GPIO.input(channel) == GPIO.LOW:
            # Button pressed down
            self.press_start = time.time()
        else:
            # Button released
            if self.press_start == 0:
                return
            duration = time.time() - self.press_start
            self.press_start = 0

            if duration >= 2.0:
                # Long press (>2.0s): Graceful shutdown for car power off
                print("Long press detected: shutting down Pi...", flush=True)
                subprocess.run(["sudo", "shutdown", "-h", "now"])
            else:
                # Short press: Toggle LCD backlight
                self.backlight_on = not self.backlight_on
                GPIO.output(BLON_PIN, GPIO.HIGH if self.backlight_on else GPIO.LOW)
                print(f"Backlight toggled: {'ON' if self.backlight_on else 'OFF'}", flush=True)

if __name__ == "__main__":
    print("Starting Head Unit Volume & Display Power Controller Daemon...", flush=True)
    ctrl = HeadUnitControl()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping daemon...", flush=True)
    finally:
        GPIO.cleanup()
