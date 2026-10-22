"""Prepare/restore only battery checks for an attended, props-off USB ESC calibration.

Never arms, changes mode, or commands motor outputs.
"""
import sys,time,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.flightlog-deps'))
from pymavlink import mavutil
mode=sys.argv[1]
if mode not in ('prepare','restore'):raise RuntimeError('Use prepare or restore')
path=root/'logs'/'2026-10-09'/'esc-calibration-monitor-backup.json'
c=mavutil.mavlink_connection('COM17',baud=115200,source_system=254)
def heartbeat():
    end=time.monotonic()+10
    while time.monotonic()<end:
        m=c.recv_match(type='HEARTBEAT',blocking=True,timeout=1)
        if m and m.get_srcSystem()==1 and m.get_srcComponent()==1 and m.autopilot==3:return m
    raise RuntimeError('Vehicle heartbeat absent')
h=heartbeat()
if h.base_mode&128:raise RuntimeError('Vehicle must be disarmed')
if mode=='prepare' and h.custom_mode!=0:raise RuntimeError('Vehicle must be in MANUAL')
def read(name):
    c.mav.param_request_read_send(1,1,name.encode(),-1)
    end=time.monotonic()+5
    while time.monotonic()<end:
        m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=1)
        if m and m.get_srcSystem()==1 and m.get_srcComponent()==1 and m.param_id==name:return {'value':m.param_value,'type':m.param_type}
    raise RuntimeError('Parameter read failed: '+name)
names=['BATT_MONITOR']
if mode=='prepare':
    if path.exists() and json.loads(path.read_text()).get('status')!='restored':raise RuntimeError('Existing bench backup; restore it first')
    original={n:read(n) for n in names}
    state={'status':'preparing','original':original,'changed':[],'scope':'Attended USB-only ESC calibration, both props removed per owner; restore before flight'}
    path.write_text(json.dumps(state,indent=2))
    desired={n:0.0 for n in names}
else:
    state=json.loads(path.read_text());original=state['original']
    desired={n:original[n]['value'] for n in names}
for n,value in desired.items():
    h=heartbeat()
    if h.base_mode&128:raise RuntimeError('Vehicle armed; stopped settings change')
    c.mav.param_set_send(1,1,n.encode(),value,original[n]['type'])
    # Independent request/readback; PARAM_SET acknowledgement may arrive first.
    deadline=time.monotonic()+5
    ack=False
    while time.monotonic()<deadline:
        m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=1)
        if m and m.get_srcSystem()==1 and m.get_srcComponent()==1 and m.param_id==n:
            if abs(m.param_value-value)>0.001:raise RuntimeError('Write mismatch '+n)
            ack=True;break
    if not ack:raise RuntimeError('No write acknowledgement '+n)
    if abs(read(n)['value']-value)>0.001:raise RuntimeError('Readback mismatch '+n)
    state['changed'].append({'parameter':n,'verified_value':value,'action':mode})
    path.write_text(json.dumps(state,indent=2))
    print(n,'=',value,flush=True)
state['status']='prepared' if mode=='prepare' else 'restored'
path.write_text(json.dumps(state,indent=2))
c.close()
print('Saved backup:',path)
