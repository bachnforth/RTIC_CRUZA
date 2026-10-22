#!/usr/bin/env python3
"""Optional loopback RTP -> SSH stdout copy. No camera, routing or FC access."""
import argparse
import os
import signal
import socket
import struct
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True, choices=range(15600, 15610))
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
                packet = sock.recv(4096)
            except socket.timeout:
                if time.monotonic()-last_progress > 20:
                    break
                continue
            if len(packet) < 12 or len(packet) > 2000 or packet[0] >> 6 != 2 or packet[1] & 127 != 96:
                continue
            framed = struct.pack('!H', len(packet))+packet
            try:
                # Nonblocking atomic pipe write below Linux PIPE_BUF: slow
                # dashboard loses copies without backpressuring the encoder.
                os.write(output, framed)
                last_progress = time.monotonic()
            except BlockingIOError:
                if time.monotonic()-last_progress > 10:
                    break
            except BrokenPipeError:
                break


if __name__ == '__main__':
    main()
