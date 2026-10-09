"""Summarize DataFlash records and plot flight control / propulsion evidence."""
import sys, json, collections
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.flightlog-deps'))
from pymavlink import mavutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

path=Path(sys.argv[1]); c=mavutil.mavlink_connection(str(path))
rows=collections.defaultdict(list); counts=collections.Counter(); params={}
wanted={'MSG','MODE','EV','ERR','ARM','ATT','RATE','RCOU','RCIN','BAT','GPS','POS','CTUN','NTUN','TECS','PIDP','PIDR','VIBE','XKF4','CMD'}
while True:
    m=c.recv_match()
    if m is None:break
    typ=m.get_type(); counts[typ]+=1
    if typ=='PARM':params[m.Name]=m.Value
    if typ in wanted:rows[typ].append(m.to_dict())
summary={'file':str(path),'counts':dict(counts),'parameters':params}
for typ in ('MSG','MODE','EV','ERR','ARM','CMD'):
    summary[typ]=rows[typ]
for typ in ('ATT','RCOU','RCIN','BAT','GPS','POS','CTUN','RATE','VIBE'):
    summary[typ+'_ranges']={}
    if not rows[typ]:continue
    for k in rows[typ][0]:
        vals=[r[k] for r in rows[typ] if isinstance(r.get(k),(int,float))]
        if vals:summary[typ+'_ranges'][k]={'min':min(vals),'max':max(vals),'median':float(np.median(vals))}
path.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2))
path.with_suffix('.records.json').write_text(json.dumps(rows))
fig,axes=plt.subplots(5,1,figsize=(12,13),sharex=True)
base=min(r['TimeUS'] for rr in rows.values() for r in rr if 'TimeUS' in r)/1e6
def line(ax,typ,key,label):
    rr=[r for r in rows[typ] if key in r and 'TimeUS' in r]
    if rr:ax.plot([r['TimeUS']/1e6-base for r in rr],[r[key] for r in rr],label=label,lw=0.8)
line(axes[0],'ATT','Pitch','Pitch');line(axes[0],'ATT','DesPitch','Desired pitch')
line(axes[1],'ATT','Roll','Roll');line(axes[1],'ATT','DesRoll','Desired roll')
line(axes[2],'RCOU','C4','Throttle PWM');line(axes[2],'RCIN','C3','RC throttle')
line(axes[3],'GPS','Spd','GPS groundspeed');line(axes[3],'POS','RelHomeAlt','Altitude above home')
line(axes[4],'BAT','Volt','Voltage');line(axes[4],'BAT','Curr','Current')
for ax in axes:
    for r in rows['MODE']:
        t=r['TimeUS']/1e6-base;ax.axvline(t,color='gray',alpha=.3)
    if ax.get_legend_handles_labels()[0]:ax.legend(loc='upper right')
    ax.grid(alpha=.2)
for ax,label in zip(axes,['Degrees','Degrees','Microseconds','m/s and m','V and A']):ax.set_ylabel(label)
axes[-1].set_xlabel('Seconds from first logged record')
fig.suptitle(path.name+' — flight controls and propulsion');fig.tight_layout()
fig.savefig(path.with_suffix('.png'),dpi=130)
print(json.dumps({k:v for k,v in summary.items() if k!='parameters'},indent=2))
