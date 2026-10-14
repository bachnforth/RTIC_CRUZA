#!/usr/bin/env python3
"""Passive UART observation only; sends no bytes or flight commands."""
import json
import os
import select
import termios
import time

fd = os.open('/dev/serial0', os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
original = termios.tcgetattr(fd)
count = 0
try:
    attrs = termios.tcgetattr(fd)
    attrs[0] = attrs[1] = attrs[3] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[4] = attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    end = time.monotonic() + 8
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], max(0, end-time.monotonic()))
        if ready:
            count += len(os.read(fd, 4096))
finally:
    termios.tcsetattr(fd, termios.TCSANOW, original)
    os.close(fd)
print(json.dumps({'device': '/dev/serial0', 'baud': 115200, 'received_bytes': count,
                  'transmitted_bytes': 0, 'mavlink_validated': False}))
