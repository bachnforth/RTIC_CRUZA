#!/usr/bin/env python3
"""Optional passive egress observer. Never opens UART or transmits network data.

AF_PACKET requires root for creation. Privileges are dropped immediately after
binding. Only selected outgoing MAVLink frames are copied to SSH stdout.
No packet, log or location is retained on disk.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import struct
import time

IDS = {0, 1, 24, 30, 33, 42, 46, 74, 147, 242, 245, 253}
# STATUSTEXT (253) carries the autopilot's warnings. Each one is a different
# message, so it bypasses the per-type 0.5 s thinning but is capped at
# TEXT_BURST messages per TEXT_WINDOW seconds.
STATUSTEXT, TEXT_BURST, TEXT_WINDOW = 253, 20, 10
SOURCES = {'cruza': ('tailscale0', '100.100.0.58', 14560),
           'quadpi': ('eth0', '10.223.79.20', 14551)}


def frames(packet, source_ip, source_port):
    if len(packet) < 28 or packet[0] >> 4 != 4 or packet[9] != 17:
        return
    offset = (packet[0] & 15)*4
    if offset < 20 or int.from_bytes(packet[6:8], 'big') & 0x3fff or len(packet) < offset+8:
        return
    if socket.inet_ntoa(packet[12:16]) != source_ip:
        return
    sport, dport, size = struct.unpack('!HHH', packet[offset:offset+6])
    if sport != source_port or dport not in (14550, 14560) or not 8 <= size <= 4096 or offset+size > len(packet):
        return
    yield from mav_frames(packet[offset+8:offset+size])


def mav_frames(payload):
    pos = 0
    while pos < len(payload):
        if payload[pos] == 253 and pos+10 <= len(payload):
            length = 12+payload[pos+1]+(13 if payload[pos+2] & 1 else 0)
            mid = int.from_bytes(payload[pos+7:pos+10], 'little')
        elif payload[pos] == 254 and pos+6 <= len(payload):
            length, mid = 8+payload[pos+1], payload[pos+5]
        else:
            break
        if pos+length > len(payload):
            break
        if mid in IDS:
            yield mid, payload[pos:pos+length]
        pos += length


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=SOURCES)
    parser.add_argument('--local-port', type=int, default=0, choices=(0,15610,15611))
    args = parser.parse_args()
    interface, address, port = SOURCES[args.source]
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    output = 1
    os.set_blocking(output, False)
    local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if args.local_port else None
    if local:
        local.setblocking(False)
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    quad = args.source == 'quadpi'
    with socket.socket(socket.AF_INET if quad else socket.AF_PACKET,
                       socket.SOCK_DGRAM, 0 if quad else socket.htons(3)) as capture:
        capture.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32768)
        capture.bind(('127.0.0.1',15612) if quad else (interface, 0))
        capture.settimeout(1)
        nobody = pwd.getpwnam('nobody')
        os.setgroups([])
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)
        os.nice(19)
        last, texts, next_meta, progress = {}, [], 0, time.monotonic()
        def emit(value):
            nonlocal progress, running
            try:
                raw = json.dumps(value, separators=(',', ':')).encode()+b'\n'
                if local:
                    local.sendto(raw, ('127.0.0.1', args.local_port))
                else:
                    os.write(output, raw)
                progress = time.monotonic()
            except BlockingIOError:
                if time.monotonic()-progress > 10:
                    running = False
            except BrokenPipeError:
                running = False
            except OSError:
                if not local:
                    running = False
        while running:
            now = time.monotonic()
            if now >= next_meta:
                emit({'boot_id': boot, 'source': args.source, 'passive': True})
                next_meta = now+5
            try:
                packet, info = capture.recvfrom(8192)
            except socket.timeout:
                continue
            if not quad and info[2] != socket.PACKET_OUTGOING:
                continue
            selected = mav_frames(packet) if quad else frames(packet, address, port)
            for mid, raw in selected:
                if mid == STATUSTEXT:
                    while texts and now-texts[0] > TEXT_WINDOW:
                        texts.pop(0)
                    if len(texts) < TEXT_BURST:
                        texts.append(now)
                        emit({'frame': raw.hex()})
                elif now-last.get(mid, -100) >= .5:
                    emit({'frame': raw.hex()})
                    last[mid] = now


if __name__ == '__main__':
    main()
