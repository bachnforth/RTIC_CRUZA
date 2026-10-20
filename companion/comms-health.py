#!/usr/bin/env python3
"""Continuous, rotating Pi-side communications evidence; never opens the AIO UART."""
import argparse
import importlib.util
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

spec = importlib.util.spec_from_file_location('flight_health', Path(__file__).with_name('flight-health.py'))
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class Observer(health.Observer):
    def __init__(self, stop, phone):
        super().__init__(stop, phone)
        self.video = {}
        self.icmp_unreachable = 0
        self.reopens = 0

    def loop(self):
        # The VPN interface may not exist at boot, or may be recreated later.
        while not self.stop.is_set():
            try:
                with socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(3)) as sock:
                    sock.bind(('tailscale0', 0))
                    sock.settimeout(1)
                    with self.lock:
                        self.error = None
                        self.reopens += 1
                    while not self.stop.is_set():
                        if not Path('/sys/class/net/tailscale0').exists():
                            raise OSError('VPN interface disappeared')
                        try:
                            self.packet(sock.recv(65535))
                        except socket.timeout:
                            pass
            except OSError as exc:
                with self.lock:
                    self.error = type(exc).__name__
                self.stop.wait(2)

    def packet(self, data):
        super().packet(data)
        if len(data) < 28 or data[0] >> 4 != 4:
            return
        offset = (data[0] & 15) * 4
        if offset < 20 or len(data) < offset + 8 or int.from_bytes(data[6:8], 'big') & 0x3fff:
            return
        src, dst = socket.inet_ntoa(data[12:16]), socket.inet_ntoa(data[16:20])
        if self.phone not in (src, dst):
            return
        with self.lock:
            if data[9] == 1 and data[offset] == 3 and src == self.phone:
                self.icmp_unreachable += 1
            if data[9] != 17:
                return
            sport, dport, length = struct.unpack('!HHH', data[offset:offset + 6])
            if dport != 5600 or dst != self.phone or length < 20 or offset + length > len(data):
                return
            body = data[offset + 8:offset + length]
            if body[0] >> 6 != 2:
                return
            seq = int.from_bytes(body[2:4], 'big')
            ssrc = str(int.from_bytes(body[8:12], 'big'))
            if ssrc not in self.video and len(self.video) >= 8:
                return
            now = time.monotonic()
            state = self.video.setdefault(ssrc, dict(packets=0, bytes=0, max_gap_s=0))
            if 'last_monotonic' in state:
                state['max_gap_s'] = max(state['max_gap_s'], now - state['last_monotonic'])
                state['last_sequence_step'] = (seq - state['last_sequence']) % 65536
            state.update(last_monotonic=now, last_utc=health.utc(), last_sequence=seq,
                         packets=state['packets'] + 1, bytes=state['bytes'] + len(body))

    def snapshot(self):
        result = super().snapshot()
        with self.lock:
            result.update(socket_opens=self.reopens, phone_icmp_unreachable=self.icmp_unreachable,
                video_rtp={key: dict(value, age_s=time.monotonic()-value['last_monotonic'])
                           for key, value in self.video.items()})
        return result


class RotatingLog:
    def __init__(self, root, metadata, segment_bytes=4*1024*1024, total_bytes=128*1024*1024,
                 reserve_bytes=256*1024*1024):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.metadata = metadata
        self.segment_bytes, self.total_bytes, self.reserve_bytes = segment_bytes, total_bytes, reserve_bytes
        self.stream = None
        self.path = None
        self.index = 0
        self.skipped = 0

    def write(self, record):
        if shutil.disk_usage(self.root).free < self.reserve_bytes:
            self.skipped += 1
            return False
        if self.stream is None or self.stream.tell() >= self.segment_bytes:
            self.close()
            self.index += 1
            self.path = self.root / f'comms-{self.metadata["session"]}-{self.index:05d}.jsonl'
            self.stream = self.path.open('x', encoding='utf-8')
            os.chmod(self.path, 0o600)
            self.stream.write(json.dumps(dict(kind='segment', **self.metadata)) + '\n')
        self.stream.write(json.dumps(dict(record, skipped_for_low_disk=self.skipped)) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        # Only this logger's regular, non-symlink files are eligible for retention.
        files = [p for p in self.root.glob('comms-*.jsonl') if p.is_file() and not p.is_symlink()]
        sizes = {p: p.stat().st_size for p in files}
        total = sum(sizes.values())
        for path in sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name)):
            if total <= self.total_bytes:
                break
            if path != self.path:
                path.unlink()
                total -= sizes[path]
        return True

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None


