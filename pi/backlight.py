#!/usr/bin/env python3
"""
Backlight enable/disable via GPIO 26 (physical pin 37) → YS-DZ-3.1 BLON.
Run after 12V supply is stable.
Usage: python3 backlight.py [on|off]
"""

import sys
import RPi.GPIO as GPIO

BLON_PIN = 26  # BCM numbering, physical pin 37

def main():
    state = (sys.argv[1].lower() == "on") if len(sys.argv) > 1 else True

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BLON_PIN, GPIO.OUT)
    GPIO.output(BLON_PIN, GPIO.HIGH if state else GPIO.LOW)

    print(f"Backlight {'ON' if state else 'OFF'}")

    try:
        input("Press Enter to exit (GPIO will be released)...\n")
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
