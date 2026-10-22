"""Review measured airspeed and phase-specific flight evidence from analyzed BINs."""
import sys, json, hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / '.flightlog-deps'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

path = Path(sys.argv[1])
r = json.loads(path.with_suffix('.records.json').read_text())
s = json.loads(path.with_suffix('.summary.json').read_text())
def stats(vals):
    a = np.asarray(vals, dtype=float)
    return dict(zip(('min','p05','median','p95','max'), map(float,
        (a.min(), np.percentile(a,5), np.median(a), np.percentile(a,95), a.max())))) if len(a) else None
def event(text):
    return next((x['TimeUS']/1e6 for x in r['MSG'] if text in x['Message']), None)
def window(typ, lo, hi):
    return [x for x in r.get(typ,[]) if lo <= x['TimeUS']/1e6 <= hi]
def values(typ, key, lo, hi):
    return [x[key] for x in window(typ,lo,hi) if key in x]
start = event('Triggered AUTO')
end = event('Throttle disarmed')
takeoff_end = event('Takeoff complete')
approach = next(x['TimeUS']/1e6 for x in r['MSG'] if x['Message'].startswith('Mission:') and x['Message'].endswith(' Land'))
flare = event('Flare ')
movement = next(x['TimeUS']/1e6 for x in window('GPS',start,takeoff_end) if x['Spd'] >= 5)
loiter_cmd = next((x for x in r['CMD'] if x['CId']==19),None)
loiter_start = event(f"Mission: {loiter_cmd['CNum']} ") if loiter_cmd else None
loiter_end = event('Loiter time complete') if loiter_cmd else None
waypoint6_start = loiter_start if loiter_start else event('Mission: 6 WP')
phases = {'pre_movement':(start,movement), 'takeoff':(movement,takeoff_end),
          'cruise':(takeoff_end+10,event('Mission: 7 WP')-10),
          'waypoint5':(event('Mission: 5 WP')+10,waypoint6_start-5),
          'approach':(approach,flare), 'flare_to_disarm':(flare,end),
          'post_disarm':(end+3,max(x['TimeUS'] for x in r['ARSP'])/1e6)}
if loiter_start is not None and loiter_end is not None:
    phases['loiter']=(loiter_start+20,loiter_end)
    phases['loiter_last_60s']=(loiter_end-60,loiter_end)
out = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
       'sensor_parameters':{k:v for k,v in s['parameters'].items() if k.startswith(('ARSPD','AIRSPEED','SCALING_SPEED'))},
       'sensor_samples':len(r['ARSP']), 'health_values':sorted(set(x['H'] for x in r['ARSP'])),
       'use_values':sorted(set(x['U'] for x in r['ARSP'])),
       'max_sensor_sample_gap_s':float(np.max(np.diff([x['TimeUS']/1e6 for x in r['ARSP']]))),
       'phases':{}}
for name,(lo,hi) in phases.items():
    att=window('ATT',lo,hi)
    out['phases'][name]={'controller_seconds':[lo,hi], 'duration_s':hi-lo,
        'airspeed_mps':stats(values('ARSP','Airspeed',lo,hi)),
        'differential_pressure_pa':stats(values('ARSP','DiffPress',lo,hi)),
        'groundspeed_mps':stats(values('GPS','Spd',lo,hi)),
        'altitude_above_home_m':stats(values('POS','RelHomeAlt',lo,hi)),
        'throttle_percent':stats(values('CTUN','ThO',lo,hi)),
        'pitch_error_rms_deg':float(np.sqrt(np.mean([(x['Pitch']-x['DesPitch'])**2 for x in att]))) if att else None,
        'roll_error_rms_deg':float(np.sqrt(np.mean([(x['Roll']-x['DesRoll'])**2 for x in att]))) if att else None}
cruise = window('ARSP',*phases['cruise'])
ratio_rows = [(x['TimeUS']/1e6, x['Airspeed']**2/x['DiffPress'])
              for x in r['ARSP'] if x['DiffPress'] > 20]
