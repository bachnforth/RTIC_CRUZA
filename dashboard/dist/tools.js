'use strict';
// Map tools: pointer coordinates (decimal, D°M′S″ or MGRS), range and bearing
// from the selected aircraft to the pointer, and a two-point measuring tool.
// Purely local display — nothing here is sent anywhere.
(function (root) {
  // ---------- Pure helpers (also used by test_tools.cjs) ----------

  const R = 6371008.8; // mean Earth radius, metres
  const rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI;

  // Great-circle distance (m) and initial bearing (degrees true) from a to b.
  function rangeBearing(a, b) {
    const p1 = rad(a.lat), p2 = rad(b.lat), dl = rad(b.lng - a.lng);
    const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    const dist = 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
    const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return {distance: dist, bearing: (deg(Math.atan2(y, x)) + 360) % 360};
  }
  function formatDistance(m) {
    if (!Number.isFinite(m)) return '—';
    return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km`;
  }
  function formatBearing(b) {
    return String(Math.round(b) % 360).padStart(3, '0') + '°';
  }

  function dms(value, pos, neg) {
    const hemi = value >= 0 ? pos : neg;
    let v = Math.abs(value), d = Math.floor(v), m = Math.floor((v - d) * 60), s = ((v - d) * 60 - m) * 60;
    if (s >= 59.95) { s = 0; m += 1; }
    if (m >= 60) { m = 0; d += 1; }
    return `${d}°${String(m).padStart(2, '0')}′${s.toFixed(1).padStart(4, '0')}″${hemi}`;
  }

  // WGS84 latitude/longitude → UTM (Krüger series, sub-metre accuracy).
  function toUtm(lat, lon) {
    const a = 6378137, f = 1 / 298.257223563, k0 = 0.9996;
    let zone = Math.floor((lon + 180) / 6) + 1;
    if (zone > 60) zone = 60;
    // Norway and Svalbard exceptions.
    if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) zone = 32;
    if (lat >= 72 && lat < 84) {
      if (lon >= 0 && lon < 9) zone = 31;
      else if (lon >= 9 && lon < 21) zone = 33;
      else if (lon >= 21 && lon < 33) zone = 35;
      else if (lon >= 33 && lon < 42) zone = 37;
    }
    const lon0 = rad((zone - 1) * 6 - 180 + 3);
    const e2 = f * (2 - f), ep2 = e2 / (1 - e2), phi = rad(lat);
    const sin = Math.sin(phi), cos = Math.cos(phi), tan = Math.tan(phi);
    const N = a / Math.sqrt(1 - e2 * sin * sin), T = tan * tan, C = ep2 * cos * cos, A = cos * (rad(lon) - lon0);
    const e4 = e2 * e2, e6 = e4 * e2;
    const M = a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
      - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
      + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi)
      - (35 * e6 / 3072) * Math.sin(6 * phi));
    const easting = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000;
    let northing = k0 * (M + N * tan * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
      + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720));
    if (lat < 0) northing += 10000000;
    return {zone, easting, northing};
  }

  // MGRS with 1 m precision (digits are truncated, as the standard requires).
  function toMgrs(lat, lon) {
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -80 || lat > 84) return null;
    lon = ((lon + 180) % 360 + 360) % 360 - 180;
    const {zone, easting, northing} = toUtm(lat, lon);
    const band = 'CDEFGHJKLMNPQRSTUVWXX'[Math.floor((lat + 80) / 8)];
    const sets = ['ABCDEFGH', 'JKLMNPQR', 'STUVWXYZ'];
    const col = sets[(zone - 1) % 3][Math.floor(easting / 100000) - 1];
    const rows = 'ABCDEFGHJKLMNPQRSTUV';
    const row = rows[(Math.floor(northing / 100000) + (zone % 2 === 0 ? 5 : 0)) % 20];
    const e = String(Math.floor(easting % 100000)).padStart(5, '0');
    const n = String(Math.floor(northing % 100000)).padStart(5, '0');
    return `${String(zone).padStart(2, "0")}${band} ${col}${row} ${e} ${n}`;
  }

  // UTM → WGS84 latitude/longitude (Snyder's series; sub-metre within a zone).
  function fromUtm(zone, easting, northing, southern) {
    const a = 6378137, f = 1 / 298.257223563, k0 = 0.9996;
    const e2 = f * (2 - f), ep2 = e2 / (1 - e2), e4 = e2 * e2, e6 = e4 * e2;
    const x = easting - 500000, y = southern ? northing - 10000000 : northing;
    const mu = y / k0 / (a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256));
    const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
    const phi1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
      + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
      + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
    const sin = Math.sin(phi1), cos = Math.cos(phi1), tan = Math.tan(phi1);
    const N1 = a / Math.sqrt(1 - e2 * sin * sin), T1 = tan * tan, C1 = ep2 * cos * cos;
    const R1 = a * (1 - e2) / (1 - e2 * sin * sin) ** 1.5, D = x / (N1 * k0);
    const lat = phi1 - (N1 * tan / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D ** 4 / 24
      + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * D ** 6 / 720);
    const lon = rad((zone - 1) * 6 - 180 + 3) + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
      + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D ** 5 / 120) / cos;
    return {lat: deg(lat), lon: deg(lon)};
  }

  // MGRS text → the centre of the grid square it names, e.g. "16S FC 12345 67890",
  // "16SFC1234567890" or "16S FC 123 678" (100 m). Spaces are optional; 2–10
  // digits. Returns {lat, lon, precision_m, mgrs} or {error}.
  const BANDS = 'CDEFGHJKLMNPQRSTUVWX';
  function fromMgrs(text) {
    const s = String(text || '').toUpperCase().replace(/\s+/g, '');
    const m = /^(\d{1,2})([C-HJ-NP-X])([A-HJ-NP-Z])([A-HJ-NP-V])(\d*)$/.exec(s);
    if (!m) return {error: 'Not an MGRS grid. Expected zone, band, square and digits, e.g. 16S FC 12345 67890.'};
    const zone = Number(m[1]), band = m[2], digits = m[5];
    if (zone < 1 || zone > 60) return {error: `Zone ${zone} does not exist (1–60).`};
    if (digits.length % 2 || digits.length > 10) return {error: 'Easting and northing need the same number of digits (2, 4, 6, 8 or 10 in all).'};
    const half = digits.length / 2, cell = 10 ** (5 - half);
    const e = half ? Number(digits.slice(0, half)) * cell : 0, n = half ? Number(digits.slice(half)) * cell : 0;
    const col = ['ABCDEFGH', 'JKLMNPQR', 'STUVWXYZ'][(zone - 1) % 3].indexOf(m[3]);
    if (col < 0) return {error: `Square letter ${m[3]} is not used in zone ${zone}.`};
    const rowIdx = ('ABCDEFGHJKLMNPQRSTUV'.indexOf(m[4]) - (zone % 2 === 0 ? 5 : 0) + 20) % 20;
    const easting = (col + 1) * 100000 + e + cell / 2;
    // The row letters repeat every 2000 km; the band says which repeat.
    const bandIdx = BANDS.indexOf(band), southern = bandIdx < 10;
    const bandSouth = -80 + bandIdx * 8, bandNorth = band === 'X' ? 84 : bandSouth + 8;
    // Northing of the band's southern edge on the zone's central meridian;
    // the 100 km margin covers points off the meridian.
    const minNorthing = toUtm(bandSouth, (zone - 1) * 6 - 180 + 3).northing - 100000;
    let northing = rowIdx * 100000 + n + cell / 2;
    while (northing < minNorthing) northing += 2000000;
    const p = fromUtm(zone, easting, northing, southern);
    // Reject squares that do not fall in the band given (typing slips). A
    // square can straddle a band edge, so allow a little either side.
    if (!Number.isFinite(p.lat) || p.lat < bandSouth - 0.5 || p.lat > bandNorth + 0.5)
      return {error: `Square ${m[3]}${m[4]} is not in band ${zone}${band}; check the letters.`};
    const pretty = `${String(zone).padStart(2, '0')}${band} ${m[3]}${m[4]}` + (half ? ` ${digits.slice(0, half)} ${digits.slice(half)}` : '');
    return {lat: p.lat, lon: p.lon, precision_m: cell, mgrs: pretty};
  }

  function formatCoords(lat, lng, format) {
    lng = ((lng + 180) % 360 + 360) % 360 - 180;
    if (format === 'mgrs') return toMgrs(lat, lng) || 'Outside MGRS (polar)';
    if (format === 'dms') return `${dms(lat, 'N', 'S')} ${dms(lng, 'E', 'W')}`;
    return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  }

  const api = {rangeBearing, formatDistance, formatBearing, toUtm, fromUtm, toMgrs, fromMgrs, formatCoords};
  root.FleetTools = api;
  if (typeof module !== 'undefined') module.exports = api;
  if (typeof document === 'undefined') return;

  // ---------- Page wiring ----------

  const fm = window.fleetMap, map = fm && fm.map;
  if (!map) return;
  const $ = s => document.querySelector(s);
  const FORMATS = ['dd', 'dms', 'mgrs'];
  let format = 'dd';
  try { format = FORMATS.includes(localStorage.getItem('fleet-coords')) ? localStorage.getItem('fleet-coords') : 'dd'; } catch (e) { /* storage unavailable */ }
  let cursor = null;

  function setFormat(f) {
    format = f;
    try { localStorage.setItem('fleet-coords', f); } catch (e) { /* storage unavailable */ }
    for (const b of document.querySelectorAll('#coord-format button')) b.classList.toggle('on', b.dataset.fmt === f);
    showCursor();
    if (a && b) drawMeasure();
  }
  for (const b of document.querySelectorAll('#coord-format button')) b.onclick = () => setFormat(b.dataset.fmt);
  $('#cursor-coords').onclick = () => setFormat(FORMATS[(FORMATS.indexOf(format) + 1) % FORMATS.length]);

  function selectedPosition() {
    const id = window.fleetUI?.selected?.(), v = fm.latest?.().find(v => v.name === id);
    const s = v && window.FleetMapState.positionState(v);
    return s && s.position ? {name: id, kind: s.kind, lat: s.position.latitude, lng: s.position.longitude} : null;
  }
  const NAMES = {cruza: 'Cruza', quadpi: 'quadpi', rn03: 'TFW drone'};

  function showCursor() {
    const out = $('#cursor-coords'), rng = $('#cursor-range');
    if (!cursor) { out.textContent = `Pointer · ${format === 'mgrs' ? 'MGRS' : format === 'dms' ? 'D°M′S″' : 'decimal'}`; rng.textContent = ''; return; }
    out.textContent = formatCoords(cursor.lat, cursor.lng, format);
    const from = selectedPosition();
    if (from) {
      const rb = rangeBearing(from, cursor);
      rng.textContent = `${NAMES[from.name]}${from.kind === 'live' ? '' : ' (last known)'} → pointer ${formatDistance(rb.distance)} · ${formatBearing(rb.bearing)}`;
    } else rng.textContent = '';
  }
  map.on('mousemove', e => { cursor = e.latlng; showCursor(); });
  map.on('mouseout', () => { cursor = null; showCursor(); });

  // ---------- Two-point range & bearing ----------

  let measuring = false, a = null, b = null, line = null, dots = [];
  const chip = $('#measure-readout'), button = $('#measure-tool');

  function clearShapes() {
    if (line) { map.removeLayer(line); line = null; }
    dots.forEach(d => map.removeLayer(d));
    dots = [];
  }
  function drawMeasure(to) {
    const end = to || b;
    if (!a) { chip.innerHTML = '<b>Measure:</b> click the first point · Esc to finish'; return; }
    const pts = end ? [a, end] : [a];
    if (!line) line = L.polyline(pts, {color: '#ffd68a', weight: 2.5, dashArray: '8 6', interactive: false}).addTo(map);
    else line.setLatLngs(pts);
    if (!end) return;
    const rb = rangeBearing(a, end), back = rangeBearing(end, a);
    const text = `${formatDistance(rb.distance)} · ${formatBearing(rb.bearing)} (back ${formatBearing(back.bearing)})`;
    chip.textContent = '';
    const strong = document.createElement('b');
    strong.textContent = text;
    chip.append(strong, document.createTextNode(b ? ' · click to start again · Esc to finish' : ' · click to set the second point'));
    line.unbindTooltip();
    if (b) line.bindTooltip(text, {permanent: true, direction: 'center', className: 'measure-label'}).openTooltip(L.latLng((a.lat + b.lat) / 2, (a.lng + b.lng) / 2));
  }
  function dot(p) { dots.push(L.circleMarker(p, {radius: 5, color: '#ffd68a', weight: 2, fillColor: '#302713', fillOpacity: 1, interactive: false}).addTo(map)); }

  function startMeasure() {
    fm.cancelPick?.();
    measuring = true; a = b = null; clearShapes();
    button.classList.add('active');
    $('#map').classList.add('measuring');
    $('#follow-fleet').checked = false;
    chip.hidden = false;
    drawMeasure();
  }
  function stopMeasure() {
    measuring = false; a = b = null; clearShapes();
    button.classList.remove('active');
    $('#map').classList.remove('measuring');
    chip.hidden = true;
  }
  function toggleMeasure() { measuring ? stopMeasure() : startMeasure(); }
  button.onclick = toggleMeasure;

  map.on('click', e => {
    if (!measuring || $('#map').classList.contains('pick-point')) return;
    const p = e.latlng;
    if (!a || b) { clearShapes(); a = p; b = null; dot(p); drawMeasure(); }
    else { b = p; dot(p); drawMeasure(); }
  });
  map.on('mousemove', e => { if (measuring && a && !b) drawMeasure(e.latlng); });
  // Starting a preview point pick ends measuring, so one click never does both.
  document.querySelector('#wf-pick')?.addEventListener('click', () => { if (measuring) stopMeasure(); });

  window.fleetTools = {toggleMeasure, stopMeasure, measuring: () => measuring};
  setFormat(format);
})(typeof window === 'undefined' ? globalThis : window);
