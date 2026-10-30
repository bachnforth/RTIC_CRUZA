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

  function formatCoords(lat, lng, format) {
    lng = ((lng + 180) % 360 + 360) % 360 - 180;
    if (format === 'mgrs') return toMgrs(lat, lng) || 'Outside MGRS (polar)';
    if (format === 'dms') return `${dms(lat, 'N', 'S')} ${dms(lng, 'E', 'W')}`;
    return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  }

  const api = {rangeBearing, formatDistance, formatBearing, toUtm, toMgrs, formatCoords};
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
