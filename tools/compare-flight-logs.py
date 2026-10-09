"""Compare AUTO takeoff and comparable level-cruise records in two analyzed logs."""
import sys,json,math,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.flightlog-deps'))
import numpy as np

def stats(values):
    a=np.asarray(values,dtype=float)
    if not len(a):return None
    return {k:float(v) for k,v in zip(('min','median','max','p95'),(a.min(),np.median(a),a.max(),np.percentile(a,95)))}

def analyze(path):
    path=Path(path)
    records=json.loads(path.with_suffix('.records.json').read_text())
    summary=json.loads(path.with_suffix('.summary.json').read_text())
    msg=records['MSG']
    events={text:next((x['TimeUS']/1e6 for x in msg if text in x['Message']),None) for text in ('Throttle armed','Triggered AUTO','Takeoff complete','Mission: 2 WP','Mission: 7 WP','Mission: 9 Land','Flare','Auto disarmed')}
    start=events['Triggered AUTO'] or events['Throttle armed']
    finish=events['Takeoff complete']
    if start is None or finish is None:raise RuntimeError(f'{path}: no completed AUTO takeoff')
    target=next(x['Alt'] for x in records['CMD'] if x['CId']==22)
    a=finish+10
    b=(events['Mission: 7 WP'] or events['Mission: 9 Land'])-10
    def window(typ,lo,hi):return [x for x in records[typ] if lo<=x['TimeUS']/1e6<=hi]
    launch=window('GPS',start,finish)
    movement=next((x['TimeUS']/1e6 for x in launch if x['Spd']>=5),None)
    full=next((x['TimeUS']/1e6 for x in window('RCOU',start,finish) if x['C4']>=1899),None)
    release=movement or start
    takepos=window('POS',release,finish)
    initial=window('POS',release,release+3)
    reach_target=next((x['TimeUS']/1e6 for x in records['POS'] if x['TimeUS']/1e6>=release and x['RelHomeAlt']>=target),None)
    cruiseatt=window('ATT',a,b)
    # Restrict comparisons to records at the cruise target altitude; remove climb/descent transitions.
    pos=records['POS']; ts=np.array([x['TimeUS']/1e6 for x in pos]); alts=np.array([x['RelHomeAlt'] for x in pos])
    def level(typ):
        rr=window(typ,a,b)
        return [x for x in rr if abs(float(np.interp(x['TimeUS']/1e6,ts,alts))-target)<=2]
    def rms(rr,actual,desired):return float(np.sqrt(np.mean([(x[actual]-x[desired])**2 for x in rr]))) if rr else None
    out={'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'events_controller_seconds':events,'mode_records':records['MODE'],'bad_data_records':summary['counts'].get('BAD_DATA',0),'error_records':records['ERR'],'mission':records['CMD'],
         'takeoff':{'target_altitude_m':target,'trigger_to_completion_s':finish-start,'movement_to_completion_s':finish-release,'movement_to_first_target_altitude_s':reach_target-release if reach_target else None,'trigger_to_first_target_altitude_s':reach_target-start if reach_target else None,'trigger_to_full_output_s':full-start if full else None,'movement_marker_s':movement,'full_output_marker_s':full,'minimum_height_first_3s_m':min(x['RelHomeAlt'] for x in initial) if initial else None,'height_at_movement_m':takepos[0]['RelHomeAlt'] if takepos else None,'throttle_percent':stats([x['ThO'] for x in window('CTUN',start,finish)]),'groundspeed_mps':stats([x['Spd'] for x in launch]),'max_climb_mps':max(-x['VZ'] for x in launch)},
         'cruise':{'window_controller_seconds':[a,b],'selection':'10 seconds after takeoff completion until 10 seconds before mission 7, within 2 m of cruise target altitude','attitude_samples':len(level('ATT')),'altitude_m':stats([x['RelHomeAlt'] for x in level('POS')]),'throttle_percent':stats([x['ThO'] for x in level('CTUN')]),'groundspeed_mps':stats([x['Spd'] for x in level('GPS')]),'estimated_airspeed_mps':stats([x['As'] for x in level('CTUN')]),'roll_error_rms_deg':rms(level('ATT'),'Roll','DesRoll'),'pitch_error_rms_deg':rms(level('ATT'),'Pitch','DesPitch')},
         'sensors':{'gps_satellites':stats([x['NSats'] for x in records['GPS']]),'gps_hdop':stats([x['HDop'] for x in records['GPS']]),'battery_voltage':stats([x['Volt'] for x in records['BAT']]),'battery_current':stats([x['Curr'] for x in records['BAT']]),'vibration_by_imu':{}},'messages':msg,'parameters':summary['parameters']}
    for i in sorted(set(x['IMU'] for x in records['VIBE'])):
        rr=window('VIBE',release,events['Mission: 9 Land'] or finish)
        rr=[x for x in rr if x['IMU']==i]
        out['sensors']['vibration_by_imu'][str(i)]={k:stats([x[k] for x in rr]) for k in ('VibeX','VibeY','VibeZ')}
        out['sensors']['vibration_by_imu'][str(i)]['clipping_count_delta']=rr[-1]['Clip']-rr[0]['Clip'] if rr else None
    straight=[x for x in level('ATT') if abs(x['DesRoll'])<5]
    out['cruise']['straight_flight_roll_error_rms_deg']=rms(straight,'Roll','DesRoll')
    out['cruise']['straight_flight_pitch_error_rms_deg']=rms(straight,'Pitch','DesPitch')
    out['cruise']['unfiltered_window_altitude_m']=stats([x['RelHomeAlt'] for x in window('POS',a,b)])
    leg_start=next(x['TimeUS']/1e6 for x in msg if x['Message']=='Mission: 5 WP')+10
    leg_end=next(x['TimeUS']/1e6 for x in msg if x['Message']=='Mission: 6 WP')-5
    leg_att=window('ATT',leg_start,leg_end)
    out['matched_waypoint5']={'window_controller_seconds':[leg_start,leg_end],'selection':'Same mission leg to waypoint 5; omit first 10 seconds and final 5 seconds','groundspeed_mps':stats([x['Spd'] for x in window('GPS',leg_start,leg_end)]),'throttle_percent':stats([x['ThO'] for x in window('CTUN',leg_start,leg_end)]),'altitude_m':stats([x['RelHomeAlt'] for x in window('POS',leg_start,leg_end)]),'roll_error_rms_deg':rms(leg_att,'Roll','DesRoll'),'pitch_error_rms_deg':rms(leg_att,'Pitch','DesPitch')}
    out['sensors']['ekf_fault_field_values']=sorted(set(x['FS'] for x in records['XKF4']))
    out['sensors']['ekf_gps_check_field_values']=sorted(set(x['GPS'] for x in records['XKF4']))
    out['landing']={'flare_message':next((x['Message'] for x in msg if x['Message'].startswith('Flare ')),None),'distance_message':next((x['Message'] for x in msg if x['Message'].startswith('Distance from LAND point=')),None),'disarm_records':[x for x in records['ARM'] if x['ArmState']==0],'auto_disarm_message':events['Auto disarmed'] is not None}
    return out

