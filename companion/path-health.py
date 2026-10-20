#!/usr/bin/env python3
"""Bounded, independent evidence for each hop of the Cruza/gateway/QuadPi path."""
import argparse
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import struct
import threading
import time

spec = importlib.util.spec_from_file_location('comms_health', Path(__file__).with_name('comms-health.py'))
comms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comms)
health = comms.health


def validate(cfg):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,32}', cfg['node']):
        raise ValueError('Invalid node name')
    if not 1 <= len(cfg['targets']) <= 4:
        raise ValueError('One to four targets required')
    names = set()
    for target in cfg['targets']:
        name = target['name']
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,32}', name) or name in names:
            raise ValueError('Invalid or duplicate target name')
        names.add(name)
        network = ipaddress.IPv4Network(target['network'])
        for key in ('source_ip', 'peer_ip'):
            ip = ipaddress.IPv4Address(target[key])
            if ip not in network or ip.is_multicast or ip.is_loopback or ip.is_unspecified or ip in (network.network_address, network.broadcast_address):
                raise ValueError('Target/source must be usable addresses in the declared network')
        if target['source_ip'] == target['peer_ip']:
            raise ValueError('Source and peer must differ')
    for service in cfg.get('services', []):
        if not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,80}', service):
            raise ValueError('Invalid service name')
    return cfg


def interface_for(source):
    result = health.run(['ip', '-j', '-4', 'address'])
    try:
        return next((item['ifname'] for item in json.loads(result.get('text', '[]'))
                     if any(addr.get('local') == source for addr in item.get('addr_info', []))), None)
    except (ValueError, TypeError, KeyError):
        return None


def probe(target):
    """Never allow a mesh probe to fall back through a VPN/default interface."""
    interface = interface_for(target['source_ip'])
    if not interface:
        return dict(state='unavailable', reason='source_address_absent')
    route = health.run(['ip', '-j', 'route', 'get', target['peer_ip'], 'from', target['source_ip']])
    try:
        routes = json.loads(route.get('text', '[]'))
        valid = route['code'] == 0 and len(routes) == 1 and routes[0].get('dev') == interface
    except (ValueError, TypeError):
        valid = False
    counters = {key: health.read(f'/sys/class/net/{interface}/statistics/{key}') for key in
                ('rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets', 'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped')}
    result = dict(interface=interface, interface_ifindex=health.read(f'/sys/class/net/{interface}/ifindex'),
                  operstate=health.read(f'/sys/class/net/{interface}/operstate'),
                  carrier=health.read(f'/sys/class/net/{interface}/carrier'), counters=counters)
    if not valid:
        return dict(result, state='unavailable', reason='route_missing_or_wrong_interface')
    reply = health.run(['ping', '-n', '-I', target['source_ip'], '-c', '1', '-W', '2', target['peer_ip']])
    rtt = re.search(r'time[=<]([0-9.]+)\s*ms', reply.get('text', ''))
    # Local execution errors are unknown availability, not measured packet loss.
    state = 'reachable' if reply['code'] == 0 else 'no_reply' if reply['code'] == 1 else 'unavailable'
    return dict(result, state=state, ping_code=reply['code'],
                rtt_ms=float(rtt[1]) if rtt else None,
                reason=reply.get('error', 'probe_error') if state == 'unavailable' else None)


class Observer(health.Observer):
    def __init__(self, stop, target):
        super().__init__(stop, target['peer_ip'])
        self.target = target
        self.traffic = {}
        self.opens = 0

    def loop(self):
        while not self.stop.is_set():
            interface = interface_for(self.target['source_ip'])
            if not interface:
                with self.lock:
                    self.error = 'source_address_absent'
                self.stop.wait(2)
                continue
            try:
                with socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(3)) as sock:
                    sock.bind((interface, 0))
                    sock.settimeout(1)
                    with self.lock:
                        self.error = None
                        self.opens += 1
                    while not self.stop.is_set():
                        try:
                            self.packet(sock.recv(65535))
                        except socket.timeout:
                            if interface_for(self.target['source_ip']) != interface:
                                raise OSError('Interface changed')
            except OSError as exc:
                with self.lock:
                    self.error = type(exc).__name__
                self.stop.wait(2)

    def packet(self, data):
        if len(data) < 20 or data[0] >> 4 != 4:
            return
        src, dst = socket.inet_ntoa(data[12:16]), socket.inet_ntoa(data[16:20])
        local, peer = self.target['source_ip'], self.target['peer_ip']
        if (src, dst) not in ((local, peer), (peer, local)):
            return
        direction = 'tx' if src == local else 'rx'
        now = time.monotonic()
        # Fixed key set: no payloads, arbitrary flow maps or positions are retained.
        key = f'{direction}_ip{data[9] if data[9] in (1, 6, 17) else "other"}'
        keys = [key]
        offset = (data[0] & 15)*4
        if data[9] == 17 and offset >= 20 and len(data) >= offset+8 and not int.from_bytes(data[6:8], 'big') & 0x3fff:
            sport, dport, length = struct.unpack('!HHH', data[offset:offset+6])
            if 8 <= length <= len(data)-offset:
                for kind, ports in (('observation_transport', {17841, 17842}),
                                    ('telemetry', {14550, 14560}), ('video', {5600})):
                    if {sport, dport} & ports:
                        keys.append(f'{direction}_{kind}')
        with self.lock:
            for key in keys:
                state = self.traffic.setdefault(key, dict(packets=0, bytes=0, max_gap_s=0))
                if 'last_monotonic' in state:
                    state['max_gap_s'] = max(state['max_gap_s'], now-state['last_monotonic'])
                state.update(packets=state['packets']+1, bytes=state['bytes']+len(data), last_monotonic=now)

    def snapshot(self):
        with self.lock:
            return dict(error=self.error, socket_opens=self.opens, traffic={key: dict(value,
                        age_s=time.monotonic()-value['last_monotonic']) for key, value in self.traffic.items()})


