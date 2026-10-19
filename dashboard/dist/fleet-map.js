'use strict';
(function(){
const titles={cruza:'Cruza',quadpi:'quadpi',rn03:'RN03 aircraft'},colors={cruza:'#7ce1ba',quadpi:'#7dbcf4',rn03:'#d3a9ed'};
const map=L.map('map',{minZoom:1,maxZoom:19,worldCopyJump:true,scrollWheelZoom:false}).setView([39,-98],3);
map.createPane('basemap').style.zIndex=240;
map.createPane('stateBorders').style.zIndex=300;
map.createPane('stateLabels').style.zIndex=350;
map.getPane('stateLabels').style.pointerEvents='none';
L.control.scale({imperial:false}).addTo(map);
const layers={},follow=document.querySelector('#follow-fleet');let latest=[],fitting=false,streets=null,countries=null,overviewMode=true;
map.on('dragstart zoomstart',e=>{if(!fitting && (e.type==='dragstart'||e.originalEvent)){follow.checked=false;overviewMode=false;}});
map.on('zoomstart',()=>{if(!fitting){follow.checked=false;overviewMode=false;}});
new ResizeObserver(()=>{map.invalidateSize({pan:false});if(overviewMode)usOverview(overviewMode);}).observe(document.querySelector('#map'));
fetch('/world.geojson').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{
 countries=L.geoJSON(data,{pane:'basemap',style:{color:'#456476',weight:1,fillColor:'#284657',fillOpacity:1},onEachFeature:(f,l)=>{l.bindTooltip(f.properties.NAME||f.properties.ADMIN||'');}});
 if(!streets)countries.addTo(map).bringToBack();map.attributionControl.addAttribution('Overview: Natural Earth (public domain)');
}).catch(()=>{document.querySelector('#map-layer-note').textContent='Offline outlines unavailable; aircraft markers still work.';});
// Offline borders and postal labels; all coordinates are public basemap data.
let stateLabels=[];
function showStateLabels(){
 const zoom=map.getZoom();
 for(const {marker,large,postal} of stateLabels){const show=!(postal==='AL'&&zoom>=6)&&(zoom>=5||(zoom>=4&&large>3)||(zoom>=3&&large>18));if(show&&!map.hasLayer(marker))marker.addTo(map);else if(!show&&map.hasLayer(marker))map.removeLayer(marker);}
}
map.on('zoomend',showStateLabels);
fetch('/us-states.geojson').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{
 L.geoJSON(data,{pane:'stateBorders',style:{color:'#94b7ca',weight:1.3,opacity:.85,fill:false},onEachFeature:(f,l)=>{
  l.bindTooltip(f.properties.name+' · '+f.properties.postal,{sticky:true});
  const p=f.properties;if(!Number.isFinite(p.label_lat)||!Number.isFinite(p.label_lon))return;
  const span=document.createElement('span');span.textContent=p.postal;
  const marker=L.marker([p.label_lat,p.label_lon],{pane:'stateLabels',interactive:false,keyboard:false,icon:L.divIcon({className:'state-label',html:span,iconSize:[28,16],iconAnchor:[14,8]})});
  const b=l.getBounds();stateLabels.push({marker,postal:p.postal,large:(b.getEast()-b.getWest())*(b.getNorth()-b.getSouth())});
 }}).addTo(map);showStateLabels();
}).catch(()=>{document.querySelector('#map-layer-note').textContent='State outlines unavailable. Aircraft positions and the world overview still work.';});
function usOverview(region='us'){overviewMode=region;fitting=true;try{map.fitBounds(region==='alabama'?AlabamaMap.bounds:[[24,-125],[50,-66]],{padding:[12,12],animate:false});}finally{fitting=false;}}
// The overview is a map location, never an inferred aircraft position.
usOverview();
document.querySelector('#us-view').onclick=()=>{follow.checked=false;usOverview();};
document.querySelector('#al-view').onclick=()=>{follow.checked=false;usOverview('alabama');};
AlabamaMap.attach(map);
function fit(){const points=latest.map(v=>FleetMapState.positionState(v)).filter(s=>s.position).map(s=>[s.position.latitude,s.position.longitude]);if(!points.length)return;overviewMode=false;fitting=true;try{map.fitBounds(L.latLngBounds(points),{padding:[60,50],maxZoom:16,animate:false});}finally{fitting=false;}}
function focus(v){const s=FleetMapState.positionState(v);if(!s.position)return;overviewMode=false;follow.checked=false;map.setView([s.position.latitude,s.position.longitude],Math.max(map.getZoom(),16),{animate:false});layers[v.name]?.marker?.openPopup();}
function popup(v,s){const box=document.createElement('div'),title=document.createElement('strong');title.textContent=titles[v.name];box.append(title,document.createElement('br'));box.append(document.createTextNode(s.label),document.createElement('br'));box.append(document.createTextNode(s.position.latitude.toFixed(6)+', '+s.position.longitude.toFixed(6)));if(s.kind==='live'&&Number.isFinite(s.position.altitude_relative_m)){box.append(document.createElement('br'),document.createTextNode('Relative altitude '+s.position.altitude_relative_m.toFixed(1)+' m'));}if(s.kind==='live'&&Number.isFinite(v.airspeed_m_s)){box.append(document.createElement('br'),document.createTextNode('Airspeed '+v.airspeed_m_s.toFixed(1)+' m/s'));}if(s.kind==='live'&&v.home){box.append(document.createElement('br'),document.createTextNode(Math.round(v.home.distance_m)+' m from '+v.home.reference));}return box;}
function update(fleet){latest=fleet;const legend=document.querySelector('#map-legend');legend.replaceChildren();let live=0,last=0;
 for(const id of Object.keys(titles)){
  const v=fleet.find(v=>v.name===id)||{name:id,configured:id!=='rn03',online:false};const s=FleetMapState.positionState(v);const group=layers[id]||(layers[id]={});const color=colors[id];
  if(s.position){const loc=[s.position.latitude,s.position.longitude];const active=s.kind==='live';live+=active?1:0;last+=active?0:1;
   if(!group.marker){group.marker=L.circleMarker(loc,{radius:9,weight:3}).addTo(map);group.marker.bindTooltip('',{permanent:true,direction:'top',offset:[0,-10],className:'aircraft-label'});}
   group.marker.setLatLng(loc).setStyle({color:active?color:'#93a6b2',fillColor:active?color:'#243b49',fillOpacity:active?.9:.5,dashArray:active?null:'4 4'});
   group.marker.setTooltipContent(titles[id]+(active?'':' · last known'));group.marker.bindPopup(popup(v,s));group.marker.bringToFront();const hdg=active&&Number.isFinite(v.heading_deg)?v.heading_deg:null;if(hdg!==null){const html=`<svg viewBox="-20 -20 40 40" width="40" height="40" style="transform:rotate(${hdg}deg)"><path d="M0 -19 L6 -9 L-6 -9 Z" fill="${color}" stroke="#0a1017" stroke-width="1.5"/></svg>`;if(!group.arrow)group.arrow=L.marker(loc,{interactive:false,keyboard:false,icon:L.divIcon({className:'heading-arrow',html,iconSize:[40,40],iconAnchor:[20,20]})}).addTo(map);else{group.arrow.setLatLng(loc);group.arrow.getElement()&&(group.arrow.getElement().innerHTML=html);}}else if(group.arrow){map.removeLayer(group.arrow);group.arrow=null;}
  }else if(group.marker){map.removeLayer(group.marker);group.marker=null;if(group.arrow){map.removeLayer(group.arrow);group.arrow=null;}}
  const trail=s.track.map(p=>[p.latitude,p.longitude]);if(trail.length>1){if(!group.trail)group.trail=L.polyline(trail,{color,weight:2,opacity:.6,interactive:false}).addTo(map);else group.trail.setLatLngs(trail);}else if(group.trail){map.removeLayer(group.trail);group.trail=null;}
  const button=document.createElement('button');button.className='map-aircraft';button.disabled=!s.position;const title=document.createElement('strong'),swatch=document.createElement('i');swatch.className='swatch';swatch.style.background=color;title.append(swatch,document.createTextNode(titles[id]));const text=document.createElement('span');text.textContent=s.label;button.append(title,text);if(s.position){const coords=document.createElement('span');coords.textContent=s.position.latitude.toFixed(5)+', '+s.position.longitude.toFixed(5);button.append(coords);button.onclick=()=>focus(v);}legend.append(button);
 }
 document.querySelector('#map-status').textContent=`${live} live · ${last} last known · ${3-live-last} without a position`;
 const empty=document.querySelector('#map-empty');empty.hidden=live+last>0;empty.textContent='No usable GPS positions yet. Aircraft will appear automatically when valid telemetry arrives.';
 document.querySelector('#fit-fleet').disabled=live+last===0;if(follow.checked)fit();
}
 document.querySelector('#fit-fleet').onclick=()=>{follow.checked=true;fit();};follow.onchange=()=>{if(follow.checked)fit();};
 document.querySelector('#map-fullscreen').onclick=()=>{const box=document.querySelector('main');(document.fullscreenElement?document.exitFullscreen():box.requestFullscreen()).catch(()=>{});};
 document.addEventListener('fullscreenchange',()=>{document.querySelector('#map-fullscreen').textContent=document.fullscreenElement?'Exit dashboard fullscreen':'Expand dashboard';map.invalidateSize({pan:false});});
 document.querySelector('#street-map').onclick=()=>{
  const b=document.querySelector('#street-map'),note=document.querySelector('#map-layer-note');
  if(streets){map.removeLayer(streets);streets=null;if(countries)countries.addTo(map).bringToBack();b.textContent='Enable street map';b.setAttribute('aria-pressed','false');note.textContent='Street maps share the viewed area and your IP with OpenStreetMap.';return;}
  streets=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>',keepBuffer:1});
  streets.on('tileerror',()=>{note.textContent='Street tiles unavailable. Switch off street maps for the offline overview; aircraft markers remain available.';});streets.addTo(map);if(countries)map.removeLayer(countries);b.textContent='Use offline overview';b.setAttribute('aria-pressed','true');note.textContent='Online street map · Visible map areas are requested from OpenStreetMap. Aircraft telemetry stays on this laptop.';
 };
 window.fleetMap={update};
})();
