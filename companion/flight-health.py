#!/usr/bin/env python3
"""Bounded, local Pi/HAT recorder. No UART access or aircraft/modem control."""
import argparse
from collections import Counter
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import threading
import time


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=3)
        return {'code': p.returncode, 'text': p.stdout[:24000]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'code': -1, 'error': type(e).__name__}


def kv(text):
    return dict((k.strip(), v.strip()) for line in text.splitlines()
                if ':' in line for k, v in [line.split(':', 1)])


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def crc(data, extra):
    value = 0xffff
    for byte in data + bytes([extra]):
        tmp = byte ^ (value & 255)
        tmp = (tmp ^ (tmp << 4)) & 255
        value = ((value >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 65535
    return value


class Observer:
    """Passive tailscale UDP metadata; only HEARTBEAT payload is decoded."""
    def __init__(self, stop, phone):
        self.stop, self.phone = stop, phone
        self.lock = threading.Lock()
        self.counts = Counter()
        self.headers = Counter()
        self.heartbeats = {}
        self.last_sequence = {}
        self.sequence_steps = Counter()
        self.error = None

    def loop(self):
        try:
            with socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM,
                               socket.htons(3)) as sock:
                sock.bind(('tailscale0', 0))
                sock.settimeout(1)
                while not self.stop.is_set():
                    try:
                        self.packet(sock.recv(65535))
                    except socket.timeout:
                        pass
        except OSError as e:
            self.error = type(e).__name__

    def packet(self, data):
        if len(data) < 28 or data[0] >> 4 != 4 or data[9] != 17:
            return
        offset = (data[0] & 15) * 4
        if offset < 20 or len(data) < offset + 8 or int.from_bytes(data[6:8], 'big') & 0x3fff:
            return
        src, dst = socket.inet_ntoa(data[12:16]), socket.inet_ntoa(data[16:20])
        sport, dport, length = struct.unpack('!HHH', data[offset:offset + 6])
        if self.phone not in (src, dst) or not ({sport, dport} & {14550, 14560, 5600}):
            return
        if length < 8 or offset + length > len(data):
            return
        flow = f'{src}:{sport}>{dst}:{dport}'
        payload = data[offset + 8:offset + length]
        with self.lock:
            self.counts[flow] += 1
            if not ({sport, dport} & {14550, 14560}):
                return
            pos = 0
            while pos < len(payload):
                magic = payload[pos]
                if magic == 253 and pos + 10 <= len(payload):
                    head = 10
                    signed = bool(payload[pos + 2] & 1)
                    size = 12 + payload[pos + 1] + (13 if signed else 0)
                    sysid, comp = payload[pos + 5:pos + 7]
                    seq = payload[pos + 4]
                    msg = int.from_bytes(payload[pos + 7:pos + 10], 'little')
                elif magic == 254 and pos + 6 <= len(payload):
                    head, signed = 6, False
                    size = 8 + payload[pos + 1]
                    sysid, comp, msg = payload[pos + 3:pos + 6]
                    seq = payload[pos + 2]
                else:
                    break
                if pos + size > len(payload):
                    break
                stream = f'{flow}/sys{sysid}/comp{comp}'
                if stream in self.last_sequence:
                    self.sequence_steps[f'{stream}/step{(seq-self.last_sequence[stream]) % 256}'] += 1
                self.last_sequence[stream] = seq
                self.headers[f'{flow}/sys{sysid}/comp{comp}/msg{msg}'] += 1
                body_end = pos + head + payload[pos + 1]
                if msg == 0 and crc(payload[pos + 1:body_end], 50) == int.from_bytes(payload[body_end:body_end + 2], 'little'):
                    body = payload[pos + head:body_end].ljust(9, b'\0')
                    key = f'{flow}/sys{sysid}/comp{comp}'
                    old = self.heartbeats.get(key, {})
                    now = time.monotonic()
                    self.heartbeats[key] = dict(utc=utc(), monotonic=now,
                        max_gap_s=max(old.get('max_gap_s', 0), now-old.get('monotonic', now)),
                        custom_mode=int.from_bytes(body[:4], 'little'),
                        vehicle_type=body[4], autopilot=body[5],
                        armed=bool(body[6] & 128), system_status=body[7],
                        crc_valid=True, signature_verified=False)
                pos += size

    def snapshot(self):
        with self.lock:
            result = dict(error=self.error, interval_udp_packets=dict(self.counts),
                interval_candidate_headers=dict(self.headers),
                interval_candidate_sequence_steps=dict(self.sequence_steps),
                heartbeats={k: dict(v, age_s=time.monotonic()-v['monotonic'])
                            for k, v in self.heartbeats.items()})
            self.counts.clear()
            self.headers.clear()
            self.sequence_steps.clear()
            return result


def sample(interface, phone, since, probe):
    start = time.monotonic()
    modem = run(['mmcli', '-L'])
    match = re.search(r'/Modem/(\d+)', modem.get('text', ''))
    metrics = {}
    if match:
        m = match[1]
        info = run(['mmcli', '-m', m, '-K'])
        fields = kv(info.get('text', ''))
        prefixes = ('modem.generic.state', 'modem.generic.access-technologies',
                    'modem.generic.signal-quality', 'modem.3gpp.registration-state')
        metrics = {k: v for k, v in fields.items() if k.startswith(prefixes)}
        # "current-bands" is an allowed band set, not the serving cell band.
        sig = run(['mmcli', '-m', m, '--signal-get', '-K'])
        metrics['extended_signal'] = {k:v for k,v in kv(sig.get('text', '')).items()
                                      if k.startswith('modem.signal.')}
        metrics['query_codes'] = [info['code'], sig['code']]
    counters = {k: read(f'/sys/class/net/{interface}/statistics/{k}') for k in
                ('rx_bytes', 'tx_bytes', 'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped')}
    mem = read('/proc/meminfo') or ''
    resources = {k: v for k, v in kv(mem).items() if k in
                 ('MemAvailable', 'MemTotal', 'SwapTotal', 'SwapFree')}
    status = run(['tailscale', 'status', '--json'])
    try:
        peers = json.loads(status.get('text', '{}')).get('Peer', {}).values()
        peer = next((p for p in peers if phone in p.get('TailscaleIPs', [])), {})
        vpn = {k: peer.get(k) for k in ('Online', 'Active', 'CurAddr', 'Relay',
                                      'RxBytes', 'TxBytes', 'LastHandshake')}
    except (ValueError, AttributeError):
        vpn = {'unavailable': True}
    services = run(['systemctl', 'show', 'cruza-router', 'cruza-video', 'ModemManager',
                    'NetworkManager', 'tailscaled', '-p', 'Id', '-p', 'ActiveState',
                    '-p', 'NRestarts', '-p', 'ActiveEnterTimestampMonotonic'])
    router = run(['journalctl', '-u', 'cruza-router', '-n', '80', '-o', 'cat', '--no-pager'])
    # Keep only counters/endpoint markers, never generic journal payloads.
    router_lines = [line.strip() for line in router.get('text', '').splitlines()
                    if re.match(r'\s*(UART Endpoint|UDP Endpoint|Received messages|Transmitted messages|CRC error:|Sequence lost:|Handled:|Total:|})', line)]
    events = run(['journalctl', '--since', f'@{since:.3f}', '-n', '100', '-o', 'json',
                  '--no-pager', '-u', 'NetworkManager', '-u', 'ModemManager'])
    kernel = run(['journalctl', '--since', f'@{since:.3f}', '-n', '60', '-o', 'json',
                  '--no-pager', '-k'])
    categories = []
    for line in (events.get('text', '') + '\n' + kernel.get('text', '')).splitlines():
        try:
            e = json.loads(line)
            message = e.get('MESSAGE', '').lower()
            kinds = [word for word in ('disconnect', 'connect', 'registered', 'registration',
                     'failed', 'error', 'reset', 'usb', 'under-voltage', 'throttl') if word in message]
            if kinds:
                categories.append({'timestamp_us': e.get('__REALTIME_TIMESTAMP'),
                    'unit': e.get('_SYSTEMD_UNIT'), 'transport': e.get('_TRANSPORT'),
                    'categories': kinds})
        except (ValueError, TypeError):
            continue
    result = dict(modem=metrics, modem_present=bool(match), interface_counters=counters,
        routes=run(['ip', '-j', 'route']), nm_devices=run(['nmcli', '-t', '-f',
        'DEVICE,TYPE,STATE', 'device']), vpn_peer=vpn, services=services,
        temperature=read('/sys/class/thermal/thermal_zone0/temp'),
        throttled=run(['vcgencmd', 'get_throttled']), memory=resources,
        cpu_stat=(read('/proc/stat') or '').splitlines()[:1],
        loadavg=read('/proc/loadavg'), uptime=read('/proc/uptime'),
        router_counter_lines=router_lines, event_categories=categories,
        event_query_codes=[events['code'], kernel['code']],
        event_query_may_be_truncated=any(len(q.get('text', '')) >= 24000 or
            len(q.get('text', '').splitlines()) >= n for q,n in ((events,100),(kernel,60))))
    if probe:
        result['lte_internet_probe'] = run(['ping', '-n', '-I', interface, '-c', '1', '-W', '2', '1.1.1.1'])
        result['vpn_path_probe'] = run(['tailscale', 'ping', '--c', '1', '--timeout', '2s', phone])
    result['collection_seconds'] = time.monotonic() - start
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--interval', type=int, default=10)
    p.add_argument('--output-root', type=Path, default=Path.home() / 'cruza-health')
    p.add_argument('--config', type=Path, default=Path('/etc/cruza/config.json'))
    args = p.parse_args()
    if not 10 <= args.seconds <= 7200 or not 10 <= args.interval <= 60:
        p.error('seconds must be 10..7200; interval 10..60')
    cfg = json.loads(args.config.read_text())
    interface, phone = cfg['lte_interface'], cfg['android_ip']
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,20}', interface) or not re.fullmatch(r'100\.\d+\.\d+\.\d+', phone):
        p.error('invalid interface/peer')
    session = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}'
    dest = args.output_root / session
    dest.mkdir(parents=True, mode=0o700, exist_ok=False)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    observer = Observer(stop, phone)
    thread = threading.Thread(target=observer.loop, daemon=True)
    thread.start()
    started = time.monotonic()
    deadline = started + args.seconds
    manifest = dict(session=session, start_utc=utc(), boot_id=read('/proc/sys/kernel/random/boot_id'),
        duration_limit_s=args.seconds, interval_s=args.interval, probe_interval_s=60,
        internet_target='1.1.1.1', vpn_target=phone, position_capture=False,
        video={k: cfg.get(k) for k in ('video_profile', 'video_max_seconds', 'video_port')},
        time_sync=run(['timedatectl', 'show', '-p', 'NTPSynchronized']),
        storage_limit_bytes=32*1024*1024,
        limits='No serving-band query; extended signal may be unavailable. UDP observation does not prove phone receipt. Candidate headers except heartbeat are not CRC-validated. Event journal contains categories only; detailed diagnosis may need scoped journal retrieval. No GPS or FC time captured.')
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(str(dest), flush=True)
    since, next_probe, count, reason = time.time(), started, 0, 'duration'
    try:
        with (dest / 'samples.jsonl').open('x') as out:
            while time.monotonic() < deadline and not stop.is_set():
                tick, wall = time.monotonic(), time.time()
                data = sample(interface, phone, since, tick >= next_probe)
                if tick >= next_probe:
                    next_probe = tick + 60
                data.update(utc=utc(), sample_start_unix=wall, monotonic=tick,
                            session=session, udp=observer.snapshot())
                out.write(json.dumps(data) + '\n')
                out.flush()
                os.fsync(out.fileno())
                count += 1
                since = wall
                if out.tell() >= 32*1024*1024:
                    reason = 'storage_limit'
                    break
                stop.wait(max(0, min(deadline-time.monotonic(), args.interval-(time.monotonic()-tick))))
    except BaseException:
        reason = 'error'
        raise
    finally:
        was_stopped = stop.is_set()
        stop.set()
        thread.join(timeout=2)
        (dest / 'end.json').write_text(json.dumps(dict(end_utc=utc(), samples=count,
            reason='signal' if was_stopped else reason,
            elapsed_s=time.monotonic()-started, final_udp=observer.snapshot()), indent=2))
        # A sudo-run capture must remain retrievable by the invoking owner.
        if os.geteuid() == 0 and os.environ.get('SUDO_UID'):
            uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
            for path in [dest, dest / 'manifest.json', dest / 'samples.jsonl', dest / 'end.json']:
                if path.exists():
                    os.chown(path, uid, gid)
                    path.chmod(0o700 if path.is_dir() else 0o600)


if __name__ == '__main__':
    main()
