"""Read-only MAVLink log retrieval and parameter snapshot for the connected Cruza."""
import sys, time, json, hashlib, argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.flightlog-deps'))
from pymavlink import mavutil

root = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',default='COM17')
parser.add_argument('--count',type=int,default=3,help='Number of newest onboard logs to retrieve')
parser.add_argument('--output-dir',type=Path,help='Optional download directory; default is a new timestamped session')
args=parser.parse_args()
if args.count<1:parser.error('--count must be positive')
now=datetime.now(ZoneInfo('America/Chicago'))
stamp=now.strftime('%Y-%m-%d_%H%M%S_%f')
out=args.output_dir or root/'logs'/now.strftime('%Y-%m-%d')/f'download-{now.strftime("%H%M%S_%f")}'
out.mkdir(parents=True, exist_ok=True)
c = mavutil.mavlink_connection(args.port, baud=115200, source_system=254)
h = None
deadline = time.monotonic()+15
while time.monotonic()<deadline:
    candidate=c.recv_match(type='HEARTBEAT',blocking=True,timeout=1)
    if candidate and candidate.autopilot==mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA and candidate.type==mavutil.mavlink.MAV_TYPE_FIXED_WING:
        h=candidate
        break
if h is None:
    raise RuntimeError('No vehicle heartbeat')
if h.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
    raise RuntimeError('Vehicle is armed; stopped retrieval')
print('Heartbeat:', h.to_dict(), flush=True)
s, comp = h.get_srcSystem(), h.get_srcComponent()
c.mav.command_long_send(s, comp, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0, 148, 0, 0, 0, 0, 0, 0)
v = c.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=5)
if v:
    (out/'autopilot-version.json').write_text(json.dumps(v.to_dict(), indent=2))
    print('Version:', v.flight_sw_version, flush=True)
c.mav.param_request_list_send(s, comp)
params, indexes, count = {}, set(), 0
deadline = time.monotonic()+90
last = time.monotonic()
while time.monotonic()<deadline:
    m = c.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
    if m and m.get_srcSystem()==s and m.get_srcComponent()==comp:
        params[m.param_id] = (m.param_value, m.param_type)
        indexes.add(m.param_index); count = m.param_count
        last = time.monotonic()
        if len(indexes)>=count: break
    elif count and time.monotonic()-last>2:
        missing = sorted(set(range(count))-indexes)
        for i in missing[:40]: c.mav.param_request_read_send(s, comp, b'', i)
        last = time.monotonic()
(out/'parameters.json').write_text(json.dumps({k:v[0] for k,v in params.items()},indent=2,sort_keys=True))
pfile=root/'params'/f'cruza_params_{stamp}_postflight.params'
pfile.write_text('# Read-only USB snapshot; received %d/%d indexes, %d unique names\n'%(len(indexes),count,len(params))+''.join(f'{s}\t{comp}\t{k}\t{v[0]:.9g}\t{v[1]}\n' for k,v in sorted(params.items())))
print(f'Parameter indexes {len(indexes)}/{count}, unique names {len(params)}', flush=True)
print({k:v[0] for k,v in params.items() if k.startswith(('TKOFF_', 'THR_', 'TRIM_THROTTLE','SERVO4_','ARSPD_'))},flush=True)
c.mav.log_request_list_send(s, comp, 0, 65535)
entries={}; deadline=time.monotonic()+20
while time.monotonic()<deadline:
    m=c.recv_match(type='LOG_ENTRY',blocking=True,timeout=2)
    if m and m.get_srcSystem()==s and m.get_srcComponent()==comp:
        entries[m.id]=m.to_dict()
        if len(entries)>=m.num_logs: break
(out/'log-index.json').write_text(json.dumps(list(entries.values()),indent=2))
print('Log index:',json.dumps(list(entries.values())),flush=True)
for entry in sorted(entries.values(), key=lambda e:e['id'], reverse=True)[:args.count]:
    logid,size=entry['id'],entry['size']
    if not size: continue
    path=out/f'log_{logid:05d}.BIN'
    if path.exists() and path.stat().st_size==size:
        print('Already downloaded',path,flush=True); continue
    data=bytearray(size); got=set(); total=(size+89)//90
    start=time.monotonic(); last_report=start
    while len(got)<total:
        missing=next(i for i in range(total) if i not in got)
        end=min(missing+500,total)
        c.mav.log_request_data_send(s,comp,logid,missing*90,min((end-missing)*90,size-missing*90))
        idle=time.monotonic()+3
        while time.monotonic()<idle:
            m=c.recv_match(type='LOG_DATA',blocking=True,timeout=0.3)
            if not m: continue
            if m.get_srcSystem()!=s or m.get_srcComponent()!=comp or m.id!=logid or not m.count: continue
            if m.ofs<0 or m.ofs>=size or m.ofs%90 or m.count!=min(90,size-m.ofs):continue
            n=min(m.count,size-m.ofs)
            data[m.ofs:m.ofs+n]=bytes(m.data[:n]);got.add(m.ofs//90)
            idle=time.monotonic()+1
            if all(i in got for i in range(missing,end)):break
        if time.monotonic()-last_report>10:
            print(f'Log {logid}: {len(got)/total:.1%}, {size} bytes',flush=True);last_report=time.monotonic()
        if time.monotonic()-start>1200: raise TimeoutError('Download exceeded 20 minutes')
    path.write_bytes(data)
    print('Saved',str(path),'bytes',size,'SHA256',hashlib.sha256(data).hexdigest(),flush=True)
c.mav.log_request_end_send(s,comp)
c.close()
