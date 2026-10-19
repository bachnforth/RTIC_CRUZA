"""CRC-checked, source-isolated telemetry state. Contains no MAVLink sender.

Besides the latest values, each aircraft keeps a short in-memory history for the
dashboard graphs, an event log (arm/disarm, mode changes and the aircraft's own
text messages) and a list of active alerts. Nothing is written to disk.
"""
from collections import deque
import math
from pathlib import Path
import sys
import threading
import time

# Reuse the project's already-installed flight-log dependency bundle.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'.flightlog-deps'))
from pymavlink.dialects.v20 import ardupilotmega as mav
from pymavlink import mavutil

ALLOWED = {'HEARTBEAT', 'SYS_STATUS', 'GPS_RAW_INT', 'ATTITUDE',
           'GLOBAL_POSITION_INT', 'MISSION_CURRENT', 'MISSION_ITEM_REACHED',
           'VFR_HUD', 'BATTERY_STATUS', 'EXTENDED_SYS_STATE',
           'STATUSTEXT', 'HOME_POSITION'}

HISTORY_SECONDS = 300
EVENT_LIMIT = 30
# ArduPilot text severities: 0-3 emergency..error, 4 warning, 5 notice, 6 info.
SEVERITY = ['EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG']
TEXT_ALERT_SECONDS = {'critical': 60, 'warning': 30}

# Sensor health bits worth naming. Bits not listed here are ignored.
SENSORS = {
    mav.MAV_SYS_STATUS_SENSOR_3D_GYRO: 'Gyro',
    mav.MAV_SYS_STATUS_SENSOR_3D_ACCEL: 'Accelerometer',
    mav.MAV_SYS_STATUS_SENSOR_3D_MAG: 'Compass',
    mav.MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE: 'Barometer',
    mav.MAV_SYS_STATUS_SENSOR_DIFFERENTIAL_PRESSURE: 'Airspeed sensor',
    mav.MAV_SYS_STATUS_SENSOR_GPS: 'GPS',
    mav.MAV_SYS_STATUS_SENSOR_RC_RECEIVER: 'RC receiver',
    mav.MAV_SYS_STATUS_AHRS: 'Attitude estimate (AHRS/EKF)',
    mav.MAV_SYS_STATUS_LOGGING: 'Onboard logging',
    mav.MAV_SYS_STATUS_SENSOR_BATTERY: 'Battery',
    mav.MAV_SYS_STATUS_GEOFENCE: 'Geofence',
}
LANDED = {1: 'On ground', 2: 'In air', 3: 'Taking off', 4: 'Landing'}


def number(value, scale=1):
    return value/scale if isinstance(value, (int, float)) and math.isfinite(value) else None


