"""quadpi click-to-fly control over the Pi's filtered MAVLink bridge.

Disabled unless DASHBOARD_QUAD_CONTROL=host:port names the bridge's UDP listen
port (10.223.79.20:14551 on quadpi; a local bridge for SITL). The bridge only
passes the exact command shapes sent here, and the Pocket stays the safety
pilot's override. Every command is logged to runtime/quad-commands.log.

While a dashboard page is open this link sends a 1 Hz GCS heartbeat (which also
keeps the bridge copying FC traffic here). Closing every page stops it, so with
FS_GCS_ENABLE set the aircraft fails safe if no other GCS is connected.
"""
import json
import math
from pathlib import Path
import socket
import subprocess
import threading
import time

from fleet import VehicleState, mav

QUAD = (1, 1)
GCS = (255, 190)
GUIDED, LOITER, RTL, LAND, BRAKE = 4, 5, 6, 9, 17
MODE_NAMES = {0: 'STABILIZE', 1: 'ACRO', 2: 'ALT_HOLD', 3: 'AUTO', 4: 'GUIDED',
              5: 'LOITER', 6: 'RTL', 7: 'CIRCLE', 9: 'LAND', 16: 'POSHOLD', 17: 'BRAKE',
              20: 'GUIDED_NOGPS', 21: 'SMART_RTL'}
MAX_ALTITUDE_M = 120.0          # same limit as the Pi bridge
MAX_GOTO_DISTANCE_M = 1000.0    # from the quad's current position
ACK_TIMEOUT = 3.0
FRESH = 3.0                     # seconds a heartbeat/position stays usable
STREAMS = (2, 3, 6, 10, 11, 12)  # EXTENDED_STATUS, RC, POSITION, EXTRA1-3
ARM_ONLY_MODES = {0, 2, 5, 16}   # STABILIZE, ALT_HOLD, LOITER, POSHOLD
CIRCLE = 7
# The circle is the FC's own: radius, rate (sign = direction) and options are
# read, never written. RCMAP_THROTTLE says which RC channel is throttle.
CIRCLE_PARAMS = ('CIRCLE_RADIUS_M', 'CIRCLE_RADIUS', 'CIRCLE_RATE', 'CIRCLE_OPTIONS', 'RCMAP_THROTTLE')
CIRCLE_START_AT_CENTRE = 4      # CIRCLE_OPTIONS bit: circle around where it enters
THROTTLE_CENTRE = (1400, 1600)  # PWM band treated as "Pocket throttle centred"
ARRIVE_M = 3.0                  # switch to CIRCLE this close to the chosen point
CIRCLE_WAIT_S = 300             # give up flying to the circle point after this
# Menu shown by the command workflow, in order. immediate = sent on one click
# from the always-visible row; the rest go through review and confirm.
ACTION_INFO = [
    dict(id='arm', label='Arm motors (current mode)', point=False, altitude=False,
         text='Arms in the mode the Pocket’s switch has selected; no mode change, no takeoff. '
              'Motors spin at idle and the aircraft disarms itself after DISARM_DELAY on the ground.'),
    dict(id='arm_takeoff', label='Arm & take off', point=False, altitude=True,
         text='Switches to GUIDED, arms and climbs straight up to the altitude. Props will spin.'),
    dict(id='goto', label='Fly to point & hold', point=True, altitude=True,
         text='Flies to the map point at the altitude (within 1 km) and holds there in GUIDED.'),
    dict(id='loiter', label='Loiter (circle)', point='optional', altitude='with-point',
         text='Circles using the aircraft’s own CIRCLE radius and direction: around the map point '
              'if you pick one (flies there first at the altitude), otherwise around where it is now. '
              'CIRCLE mode takes climb/descent from the Pocket throttle, so keep it centred.'),
    dict(id='hold', label='Hold position (BRAKE)', point=False, altitude=False, immediate=True,
         text='Stops and holds where it is. Ignores the Pocket sticks.'),
    dict(id='rtl', label='Return to launch (RTL)', point=False, altitude=False, immediate=True,
         text='Flies home using the aircraft’s RTL settings and lands.'),
    dict(id='land', label='Land here', point=False, altitude=False, immediate=True,
         text='Descends and lands where it is, then disarms.'),
    dict(id='disarm', label='Disarm (on the ground)', point=False, altitude=False,
         text='Stops the motors. The aircraft refuses this in the air.'),
]
ACTIONS = tuple(a['id'] for a in ACTION_INFO)


