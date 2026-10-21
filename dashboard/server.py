#!/usr/bin/env python3
"""Laptop-only two-camera viewer. Closing viewers stops optional SSH copies."""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import shlex
import socket
import struct
import subprocess
import threading
import time
from fleet import VehicleState

HERE = Path(__file__).resolve().parent
KEY = Path.home()/'.ssh'/'id_ed25519_rpi'
# RN03 needs no tap: mavlink-router already serves every GCS on TCP 5760 and
# fpv-relay already pushes RTP at the roster-3 laptop address on the mesh.
RN03_PI = '10.223.53.30'
RN03_TELEMETRY_PORT = 5760
RN03_VIDEO_BIND = ('10.223.53.10', 5600)
STOP = threading.Event()
last_viewer = 0
last_telemetry_viewer = 0
feeds = []
telemetry = []
media = None


def active():
    return time.monotonic()-last_viewer < 12


def telemetry_active():
    return time.monotonic()-last_telemetry_viewer < 12


def read_exact(stream, length):
    data = bytearray()
    while len(data) < length:
        part = stream.read(length-len(data))
        if not part:
            raise EOFError('Video connection closed')
        data.extend(part)
    return bytes(data)


class Feed:
    def __init__(self, name, host, alias, remote_port, local_port):
        self.name, self.host, self.alias = name, host, alias
        self.remote_port, self.local_port = remote_port, local_port
        self.proc = None
        self.lock = threading.Lock()
        self.total = self.packets = self.last_packet = 0
        self.error = ''
        self.thread = threading.Thread(target=self.run, daemon=True)

    def disconnect(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()

    def snapshot(self):
        age = time.monotonic()-self.last_packet if self.last_packet else None
        return dict(name=self.name, receiving=age is not None and age < 3,
                    age_seconds=round(age, 1) if age is not None else None,
                    bytes=self.total, packets=self.packets, error=self.error)

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as output:
            while not STOP.is_set():
                if not active():
                    STOP.wait(.5)
                    continue
                argv = ['ssh', '-T', '-i', str(KEY), '-o', 'IdentitiesOnly=yes',
                        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        '-o', 'ConnectTimeout=6', '-o', 'ServerAliveInterval=5',
                        '-o', 'ServerAliveCountMax=2', '-o', 'LogLevel=ERROR',
                        '-o', 'HostKeyAlias='+self.alias, 'ebach@'+self.host,
                        'python3 /opt/cruza-video-tap.py --port '+str(self.remote_port)]
                errors = deque(maxlen=2)
                try:
                    with self.lock:
                        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        proc = self.proc
                    def collect_errors():
                        for line in iter(proc.stderr.readline, b''):
                            errors.append(line.decode(errors='replace').strip()[:200])
                    reader = threading.Thread(target=collect_errors, daemon=True)
                    reader.start()
                    while not STOP.is_set() and active():
                        length = struct.unpack('!H', read_exact(proc.stdout, 2))[0]
                        if not 12 <= length <= 2000:
                            raise ValueError('Invalid video packet framing')
                        raw = read_exact(proc.stdout, length)
                        if raw[0] >> 6 != 2 or raw[1] & 127 != 96:
                            raise ValueError('Unexpected video packet')
                        output.sendto(raw, ('127.0.0.1', self.local_port))
                        self.total += length
                        self.packets += 1
                        self.last_packet = time.monotonic()
                        self.error = ''
                except (EOFError, OSError, ValueError) as exc:
                    self.error = ' / '.join(errors) or str(exc)
                finally:
                    self.disconnect()
                    if self.proc:
                        try:
                            self.proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            self.proc.kill()
                            self.proc.wait(timeout=3)
                        self.proc.stdout.close()
                        self.proc.stderr.close()
                        self.proc = None
                STOP.wait(3)


class UdpFeed:
    """RN03 sends RTP to the laptop's mesh address already, so no tap, SSH or
    aircraft change is needed. The socket is bound only while a viewer watches,
    and only on the mesh address, so pausing hands the port back to QGC."""
    def __init__(self, name, bind, local_port):
        self.name, self.bind, self.local_port = name, bind, local_port
        self.sock = None
        self.lock = threading.Lock()
        self.total = self.packets = self.last_packet = 0
        self.error = ''
        self.thread = threading.Thread(target=self.run, daemon=True)

    def disconnect(self):
        with self.lock:
            if self.sock:
                self.sock.close()
                self.sock = None

    def snapshot(self):
        age = time.monotonic()-self.last_packet if self.last_packet else None
        return dict(name=self.name, receiving=age is not None and age < 3,
                    age_seconds=round(age, 1) if age is not None else None,
                    bytes=self.total, packets=self.packets, error=self.error)

    def listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1)
            sock.bind(self.bind)
        except OSError as exc:
            sock.close()
            # The pilot's own QGC video link binds the same port; say so plainly.
            self.error = f'Cannot receive on {self.bind[0]}:{self.bind[1]} ({exc.strerror or exc}). Stop the QGC video source on this port, or pause video here.'
            return None
        self.error = ''
        return sock

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as output:
            while not STOP.is_set():
                if not active():
                    self.disconnect()
                    STOP.wait(.5)
                    continue
                with self.lock:
                    if self.sock is None:
                        self.sock = self.listen()
                    sock = self.sock
                if sock is None:
                    STOP.wait(3)
                    continue
                try:
                    raw = sock.recv(65535)
                except socket.timeout:
                    continue
                except OSError as exc:
                    self.error = str(exc)
                    self.disconnect()
                    STOP.wait(3)
                    continue
                output.sendto(raw, ('127.0.0.1', self.local_port))
                with self.lock:
                    self.total += len(raw)
                    self.packets += 1
                    self.last_packet = time.monotonic()


