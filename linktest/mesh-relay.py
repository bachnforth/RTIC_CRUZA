"""Fixed-destination UDP relay. No forwarding/routing configuration changes."""
import argparse
import json
from pathlib import Path
import selectors
import signal
import socket
import time


class Relay:
    def __init__(self, config, idle_s=120):
        self.selector = selectors.DefaultSelector()
        self.sessions = {}
        self.idle_s = idle_s
        self.allowed = set(config['allowed_sources'])
        self.source_ip = config['mesh_source_ip']
        self.counts = dict(forwarded=0, replies=0, rejected=0, errors=0, expired=0)
        self.listeners = []
        try:
            for item in config['mappings']:
                listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.listeners.append(listener)
                listener.bind((config['vpn_bind_ip'], item['listen_port']))
                listener.setblocking(False)
                self.selector.register(listener, selectors.EVENT_READ,
                                       ('listener', (item['destination_ip'], item['destination_port'])))
        except Exception:
            self.close()
            raise

    def tick(self, timeout=0.25):
        for key, _ in self.selector.select(timeout):
            role, data = key.data
            try:
                packet, sender = key.fileobj.recvfrom(65535)
                if role == 'listener':
                    if sender[0] not in self.allowed:
                        self.counts['rejected'] += 1
                        continue
                    identity = (key.fileobj, sender)
                    entry = self.sessions.get(identity)
                    if entry is None:
                        if len(self.sessions) >= 64:
                            self.counts['rejected'] += 1
                            continue
                        upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        try:
                            upstream.bind((self.source_ip, 0))
                            upstream.connect(data)
                            upstream.setblocking(False)
                            self.selector.register(upstream, selectors.EVENT_READ, ('reply', identity))
                        except Exception:
                            upstream.close()
                            raise
                        entry = self.sessions[identity] = [upstream, time.monotonic()]
                    entry[1] = time.monotonic()
                    entry[0].send(packet)
                    self.counts['forwarded'] += 1
                else:
                    listener, client = data
                    listener.sendto(packet, client)
                    self.counts['replies'] += 1
            except OSError:
                self.counts['errors'] += 1
        now = time.monotonic()
        for identity, (upstream, touched) in list(self.sessions.items()):
            if now - touched > self.idle_s:
                self.selector.unregister(upstream)
                upstream.close()
                del self.sessions[identity]
                self.counts['expired'] += 1

    def close(self):
        for upstream, _ in self.sessions.values():
            upstream.close()
        for listener in self.listeners:
            listener.close()
        self.sessions.clear()
        self.selector.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True)
    p.add_argument('--status', required=True)
    args = p.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    relay = Relay(config)
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    status = Path(args.status)
    status.parent.mkdir(parents=True, exist_ok=True)
    last = 0
    try:
        while running:
            relay.tick()
            if time.monotonic() - last > 2:
                state = dict(updated=time.time(), sessions=len(relay.sessions), **relay.counts)
                temp = status.with_suffix('.tmp')
                temp.write_text(json.dumps(state), encoding='utf-8')
                temp.replace(status)
                last = time.monotonic()
    finally:
        relay.close()


if __name__ == '__main__':
    main()
