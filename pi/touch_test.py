#!/usr/bin/env python3
"""
Touch coordinate monitor.
Reads T/U events from ESP32 over software UART on /dev/ttyS0.
Usage: python3 touch_test.py [port]
"""

import sys
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyS0"

with serial.Serial(port, 9600, timeout=1) as s:
    print(f"Listening on {port} — touch the screen (Ctrl+C to quit)")
    while True:
        line = s.readline().decode(errors="ignore").strip()
        if line:
            print(line)
