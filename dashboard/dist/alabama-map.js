'use strict';
(function(){
const bounds=[[30.14,-88.48],[35.02,-84.85]];
function attach(map){
 const area=L.latLngBounds(bounds),toggles={counties:document.querySelector('#al-counties'),cities:document.querySelector('#al-cities'),roads:document.querySelector('#al-roads')};
 for(const [name,z] of [['alCounties',270],['alRoads',280],['alPlaces',320],['alLabels',370]]){map.createPane(name).style.zIndex=z;}
 map.getPane('alLabels').style.pointerEvents='none';
 const county=L.layerGroup(),roadGroups={I:L.layerGroup(),U:L.layerGroup(),S:L.layerGroup()},dots=L.layerGroup(),labels=L.layerGroup().addTo(map),renderer=L.canvas({pane:'alRoads',padding:.1});
 const colors={I:'#f4b365',U:'#d6c18a',S:'#819ca8'};let data=null,loading=false,failed=false;
 function toggle(layer,on){if(on&&!map.hasLayer(layer))layer.addTo(map);else if(!on&&map.hasLayer(layer))map.removeLayer(layer);}
 function load(){if(data||loading||failed)return;loading=true;document.querySelector('#al-detail-status').textContent='Loading local Alabama detail…';
  Promise.all(['al-counties.geojson','al-places.geojson','al-roads.geojson'].map(path=>fetch('/'+path).then(r=>{if(!r.ok)throw Error(path);return r.json();}))).then(([counties,places,roads])=>{
   data={counties:counties.features,places:places.features.sort((a,b)=>a.properties.min_zoom-b.properties.min_zoom||b.properties.area-a.properties.area),roads:roads.features};
   L.geoJSON(counties,{pane:'alCounties',style:{color:'#95adb9',weight:1,opacity:.7,dashArray:'3 4',fill:false},onEachFeature:(f,l)=>l.bindTooltip(f.properties.name,{sticky:true})}).addTo(county);
   for(const f of roads.features){const kind=f.properties.kind;L.geoJSON(f,{pane:'alRoads',renderer,style:{color:colors[kind],weight:kind==='I'?2.6:kind==='U'?1.8:1.2,opacity:.9},onEachFeature:(feature,l)=>l.bindTooltip(feature.properties.name,{sticky:true})}).addTo(roadGroups[kind]);}
   map.attributionControl.addAttribution('AL: U.S. Census Bureau');loading=false;render();
  }).catch(()=>{loading=false;failed=true;document.querySelector('#al-detail-status').textContent='Alabama detail unavailable. Reload to retry the local files.';});
 }
 function render(){const z=map.getZoom(),visible=z>=5&&map.getBounds().intersects(area);if(visible)load();
  toggle(county,visible&&z>=6&&toggles.counties.checked);toggle(roadGroups.I,visible&&z>=6&&toggles.roads.checked);toggle(roadGroups.U,visible&&z>=7&&toggles.roads.checked);toggle(roadGroups.S,visible&&z>=9&&toggles.roads.checked);dots.clearLayers();labels.clearLayers();
  if(!data)return;
  const candidates=[];
  if(visible&&toggles.cities.checked){for(const f of data.places){if(z<f.properties.min_zoom)continue;const [lon,lat]=f.geometry.coordinates;if(!map.getBounds().contains([lat,lon]))continue;
    L.circleMarker([lat,lon],{pane:'alPlaces',radius:f.properties.min_zoom===6?3.6:2.4,weight:1,color:'#eff6fb',fillColor:'#d0e5f2',fillOpacity:1}).bindTooltip(f.properties.description,{direction:'top'}).addTo(dots);
    candidates.push({text:f.properties.name,loc:[lat,lon],kind:'city',priority:f.properties.min_zoom===6?0:3});
  }}toggle(dots,visible&&toggles.cities.checked);
  if(visible&&toggles.roads.checked){for(const f of data.roads){const p=f.properties;if(z<(p.kind==='I'?7:p.kind==='U'?9:11))continue;for(const [lon,lat] of p.labels){if(map.getBounds().contains([lat,lon]))candidates.push({text:p.name.replace(/^US Hwy /,'US ').replace(/^State Hwy /,'AL ').replace(/^State Rte /,'AL '),loc:[lat,lon],kind:'road',priority:p.kind==='I'?1:p.kind==='U'?2:4});}}}
  if(visible&&z>=8&&toggles.counties.checked){for(const f of data.counties){const [lon,lat]=f.properties.label;if(map.getBounds().contains([lat,lon]))candidates.push({text:f.properties.name.replace(/ County$/,' Co.'),loc:[lat,lon],kind:'county',priority:5});}}
  // Select visible labels in priority order; avoid collisions between cities,
  // route badges and county names instead of placing every label at once.
  const occupied=[],size=map.getSize();candidates.sort((a,b)=>a.priority-b.priority);
  for(const c of candidates){const p=map.latLngToContainerPoint(c.loc),w=Math.min(150,c.text.length*(c.kind==='county'?5.5:6.2)+12),h=18,x=c.kind==='city'?p.x+6:p.x-w/2,y=p.y-9;
   if(x<2||y<2||x+w>size.x-2||y+h>size.y-2)continue;
   if(occupied.some(b=>x<b.x+b.w+5&&x+w+5>b.x&&y<b.y+b.h+4&&y+h+4>b.y))continue;
   occupied.push({x,y,w,h});const text=document.createElement('span');text.textContent=c.text;
   L.marker(c.loc,{pane:'alLabels',keyboard:false,interactive:false,icon:L.divIcon({className:'al-label '+c.kind,html:text,iconSize:[w,h],iconAnchor:[c.kind==='city'?-6:w/2,9]})}).addTo(labels);
  }
  if(!visible)document.querySelector('#al-detail-status').textContent='Alabama detail appears as you zoom into the state.';
  else document.querySelector('#al-detail-status').textContent='Alabama · '+(z<6?'zoom in for counties and highways':z<8?'counties, major cities and highways':z<10?'county names, cities and highways':z<12?'towns and state highways':'cities, towns, Census places and major roads');
 }
 for(const toggle of Object.values(toggles))toggle.onchange=render;
 map.on('moveend zoomend',render);render();
}
window.AlabamaMap={attach,bounds};
})();
