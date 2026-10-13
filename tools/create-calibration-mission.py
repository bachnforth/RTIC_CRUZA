"""Build a QGC calibration plan from log 14's recorded mission; no aircraft writes."""
import sys, json, math, copy
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.flightlog-deps'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as Polygon

source=root/'logs/2026-10-13/download-102304_471623/log_00014.records.json'
records=json.loads(source.read_text())
cmds=records['CMD']
template=Path(r'C:\Users\ebach\Documents\QGroundControl\Missions\Clark_Range_T2_WITH_LAUNCH_SE_DRAFT.plan')
plan=json.loads(template.read_text())
center=(33.7244733115942,-85.91135246262625)
radius=60
duration=300
def item(cmd):
    return {'AMSLAltAboveTerrain':None,'Altitude':cmd['Alt'],'AltitudeMode':1,
            'autoContinue':True,'command':cmd['CId'],'doJumpId':0,'frame':cmd['Frame'],
            'params':[cmd['Prm1'],cmd['Prm2'],cmd['Prm3'],cmd['Prm4'],cmd['Lat'],cmd['Lng'],cmd['Alt']],
            'type':'SimpleItem'}
items=[item(c) for c in cmds[1:6]]
items.append({'AMSLAltAboveTerrain':None,'Altitude':60,'AltitudeMode':1,
              'autoContinue':True,'command':19,'doJumpId':6,'frame':3,
              'params':[duration,0,radius,1,*center,60],'type':'SimpleItem'})
items.extend(item(c) for c in cmds[6:])
for i,it in enumerate(items,1):it['doJumpId']=i
plan['mission']['items']=items
plan['mission']['plannedHomePosition']=[cmds[0]['Lat'],cmds[0]['Lng'],cmds[0]['Alt']]
plan['mission']['cruiseSpeed']=15
out=root/'missions'
out.mkdir(exist_ok=True)
name='Cruza_Airspeed_Calibration_5min_60m_2026-10-13'
path=out/(name+'.plan')
payload=json.dumps(plan,indent=4,allow_nan=False)+'\n'
path.write_text(payload)
qgc_path=template.parent/path.name
qgc_path.write_text(payload)

# Validate the serialized plan and every retained mission item against onboard evidence.
loaded=json.loads(path.read_text())
assert len(items)==10
assert [x['doJumpId'] for x in loaded['mission']['items']]==list(range(1,11))
assert items[0]['command']==22 and items[-1]['command']==21
assert all(len(x['params'])==7 and x['frame']==3 for x in items)
assert items[5]['command']==19 and items[5]['params'][0]==300
assert all(x['Altitude']==60 for x in items[:7])
original=[x for x in items if x['command']!=19]
for x,c in zip(original,cmds[1:]):
    assert x['command']==c['CId'] and x['params']==item(c)['params']
assert path.read_bytes()==qgc_path.read_bytes()
parameters=json.loads((source.parent/'parameters.json').read_text())
assert parameters['WP_LOITER_RAD']==radius

# Preview in local metric coordinates, including the previous flight's actual track.
lat0,lon0=center
mx=111195*math.cos(math.radians(lat0))
def xy(lat,lon):return ((lon-lon0)*mx,(lat-lat0)*111195)
poly=np.array([xy(c['Lat'],c['Lng']) for c in cmds[2:9]])
theta=np.linspace(0,2*math.pi,361)
orbit=np.column_stack((radius*np.cos(theta),radius*np.sin(theta)))
assert Polygon(poly).contains_points(orbit).all()
fig,ax=plt.subplots(figsize=(12,8))
gps=np.array([xy(x['Lat'],x['Lng']) for x in records['GPS']])
ax.plot(gps[:,0],gps[:,1],color='#98a2b3',lw=1,label='Previous flight actual GPS track')
pts=np.array([xy(x['params'][4],x['params'][5]) for x in items])
ax.plot(pts[:,0],pts[:,1],'o--',color='#1d4ed8',ms=5,lw=1,label='Mission waypoint connections (schematic)')
ax.plot(orbit[:,0],orbit[:,1],color='#059669',lw=3,label='5-minute loiter, nominal 60 m radius')
ax.fill(orbit[:,0],orbit[:,1],color='#059669',alpha=.10)
for i,(x,p) in enumerate(zip(items,pts),1):
    label=f'{i}: '+('Takeoff 60 m' if x['command']==22 else 'Loiter 300 s / 60 m altitude' if x['command']==19 else 'Land' if x['command']==21 else f'WP {x["Altitude"]:g} m')
    ax.annotate(label,p,xytext=(7,7 if i not in (3,5,8) else -18),textcoords='offset points',fontsize=8)
ax.annotate('',xy=(radius*.7,-radius*.7),xytext=(radius,0),arrowprops={'arrowstyle':'->','color':'#059669','lw':2})
ax.set_aspect('equal');ax.grid(alpha=.2)
ax.set_xlabel('East of loiter center (m)');ax.set_ylabel('North of loiter center (m)')
ax.set_title('Cruza calibration route: five minutes of continuous turns at 60 m\nNominal circle only; actual turns/entry/exit depend on speed, wind, and guidance')
ax.legend(loc='upper right');fig.tight_layout()
preview=out/(name+'.png');fig.savefig(preview,dpi=140)
manifest={'source_log':str(source),'qgc_plan':str(qgc_path),'workspace_plan':str(path),
          'items':len(items),'loiter_sequence':6,'loiter_command':19,'loiter_seconds':duration,
          'loiter_center_lat_lon':center,'nominal_radius_m':radius,'relative_altitude_m':60,
          'required_parameters':{'ARSPD_AUTOCAL':1,'ARSPD_USE':0,'ARSPD_SKIP_CAL':0,'WP_LOITER_RAD':60},
          'estimated_total_flight_minutes':[7,8],
          'nominal_circle_inside_previous_waypoint_outline':True,
          'notes':'Outline is not a surveyed boundary or fence. Plane timed loiter uses WP_LOITER_RAD; command radius magnitude is ignored. File created only; not loaded into QGC or uploaded.'}
(out/(name+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
