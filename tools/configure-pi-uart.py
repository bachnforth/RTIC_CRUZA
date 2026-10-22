"""Audit or configure only Cruza UART2; no arming, motor or reboot commands."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.flightlog-deps'))
from pymavlink import mavutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', default='COM17')
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
c = mavutil.mavlink_connection(args.port, baud=115200, source_system=254)
target = None


def heartbeat(seconds=12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        h = c.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
        if h and h.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA and h.type == mavutil.mavlink.MAV_TYPE_FIXED_WING:
            if target and (h.get_srcSystem(), h.get_srcComponent()) != target:
                continue
            if h.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                raise RuntimeError('Vehicle is armed; no parameter changes permitted')
            return h
    raise RuntimeError('No fresh disarmed ArduPlane heartbeat')


def snapshot():
    c.mav.param_request_list_send(*target)
    byindex = {}
    expected = 0
    end = time.monotonic() + 85
    retried = time.monotonic()
    while time.monotonic() < end:
        m = c.recv_match(blocking=True, timeout=1)
        if m and (m.get_srcSystem(), m.get_srcComponent()) == target:
            if m.get_type() == 'HEARTBEAT' and m.base_mode & 128:
                raise RuntimeError('Vehicle armed during audit; stopped')
            if m.get_type() == 'PARAM_VALUE':
                byindex[m.param_index] = m.to_dict()
                expected = m.param_count
                if len(byindex) == expected:
                    return {v['param_id']: v for v in byindex.values()}
        if expected and time.monotonic() - retried > 3:
            for i in sorted(set(range(expected)) - set(byindex))[:40]:
                c.mav.param_request_read_send(*target, b'', i)
            retried = time.monotonic()
    raise RuntimeError(f'Incomplete snapshot: {len(byindex)}/{expected}')


def save(params, path):
    path.write_text('# Live USB snapshot for Pi UART2 integration; ' + str(len(params)) + ' unique parameters\n' +
                    ''.join(f'{target[0]}\t{target[1]}\t{k}\t{v["param_value"]:.9g}\t{v["param_type"]}\n'
                            for k, v in sorted(params.items())))


def read(name):
    c.mav.param_request_read_send(*target, name.encode(), -1)
    end = time.monotonic() + 8
    while time.monotonic() < end:
        m = c.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
        if m and (m.get_srcSystem(), m.get_srcComponent()) == target and m.param_id == name:
            return m.param_value
    raise RuntimeError('No independent readback: ' + name)


try:
    h = heartbeat()
    target = h.get_srcSystem(), h.get_srcComponent()
    if target != (1, 1):
        raise RuntimeError(f'Unexpected vehicle identity {target}; expected Cruza (1,1)')
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%SZ')
    out = ROOT / 'logs' / '2026-10-14' / ('pi-uart-' + stamp)
    out.mkdir(parents=True, exist_ok=False)
    c.mav.command_long_send(*target, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0, 148, 0, 0, 0, 0, 0, 0)
    version = c.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=5)
    if version:
        (out / 'version.json').write_text(json.dumps(version.to_dict(), indent=2))
    before = snapshot()
    before_path = ROOT / 'params' / f'cruza_params_{stamp}_before_pi_uart.params'
    save(before, before_path)
    keys = [k for k in before if k.startswith(('SERIAL', 'FS_', 'BATT_FS', 'ARMING_', 'FENCE_'))]
    selected = {k: before[k]['param_value'] for k in sorted(keys)}
    (out / 'audit.json').write_text(json.dumps(selected, indent=2))
    print(json.dumps({'disarmed': True, 'system': target, 'snapshot': str(before_path),
                      'parameters': len(before), 'settings': selected}, indent=2), flush=True)
    if args.apply:
        if before['SERIAL2_PROTOCOL']['param_value'] not in (-1, 2):
            raise RuntimeError('UART2 assigned to another protocol; refused to replace')
        if before['SERIAL4_PROTOCOL']['param_value'] != 2 or before['SERIAL6_PROTOCOL']['param_value'] != 5:
            raise RuntimeError('ELRS/GPS mapping differs from verified build; stopped')
        changes = {}
        for name, value in [('SERIAL2_BAUD', 115), ('SERIAL2_OPTIONS', 0), ('SERIAL2_PROTOCOL', 2)]:
            heartbeat(5)
            if before[name]['param_value'] != value:
                c.mav.param_set_send(*target, name.encode(), value, before[name]['param_type'])
                # Readback itself is authoritative, independent of write acknowledgment.
                time.sleep(0.3)
                actual = read(name)
                if actual != value:
                    raise RuntimeError(f'{name}: expected {value}, read {actual}; stopped')
                changes[name] = {'before': before[name]['param_value'], 'after': actual}
                (out / 'changes.json').write_text(json.dumps(changes, indent=2))
        after = snapshot()
        after_path = ROOT / 'params' / f'cruza_params_{stamp}_after_pi_uart.params'
        save(after, after_path)
        unrelated = {k: [before[k]['param_value'], after[k]['param_value']] for k in before
                     if k in after and not k.startswith('SERIAL2_') and
                     before[k]['param_value'] != after[k]['param_value']}
        report = {'changes': changes, 'unrelated_differences': unrelated,
                  'after_snapshot': str(after_path), 'reboot_sent': False,
                  'arming_or_motor_commands_sent': False}
        (out / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
finally:
    c.close()
