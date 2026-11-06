#!/usr/bin/env python3
"""Optional loopback observation -> SSH stdout copy. No camera, FC or routing.

Binds a loopback UDP port the detector publishes to, frames each JSON record
with a two-byte length and writes it to stdout, which the laptop dashboard reads
over SSH. It has no camera, serial, MAVLink, route or modem access and sends
nothing back to the aircraft. Started by the dashboard when a viewer connects;
it expires on its own when idle, like the video tap.
"""
import argparse
import json
import os
import signal
import socket
import struct
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True, choices=range(15620, 15630))
    args = parser.parse_args()
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    output = sys.stdout.fileno()
    os.set_blocking(output, False)
    last_progress = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32768)
        sock.bind(('127.0.0.1', args.port))
        sock.settimeout(1)
        while running:
            try:
                packet = sock.recv(1024)
            except socket.timeout:
                if time.monotonic()-last_progress > 30:
                    break
                continue
            if not 2 <= len(packet) <= 512:
                continue
            try:
                # Parse-and-reserialise: forward only well-formed, finite JSON
                # objects. A malformed datagram is dropped, never framed.
                obj = json.loads(packet)
                if not isinstance(obj, dict):
                    continue
                clean = json.dumps(obj, allow_nan=False).encode()
            except (ValueError, TypeError):
                continue
            if len(clean) > 512:
                continue
            framed = struct.pack('!H', len(clean))+clean
            try:
                # Nonblocking atomic write below PIPE_BUF: a slow dashboard loses
                # records without backpressuring the detector.
                os.write(output, framed)
                last_progress = time.monotonic()
            except BlockingIOError:
                if time.monotonic()-last_progress > 10:
                    break
            except BrokenPipeError:
                break


if __name__ == '__main__':
    main()