old,new=map(analyze,sys.argv[1:3])
ignored=('BARO','INS_ACC','INS_GYR','COMPASS_OFS','COMPASS_DIA','COMPASS_ODI','STAT_')
changes={k:{'before':v,'after':new['parameters'][k]} for k,v in old['parameters'].items() if k in new['parameters'] and not math.isclose(v,new['parameters'][k],rel_tol=1e-6,abs_tol=1e-5)}
result={'baseline':old,'new_flight':new,'parameter_changes':changes,'non_sensor_or_runtime_parameter_changes':{k:v for k,v in changes.items() if not k.startswith(ignored)}}
land1,land2=old['mission'][-1],new['mission'][-1]
lat1,lat2=map(math.radians,[land1['Lat'],land2['Lat']])
dlat,dlon=lat2-lat1,math.radians(land2['Lng']-land1['Lng'])
result['land_target_moved_m']=6371000*2*math.asin(math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2))
dest=Path(sys.argv[3])
dest.write_text(json.dumps(result,indent=2))
print(json.dumps({k:{n:v for n,v in r.items() if n not in ('parameters','messages','mission')} for k,r in [('baseline',old),('new_flight',new)]},indent=2))
print('Non-sensor/runtime parameter changes:',json.dumps(result['non_sensor_or_runtime_parameter_changes']))
