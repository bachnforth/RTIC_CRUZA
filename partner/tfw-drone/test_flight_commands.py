import unittest

import safety_mavlink_filter as bridge

mav = bridge.mav
NAN = float('nan')


def parse(msg):
    raw = msg.pack(mav.MAVLink(None, srcSystem=255, srcComponent=190))
    return mav.MAVLink(None).parse_char(raw)


def long(command, *params, target=(1, 1)):
    params = (list(params) + [0.0] * 7)[:7]
    return parse(mav.MAVLink_command_long_message(*target, command, 0, *params))


def reposition(lat=35.0495395, lon=-79.4901843, alt=20.0, target=(1, 1), frame=None,
               speed=-1.0, flags=1.0, yaw=NAN, current=0, autocontinue=0):
    frame = mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT if frame is None else frame
    return parse(mav.MAVLink_command_int_message(
        *target, frame, mav.MAV_CMD_DO_REPOSITION, current, autocontinue,
        speed, flags, 0.0, yaw, int(lat * 1e7), int(lon * 1e7), alt))


ARM = mav.MAV_CMD_COMPONENT_ARM_DISARM
MODE = mav.MAV_CMD_DO_SET_MODE
TAKEOFF = mav.MAV_CMD_NAV_TAKEOFF


class AllowedFlightCommands(unittest.TestCase):
    def test_arm_and_disarm(self):
        self.assertTrue(bridge.is_allowed(long(ARM, 1)))
        self.assertTrue(bridge.is_allowed(long(ARM, 0)))

    def test_dashboard_modes(self):
        for mode in (4, 5, 6, 7, 9, 17):
            self.assertTrue(bridge.is_allowed(long(MODE, 1, mode)), mode)

    def test_takeoff_within_altitude_limit(self):
        for alt in (1, 20, 120):
            self.assertTrue(bridge.is_allowed(long(TAKEOFF, 0, 0, 0, 0, 0, 0, alt)), alt)

    def test_reposition(self):
        self.assertTrue(bridge.is_allowed(reposition()))

    def test_mission_start_whole_mission(self):
        self.assertTrue(bridge.is_allowed(long(mav.MAV_CMD_MISSION_START)))


class BlockedFlightCommands(unittest.TestCase):
    def test_forced_arm_or_disarm(self):
        self.assertFalse(bridge.is_allowed(long(ARM, 1, 21196)))
        self.assertFalse(bridge.is_allowed(long(ARM, 0, 21196)))

    def test_arm_with_other_values(self):
        self.assertFalse(bridge.is_allowed(long(ARM, 2)))
        self.assertFalse(bridge.is_allowed(long(ARM, 1, 0, 1)))

    def test_other_targets(self):
        self.assertFalse(bridge.is_allowed(long(ARM, 1, target=(2, 1))))
        self.assertFalse(bridge.is_allowed(long(ARM, 1, target=(1, 0))))
        self.assertFalse(bridge.is_allowed(long(MODE, 1, 4, target=(0, 0))))
        self.assertFalse(bridge.is_allowed(reposition(target=(2, 1))))

    def test_other_modes(self):
        # STABILIZE, ACRO, ALT_HOLD, AUTO, FLIP and an unknown mode.
        for mode in (0, 1, 2, 3, 14, 99):
            self.assertFalse(bridge.is_allowed(long(MODE, 1, mode)), mode)
        self.assertFalse(bridge.is_allowed(long(MODE, 0, 4)))
        self.assertFalse(bridge.is_allowed(long(MODE, 1, 4, 1)))

    def test_takeoff_outside_limit_or_with_extra_params(self):
        for alt in (0, 0.5, 121, -5, NAN, float('inf')):
            self.assertFalse(bridge.is_allowed(long(TAKEOFF, 0, 0, 0, 0, 0, 0, alt)), alt)
        self.assertFalse(bridge.is_allowed(long(TAKEOFF, 1, 0, 0, 0, 0, 0, 20)))

    def test_mission_start_variants(self):
        # A chosen start/end item, other targets, or AUTO by mode change stay blocked.
        self.assertFalse(bridge.is_allowed(long(mav.MAV_CMD_MISSION_START, 5)))
        self.assertFalse(bridge.is_allowed(long(mav.MAV_CMD_MISSION_START, 0, 10)))
        self.assertFalse(bridge.is_allowed(long(mav.MAV_CMD_MISSION_START, target=(2, 1))))
        self.assertFalse(bridge.is_allowed(long(MODE, 1, 3)))
        self.assertFalse(bridge.is_allowed(long(mav.MAV_CMD_DO_SET_MISSION_CURRENT, 3)))

    def test_reposition_variants(self):
        bad = [dict(alt=0), dict(alt=121), dict(alt=NAN), dict(lat=0), dict(lon=0),
               dict(frame=mav.MAV_FRAME_GLOBAL_INT), dict(speed=15), dict(flags=0),
               dict(yaw=90), dict(current=1), dict(autocontinue=1), dict(lat=91)]
        for kwargs in bad:
            self.assertFalse(bridge.is_allowed(reposition(**kwargs)), kwargs)

    def test_other_command_int_and_controls(self):
        self.assertFalse(bridge.is_allowed(parse(mav.MAVLink_command_int_message(
            1, 1, mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, mav.MAV_CMD_NAV_WAYPOINT,
            0, 0, 0, 0, 0, 0, 350495395, -794901843, 20))))
        self.assertFalse(bridge.is_allowed(parse(mav.MAVLink_manual_control_message(
            1, 0, 0, 500, 0, 0))))
        self.assertFalse(bridge.is_allowed(parse(mav.MAVLink_rc_channels_override_message(
            1, 1, *([1500] * 8)))))
        self.assertFalse(bridge.is_allowed(parse(mav.MAVLink_set_mode_message(
            1, mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 4))))
        self.assertFalse(bridge.is_allowed(parse(mav.MAVLink_param_set_message(
            1, 1, b'FS_GCS_ENABLE', 0, mav.MAV_PARAM_TYPE_REAL32))))
        self.assertFalse(bridge.is_allowed(long(mav.MAV_CMD_DO_SET_SERVO, 9, 1900)))
        self.assertFalse(bridge.is_allowed(long(mav.MAV_CMD_DO_FLIGHTTERMINATION, 1)))

    def test_safety_device_shape_unchanged(self):
        self.assertTrue(bridge.is_allowed(long(31010, 1, 7713)))
        self.assertFalse(bridge.is_allowed(long(31010, 3, 7713)))


class PeerForwarding(unittest.TestCase):
    def test_recent_senders_receive_traffic(self):
        peers = bridge.Peers()
        peers.heard(('10.223.58.11', 14550), 0)
        peers.heard(('10.223.196.130', 50000), 1)
        self.assertEqual(len(peers.active(4)), 2)
        self.assertEqual(peers.active(5.5), [('10.223.196.130', 50000)])
        self.assertEqual(peers.active(7), [])

    def test_peer_count_is_bounded(self):
        peers = bridge.Peers()
        for i in range(10):
            peers.heard(('10.0.0.%d' % i, 1), i)
        self.assertEqual(len(peers.seen), bridge.Peers.LIMIT)
        self.assertNotIn(('10.0.0.0', 1), peers.seen)


if __name__ == '__main__':
    unittest.main()