class CommandError(Exception):
    pass


def parse_target(text):
    host, port = text.rsplit(':', 1)
    return host, int(port)


def distance_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2-p1)/2)**2
         + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2)
    return 2*r*math.asin(math.sqrt(a))


def number(body, key, low, high):
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CommandError(f'{key} must be a number')
    if not low <= value <= high:
        raise CommandError(f'{key} must be between {low:g} and {high:g}')
    return float(value)


class QuadControl:
    """One UDP link to the bridge: sends commands, receives the FC stream."""
    def __init__(self, target, log_path, active, limits=None, stop=None,
                 gcs=GCS, actions=ACTION_INFO):
        self.target = target
        self.label = '%s:%d' % target
        self.gcs = gcs
        self.actions = actions
        self.action_ids = tuple(a['id'] for a in actions)
        self.ack_timeout = ACK_TIMEOUT
        self.fresh = FRESH
        self.active = active                      # callable: is a page open?
        self.stop = stop or threading.Event()
        self.log_path = Path(log_path)
        self.state = VehicleState('quadpi', limits=limits)
        self.encoder = mav.MAVLink(None, srcSystem=gcs[0], srcComponent=gcs[1])
        self.parser = mav.MAVLink(None)
        self.parser.robust_parsing = True
        self.open_link()
        self.lock = threading.Lock()              # one command sequence at a time
        self.cond = threading.Condition()
        self.acks = {}                            # command id -> (result, time)
        self.heartbeat = None                     # (message, time)
        self.position = None                      # (lat, lon, rel alt, time)
        self.landed = None                        # (MAV_LANDED_STATE, time)
        self.texts = []                           # recent (time, text)
        self.params = {}                          # circle-related FC parameters
        self.rc = None                            # (RC_CHANNELS, time)
        self.pending_circle = None                # point to circle on arrival
        self.last_rx = 0.0
        self.busy = ''
        self.history = []
        self.error = ''
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.sender = threading.Thread(target=self.send_heartbeats, daemon=True)
        self.watcher = threading.Thread(target=self.watch_circle, daemon=True)
        self.state.reset_boot(f'control:{target[0]}:{time.time():.0f}')

    # ---- telemetry-source interface used by server.py -------------------
    def disconnect(self):
        pass

    def snapshot(self):
        data = self.state.snapshot()
        data['observer_connected'] = time.monotonic()-self.last_rx < 12
        data['error'] = self.error
        return data

    def start(self):
        self.thread.start()
        self.sender.start()
        self.watcher.start()

    # ---- link ------------------------------------------------------------
    def open_link(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0))
        self.sock.settimeout(.5)

    def send(self, message):
        self.sock.sendto(message.pack(self.encoder), self.target)

    def receive(self):
        """Next chunk of FC bytes, or None after a quiet half second."""
        try:
            return self.sock.recvfrom(65535)[0]
        except socket.timeout:
            return None

    def request_telemetry(self):
        # Without QGC there may be no telemetry streams; ask for the same ones
        # the bridge's startup profile uses.
        for stream in STREAMS:
            self.send(mav.MAVLink_request_data_stream_message(*QUAD, stream, 4, 1))
        # Landed state is not in any stream; ask for it at 2 Hz.
        self.send(self.long(mav.MAV_CMD_SET_MESSAGE_INTERVAL,
                            mav.MAVLINK_MSG_ID_EXTENDED_SYS_STATE, 500000))

    def request_params(self):
        # PARAM_REQUEST_READ is read-only and already allowed by the bridge.
        for name in CIRCLE_PARAMS:
            self.send(mav.MAVLink_param_request_read_message(*QUAD, name.encode(), -1))

    def circle_known(self):
        return ('CIRCLE_RADIUS_M' in self.params or 'CIRCLE_RADIUS' in self.params) \
            and 'CIRCLE_RATE' in self.params and 'CIRCLE_OPTIONS' in self.params

    def throttle_pwm(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.rc or now-self.rc[1] > self.fresh:
            return None
        channel = int(self.params.get('RCMAP_THROTTLE', 3))
        return getattr(self.rc[0], f'chan{channel}_raw', None)

    def circle_info(self):
        p = self.params
        radius = p['CIRCLE_RADIUS_M'] if 'CIRCLE_RADIUS_M' in p else \
            p['CIRCLE_RADIUS']/100 if 'CIRCLE_RADIUS' in p else None
        rate = p.get('CIRCLE_RATE')
        options = int(p['CIRCLE_OPTIONS']) if 'CIRCLE_OPTIONS' in p else None
        pending = self.pending_circle
        return dict(known=self.circle_known(), radius_m=radius, rate_deg_s=rate,
                    direction=None if rate is None else 'clockwise' if rate >= 0 else 'counter-clockwise',
                    centred=None if options is None else bool(options & CIRCLE_START_AT_CENTRE),
                    throttle_pwm=self.throttle_pwm(), throttle_centre=list(THROTTLE_CENTRE),
                    pending=dict(latitude=pending['lat'], longitude=pending['lon'],
                                 altitude_m=pending['alt']) if pending else None)

    def watch_circle(self):
        """Switch to CIRCLE once the quad reaches a chosen loiter point."""
        while not self.stop.wait(.5):
            p = self.pending_circle
            if not p:
                continue
            v = self.vehicle()
            if time.monotonic() > p['deadline'] or not v['armed'] or v['mode_id'] != GUIDED:
                # Timed out, landed, or someone (Pocket, QGC, RTL) changed mode.
                self.pending_circle = None
                self.record(dict(action='loiter'), False, 'Circle cancelled before arrival')
                continue
            pos = v['position']
            if not pos or distance_m(pos['latitude'], pos['longitude'], p['lat'], p['lon']) > ARRIVE_M \
                    or abs(pos['altitude_relative_m']-p['alt']) > 2:
                continue
            if not self.lock.acquire(blocking=False):
                continue                          # a user command is running; try again
            try:
                if self.pending_circle is not p:
                    continue
                self.pending_circle = None
                self.busy = 'loiter'
                try:
                    self.set_mode(CIRCLE)
                    self.record(dict(action='loiter'), True, 'Arrived; circling')
                except (CommandError, OSError) as exc:
                    self.record(dict(action='loiter'), False, f'Arrived but {exc}')
            finally:
                self.busy = ''
                self.lock.release()

    def send_heartbeats(self):
        last_request = last_params = 0.0
        while not self.stop.wait(1):
            if self.active():
                try:
                    self.send(mav.MAVLink_heartbeat_message(
                        mav.MAV_TYPE_GCS, mav.MAV_AUTOPILOT_INVALID, 0, 0, 0, 3))
                    # Every 5 s until position, landed state and RC arrive.
                    now = time.monotonic()
                    v = self.vehicle(now)
                    # RC is only needed for Loiter's throttle check.
                    rc_stale = 'loiter' in self.action_ids and (not self.rc or now-self.rc[1] > self.fresh)
                    if v['online'] and (not v['position'] or v['in_air'] is None or rc_stale) \
                            and now-last_request >= 5:
                        last_request = now
                        self.request_telemetry()
                    if v['online'] and now-last_params >= (60 if self.circle_known() else 5):
                        last_params = now
                        self.request_params()
                    self.error = ''
                except OSError as exc:
                    self.error = str(exc)

    def run(self):
        while not self.stop.is_set():
            try:
                chunk = self.receive()
            except OSError as exc:
                # Windows reports an unreachable bridge on the next receive.
                self.error = str(exc)
                self.stop.wait(.5)
                continue
            if not chunk:
                continue
            now = time.monotonic()
            try:
                messages = self.parser.parse_buffer(chunk) or []
            except Exception:
                continue
            for message in messages:
                self.state.consume(message.get_msgbuf())
                if (message.get_srcSystem(), message.get_srcComponent()) != QUAD:
                    continue
                self.last_rx = now
                kind = message.get_type()
                if kind == 'HEARTBEAT' and message.type != mav.MAV_TYPE_GCS:
                    self.heartbeat = (message, now)
                elif kind == 'GLOBAL_POSITION_INT':
                    self.position = (message.lat/1e7, message.lon/1e7,
                                     message.relative_alt/1000, now)
                elif kind == 'EXTENDED_SYS_STATE':
                    self.landed = (message.landed_state, now)
                elif kind == 'STATUSTEXT':
                    self.texts = (self.texts+[(now, message.text)])[-8:]
                elif kind == 'PARAM_VALUE' and message.param_id in CIRCLE_PARAMS:
                    self.params[message.param_id] = message.param_value
                elif kind == 'RC_CHANNELS':
                    self.rc = (message, now)
                elif kind == 'COMMAND_ACK' and message.target_system in (self.gcs[0], 0):
                    with self.cond:
                        self.acks[message.command] = (message.result, now)
                        self.cond.notify_all()

    # ---- current aircraft state -----------------------------------------
    def vehicle(self, now=None):
        now = time.monotonic() if now is None else now
        hb = self.heartbeat if self.heartbeat and now-self.heartbeat[1] <= self.fresh else None
        pos = self.position if self.position and now-self.position[3] <= self.fresh else None
        landed = self.landed[0] if self.landed and now-self.landed[1] <= 5 else None
        return dict(
            online=hb is not None,
            armed=bool(hb and hb[0].base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED),
            mode=MODE_NAMES.get(hb[0].custom_mode, str(hb[0].custom_mode)) if hb else None,
            mode_id=hb[0].custom_mode if hb else None,
            position=dict(latitude=pos[0], longitude=pos[1], altitude_relative_m=pos[2]) if pos else None,
            in_air=None if landed in (None, mav.MAV_LANDED_STATE_UNDEFINED)
                   else landed != mav.MAV_LANDED_STATE_ON_GROUND)

    def status(self):
        return dict(enabled=True, target=self.label, link=self.vehicle(),
                    actions=self.actions, circle=self.circle_info(),
                    busy=self.busy, history=self.history[-6:], error=self.error,
                    max_altitude_m=MAX_ALTITUDE_M, max_distance_m=MAX_GOTO_DISTANCE_M)

    # ---- commands --------------------------------------------------------
    def command(self, label, command_id, message):
        """Send once and wait for the matching COMMAND_ACK. Never retries."""
        with self.cond:
            self.acks.pop(command_id, None)
        sent = time.monotonic()
        self.send(message)
        deadline = sent+self.ack_timeout
        with self.cond:
            while True:
                ack = self.acks.get(command_id)
                # IN_PROGRESS is not final; keep waiting for the real answer.
                if ack and ack[1] >= sent and ack[0] != mav.MAV_RESULT_IN_PROGRESS:
                    break
                left = deadline-time.monotonic()
                if left <= 0:
                    raise CommandError(f'{label}: no reply from the aircraft')
                self.cond.wait(left)
        if ack[0] != mav.MAV_RESULT_ACCEPTED:
            name = mav.enums['MAV_RESULT'][ack[0]].name.replace('MAV_RESULT_', '') \
                if ack[0] in mav.enums['MAV_RESULT'] else str(ack[0])
            # The FC's reason (STATUSTEXT) can arrive just after the refusal.
            until = time.monotonic()+.6
            while time.monotonic() < until and not any(at >= sent-1 for at, _ in self.texts):
                self.stop.wait(.05)
            texts = [t for at, t in self.texts if at >= sent-1]
            raise CommandError(f'{label} refused ({name})' + (': '+'; '.join(texts) if texts else ''))

    def long(self, command_id, *params):
        params = (list(params)+[0.0]*7)[:7]
        return mav.MAVLink_command_long_message(*QUAD, command_id, 0, *params)

    def set_mode(self, mode):
        self.command(f'Mode {MODE_NAMES[mode]}', mav.MAV_CMD_DO_SET_MODE,
                     self.long(mav.MAV_CMD_DO_SET_MODE, mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode))

    def arm(self, value):
        self.command('Arm' if value else 'Disarm', mav.MAV_CMD_COMPONENT_ARM_DISARM,
                     self.long(mav.MAV_CMD_COMPONENT_ARM_DISARM, 1.0 if value else 0.0))

    def execute(self, body):
        """Run one dashboard action; returns a result dict for the browser."""
        action = body.get('action') if isinstance(body, dict) else None
        if action not in self.action_ids:
            return self.record(dict(action=str(action)[:20]), False, 'Not available on this link')
        if not self.lock.acquire(blocking=False):
            return self.record(dict(action=action), False, f'Busy: {self.busy}')
        try:
            self.busy = action
            entry = dict(action=action)
            # Any new command, including another Loiter, replaces a circle
            # still waiting for the quad to reach its point.
            if self.pending_circle:
                self.pending_circle = None
                entry['cancelled_pending_circle'] = True
            try:
                steps = self.plan(action, body, entry)
                for step in steps:
                    step()
            except CommandError as exc:
                return self.record(entry, False, str(exc))
            except OSError as exc:
                return self.record(entry, False, f'Send failed: {exc}')
            return self.record(entry, True, entry.pop('ok_text', 'Accepted by the aircraft'))
        finally:
            self.busy = ''
            self.lock.release()

    def plan(self, action, body, entry):
        v = self.vehicle()
        if not v['online']:
            raise CommandError('No recent heartbeat from quadpi')
        if action == 'arm':
            if v['armed']:
                raise CommandError('Already armed')
            # Arming in AUTO can start the mission; GUIDED/RTL/LAND are not
            # bench modes either. Only pilot modes the Pocket's sticks control.
            if v['mode_id'] not in ARM_ONLY_MODES:
                raise CommandError(f'Mode is {v["mode"]}; set the Pocket switch to STABILIZE '
                                   '(or ALT_HOLD/LOITER/POSHOLD) before arming')
            entry['mode'] = v['mode']
            return [lambda: self.arm(True)]
        if action == 'arm_takeoff':
            alt = number(body, 'altitude_m', 1, MAX_ALTITUDE_M)
            entry['altitude_m'] = alt
            if v['armed']:
                raise CommandError('Already armed; use Fly to point or Hold')
            if not v['position']:
                raise CommandError('No position fix; GUIDED takeoff needs GPS')
            steps = [] if v['mode_id'] == GUIDED else [lambda: self.set_mode(GUIDED)]
            return steps+[lambda: self.arm(True),
                          lambda: self.command('Takeoff', mav.MAV_CMD_NAV_TAKEOFF,
                                               self.long(mav.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, alt))]
        if action == 'goto':
            lat, lon, alt, message = self.reposition(body, v, entry)
            return [lambda: self.command('Fly to point', mav.MAV_CMD_DO_REPOSITION, message)]
        if action == 'loiter':
            if not v['armed'] or v['in_air'] is False:
                raise CommandError('Take off first; Loiter needs the quad in the air')
            if not self.circle_known():
                raise CommandError('Circle settings not read from the aircraft yet; try again shortly')
            pwm = self.throttle_pwm()
            if pwm is None:
                raise CommandError('No Pocket throttle reading; CIRCLE needs the throttle centred')
            if not THROTTLE_CENTRE[0] <= pwm <= THROTTLE_CENTRE[1]:
                raise CommandError(f'Pocket throttle is {pwm} µs; centre it ({THROTTLE_CENTRE[0]}–'
                                   f'{THROTTLE_CENTRE[1]}) first or CIRCLE will climb or sink')
            c = self.circle_info()
            entry.update(radius_m=c['radius_m'], direction=c['direction'])
            if body.get('latitude') is None and body.get('longitude') is None:
                entry['centre'] = 'current position'
                return [lambda: self.set_mode(CIRCLE)]
            lat, lon, alt, message = self.reposition(body, v, entry)

            def arm_watch():
                self.pending_circle = dict(lat=lat, lon=lon, alt=alt,
                                           deadline=time.monotonic()+CIRCLE_WAIT_S)
                entry['ok_text'] = 'Flying to the point; will circle on arrival'
            return [lambda: self.command('Fly to circle point', mav.MAV_CMD_DO_REPOSITION, message),
                    arm_watch]
        if action == 'hold':
            # BRAKE holds position without reading the Pocket's sticks.
            return [lambda: self.set_mode(BRAKE)]
        if action == 'rtl':
            return [lambda: self.set_mode(RTL)]
        if action == 'land':
            return [lambda: self.set_mode(LAND)]
        if action == 'disarm':
            if v['armed'] and v['in_air']:
                raise CommandError('Refusing to disarm in the air; use Land')
            return [lambda: self.arm(False)]
        raise CommandError('Unknown action')

    def reposition(self, body, v, entry):
        """Validated DO_REPOSITION to a map point (fly-to-point and Loiter)."""
        lat = number(body, 'latitude', -90, 90)
        lon = number(body, 'longitude', -180, 180)
        alt = number(body, 'altitude_m', 1, MAX_ALTITUDE_M)
        entry.update(latitude=round(lat, 7), longitude=round(lon, 7), altitude_m=alt)
        if not v['armed'] or v['in_air'] is False:
            raise CommandError('Take off first; flying to a point needs the quad in the air')
        if not v['position']:
            raise CommandError('No current position')
        d = distance_m(v['position']['latitude'], v['position']['longitude'], lat, lon)
        entry['distance_m'] = round(d)
        if d > MAX_GOTO_DISTANCE_M:
            raise CommandError(f'Point is {d:.0f} m away; limit is {MAX_GOTO_DISTANCE_M:.0f} m')
        message = mav.MAVLink_command_int_message(
            *QUAD, mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, mav.MAV_CMD_DO_REPOSITION, 0, 0,
            -1.0, mav.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE, 0.0, float('nan'),
            int(round(lat*1e7)), int(round(lon*1e7)), alt)
        return lat, lon, alt, message

    def record(self, entry, ok, text):
        entry.update(ok=ok, result=text, time=time.strftime('%H:%M:%S'))
        self.history.append(entry)
        self.history = self.history[-20:]
        try:
            with self.log_path.open('a', encoding='utf-8') as log:
                log.write(json.dumps(dict(entry, logged=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                                          target=self.label))+'\n')
        except OSError:
            pass
        return entry


# The bench port of the bridge installed on quadpi (/opt/quadpi-dashboard-bench)
# accepts, from GCS 254/190 only: on-ground arm/disarm, GUIDED/STABILIZE while
# disarmed, a few telemetry requests at 2 Hz and four failsafe parameters. The
# dashboard offers only arm and disarm through it.
BENCH_GCS = (254, 190)
BENCH_REMOTE_PORT = 15760
BENCH_ACTIONS = [a for a in ACTION_INFO if a['id'] in ('arm', 'disarm')]
# Message ids the bench port lets us request (2 Hz): SYS_STATUS, GPS_RAW_INT,
# GLOBAL_POSITION_INT, EXTENDED_SYS_STATE.
BENCH_TELEMETRY = (1, 24, 33, 245)


def parse_bench(text):
    """'127.0.0.1:15760' connects directly (SITL); a bare host is reached
    through an SSH tunnel to its loopback bench port."""
    if ':' in text:
        host, port = parse_target(text)
        return None, port if host in ('127.0.0.1', 'localhost') else None
    return text, None


class BenchControl(QuadControl):
    """quadpi via the installed bridge's TCP bench port, optionally through SSH."""
    def __init__(self, spec, log_path, active, key=None, limits=None, stop=None,
                 local_port=18760):
        self.tunnel_host, direct = parse_bench(spec)
        if self.tunnel_host is None and direct is None:
            raise ValueError('bench target must be 127.0.0.1:port or a host name')
        self.key = key
        self.local_port = direct or local_port
        self.tunnel = None
        self.tunnel_started = 0.0
        self.conn = None
        self.send_lock = threading.Lock()
        super().__init__(('127.0.0.1', self.local_port), log_path, active, limits, stop,
                         gcs=BENCH_GCS, actions=BENCH_ACTIONS)
        self.label = (f'bench port {BENCH_REMOTE_PORT} on {self.tunnel_host} (SSH)'
                      if self.tunnel_host else f'bench port {self.label}')
        # A relayed VPN link can take seconds each way; wait longer for replies.
        self.ack_timeout = 10.0 if self.tunnel_host else ACK_TIMEOUT
        # Relayed heartbeats can arrive several seconds apart. The bridge on
        # the Pi still checks "on the ground" with its own fresh data.
        self.fresh = 8.0 if self.tunnel_host else FRESH

    def open_link(self):
        pass                                     # connected lazily in receive()

    def close_conn(self):
        with self.send_lock:
            if self.conn:
                self.conn.close()
                self.conn = None

    def disconnect(self):
        self.close_conn()
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.terminate()
        self.tunnel = None

    def connect(self):
        # The bench port serves one client, so never probe it: the first
        # connection that succeeds is the one we keep. A dropped connection is
        # retried through the same tunnel; only a dead tunnel is restarted.
        if self.tunnel_host and (self.tunnel is None or self.tunnel.poll() is not None):
            argv = ['ssh', '-N', '-T', '-i', str(self.key), '-o', 'IdentitiesOnly=yes',
                    '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                    '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=30',
                    '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3',
                    '-o', 'HostKeyAlias=10.223.79.20',
                    '-L', f'127.0.0.1:{self.local_port}:127.0.0.1:{BENCH_REMOTE_PORT}',
                    'ebach@'+self.tunnel_host]
            self.tunnel = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.tunnel_started = time.monotonic()
        try:
            conn = socket.create_connection(self.target, timeout=4)
        except OSError:
            # Tailscale may relay through DERP (~2 s each way, ~25 s to log in).
            if self.tunnel and self.tunnel.poll() is None and time.monotonic()-self.tunnel_started < 60:
                raise OSError('waiting for the SSH tunnel')
            raise
        conn.settimeout(.5)
        with self.send_lock:
            self.conn = conn
        self.parser = mav.MAVLink(None)
        self.parser.robust_parsing = True
        self.error = ''

    def send(self, message):
        with self.send_lock:
            if not self.conn:
                raise OSError('bench port not connected')
            self.conn.sendall(message.pack(self.encoder))

    def receive(self):
        if self.conn is None:
            try:
                self.connect()
            except OSError as exc:
                self.error = f'bench port: {exc}'
                if str(exc) != 'waiting for the SSH tunnel':
                    self.disconnect()            # tunnel gave up: start a new one
                self.stop.wait(3)
                return None
        try:
            chunk = self.conn.recv(8192)
        except socket.timeout:
            return None
        except OSError as exc:
            self.error = f'bench port: {exc}'
            self.close_conn()
            return None
        if not chunk:
            # Remote bench port busy or not listening; retry the same tunnel.
            self.error = 'bench port closed the connection'
            self.close_conn()
            self.stop.wait(3)
            return None
        return chunk

    def request_telemetry(self):
        # The bench port drops REQUEST_DATA_STREAM; it allows these exact
        # SET_MESSAGE_INTERVAL shapes (2 Hz, other params zero).
        for msg_id in BENCH_TELEMETRY:
            self.send(self.long(mav.MAV_CMD_SET_MESSAGE_INTERVAL, msg_id, 500000))