def distance_bearing(lat1, lon1, lat2, lon2):
    """Great-circle distance (m) and initial bearing (deg) from point 1 to 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2-p1, math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    distance = 2*6371000*math.asin(min(1, math.sqrt(a)))
    y = math.sin(dlon)*math.cos(p2)
    x = math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dlon)
    return distance, (math.degrees(math.atan2(y, x))+360) % 360


class Limits:
    """Alert thresholds for one aircraft. None disables that check."""
    def __init__(self, battery_low_v=None, battery_critical_v=None,
                 airspeed_min_m_s=None, min_satellites=6, sustain_s=5):
        self.battery_low_v = battery_low_v
        self.battery_critical_v = battery_critical_v
        self.airspeed_min_m_s = airspeed_min_m_s
        self.min_satellites = min_satellites
        self.sustain_s = sustain_s


class VehicleState:
    def __init__(self, name, expected_system=1, expected_component=1, limits=None):
        self.name = name
        self.expected = (expected_system, expected_component)
        self.limits = limits or Limits()
        self.lock = threading.Lock()
        self.values = {}
        self.track = []
        self.boot_id = None
        self.invalid = self.accepted = 0
        self._clear_derived()

    def _clear_derived(self):
        self.history = deque()
        self.events = deque(maxlen=EVENT_LIMIT)
        self.text_alerts = []
        self.text_parts = {}
        self.last_armed = None
        self.last_mode = None
        self.launch = None
        self.link_lost = False

    def reset_boot(self, boot):
        with self.lock:
            if boot != self.boot_id:
                self.values.clear()
                self.track.clear()
                self._clear_derived()
                self.boot_id = boot

    def _event(self, now, level, text):
        # ArduPilot repeats some messages (e.g. pre-arm failures every 30 s);
        # an identical repeat updates the newest entry instead of adding one.
        if self.events and self.events[-1][1:3] == (level, text):
            count = self.events[-1][3]+1
            self.events[-1] = (now, level, text, count)
        else:
            self.events.append((now, level, text, 1))

    def _text(self, message, now):
        text = message.text if isinstance(message.text, str) else message.text.decode(errors='replace')
        text = text.split('\0', 1)[0]
        if message.id:
            # Long messages arrive in 50-character chunks sharing one id.
            parts = self.text_parts.setdefault(message.id, {})
            parts[message.chunk_seq] = text
            if len(text) == 50:
                return
            text = ''.join(parts[k] for k in sorted(parts))
            del self.text_parts[message.id]
        text = text.strip()[:200]
        if not text:
            return
        severity = message.severity if 0 <= message.severity <= 7 else 6
        level = 'critical' if severity <= 3 else 'warning' if severity == 4 else 'info'
        self._event(now, level, text)
        if level != 'info':
            self.text_alerts.append((now, level, text))
            self.text_alerts = self.text_alerts[-10:]

    def _heartbeat(self, message, now):
        armed = bool(message.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED)
        mode = mavutil.mode_string_v10(message)
        if self.last_armed is not None and armed != self.last_armed:
            self._event(now, 'notice', 'ARMED' if armed else 'Disarmed')
            if armed:
                self.launch = None
        if self.last_mode is not None and mode != self.last_mode:
            self._event(now, 'notice', f'Mode {self.last_mode} → {mode}')
        self.last_armed, self.last_mode = armed, mode

    def _sample(self, now):
        """Record one graph point per second from the freshest values."""
        if self.history and now-self.history[-1]['t'] < 1:
            return
        def fresh(kind, ttl=3):
            entry = self.values.get(kind)
            return entry[0] if entry and now-entry[1] <= ttl else None
        hud, pos = fresh('VFR_HUD'), fresh('GLOBAL_POSITION_INT')
        volts = self._voltage(fresh('BATTERY_STATUS', 10), fresh('SYS_STATUS', 10))[1]
        self.history.append(dict(t=now,
            altitude=number(pos.relative_alt, 1000) if pos else None,
            airspeed=number(hud.airspeed) if hud else None,
            groundspeed=number(hud.groundspeed) if hud else None,
            voltage=volts))
        while self.history and now-self.history[0]['t'] > HISTORY_SECONDS:
            self.history.popleft()

    @staticmethod
    def _voltage(battery, sys_status):
        if battery and battery.id == 0:
            pct = battery.battery_remaining if 0 <= battery.battery_remaining <= 100 else None
            cells = [v for v in battery.voltages if v not in (0, 65535)]
            return pct, (sum(cells)/1000 if cells else None)
        if sys_status:
            pct = sys_status.battery_remaining if 0 <= sys_status.battery_remaining <= 100 else None
            return pct, (sys_status.voltage_battery/1000 if sys_status.voltage_battery != 65535 else None)
        return None, None

    def consume(self, raw, now=None):
        now = time.monotonic() if now is None else now
        try:
            # A new parser per bounded frame prevents cross-source/partial reuse.
            parser = mav.MAVLink(None)
            messages = parser.parse_buffer(raw) or []
        except Exception:
            self.invalid += 1
            return
        with self.lock:
            for message in messages:
                kind = message.get_type()
                if kind not in ALLOWED or (message.get_srcSystem(), message.get_srcComponent()) != self.expected:
                    self.invalid += 1
                    continue
                if kind == 'HEARTBEAT' and (message.autopilot == mav.MAV_AUTOPILOT_INVALID or message.type == mav.MAV_TYPE_GCS):
                    self.invalid += 1
                    continue
                self.values[kind] = (message, now)
                self.accepted += 1
                if kind == 'HEARTBEAT':
                    self._heartbeat(message, now)
                elif kind == 'STATUSTEXT':
                    self._text(message, now)
                elif kind in ('VFR_HUD', 'GLOBAL_POSITION_INT', 'SYS_STATUS', 'BATTERY_STATUS'):
                    self._sample(now)
                if kind == 'GLOBAL_POSITION_INT':
                    gps = self.values.get('GPS_RAW_INT')
                    if gps and now-gps[1] <= 10 and gps[0].fix_type >= 3:
                        lat, lon = message.lat/1e7, message.lon/1e7
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            if self.last_armed and self.launch is None:
                                self.launch = (lat, lon)
                            if not self.track or now-self.track[-1][2] >= 1:
                                self.track.append((lat, lon, now))
                                self.track = self.track[-180:]

    def _sustained_below(self, field, limit, now):
        """True when every graph sample of `field` from the last few seconds is
        below `limit` and the samples cover that whole period. Brief dips (for
        example voltage sag at full throttle) therefore do not raise alerts."""
        window = [p for p in self.history if now-p['t'] <= self.limits.sustain_s+1]
        values = [p[field] for p in window if p[field] is not None]
        if not values or now-window[0]['t'] < self.limits.sustain_s:
            return False
        return all(v < limit for v in values)

    def _alerts(self, now, s, hb_entry, sys_status, landed):
        alerts = []
        def add(level, code, text):
            alerts.append(dict(level=level, code=code, text=text))
        armed = bool(self.last_armed)
        if hb_entry and not s['online']:
            age = now-hb_entry[1]
            add('critical' if armed else 'warning', 'link',
                f'Telemetry lost {age:.0f} s ago' + (' — aircraft was ARMED' if armed else ''))
        if not s['online']:
            return alerts
        lim = self.limits
        volts = s['battery_voltage']
        if volts is not None and lim.battery_critical_v and self._sustained_below('voltage', lim.battery_critical_v, now):
            add('critical', 'battery', f'Battery critical: {volts:.2f} V (limit {lim.battery_critical_v:.1f} V)')
        elif volts is not None and lim.battery_low_v and self._sustained_below('voltage', lim.battery_low_v, now):
            add('warning', 'battery', f'Battery low: {volts:.2f} V (limit {lim.battery_low_v:.1f} V)')
        gps = s['gps']
        if armed and (gps is None or gps['fix_type'] < 3):
            add('critical', 'gps', 'No 3D GPS fix while ARMED')
        elif armed and gps and gps['satellites'] is not None and gps['satellites'] < lim.min_satellites:
            add('warning', 'gps', f'Only {gps["satellites"]} GPS satellites')
        for name in s['sensors_unhealthy']:
            if name == 'RC receiver':
                add('critical' if armed else 'warning', 'rc', 'RC receiver signal lost (RC failsafe)')
            else:
                add('critical' if armed and name.startswith('Attitude') else 'warning',
                    'sensor', f'{name} reported unhealthy')
        airborne = landed == 2 if landed else (s['position'] or {}).get('altitude_relative_m', 0) > 10
        aspd = s['airspeed_m_s']
        if lim.airspeed_min_m_s and armed and airborne and aspd is not None and \
                self._sustained_below('airspeed', lim.airspeed_min_m_s, now):
            add('warning', 'airspeed', f'Airspeed {aspd:.1f} m/s below minimum {lim.airspeed_min_m_s:.0f} m/s')
        for stamp, level, text in self.text_alerts:
            if now-stamp <= TEXT_ALERT_SECONDS[level]:
                add(level, 'message', text)
        alerts.sort(key=lambda a: a['level'] != 'critical')
        return alerts

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            def get(kind, ttl):
                entry = self.values.get(kind)
                return entry[0] if entry and now-entry[1] <= ttl else None
            def age(kind):
                entry = self.values.get(kind)
                return round(max(0, now-entry[1]), 1) if entry else None
            hb = get('HEARTBEAT', 5)
            gps = get('GPS_RAW_INT', 10)
            pos = get('GLOBAL_POSITION_INT', 3)
            attitude = get('ATTITUDE', 3)
            hud = get('VFR_HUD', 3)
            battery = get('BATTERY_STATUS', 10)
            sys_status = get('SYS_STATUS', 10)
            mission = get('MISSION_CURRENT', 10)
            extended = get('EXTENDED_SYS_STATE', 10)
            home = self.values.get('HOME_POSITION')
            reached = self.values.get('MISSION_ITEM_REACHED')
            valid_pos = bool(pos and gps and gps.fix_type >= 3 and -900000000 <= pos.lat <= 900000000 and -1800000000 <= pos.lon <= 1800000000)
            if not hb:
                # A recent data packet without a current FC heartbeat is not a
                # live vehicle: suppress operational values until identity returns.
                valid_pos = False
                attitude = hud = battery = sys_status = mission = extended = None
            battery_pct, volts = self._voltage(battery, sys_status)
            mission_state = None
            if mission:
                code = getattr(mission, 'mission_state', 0)
                entry = mav.enums.get('MISSION_STATE', {}).get(code)
                mission_state = entry.name.replace('MISSION_STATE_', '').replace('_', ' ').title() if entry and code else None
            unhealthy, prearm_ok = [], None
            if sys_status:
                watched = sys_status.onboard_control_sensors_present & sys_status.onboard_control_sensors_enabled
                bad = watched & ~sys_status.onboard_control_sensors_health
                unhealthy = [name for bit, name in SENSORS.items() if bad & bit]
                if sys_status.onboard_control_sensors_present & mav.MAV_SYS_STATUS_PREARM_CHECK:
                    prearm_ok = not bad & mav.MAV_SYS_STATUS_PREARM_CHECK
            landed = extended.landed_state if extended and extended.landed_state in LANDED else None
            position = {'latitude':pos.lat/1e7, 'longitude':pos.lon/1e7,
                        'altitude_relative_m':pos.relative_alt/1000,
                        'heading_deg':pos.hdg/100 if pos.hdg != 65535 else None} if valid_pos else None
            home_info = None
            reference = (home[0].latitude/1e7, home[0].longitude/1e7, 'home') if home else \
                (*self.launch, 'launch point') if self.launch else None
            if position and reference:
                dist, bearing = distance_bearing(reference[0], reference[1], position['latitude'], position['longitude'])
                home_info = {'distance_m':round(dist, 1), 'bearing_deg':round(bearing), 'reference':reference[2]}
            heading = number(hud.heading) if hud else None
            if heading is None and position:
                heading = position['heading_deg']
            s = dict(name=self.name, configured=True, online=hb is not None,
                identity={'system':self.expected[0], 'component':self.expected[1]},
                heartbeat_age=age('HEARTBEAT'), boot_id=self.boot_id,
                armed=bool(hb.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED) if hb else None,
                mode=mavutil.mode_string_v10(hb) if hb else None,
                position=position,
                position_age=age('GLOBAL_POSITION_INT'),
                gps={'fix_type':gps.fix_type, 'satellites':gps.satellites_visible if gps.satellites_visible != 255 else None} if gps and hb else None,
                roll_deg=number(attitude.roll, 1/math.degrees(1)) if attitude else None,
                pitch_deg=number(attitude.pitch, 1/math.degrees(1)) if attitude else None,
                groundspeed_m_s=number(hud.groundspeed) if hud else None,
                airspeed_m_s=number(hud.airspeed) if hud else None,
                heading_deg=heading,
                throttle_pct=hud.throttle if hud and 0 <= hud.throttle <= 100 else None,
                climb_m_s=number(hud.climb) if hud else None,
                battery_percent=battery_pct, battery_voltage=volts,
                sensors_unhealthy=unhealthy, prearm_ok=prearm_ok,
                landed_state=LANDED.get(landed),
                home=home_info,
                mission={'current_seq':mission.seq if mission else None,
                         'total':getattr(mission, 'total', 0) or None if mission else None,
                         'state':mission_state, 'age_seconds':age('MISSION_CURRENT'),
                         'last_reached_seq':reached[0].seq if reached else None,
                         'last_reached_age':round(now-reached[1],1) if reached else None,
                         'route_status':'No aircraft-confirmed route received'},
                track=[{'latitude':lat, 'longitude':lon, 'age_seconds':round(now-stamp,1)} for lat,lon,stamp in self.track if now-stamp <= 300],
                accepted_frames=self.accepted, rejected_frames=self.invalid)
            hb_entry = self.values.get('HEARTBEAT')
            if hb_entry and not hb and not self.link_lost:
                self.link_lost = True
                self._event(hb_entry[1]+5, 'critical' if self.last_armed else 'warning', 'Telemetry lost')
            elif hb and self.link_lost:
                self.link_lost = False
                self._event(now, 'notice', 'Telemetry restored')
            s['alerts'] = self._alerts(now, s, hb_entry, sys_status, landed)
            s['events'] = [{'age_seconds':round(now-t, 1), 'level':level, 'text':text, 'count':count}
                           for t, level, text, count in reversed(self.events)]
            s['history'] = [dict(age=round(now-p['t'], 1), **{k:p[k] for k in ('altitude','airspeed','groundspeed','voltage')})
                            for p in self.history]
            return s