class Tracker:
    def __init__(self):
        self.state = None
        self.since = None

    def update(self, state, now):
        if self.state == state:
            return None
        event = dict(previous=self.state, state=state, monotonic=now,
                     previous_observed_duration_s=None if self.since is None else now-self.since)
        self.state, self.since = state, now
        return event


def report(paths):
    sessions = {}
    for path in paths:
        with Path(path).open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # Abrupt power loss may truncate the final write.
                if row.get('kind') != 'sample' or 'targets' not in row:
                    continue
                session = sessions.setdefault(row['session'], dict(node=row['node'], samples=0, targets={}))
                session['samples'] += 1
                for name, item in row['targets'].items():
                    stats = session['targets'].setdefault(name, dict(reachable=0, no_reply=0, unavailable=0, last_utc='', last_monotonic=-1, last_state=None, rtt_sum_ms=0, rtt_count=0))
                    stats[item['state']] += 1
                    if row.get('monotonic', 0) >= stats['last_monotonic']:
                        stats.update(last_utc=row['utc'], last_monotonic=row.get('monotonic', 0), last_state=item['state'])
                    if item.get('rtt_ms') is not None:
                        stats['rtt_sum_ms'] += item['rtt_ms']
                        stats['rtt_count'] += 1
    for session in sessions.values():
        for stats in session['targets'].values():
            stats['mean_rtt_ms'] = stats.pop('rtt_sum_ms') / stats['rtt_count'] if stats['rtt_count'] else None
            stats.pop('rtt_count')
    return dict(sessions=sessions, limits='Probe samples only; unavailable is not packet loss. No application delivery/display proof. Separate sessions across process restarts/boots. Do not supply duplicate segments.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/cruza-path-health.json'))
    parser.add_argument('--output-root', type=Path, default=Path('/home/ebach/cruza-path-health'))
    parser.add_argument('--seconds', type=int, default=0)
    parser.add_argument('--report', nargs='+', metavar='JSONL')
    args = parser.parse_args()
    if args.report:
        print(json.dumps(report(args.report), indent=2))
        return
    cfg = validate(json.loads(args.config.read_text()))
    if args.seconds < 0:
        parser.error('seconds must be nonnegative')
    started = time.monotonic()
    boot = health.read('/proc/sys/kernel/random/boot_id')
    session = f'{boot}-{time.monotonic_ns()}-{os.getpid()}'
    metadata = dict(schema=1, node=cfg['node'], session=session, boot_id=boot,
                    start_utc=health.utc(), interval_s=10, targets=cfg['targets'],
                    limits='Hop reachability only, not authenticated application delivery. Observation sharing is not enabled by this logger. No payloads/positions retained. Gaps below sampling interval may be missed. Counter epochs use boot ID/interface ifindex.')
    logger = comms.RotatingLog(args.output_root, metadata)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    observers = {t['name']: Observer(stop, t) for t in cfg['targets']}
    threads = [threading.Thread(target=o.loop, daemon=True) for o in observers.values()]
    trackers = {t['name']: Tracker() for t in cfg['targets']}
    for thread in threads:
        thread.start()
    print(f'Path logger {session}: {args.output_root}', flush=True)
    count = 0
    try:
        while not stop.is_set() and (not args.seconds or time.monotonic()-started < args.seconds):
            tick = time.monotonic()
            targets, transitions = {}, {}
            for target in cfg['targets']:
                name = target['name']
                item = probe(target)
                item['observed_monotonic'] = time.monotonic()
                item['udp'] = observers[name].snapshot()
                targets[name] = item
                change = trackers[name].update(item['state'], item['observed_monotonic'])
                if change:
                    transitions[name] = change
            services = cfg.get('services', [])
            row = dict(kind='sample', node=cfg['node'], session=session, boot_id=boot,
                       utc=health.utc(), monotonic=tick, targets=targets, transitions=transitions,
                       temperature=health.read('/sys/class/thermal/thermal_zone0/temp'),
                       throttled=health.run(['vcgencmd', 'get_throttled']),
                       uptime=health.read('/proc/uptime'), loadavg=health.read('/proc/loadavg'),
                       time_sync=health.run(['timedatectl', 'show', '-p', 'NTPSynchronized']),
                       services=health.run(['systemctl', 'show', *services, '-p', 'Id', '-p', 'ActiveState', '-p', 'NRestarts']) if services else {},
                       collection_seconds=time.monotonic()-tick,
                       filesystem_free_bytes=shutil.disk_usage(args.output_root).free)
            if not logger.write(row):
                print('Low free disk: sample skipped', flush=True)
            count += 1
            remaining = 10-(time.monotonic()-tick)
            if args.seconds:
                remaining = min(remaining, args.seconds-(time.monotonic()-started))
            stop.wait(max(0, remaining))
    finally:
        stop.set()
        for thread in threads:
            thread.join(2)
        logger.write(dict(kind='end', session=session, utc=health.utc(), samples=count))
        logger.close()


if __name__ == '__main__':
    main()
