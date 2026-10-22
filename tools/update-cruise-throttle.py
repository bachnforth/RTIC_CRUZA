"""Apply the owner's requested 20% relative cruise-trim increase, disarmed only."""
import sys,time,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.flightlog-deps'))
from pymavlink import mavutil
out=root/'logs'/'2026-10-09'
c=mavutil.mavlink_connection('COM17',baud=115200,source_system=254)
def vehicle_heartbeat(timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        hb=c.recv_match(type='HEARTBEAT',blocking=True,timeout=1)
        if hb and hb.autopilot==mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA and hb.type==mavutil.mavlink.MAV_TYPE_FIXED_WING:
            return hb
    return None
h=vehicle_heartbeat()
if h is None or h.base_mode & 128:raise RuntimeError('No disarmed vehicle heartbeat')
s,comp=h.get_srcSystem(),h.get_srcComponent()
c.mav.param_request_list_send(s,comp)
byindex={}; deadline=time.monotonic()+60
while time.monotonic()<deadline:
    m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=1)
    if m and m.get_srcSystem()==s and m.get_srcComponent()==comp:
        byindex[m.param_index]=m.to_dict()
        if len(byindex)>=m.param_count:break
if not byindex or len(byindex)<m.param_count:raise RuntimeError('Incomplete parameter snapshot')
params={v['param_id']:v for v in byindex.values()}
(out/'parameter-index-before-change.json').write_text(json.dumps(byindex,indent=2))
def save_params(path,comment):
    path.write_text('# '+comment+f'; {len(byindex)} parameter indexes, {len(params)} unique names\n'+''.join(f"{s}\t{comp}\t{k}\t{v['param_value']:.9g}\t{v['param_type']}\n" for k,v in sorted(params.items())))
save_params(root/'params'/'cruza_params_2026-10-09_postflight.params','Before cruise throttle change')
before=params['TRIM_THROTTLE']['param_value']
if before!=45:raise RuntimeError(f'Unexpected trim throttle {before}; expected 45')
h=vehicle_heartbeat(5)
if h is None or h.base_mode & 128:raise RuntimeError('Vehicle no longer confirmed disarmed')
desired=54.0
c.mav.param_set_send(s,comp,b'TRIM_THROTTLE',desired,params['TRIM_THROTTLE']['param_type'])
confirmed=False
deadline=time.monotonic()+10
while time.monotonic()<deadline:
    m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=1)
    if m and m.get_srcSystem()==s and m.get_srcComponent()==comp and m.param_id=='TRIM_THROTTLE':
        if abs(m.param_value-desired)>0.001:raise RuntimeError('Parameter write rejected')
        params[m.param_id]=m.to_dict();confirmed=True;break
if not confirmed:raise RuntimeError('Parameter write acknowledgement not received')
c.mav.param_request_read_send(s,comp,b'TRIM_THROTTLE',-1)
deadline=time.monotonic()+10;verified=False
while time.monotonic()<deadline:
    m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=1)
    if m and m.get_srcSystem()==s and m.get_srcComponent()==comp and m.param_id=='TRIM_THROTTLE':
        if abs(m.param_value-desired)>0.001:raise RuntimeError('Readback mismatch')
        verified=True;break
if not verified:raise RuntimeError('Readback not received')
save_params(root/'params'/'cruza_params_2026-10-09_cruise54.params','After verified cruise throttle change')
(out/'cruise-throttle-change.json').write_text(json.dumps({'parameter':'TRIM_THROTTLE','before':before,'after':desired,'acknowledged':confirmed,'independent_readback':verified,'takeoff_parameters_changed':False},indent=2))
c.close()
print('Verified TRIM_THROTTLE: 45 -> 54. Takeoff already at 100%; unchanged.')
