"""Plot two analyzed flight logs using the saved comparison's phase markers."""
import sys,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.flightlog-deps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

comparison=Path(sys.argv[1]);c=json.loads(comparison.read_text())
fig,axes=plt.subplots(2,2,figsize=(12,9))
colors=['#667085','#137a53']
labels=['Before: trim 45, before ESC calibration','After: trim 54, after ESC calibration']
origin=c['baseline']['mission'][0]
for key,color,label in zip(['baseline','new_flight'],colors,labels):
    s=c[key];r=json.loads(Path(s['file']).with_suffix('.records.json').read_text())
    start=s['takeoff']['movement_marker_s']
    for ax,typ,field in [(axes[0,0],'POS','RelHomeAlt'),(axes[0,1],'GPS','Spd')]:
        rr=[x for x in r[typ] if 0<=x['TimeUS']/1e6-start<=25]
        ax.plot([x['TimeUS']/1e6-start for x in rr],[x[field] for x in rr],color=color,label=label,lw=1.5)
    a,b=s['matched_waypoint5']['window_controller_seconds']
    rr=[x for x in r['GPS'] if a<=x['TimeUS']/1e6<=b]
    axes[1,0].plot([x['TimeUS']/1e6-a for x in rr],[x['Spd'] for x in rr],color=color,label=label,lw=1.2)
    def xy(x):return ((x['Lng']-origin['Lng'])*math.pi/180*6371000*math.cos(math.radians(origin['Lat'])),(x['Lat']-origin['Lat'])*math.pi/180*6371000)
    pts=[xy(x) for x in r['GPS']]
    axes[1,1].plot([x[0] for x in pts],[x[1] for x in pts],color=color,label=label,lw=1.2)
    land=xy(s['mission'][-1]);axes[1,1].scatter(*land,marker='x',s=65,color=color)
axes[0,0].axhline(60,color='black',ls=':',lw=1,label='60 m mission target')
axes[0,0].set(title='Climb after GPS groundspeed first exceeds 5 m/s',xlabel='Seconds after movement marker',ylabel='Altitude above home (m)')
axes[0,1].set(title='Launch groundspeed',xlabel='Seconds after movement marker',ylabel='GPS groundspeed (m/s)')
axes[1,0].set(title='Groundspeed on the same cruise leg to waypoint 5',xlabel='Seconds into trimmed leg comparison window',ylabel='GPS groundspeed (m/s)')
axes[1,1].set(title='Ground tracks; crosses mark each LAND target',xlabel='East from first flight home (m)',ylabel='North from first flight home (m)')
axes[1,1].set_aspect('equal',adjustable='datalim')
for ax in axes.flat:ax.grid(alpha=.2)
axes[0,0].legend(fontsize=8,loc='lower right')
fig.suptitle('Cruza AUTO comparison — log 9 versus log 12\nOwner reports same equipment, launch method, and conditions; LAND target moved 35.8 m')
fig.tight_layout();dest=comparison.with_suffix('.png');fig.savefig(dest,dpi=140);print(dest)