out['derived_ratio'] = {
    'method':'ARSP.Airspeed squared / ARSP.DiffPress; pressure >20 Pa; MS4525 raw-speed logging',
    'stats':stats([v for t,v in ratio_rows]),
    'first':ratio_rows[0], 'last':ratio_rows[-1],
    'last_30s':stats([v for t,v in ratio_rows if t >= ratio_rows[-1][0]-30]),
    'last_30s_first_to_last_change':ratio_rows[-1][1]-next(v for t,v in ratio_rows if t>=ratio_rows[-1][0]-30)
} if ratio_rows else None
if loiter_start is not None and loiter_end is not None:
    out['loiter']={'mission_start_s':loiter_start,'completion_s':loiter_end,
        'commanded_duration_s':loiter_cmd['Prm1'],'mission_start_to_completion_s':loiter_end-loiter_start,
        'ratio_last_60s':stats([v for t,v in ratio_rows if loiter_end-60<=t<=loiter_end]),
        'ratio_blocks':[]}
    for lo in np.arange(loiter_start+20,loiter_end,30):
        rr=[v for t,v in ratio_rows if lo<=t<min(lo+30,loiter_end)]
        if rr:out['loiter']['ratio_blocks'].append({'start_s':float(lo),'end_s':float(min(lo+30,loiter_end)),'ratio':stats(rr)})
out['cruise_zero_or_nearzero_samples'] = sum(x['Airspeed']<3 for x in cruise)
out['ekf_fault_values'] = sorted(set(x['FS'] for x in r['XKF4']))
out['ekf_gps_check_values'] = sorted(set(x['GPS'] for x in r['XKF4']))
out['vibration']={str(i):{k:stats([x[k] for x in window('VIBE',movement,approach) if x['IMU']==i])
    for k in ('VibeX','VibeY','VibeZ','Clip')} for i in (0,1)}
out['logger_dropped_records_max'] = max(x['Dp'] for x in r['DSF'])
out['parameter_changes_during_log'] = []
from pymavlink import mavutil
c=mavutil.mavlink_connection(str(path))
seen={}
while True:
    m=c.recv_match(type='PARM')
    if m is None: break
    if m.Name in seen and seen[m.Name]!=m.Value:
        out['parameter_changes_during_log'].append({'time_s':m.TimeUS/1e6,'name':m.Name,'before':seen[m.Name],'after':m.Value})
    seen[m.Name]=m.Value
c.close()
path.with_suffix('.airspeed-review.json').write_text(json.dumps(out,indent=2))
fig,axes=plt.subplots(6,1,figsize=(12,15),sharex=True)
def line(ax,typ,key,label):
    rr=[x for x in r[typ] if key in x]
    ax.plot([x['TimeUS']/1e6-movement for x in rr],[x[key] for x in rr],label=label,lw=1)
line(axes[0],'ARSP','Airspeed','Pitot airspeed (working ratio varies during autocal)')
line(axes[0],'GPS','Spd','GPS groundspeed')
line(axes[1],'POS','RelHomeAlt','Altitude above home')
line(axes[2],'CTUN','ThO','Commanded throttle')
line(axes[3],'ATT','Pitch','Pitch');line(axes[3],'ATT','DesPitch','Desired pitch')
line(axes[4],'ATT','Roll','Roll');line(axes[4],'ATT','DesRoll','Desired roll')
if ratio_rows:
    axes[5].plot([t-movement for t,v in ratio_rows],[v for t,v in ratio_rows],label='Ratio inferred from logged raw speed and pressure',lw=1)
for ax,label in zip(axes,('m/s','m','%','Degrees','Degrees','Ratio')):
    for t,name in ((takeoff_end,'Takeoff complete'),(approach,'Approach'),(flare,'Flare'),(end,'Disarm')):
        ax.axvline(t-movement,color='gray',ls=':',alpha=.6)
    ax.set_ylabel(label);ax.legend(loc='upper right');ax.grid(alpha=.2)
for t,name in ((takeoff_end,'Cruise'),(approach,'Approach'),(flare,'Flare'),(end,'Disarm')):
    axes[0].text(t-movement,28,name,rotation=90,va='top',fontsize=8)
axes[-1].set_xlabel('Seconds from first GPS groundspeed >= 5 m/s (launch proxy)')
fig.suptitle(path.name+' — measured airspeed and flight response; ARSPD_USE=0')
fig.tight_layout();fig.savefig(path.with_suffix('.airspeed-review.png'),dpi=140)
print(json.dumps(out,indent=2))
