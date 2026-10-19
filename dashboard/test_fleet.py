import json
import unittest
from fleet import Limits, VehicleState, mav


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

    def test_status_text_becomes_event_and_timed_alert(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_statustext_message(2,b'Failsafe: battery',0,0)),100)
        state.consume(packet(mav.MAVLink_statustext_message(6,b'Mission: 3 WP',0,0)),100)
        snap = state.snapshot(101)
        self.assertEqual([a['text'] for a in snap['alerts']],['Failsafe: battery'])
        self.assertEqual(snap['alerts'][0]['level'],'critical')
        self.assertEqual([e['text'] for e in snap['events']],['Mission: 3 WP','Failsafe: battery'])
        state.consume(packet(heartbeat()),165)
        self.assertEqual(state.snapshot(165)['alerts'],[])

    def test_chunked_status_text_is_joined(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_statustext_message(4,b'A'*50,7,0)),100)
        self.assertEqual(state.snapshot(100)['events'],[])
        state.consume(packet(mav.MAVLink_statustext_message(4,b'tail',7,1)),100)
        self.assertEqual(state.snapshot(100)['events'][0]['text'],'A'*50+'tail')

    def test_arm_and_mode_changes_are_logged(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        armed = mav.MAVLink_heartbeat_message(mav.MAV_TYPE_FIXED_WING,mav.MAV_AUTOPILOT_ARDUPILOTMEGA,
                                              1|mav.MAV_MODE_FLAG_SAFETY_ARMED,10,4,3)
        state.consume(packet(armed),101)
        texts = [e['text'] for e in state.snapshot(101)['events']]
        self.assertIn('ARMED',texts)
        self.assertIn('Mode MANUAL → AUTO',texts)

    def test_lost_link_while_armed_is_critical(self):
        state = VehicleState('cruza')
        armed = mav.MAVLink_heartbeat_message(mav.MAV_TYPE_FIXED_WING,mav.MAV_AUTOPILOT_ARDUPILOTMEGA,
                                              1|mav.MAV_MODE_FLAG_SAFETY_ARMED,10,4,3)
        state.consume(packet(armed),100)
        alert = state.snapshot(108)['alerts'][0]
        self.assertEqual((alert['code'],alert['level']),('link','critical'))
        self.assertEqual(state.snapshot(108)['events'][0]['text'],'Telemetry lost')

    def test_battery_alert_needs_sustained_low_voltage(self):
        state = VehicleState('cruza',limits=Limits(battery_low_v=14,battery_critical_v=13.2))
        sys_status = mav.MAVLink_sys_status_message(0,0,0,0,13800,-1,-1,0,0,0,0,0,0)
        for t in range(100,107):
            state.consume(packet(heartbeat()),t)
            state.consume(packet(sys_status),t)
            if t == 100:
                self.assertEqual(state.snapshot(t)['alerts'],[])
        alert = state.snapshot(106)['alerts'][0]
        self.assertEqual((alert['code'],alert['level']),('battery','warning'))

    def test_unhealthy_rc_receiver_and_sensor_names(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        rc, gps = mav.MAV_SYS_STATUS_SENSOR_RC_RECEIVER, mav.MAV_SYS_STATUS_SENSOR_GPS
        state.consume(packet(mav.MAVLink_sys_status_message(rc|gps,rc|gps,gps,0,15000,-1,-1,0,0,0,0,0,0)),100)
        snap = state.snapshot(100)
        self.assertEqual(snap['sensors_unhealthy'],['RC receiver'])
        self.assertEqual(snap['alerts'][0]['code'],'rc')

    def test_new_readings_distance_and_history(self):
        state = VehicleState('cruza')
        state.consume(packet(heartbeat()),100)
        state.consume(packet(mav.MAVLink_home_position_message(337245032,-859121447,0,0,0,0,[1,0,0,0],0,0,0)),100)
        state.consume(packet(mav.MAVLink_gps_raw_int_message(0,3,0,0,0,100,100,0,0,14)),100)
        state.consume(packet(mav.MAVLink_vfr_hud_message(15.5,14,270,42,60,-1.5)),100)
        state.consume(packet(mav.MAVLink_global_position_int_message(1000,337245032+9000,-859121447,0,60000,0,0,0,65535)),101)
        snap = state.snapshot(101)
        self.assertEqual((snap['airspeed_m_s'],snap['heading_deg'],snap['throttle_pct'],snap['climb_m_s']),(15.5,270,42,-1.5))
        self.assertAlmostEqual(snap['home']['distance_m'],100,delta=1)
        self.assertEqual(snap['home']['reference'],'home')
        self.assertEqual(len(snap['history']),2)
        self.assertEqual(snap['history'][-1]['altitude'],60)
        json.dumps(snap,allow_nan=False)

    def test_brief_voltage_sag_does_not_alert(self):
        state = VehicleState('cruza',limits=Limits(battery_low_v=14,battery_critical_v=13.2))
        for t in range(100,108):
            volts = 13800 if t == 104 else 15500
            state.consume(packet(heartbeat()),t)
            state.consume(packet(mav.MAVLink_sys_status_message(0,0,0,0,volts,-1,-1,0,0,0,0,0,0)),t)
            self.assertEqual(state.snapshot(t)['alerts'],[])

    def test_repeated_messages_collapse_into_one_entry(self):
        state = VehicleState('cruza')
        for t in (100,130,160):
            state.consume(packet(heartbeat()),t)
            state.consume(packet(mav.MAVLink_statustext_message(3,b'PreArm: Compass not calibrated',0,0)),t)
        events = state.snapshot(160)['events']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['count'],3)


if __name__ == '__main__':
    unittest.main()
