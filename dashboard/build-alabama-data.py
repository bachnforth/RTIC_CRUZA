"""Build small offline Alabama layers from Census downloads in ignored runtime/."""
from collections import defaultdict
import hashlib
import io
import json
import re
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE/'runtime'/'map-build-deps'),str(HERE.parent/'.flightlog-deps')]
import shapefile
from shapely.geometry import shape, mapping, MultiLineString
from shapely.ops import linemerge, unary_union

OUT=HERE/'dist'
def write(name,features):
    raw=(json.dumps({'type':'FeatureCollection','features':features},separators=(',',':'))+'\n').encode()
    (OUT/name).write_bytes(raw)
    print(name,len(features),len(raw),hashlib.sha256(raw).hexdigest(),flush=True)
def point(geom):
    p=geom.representative_point()
    return [round(p.x,6),round(p.y,6)]
def rounded(value):
    if isinstance(value,float): return round(value,6)
    if isinstance(value,(list,tuple)): return [rounded(x) for x in value]
    if isinstance(value,dict): return {k:rounded(v) for k,v in value.items()}
    return value
def reader(name):
    with zipfile.ZipFile(HERE/'runtime'/name) as z:
        base=next(n[:-4] for n in z.namelist() if n.endswith('.shp'))
        return shapefile.Reader(shp=io.BytesIO(z.read(base+'.shp')),shx=io.BytesIO(z.read(base+'.shx')),dbf=io.BytesIO(z.read(base+'.dbf')))

counties=json.loads((HERE/'runtime'/'al-counties-source.geojson').read_bytes())
assert len(counties['features'])==67 and not counties.get('exceededTransferLimit')
result=[]
for f in counties['features']:
    p=f['properties'];assert p['GEOID'].startswith('01')
    g=shape(f['geometry']).simplify(.00025,preserve_topology=True)
    result.append({'type':'Feature','properties':{'name':p['NAME'],'geoid':p['GEOID'],'label':point(g)},'geometry':rounded(mapping(g))})
write('al-counties.geojson',result)

major={'Birmingham','Huntsville','Montgomery','Mobile','Tuscaloosa'}
regional={'Auburn','Dothan','Decatur','Florence','Gadsden','Anniston','Opelika','Selma','Troy','Phenix City','Talladega','Enterprise','Cullman','Jasper','Fort Payne','Muscle Shoals','Gulf Shores','Fairhope','Alexander City','Prattville','Andalusia','Eufaula','Demopolis'}
result=[]
for row in reader('al-places.zip').iterShapeRecords():
    p=row.record.as_dict();assert p['STATEFP']=='01'
    g=shape(row.shape.__geo_interface__)
    minimum=6 if p['NAME'] in major else 8 if p['NAME'] in regional else 10 if p['LSAD']!='57' else 12
    result.append({'type':'Feature','properties':{'name':p['NAME'],'description':p['NAMELSAD'],'geoid':p['GEOID'],'min_zoom':minimum,'area':p['ALAND']},'geometry':{'type':'Point','coordinates':point(g)}})
assert major.issubset({f['properties']['name'] for f in result})
write('al-places.geojson',result)

routes=defaultdict(list)
for row in reader('al-roads.zip').iterShapeRecords():
    p=row.record.as_dict();kind=p.get('RTTYP');name=p.get('FULLNAME')
    if kind not in ('I','U','S') or not name:continue
    name=re.sub(r'^I-\s+', 'I-', name)
    g=shape(row.shape.__geo_interface__).simplify(.00012,preserve_topology=True)
    routes[(kind,name)].extend(list(g.geoms) if g.geom_type=='MultiLineString' else [g])
result=[]
for (kind,name),parts in sorted(routes.items()):
    merged=unary_union(parts)
    if merged.geom_type=='MultiLineString': merged=linemerge(merged)
    lines=list(merged.geoms) if merged.geom_type=='MultiLineString' else [merged]
    labels=[]
    for line in lines:
        # At most one label every ~30 km; short disconnected fragments have no label.
        if line.length < .03:continue
        count=max(1,int(line.length/.35))
        for n in range(count):labels.append(point(line.interpolate((n+.5)/count,normalized=True)))
    result.append({'type':'Feature','properties':{'name':name,'kind':kind,'labels':labels},'geometry':rounded(mapping(merged))})
assert {'I-65','I-20','I-59'}.issubset({f['properties']['name'] for f in result})
write('al-roads.geojson',result)
