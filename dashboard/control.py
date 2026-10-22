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
# Menu shown by the command workflow, in order. immediate = sent on one click
# from the always-visible row; the rest go through review and confirm.
ACTION_INFO = [
    dict(id='arm_takeoff', label='Arm & take off', point=False, altitude=True,
         text='Switches to GUIDED, arms and climbs straight up to the altitude. Props will spin.'),
    dict(id='goto', label='Fly to point & hold', point=True, altitude=True,
         text='Flies to the map point at the altitude (within 1 km) and holds there in GUIDED.'),
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
    def __init__(self, target, log_path, active, limits=None, stop=None):
        self.target = target
        self.active = active                      # callable: is a page open?
        self.stop = stop or threading.Event()
        self.log_path = Path(log_path)
        self.state = VehicleState('quadpi', limits=limits)
        self.encoder = mav.MAVLink(None, srcSystem=GCS[0], srcComponent=GCS[1])
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0))
        self.sock.settimeout(.5)
        self.lock = threading.Lock()              # one command sequence at a time
        self.cond = threading.Condition()
        self.acks = {}                            # command id -> (result, time)
        self.heartbeat = None                     # (message, time)
        self.position = None                      # (lat, lon, rel alt, time)
        self.landed = None                        # (MAV_LANDED_STATE, time)
        self.texts = []                           # recent (time, text)
        self.last_rx = 0.0
        self.busy = ''
        self.history = []
        self.error = ''
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.sender = threading.Thread(target=self.send_heartbeats, daemon=True)
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

    # ---- link ------------------------------------------------------------
    def send(self, message):
        self.sock.sendto(message.pack(self.encoder), self.target)

    def send_heartbeats(self):
        last_request = 0.0
        while not self.stop.wait(1):
            if self.active():
                try:
                    self.send(mav.MAVLink_heartbeat_message(
                        mav.MAV_TYPE_GCS, mav.MAV_AUTOPILOT_INVALID, 0, 0, 0, 3))
                    # Without QGC there may be no telemetry streams; ask for the
                    # same ones the bridge's startup profile uses, every 5 s
                    # until position arrives.
                    now = time.monotonic()
                    v = self.vehicle(now)
                    if v['online'] and (not v['position'] or v['in_air'] is None) and now-last_request >= 5:
                        last_request = now
                        for stream in STREAMS:
                            self.send(mav.MAVLink_request_data_stream_message(*QUAD, stream, 4, 1))
                        # Landed state is not in any stream; ask for it at 2 Hz.
                        self.send(mav.MAVLink_command_long_message(
                            *QUAD, mav.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                            mav.MAVLINK_MSG_ID_EXTENDED_SYS_STATE, 500000, 0, 0, 0, 0, 0))
                    self.error = ''
                except OSError as exc:
                    self.error = str(exc)

    def run(self):
        while not self.stop.is_set():
            try:
                datagram, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                # Windows reports an unreachable bridge on the next receive.
                self.error = str(exc)
                self.stop.wait(.5)
                continue
            self.state.consume(datagram)
            now = time.monotonic()
            try:
                messages = mav.MAVLink(None).parse_buffer(datagram) or []
            except Exception:
                continue
            for message in messages:
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
                elif kind == 'COMMAND_ACK' and message.target_system in (GCS[0], 0):
                    with self.cond:
                        self.acks[message.command] = (message.result, now)
                        self.cond.notify_all()

    # ---- current aircraft state -----------------------------------------
    def vehicle(self, now=None):
        now = time.monotonic() if now is None else now
        hb = self.heartbeat if self.heartbeat and now-self.heartbeat[1] <= FRESH else None
        pos = self.position if self.position and now-self.position[3] <= FRESH else None
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
        return dict(enabled=True, target='%s:%d' % self.target, link=self.vehicle(),
                    actions=ACTION_INFO,
                    busy=self.busy, history=self.history[-6:], error=self.error,
                    max_altitude_m=MAX_ALTITUDE_M, max_distance_m=MAX_GOTO_DISTANCE_M)

    # ---- commands --------------------------------------------------------
    def command(self, label, command_id, message):
        """Send once and wait for the matching COMMAND_ACK. Never retries."""
        with self.cond:
            self.acks.pop(command_id, None)
        sent = time.monotonic()
        self.send(message)
        deadline = sent+ACK_TIMEOUT
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
        if action not in ACTIONS:
            return self.record(dict(action=str(action)[:20]), False, 'Unknown action')
        if not self.lock.acquire(blocking=False):
            return self.record(dict(action=action), False, f'Busy: {self.busy}')
        try:
            self.busy = action
            entry = dict(action=action)
            try:
                steps = self.plan(action, body, entry)
                for step in steps:
                    step()
            except CommandError as exc:
                return self.record(entry, False, str(exc))
            except OSError as exc:
                return self.record(entry, False, f'Send failed: {exc}')
            return self.record(entry, True, 'Accepted by the aircraft')
        finally:
            self.busy = ''
            self.lock.release()

    def plan(self, action, body, entry):
        v = self.vehicle()
        if not v['online']:
            raise CommandError('No recent heartbeat from quadpi')
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
            lat = number(body, 'latitude', -90, 90)
            lon = number(body, 'longitude', -180, 180)
            alt = number(body, 'altitude_m', 1, MAX_ALTITUDE_M)
            entry.update(latitude=round(lat, 7), longitude=round(lon, 7), altitude_m=alt)
            if not v['armed'] or v['in_air'] is False:
                raise CommandError('Take off first; fly-to-point needs the quad in the air')
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
            return [lambda: self.command('Fly to point', mav.MAV_CMD_DO_REPOSITION, message)]
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

    def record(self, entry, ok, text):
        entry.update(ok=ok, result=text, time=time.strftime('%H:%M:%S'))
        self.history.append(entry)
        self.history = self.history[-20:]
        try:
            with self.log_path.open('a', encoding='utf-8') as log:
                log.write(json.dumps(dict(entry, logged=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                                          target='%s:%d' % self.target))+'\n')
        except OSError:
            pass
        return entry
