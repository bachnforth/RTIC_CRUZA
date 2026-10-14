#!/usr/bin/env python3
"""Observe bounded QGC UDP traffic on tailscale0; no packet payload is retained."""
import argparse
from collections import Counter
import datetime as dt
import json
import socket
import struct
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds', type=int, default=30)
args = parser.parse_args()
if not 1 <= args.seconds <= 120:
    parser.error('--seconds must be 1..120')
counts = Counter()
headers = Counter()
# ETH_P_ALL is required to observe locally transmitted packets as well as RX.
sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(0x0003))
sock.bind(('tailscale0', 0))
sock.settimeout(1)
print(json.dumps({'event': 'start', 'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'seconds': args.seconds}), flush=True)
deadline = time.monotonic() + args.seconds
try:
    while time.monotonic() < deadline:
        try:
            data = sock.recv(65535)
        except socket.timeout:
            continue
        if len(data) < 28 or data[0] >> 4 != 4 or data[9] != 17:
            continue
        offset = (data[0] & 15) * 4
        if offset < 20 or len(data) < offset + 8:
            continue
        if struct.unpack('!H', data[6:8])[0] & 0x1fff:
            continue
        source, dest = socket.inet_ntoa(data[12:16]), socket.inet_ntoa(data[16:20])
        sport, dport, length = struct.unpack('!HHH', data[offset:offset + 6])
        if not ({sport, dport} & {14550, 14560, 5600}):
            continue
        key = (source, sport, dest, dport)
        counts[key] += 1
        # Count candidate MAVLink headers only; no position/parameter payloads
        # are retained, and this is not a CRC validation.
        payload = data[offset + 8:offset + length]
        pos = 0
        while pos < len(payload):
            magic = payload[pos]
            if magic == 0xfd and pos + 10 <= len(payload):
                size = 12 + payload[pos + 1] + (13 if payload[pos + 2] & 1 else 0)
                system, component = payload[pos + 5], payload[pos + 6]
                message = int.from_bytes(payload[pos + 7:pos + 10], 'little')
            elif magic == 0xfe and pos + 6 <= len(payload):
                size = 8 + payload[pos + 1]
                system, component, message = payload[pos + 3:pos + 6]
            else:
                pos += 1
                continue
            if pos + size > len(payload):
                break
            headers[(source, dest, system, component, message)] += 1
            pos += size
        if counts[key] == 1:
            print(json.dumps({'event': 'first_packet', 'source': source, 'source_port': sport,
                              'destination': dest, 'destination_port': dport,
                              'udp_bytes': length}), flush=True)
finally:
    sock.close()
print(json.dumps({'event': 'summary', 'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'flows': [{'source': k[0], 'source_port': k[1], 'destination': k[2],
                             'destination_port': k[3], 'packets': v}
                            for k, v in sorted(counts.items())],
                  'candidate_mavlink_headers': [
                      {'source': k[0], 'destination': k[1], 'system': k[2],
                       'component': k[3], 'message_id': k[4], 'count': v}
                      for k, v in sorted(headers.items())]}), flush=True)
