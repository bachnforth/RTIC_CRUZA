#!/usr/bin/env python3
"""One DNS query explicitly bound to the verified LTE interface, no flight traffic."""
import json
import secrets
import socket
import struct

transaction = secrets.randbits(16)
name = b''.join(bytes([len(label)]) + label for label in [b'example', b'com']) + b'\0'
request = struct.pack('!6H', transaction, 0x0100, 1, 0, 0, 0) + name + struct.pack('!2H', 1, 1)
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'wwan0\0')
    s.settimeout(8)
    s.connect(('8.8.8.8', 53))
    s.send(request)
    reply = s.recv(4096)
    ident, flags, questions, answers, _, _ = struct.unpack('!6H', reply[:12])
    valid = ident == transaction and bool(flags & 0x8000) and (flags & 15) == 0 and answers > 0
    print(json.dumps({'interface': 'wwan0', 'server': '8.8.8.8', 'query': 'example.com',
                      'response_valid': valid, 'answers': answers, 'local_ip': s.getsockname()[0]}))
    if not valid:
        raise SystemExit(1)
