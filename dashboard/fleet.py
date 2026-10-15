"""CRC-checked, source-isolated telemetry state. Contains no MAVLink sender."""
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
           'VFR_HUD', 'BATTERY_STATUS', 'EXTENDED_SYS_STATE'}


def number(value, scale=1):
    return value/scale if isinstance(value, (int, float)) and math.isfinite(value) else None


class VehicleState:
    def __init__(self, name, expected_system=1, expected_component=1):
        self.name = name
        self.expected = (expected_system, expected_component)
        self.lock = threading.Lock()
        self.values = {}
        self.track = []
        self.boot_id = None
        self.invalid = self.accepted = 0

    def reset_boot(self, boot):
        with self.lock:
            if boot != self.boot_id:
                self.values.clear()
                self.track.clear()
                self.boot_id = boot

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
                if kind == 'GLOBAL_POSITION_INT':
                    gps = self.values.get('GPS_RAW_INT')
                    if gps and now-gps[1] <= 10 and gps[0].fix_type >= 3:
                        lat, lon = message.lat/1e7, message.lon/1e7
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            if not self.track or now-self.track[-1][2] >= 1:
                                self.track.append((lat, lon, now))
                                self.track = self.track[-180:]

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
            reached = self.values.get('MISSION_ITEM_REACHED')
            valid_pos = bool(pos and gps and gps.fix_type >= 3 and -900000000 <= pos.lat <= 900000000 and -1800000000 <= pos.lon <= 1800000000)
            if not hb:
                # A recent data packet without a current FC heartbeat is not a
                # live vehicle: suppress operational values until identity returns.
                valid_pos = False
                attitude = hud = battery = sys_status = mission = None
            battery_pct, volts = None, None
            if battery and battery.id == 0:
                battery_pct = battery.battery_remaining if 0 <= battery.battery_remaining <= 100 else None
                cells = [v for v in battery.voltages if v not in (0, 65535)]
                volts = sum(cells)/1000 if cells else None
            elif sys_status:
                battery_pct = sys_status.battery_remaining if 0 <= sys_status.battery_remaining <= 100 else None
                volts = sys_status.voltage_battery/1000 if sys_status.voltage_battery != 65535 else None
            mission_state = None
            if mission:
                code = getattr(mission, 'mission_state', 0)
                entry = mav.enums.get('MISSION_STATE', {}).get(code)
                mission_state = entry.name.replace('MISSION_STATE_', '').replace('_', ' ').title() if entry and code else None
            return dict(name=self.name, configured=True, online=hb is not None,
                identity={'system':self.expected[0], 'component':self.expected[1]},
                heartbeat_age=age('HEARTBEAT'), boot_id=self.boot_id,
                armed=bool(hb.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED) if hb else None,
                mode=mavutil.mode_string_v10(hb) if hb else None,
                position={'latitude':pos.lat/1e7, 'longitude':pos.lon/1e7,
                          'altitude_relative_m':pos.relative_alt/1000,
                          'heading_deg':pos.hdg/100 if pos.hdg != 65535 else None} if valid_pos else None,
                position_age=age('GLOBAL_POSITION_INT'),
                gps={'fix_type':gps.fix_type, 'satellites':gps.satellites_visible if gps.satellites_visible != 255 else None} if gps and hb else None,
                roll_deg=number(attitude.roll, 1/math.degrees(1)) if attitude else None,
                pitch_deg=number(attitude.pitch, 1/math.degrees(1)) if attitude else None,
                groundspeed_m_s=number(hud.groundspeed) if hud else None,
                airspeed_m_s=number(hud.airspeed) if hud else None,
                battery_percent=battery_pct, battery_voltage=volts,
                mission={'current_seq':mission.seq if mission else None,
                         'total':getattr(mission, 'total', 0) or None if mission else None,
                         'state':mission_state, 'age_seconds':age('MISSION_CURRENT'),
                         'last_reached_seq':reached[0].seq if reached else None,
                         'last_reached_age':round(now-reached[1],1) if reached else None,
                         'route_status':'No aircraft-confirmed route received'},
                track=[{'latitude':lat, 'longitude':lon, 'age_seconds':round(now-stamp,1)} for lat,lon,stamp in self.track if now-stamp <= 300],
                accepted_frames=self.accepted, rejected_frames=self.invalid)