def split_frames(buffer):
    """Split a MAVLink byte stream into whole frames; return the unread tail."""
    frames, pos = [], 0
    while pos < len(buffer):
        stx = buffer[pos]
        if stx == 0xFD:
            if len(buffer)-pos < 12:
                break
            size = 12+buffer[pos+1]+(13 if buffer[pos+2] & 1 else 0)
        elif stx == 0xFE:
            if len(buffer)-pos < 8:
                break
            size = 8+buffer[pos+1]
        else:
            pos += 1
            continue
        if len(buffer)-pos < size:
            break
        frames.append(bytes(buffer[pos:pos+size]))
        pos += size
    return frames, buffer[pos:]


class DirectTelemetry:
    """Reads RN03's existing mavlink-router TCP server. It never writes to the
    socket, so the flight controller gains no GCS and no stream is requested."""
    def __init__(self, name, host, port):
        self.name, self.host, self.port = name, host, port
        self.state = VehicleState(name)
        self.sock = None
        self.lock = threading.Lock()
        self.error = ''
        self.last_observer = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def disconnect(self):
        with self.lock:
            if self.sock:
                self.sock.close()
                self.sock = None

    def snapshot(self):
        data = self.state.snapshot()
        data['observer_connected'] = time.monotonic()-self.last_observer < 12
        data['error'] = self.error
        return data

    def run(self):
        while not STOP.is_set():
            if not telemetry_active():
                self.disconnect()
                STOP.wait(.5)
                continue
            buffer = bytearray()
            try:
                sock = socket.create_connection((self.host, self.port), timeout=6)
                sock.settimeout(1)
                with self.lock:
                    self.sock = sock
                # A fresh token per connection drops values from the old session.
                self.state.reset_boot(f'tcp:{self.host}:{time.time():.0f}')
                self.error = ''
                while not STOP.is_set() and telemetry_active():
                    try:
                        raw = sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not raw:
                        raise EOFError('Telemetry connection closed')
                    buffer += raw
                    if len(buffer) > 8192:
                        del buffer[:-2048]
                    frames, buffer = split_frames(buffer)
                    buffer = bytearray(buffer)
                    for frame in frames:
                        self.state.consume(frame)
                    if frames:
                        self.last_observer = time.monotonic()
            except (EOFError, OSError, ValueError) as exc:
                self.error = getattr(exc, 'strerror', None) or str(exc)
            finally:
                self.disconnect()
            STOP.wait(3)