def service_events(since):
    result = health.run(['journalctl', '--since', f'@{since:.3f}', '-p', 'notice', '-n', '60', '-o', 'json',
        '--no-pager', '-u', 'cruza-video', '-u', 'cruza-router', '-u', 'tailscaled'])
    events = []
    for line in result.get('text', '').splitlines():
        try:
            item = json.loads(line)
            message = str(item.get('MESSAGE', '')).lower()
            categories = [word for word in ('failed', 'error', 'exit', 'start', 'stop', 'timeout',
                'camera', 'disconnect', 'connect', 'derp', 'relay') if word in message]
            if categories:
                events.append(dict(timestamp_us=item.get('__REALTIME_TIMESTAMP'),
                    unit=item.get('_SYSTEMD_UNIT'), categories=categories))
        except (ValueError, TypeError):
            continue
    return dict(code=result['code'], events=events,
        may_be_truncated=len(result.get('text', '')) >= 24000 or len(result.get('text', '').splitlines()) >= 60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/cruza/config.json'))
    parser.add_argument('--output-root', type=Path, default=Path('/home/ebach/cruza-comms-health'))
    parser.add_argument('--seconds', type=int, default=0, help='0 means continuous')
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    interface, phone = cfg['lte_interface'], cfg['android_ip']
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,20}', interface) or not re.fullmatch(r'100\.\d+\.\d+\.\d+', phone):
        parser.error('Invalid LTE interface or phone peer')
    boot = health.read('/proc/sys/kernel/random/boot_id')
    started = time.monotonic()
    session = f'{boot}-{time.monotonic_ns()}-{os.getpid()}'
    metadata = dict(schema=1, session=session, boot_id=boot, start_utc=health.utc(),
        start_monotonic=started, interface=interface, phone=phone,
        interval_s=10, probe_interval_s=60, retention_bytes=128*1024*1024,
        video={k:cfg.get(k) for k in ('video_profile', 'video_max_seconds', 'video_port')},
        limits='Pi vantage only. Video egress is not phone decode/display. No packet payloads, GPS, SIM identifiers or credentials retained. CRC validated for MAVLink heartbeat only; signatures not verified. Sequence steps are not end-to-end loss. No UART access, FC commands or network recovery actions.')
    logger = RotatingLog(args.output_root, metadata)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    observer = Observer(stop, phone)
    thread = threading.Thread(target=observer.loop, daemon=True)
    thread.start()
    print(f'Logging session {session} to {args.output_root}', flush=True)
    since, next_probe, count = time.time(), started, 0
    try:
        while not stop.is_set() and (not args.seconds or time.monotonic()-started < args.seconds):
            tick, wall = time.monotonic(), time.time()
            data = health.sample(interface, phone, since, tick >= next_probe)
            if tick >= next_probe:
                next_probe = tick + 60
            data.update(kind='sample', utc=health.utc(), monotonic=tick, unix=wall,
                session=session, boot_id=boot, udp=observer.snapshot(),
                time_sync=health.run(['timedatectl', 'show', '-p', 'NTPSynchronized']),
                service_events=service_events(since),
                filesystem_free_bytes=shutil.disk_usage(args.output_root).free)
            if not logger.write(data):
                print('Low free disk: sample skipped', flush=True)
            since = wall
            count += 1
            remaining = 10-(time.monotonic()-tick)
            if args.seconds:
                remaining = min(remaining, args.seconds-(time.monotonic()-started))
            stop.wait(max(0, remaining))
    finally:
        stop.set()
        thread.join(2)
        logger.write(dict(kind='end', utc=health.utc(), monotonic=time.monotonic(), samples=count))
        logger.close()


if __name__ == '__main__':
    main()
