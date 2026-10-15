#!/usr/bin/env python3
"""Unprivileged loopback-only reader. No camera, UART or network transmit API."""
import argparse
import json
import os
import socket
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--port', type=int, choices=(15610,15611), required=True)
args = p.parse_args()
os.set_blocking(1, False)
progress = time.monotonic()
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
    sock.bind(('127.0.0.1', args.port))
    sock.settimeout(5)
    while True:
        try:
            raw = sock.recv(2048)
            record = json.loads(raw)
            if not isinstance(record,dict) or not set(record).issubset({'frame','boot_id','source','passive'}):
                continue
        except socket.timeout:
            raw = b'{"observer_waiting":true}\n'
        except (ValueError,TypeError):
            continue
        try:
            os.write(1, raw)
            progress = time.monotonic()
        except BlockingIOError:
            if time.monotonic()-progress > 10:
                break
        except BrokenPipeError:
            break