class Telemetry:
    """Receives bounded JSON via SSH; cannot write bytes to an aircraft socket."""
    def __init__(self, name, host, alias, port, user='ebach'):
        self.name, self.host, self.alias, self.port = name, host, alias, port
        # Companion Pis are not all owned by the same person. RN03's Pi has no
        # ebach account, so the login name travels with the source.
        self.user = user
        self.state = VehicleState(name)
        self.proc = None
        self.lock = threading.Lock()
        self.error = ''
        self.last_observer = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def disconnect(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()

    def snapshot(self):
        data = self.state.snapshot()
        data['observer_connected'] = time.monotonic()-self.last_observer < 12
        data['error'] = self.error
        return data

    def run(self):
        while not STOP.is_set():
            if not telemetry_active():
                STOP.wait(.5)
                continue
            errors = deque(maxlen=2)
            argv = ['ssh','-T','-i',str(KEY),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
                    '-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=6',
                    '-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2',
                    '-o','LogLevel=ERROR','-o','HostKeyAlias='+self.alias,self.user+'@'+self.host,
                    'python3 -c '+shlex.quote((HERE.parent/'companion'/'telemetry-session.py').read_text(encoding='utf-8-sig'))+' '+str(self.port)]
            reader = lease_thread = None
            lease_stop = threading.Event()
            try:
                with self.lock:
                    self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    proc = self.proc
                def keep_lease():
                    while not lease_stop.is_set() and not STOP.is_set():
                        try:
                            proc.stdin.write(b'view\n')
                            proc.stdin.flush()
                        except (OSError,ValueError):
                            return
                        lease_stop.wait(3)
                lease_thread = threading.Thread(target=keep_lease,daemon=True)
                lease_thread.start()
                def collect():
                    for line in iter(proc.stderr.readline,b''):
                        errors.append(line.decode(errors='replace').strip()[:200])
                reader = threading.Thread(target=collect,daemon=True)
                reader.start()
                while not STOP.is_set() and telemetry_active():
                    raw = proc.stdout.readline(2049)
                    if not raw:
                        raise EOFError('Telemetry connection closed')
                    if len(raw)>2048 or not raw.endswith(b'\n'):
                        raise ValueError('Invalid telemetry record')
                    record = json.loads(raw)
                    if 'boot_id' in record:
                        if record.get('source') != self.name or record.get('passive') is not True:
                            raise ValueError('Unexpected observer identity')
                        self.state.reset_boot(record['boot_id'])
                        self.last_observer = time.monotonic()
                        self.error = ''
                    if 'frame' in record:
                        if not isinstance(record['frame'],str) or len(record['frame'])>600:
                            raise ValueError('Oversize frame')
                        self.state.consume(bytes.fromhex(record['frame']))
                        self.last_observer = time.monotonic()
                        self.error = ''
                    if record.get('observer_waiting'):
                        self.error = 'Waiting for passive observer'
            except (EOFError,OSError,ValueError,TypeError) as exc:
                self.error = ' / '.join(errors) or str(exc)
            finally:
                lease_stop.set()
                if lease_thread:
                    lease_thread.join(1)
                self.disconnect()
                if self.proc:
                    try:
                        self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=3)
                    if reader:
                        reader.join(1)
                    self.proc.stdout.close()
                    self.proc.stderr.close()
                    self.proc.stdin.close()
                    self.proc = None
            STOP.wait(3)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        global last_viewer
        if (self.path not in ('/pause', '/shutdown') or self.headers.get('Host') not in ('127.0.0.1:8765', 'localhost:8765')
            or self.headers.get('Origin') not in ('http://127.0.0.1:8765', 'http://localhost:8765')
            or self.headers.get('Sec-Fetch-Site', 'same-origin') != 'same-origin'):
            self.send_error(403)
            return
        last_viewer = 0
        for feed in feeds:
            feed.disconnect()
        if self.path == '/shutdown':
            STOP.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        global last_viewer, last_telemetry_viewer
        # Reject DNS rebinding and foreign sites attempting to start LTE copies.
        if self.headers.get('Host') not in ('127.0.0.1:8765', 'localhost:8765'):
            self.send_error(403)
            return
        path = self.path.split('?', 1)[0]
        if path == '/status':
            origin = self.headers.get('Origin')
            site = self.headers.get('Sec-Fetch-Site', 'none')
            if site not in ('same-origin', 'none') or origin not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'):
                self.send_error(403)
                return
            if self.path == '/status?watch=1':
                last_viewer = time.monotonic()
            if self.path in ('/status?watch=1','/status?watch=0'):
                last_telemetry_viewer = time.monotonic()
            raw = json.dumps(dict(active=active(), media_running=media.poll() is None,
                                  feeds=[feed.snapshot() for feed in feeds],
                                  fleet=[source.snapshot() for source in telemetry]),
                                  allow_nan=False).encode()
            content_type = 'application/json'
        elif path in ('/', '/index.html','/fleet.js','/fleet.css','/fleet-map.js',
                      '/leaflet.js','/leaflet.css','/world.geojson','/us-states.geojson','/map-state.js',
                      '/alabama-map.js','/al-counties.geojson','/al-places.geojson','/al-roads.geojson'):
            name = 'index.html' if path == '/' else path.lstrip('/')
            raw = (HERE/'dist'/name).read_bytes()
            content_type = {'js':'application/javascript','css':'text/css',
                            'geojson':'application/geo+json'}.get(name.rsplit('.',1)[-1], 'text/html; charset=utf-8')
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src http://127.0.0.1:8889; connect-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)


