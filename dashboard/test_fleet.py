import json
import unittest
from fleet import VehicleState, mav


def packet(message, system=1, component=1):
    return message.pack(mav.MAVLink(None,srcSystem=system,srcComponent=component))


def heartbeat(vehicle=mav.MAV_TYPE_FIXED_WING):
    return mav.MAVLink_heartbeat_message(vehicle,mav.MAV_AUTOPILOT_ARDUPILOTMEGA,1,0,3,3)


class FleetTests(unittest.TestCase):
    def test_same_system_ids_do_not_merge_aircraft(self):
        cruza, quad = VehicleState('cruza'), VehicleState('quadpi')
        cruza.consume(packet(heartbeat()),100)
        quad.consume(packet(heartbeat(mav.MAV_TYPE_QUADROTOR)),100)
        self.assertEqual(cruza.snapshot(100)['mode'],'MANUAL')
        self.assertEqual(quad.snapshot(100)['mode'],'STABILIZE')

    def test_wrong_source_and_ground_station_are_rejected(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat(),system=2),100)
        state.consume(packet(heartbeat(mav.MAV_TYPE_GCS)),100)
        self.assertFalse(state.snapshot(100)['online'])

    def test_crc_failure_cannot_update_state(self):
        raw = bytearray(packet(heartbeat()))
        raw[-1] ^= 1
        state = VehicleState('cruza')
        state.consume(bytes(raw),100)
        self.assertFalse(state.snapshot(100)['online'])
        self.assertGreater(state.invalid,0)

    def test_stale_heartbeat_removes_operational_values(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_vfr_hud_message(10,20,0,0,30,0)),100)
        self.assertEqual(state.snapshot(101)['groundspeed_m_s'],20)
        snap = state.snapshot(106)
        self.assertFalse(snap['online'])
        self.assertIsNone(snap['mode'])
        self.assertIsNone(snap['groundspeed_m_s'])

    def test_position_requires_current_fix_and_expires(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        pos = mav.MAVLink_global_position_int_message(1000,350000000,-790000000,100000,20000,0,0,0,65535)
        state.consume(packet(pos),100)
        self.assertIsNone(state.snapshot(100)['position'])
        gps = mav.MAVLink_gps_raw_int_message(0,3,0,0,0,100,100,0,0,12)
        state.consume(packet(gps),100)
        state.consume(packet(pos),100)
        self.assertEqual(state.snapshot(100)['position']['latitude'],35)
        self.assertEqual(state.snapshot(100)['position']['altitude_relative_m'],20)
        self.assertIsNone(state.snapshot(104)['position'])

    def test_unknown_mission_fields_do_not_become_progress_or_completion(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_mission_current_message(9,10,0,0)),100)
        mission = state.snapshot(100)['mission']
        self.assertEqual(mission['current_seq'],9)
        self.assertIsNone(mission['state'])
        self.assertNotIn('progress',mission)
        self.assertIsNone(state.snapshot(111)['mission']['current_seq'])

    def test_battery_unknown_sentinels_are_null(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        sys_status = mav.MAVLink_sys_status_message(0,0,0,0,65535,-1,-1,0,0,0,0,0,0)
        state.consume(packet(sys_status),100)
        snap = state.snapshot(100)
        self.assertIsNone(snap['battery_percent'])
        self.assertIsNone(snap['battery_voltage'])

    def test_pi_restart_clears_cached_mission_and_tracks(self):
        state = VehicleState('cruza')
        state.reset_boot('first')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_mission_item_reached_message(2)),100)
        state.reset_boot('second')
        self.assertFalse(state.snapshot(101)['online'])
        self.assertIsNone(state.snapshot(101)['mission']['last_reached_seq'])

    def test_nonfinite_attitude_is_not_exposed_as_json_nan(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_attitude_message(0,float('nan'),0,0,0,0,0)),100)
        snap = state.snapshot(100)
        self.assertIsNone(snap['roll_deg'])
        json.dumps(snap,allow_nan=False)


if __name__ == '__main__':
    unittest.main()
