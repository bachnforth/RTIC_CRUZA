/* Pure position-state helpers, shared with deterministic map tests. */
(function(root){
 function validPosition(p){return !!p && Number.isFinite(p.latitude) && Number.isFinite(p.longitude) && Math.abs(p.latitude)<=90 && Math.abs(p.longitude)<=180;}
 function positionState(v){
  if(!v.configured)return {kind:'unconfigured',position:null,track:[],label:'Telemetry/video not configured'};
  const track=(v.track||[]).filter(p=>validPosition(p)&&Number.isFinite(p.age_seconds)&&p.age_seconds>=0&&p.age_seconds<=300);
  if(v.online&&validPosition(v.position))return {kind:'live',position:v.position,track,label:'Live GPS · '+(v.position_age??0).toFixed(1)+' s old'};
  if(track.length){const last=track[track.length-1];return {kind:'last',position:last,track,label:'Last known · '+Math.round(last.age_seconds)+' s old'};}
  return {kind:'missing',position:null,track,label:!v.online?'Telemetry offline':v.gps&&v.gps.fix_type<3?'No GPS fix · '+(v.gps.satellites??'—')+' satellites':'Waiting for GPS telemetry'};
 }
 const api={validPosition,positionState};root.FleetMapState=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