def supervisor():
    while not STOP.wait(1):
        if not active():
            for feed in feeds:
                feed.disconnect()
        if not telemetry_active():
            for source in telemetry:
                source.disconnect()


def main():
    global feeds, media, telemetry
    exe = HERE/'runtime'/'mediamtx-v1.21.2'/'mediamtx.exe'
    if not exe.is_file() or not KEY.is_file():
        raise SystemExit('MediaMTX runtime or existing SSH key is missing. See README.')
    # Bind first: another dashboard cannot replace or disrupt the running one.
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    logger = logging.getLogger('media')
    logger.setLevel(logging.INFO)
    log = RotatingFileHandler(HERE/'runtime'/'media.log', maxBytes=1024*1024, backupCount=2)
    logger.addHandler(log)
    media = subprocess.Popen([str(exe), str(HERE/'mediamtx.yml')], cwd=HERE,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    def media_logs():
        for line in iter(media.stdout.readline, b''):
            logger.info(line.decode(errors='replace').rstrip())
    log_thread = threading.Thread(target=media_logs, daemon=True)
    log_thread.start()
    (HERE/'runtime'/'dashboard.pid').write_text(str(os.getpid()))
    feeds = [Feed('cruza', '100.100.0.58', '10.229.125.15', 15600, 18000),
             Feed('quadpi', '10.223.79.20', '10.223.79.20', 15601, 18002),
             UdpFeed('rn03', RN03_VIDEO_BIND, 18004)]
    for feed in feeds:
        feed.thread.start()
    telemetry = [Telemetry('cruza','100.100.0.58','10.229.125.15',15610),
                 Telemetry('quadpi','10.223.79.20','10.223.79.20',15611),
                 # RN03 reads mavlink-router's TCP server directly: no SSH, no key on
                 # the aircraft, nothing installed. The passive observer is now also
                 # running on that Pi, so the SSH path is available as an alternative:
                 #     Telemetry('rn03', RN03_PI, RN03_PI, 15611, user='jbrascom')
                 # It needs the dashboard key in jbrascom's authorized_keys and the
                 # host key under HostKeyAlias. Pick one; running both is pointless.
                 DirectTelemetry('rn03', RN03_PI, RN03_TELEMETRY_PORT)]
    for source in telemetry:
        source.thread.start()
    threading.Thread(target=supervisor, daemon=True).start()
    def stop(*_):
        STOP.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print('Local video dashboard: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever(poll_interval=.5)
    finally:
        STOP.set()
        for feed in feeds:
            feed.disconnect()
        for source in telemetry:
            source.disconnect()
        for feed in feeds:
            feed.thread.join(5)
        for source in telemetry:
            source.thread.join(5)
        media.terminate()
        try:
            media.wait(timeout=4)
        except subprocess.TimeoutExpired:
            media.kill()
        log_thread.join(2)
        media.stdout.close()
        log.close()
        (HERE/'runtime'/'dashboard.pid').unlink(missing_ok=True)
        server.server_close()


if __name__ == '__main__':
    main()
