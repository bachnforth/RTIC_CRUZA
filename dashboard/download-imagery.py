"""One-time download of offline aerial imagery around the flying field.

Run this once on the laptop while it has internet. Tiles are saved under the
ignored runtime/imagery/ folder and the dashboard map then shows them without
any further network requests. Re-running skips tiles already on disk, so an
interrupted download can simply be started again.

Imagery: USGS The National Map "USGSImageryOnly" service, U.S. Government
public-domain orthoimagery (mostly USDA NAIP aerial photography).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import math
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
OUT = HERE/'runtime'/'imagery'
SOURCE = 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}'
# Planned home of the October 2026 calibration mission (missions/*.plan).
FIELD = (33.7232248, -85.9066882)
# (first zoom, last zoom, radius as a multiple of --radius-km). Wide, coarse
# imagery for context; full detail only near the field to keep the size down.
RINGS = [(11, 14, 6), (15, 16, 2.4), (17, 18, 1)]


def tile_range(lat, lon, radius_km, z):
    dlat = radius_km/111.32
    dlon = radius_km/(111.32*math.cos(math.radians(lat)))
    def tile(la, lo):
        n = 2**z
        x = int((lo+180)/360*n)
        r = math.radians(la)
        y = int((1-math.asinh(math.tan(r))/math.pi)/2*n)
        return x, y
    x0, y0 = tile(lat+dlat, lon-dlon)
    x1, y1 = tile(lat-dlat, lon+dlon)
    bounds = [[round(lat-dlat, 6), round(lon-dlon, 6)], [round(lat+dlat, 6), round(lon+dlon, 6)]]
    return [(z, x, y) for x in range(x0, x1+1) for y in range(y0, y1+1)], bounds


def fetch(job):
    z, x, y = job
    path = OUT/str(z)/str(x)/f'{y}.jpg'
    if path.exists():
        return 'kept'
    request = urllib.request.Request(SOURCE.format(z=z, x=x, y=y),
                                     headers={'User-Agent': 'cruza-fleet-dashboard offline field imagery'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as error:
            if error.code in (400, 404):
                return 'missing'
            time.sleep(2**attempt)
        except OSError:
            time.sleep(2**attempt)
    else:
        return 'failed'
    if not (raw.startswith(b'\xff\xd8') or raw.startswith(b'\x89PNG')):
        return 'missing'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    temporary.write_bytes(raw)
    temporary.replace(path)
    return 'saved'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lat', type=float, default=FIELD[0])
    parser.add_argument('--lon', type=float, default=FIELD[1])
    parser.add_argument('--radius-km', type=float, default=2.5,
                        help='full-detail radius around the field (default 2.5 km)')
    args = parser.parse_args()
    if not (-85 < args.lat < 85 and -180 <= args.lon <= 180 and 0.2 <= args.radius_km <= 10):
        sys.exit('Latitude, longitude or radius out of range.')

    layers, jobs = [], []
    for first, last, scale in RINGS:
        radius = args.radius_km*scale
        ring_jobs = []
        for z in range(first, last+1):
            tiles, bounds = tile_range(args.lat, args.lon, radius, z)
            ring_jobs += tiles
        layers.append(dict(min_zoom=first, max_native_zoom=last, radius_km=round(radius, 2), bounds=bounds))
        jobs += ring_jobs
    print(f'Downloading up to {len(jobs)} imagery tiles (about {len(jobs)*25//1000} MB) '
          f'around {args.lat:.5f}, {args.lon:.5f}. Existing tiles are skipped.', flush=True)

    counts = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for done, result in enumerate(pool.map(fetch, jobs), 1):
            counts[result] = counts.get(result, 0)+1
            if done % 100 == 0 or done == len(jobs):
                print(f'  {done}/{len(jobs)} · ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())), flush=True)

    saved = sum(1 for _ in OUT.rglob('*.jpg'))
    if not saved:
        sys.exit('No imagery was downloaded. Check the internet connection and run again.')
    manifest = dict(source='USGS The National Map — USGSImageryOnly', license='U.S. Government public domain',
                    attribution='Imagery: USGS The National Map (public domain)',
                    downloaded=datetime.date.today().isoformat(), center=[args.lat, args.lon],
                    tiles=saved, layers=layers)
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print(f'Done: {saved} tiles on disk. Restart the dashboard (or reload the page) to see them.')
    if counts.get('failed'):
        print(f'{counts["failed"]} tiles failed to download; run this again to retry them.')


if __name__ == '__main__':
    main()
