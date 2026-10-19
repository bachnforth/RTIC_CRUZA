'use strict';
(function(){
const titles={cruza:'Cruza',quadpi:'quadpi',rn03:'RN03 aircraft'},colors={cruza:'#7ce1ba',quadpi:'#7dbcf4',rn03:'#d3a9ed'};
const map=L.map('map',{minZoom:1,maxZoom:19,worldCopyJump:true,scrollWheelZoom:false}).setView([39,-98],3);
map.createPane('basemap').style.zIndex=240;
map.createPane('stateBorders').style.zIndex=300;
map.createPane('stateLabels').style.zIndex=350;
map.getPane('stateLabels').style.pointerEvents='none';
L.control.scale({imperial:false}).addTo(map);
const layers={},follow=document.querySelector('#follow-fleet');let latest=[],fitting=false,streets=null,countries=null,overviewMode=true,field=null;
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
function usOverview(region='us'){overviewMode=region;fitting=true;try{map.fitBounds(region==='field'&&field?field:region==='alabama'?AlabamaMap.bounds:[[24,-125],[50,-66]],{padding:[12,12],animate:false});}finally{fitting=false;}}
// The overview is a map location, never an inferred aircraft position.
usOverview();
document.querySelector('#us-view').onclick=()=>{follow.checked=false;usOverview();};
document.querySelector('#al-view').onclick=()=>{follow.checked=false;usOverview('alabama');};
AlabamaMap.attach(map);
// Offline aerial imagery saved once by download-imagery.py (USGS, public domain).
// Coarse wide rings sit under the detailed one; no request leaves this laptop.
map.createPane('imagery').style.zIndex=250;
fetch('/imagery/manifest.json').then(r=>{if(!r.ok)throw Error();return r.json();}).then(m=>{
 const group=L.layerGroup(m.layers.map(l=>L.tileLayer('/imagery/{z}/{x}/{y}',{pane:'imagery',bounds:l.bounds,minZoom:l.min_zoom,maxNativeZoom:l.max_native_zoom,maxZoom:19,keepBuffer:1}))).addTo(map);
 map.attributionControl.addAttribution(m.attribution);
 field=L.latLngBounds(m.layers[m.layers.length-1].bounds);
 const button=document.querySelector('#field-view'),toggle=document.querySelector('#imagery');
 button.hidden=false;button.onclick=()=>{follow.checked=false;usOverview('field');};
 toggle.closest('label').hidden=false;toggle.onchange=()=>{if(toggle.checked)group.addTo(map);else map.removeLayer(group);};
 if(overviewMode==='us')usOverview('field');
}).catch(()=>{});
function fit(){const points=latest.map(v=>FleetMapState.positionState(v)).filter(s=>s.position).map(s=>[s.position.latitude,s.position.longitude]);if(!points.length)return;overviewMode=false;fitting=true;try{map.fitBounds(L.latLngBounds(points),{padding:[60,50],maxZoom:16,animate:false});}finally{fitting=false;}}
function focus(v){const s=FleetMapState.positionState(v);if(!s.position)return;overviewMode=false;follow.checked=false;map.setView([s.position.latitude,s.position.longitude],Math.max(map.getZoom(),16),{animate:false});layers[v.name]?.marker?.openPopup();}
function popup(v,s){const box=document.createElement('div'),title=document.createElement('strong');title.textContent=titles[v.name];box.append(title,document.createElement('br'));box.append(document.createTextNode(s.label),document.createElement('br'));box.append(document.createTextNode(s.position.latitude.toFixed(6)+', '+s.position.longitude.toFixed(6)));if(s.kind==='live'&&Number.isFinite(s.position.altitude_relative_m)){box.append(document.createElement('br'),document.createTextNode('Relative altitude '+s.position.altitude_relative_m.toFixed(1)+' m'));}if(s.kind==='live'&&Number.isFinite(v.airspeed_m_s)){box.append(document.createElement('br'),document.createTextNode('Airspeed '+v.airspeed_m_s.toFixed(1)+' m/s'));}if(s.kind==='live'&&v.home){box.append(document.createElement('br'),document.createTextNode(Math.round(v.home.distance_m)+' m from '+v.home.reference));}return box;}
// Top-down aircraft silhouettes, nose up; the marker rotates to the heading.
// Cruza is a conventional twin-motor Hee Wing T2; quadpi and the RN03 Mini are X quads.
const PLANE='<path class="hull" d="M0-19c1.6 0 2.4 1.8 2.4 4V-4L21-2.6c.9.1 1.2.6 1.2 1.3v2.2c0 .6-.4 1-1.1 1L2.4 2.6 2 12.4 8 13.6c.6.1.9.5.9 1v1.6c0 .5-.4.9-1 .9H1.2L0 19l-1.2-1.9h-6.7c-.6 0-1-.4-1-.9v-1.6c0-.5.3-.9.9-1L-2 12.4l-.4-9.8-18.7-.7c-.7 0-1.1-.4-1.1-1v-2.2c0-.7.3-1.2 1.2-1.3L-2.4-4v-11c0-2.2.8-4 2.4-4z"/><rect class="pod" x="-10" y="-8" width="3.6" height="9" rx="1.8"/><rect class="pod" x="6.4" y="-8" width="3.6" height="9" rx="1.8"/><path class="prop" d="M-13.2-8.6h9.6M3.6-8.6h9.6"/>';
const quad=(r,arm)=>{const k=arm*.7071,disc=(x,y,front)=>`<circle class="rotor${front?' front':''}" cx="${x}" cy="${y}" r="${r}"/>`;return `<path class="arm" d="M${-k} ${-k}L${k} ${k}M${k} ${-k}L${-k} ${k}"/>${disc(-k,-k,1)}${disc(k,-k,1)}${disc(-k,k)}${disc(k,k)}<rect class="hull" x="-4" y="-6" width="8" height="12" rx="2.5"/><path class="nose" d="M0-10l3 4h-6z"/>`;};
const SHAPES={cruza:PLANE,quadpi:quad(6.5,15),rn03:quad(5,11)},SIZES={cruza:56,quadpi:46,rn03:38};
function aircraftSvg(id,size){return `<svg class="ac-svg" viewBox="-24 -24 48 48" width="${size}" height="${size}" aria-hidden="true">${SHAPES[id]}</svg>`;}
function update(fleet){latest=fleet;const legend=document.querySelector('#map-legend');legend.replaceChildren();let live=0,last=0;
 for(const id of Object.keys(titles)){
  const v=fleet.find(v=>v.name===id)||{name:id,configured:id!=='rn03',online:false};const s=FleetMapState.positionState(v);const group=layers[id]||(layers[id]={});const color=colors[id];
  if(s.position){const loc=[s.position.latitude,s.position.longitude];const active=s.kind==='live';live+=active?1:0;last+=active?0:1;
   if(!group.marker){const size=SIZES[id];group.marker=L.marker(loc,{keyboard:false,icon:L.divIcon({className:'ac-marker',html:`<div class="ac" style="--c:${color}">${aircraftSvg(id,size)}</div>`,iconSize:[size,size],iconAnchor:[size/2,size/2],popupAnchor:[0,-size/2]})}).addTo(map);group.marker.bindTooltip('',{permanent:true,direction:'top',offset:[0,-size/2+2],className:'aircraft-label'});}
   group.marker.setLatLng(loc).setZIndexOffset(1000);const hdg=active&&Number.isFinite(v.heading_deg)?v.heading_deg:null;const el=group.marker.getElement();
   if(el){const ac=el.querySelector('.ac');const prev=+ac.dataset.rot||0,turn=((((hdg??0)-prev)%360)+540)%360-180;ac.dataset.rot=prev+turn;ac.style.transform=`rotate(${prev+turn}deg)`;ac.classList.toggle('stale',!active);ac.classList.toggle('no-heading',active&&hdg===null);}
   const armed=active&&v.armed===true;group.marker.setTooltipContent(titles[id]+(armed?' · ARMED':active?'':' · last known'));group.marker.getTooltip().getElement()?.classList.toggle('armed',armed);group.marker.bindPopup(popup(v,s));
  }else if(group.marker){map.removeLayer(group.marker);group.marker=null;}
  const trail=s.track.map(p=>[p.latitude,p.longitude]);if(trail.length>1){if(!group.trail)group.trail=L.polyline(trail,{color,weight:2,opacity:.6,interactive:false}).addTo(map);else group.trail.setLatLngs(trail);}else if(group.trail){map.removeLayer(group.trail);group.trail=null;}
  const button=document.createElement('button');button.className='map-aircraft';button.disabled=!s.position;const title=document.createElement('strong'),swatch=document.createElement('i');swatch.className='swatch-ac';swatch.style.setProperty('--c',color);swatch.innerHTML=aircraftSvg(id,18);title.append(swatch,document.createTextNode(titles[id]));const text=document.createElement('span');text.textContent=s.label;button.append(title,text);if(s.position){const coords=document.createElement('span');coords.textContent=s.position.latitude.toFixed(5)+', '+s.position.longitude.toFixed(5);button.append(coords);button.onclick=()=>focus(v);}legend.append(button);
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
