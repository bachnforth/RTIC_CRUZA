'use strict';
// Fleet dashboard page: aircraft tiles, detail drawer, picture-in-picture video,
// alerts and graphs. Everything here is read-only; the page never sends
// anything to an aircraft.

const AIRCRAFT = [
  {id: 'cruza', name: 'Cruza', route: 'Fixed wing · LTE / VPN', color: '#7ce1ba', video: true, fixedWing: true},
  {id: 'quadpi', name: 'quadpi', route: '10-inch quad · wearable radio / mesh', color: '#7dbcf4', video: true},
  {id: 'rn03', name: 'TFW drone', route: '10-inch quad · wearable radio / mesh', color: '#d3a9ed', video: false},
];
const byId = Object.fromEntries(AIRCRAFT.map(a => [a.id, a]));
const names = Object.fromEntries(AIRCRAFT.map(a => [a.id, [a.name, a.route]]));
const colors = Object.fromEntries(AIRCRAFT.map(a => [a.id, a.color]));
const VIDEO_URL = id => `http://127.0.0.1:8889/${id}?controls=false&muted=true`;
const $ = sel => document.querySelector(sel);

let watching = true, previous = {}, failures = 0, busy = false, lastFleet = [];

// ---------- Saved layout preferences (this browser only) ----------

const ui = Object.assign({selected: 'cruza', size: 'm', minimized: [], msgFilter: 'all', msgSeen: 0},
  (() => { try { return JSON.parse(localStorage.getItem('fleet-ui') || '{}'); } catch (e) { return {}; } })());
if (!byId[ui.selected]) ui.selected = 'cruza';
function save() { try { localStorage.setItem('fleet-ui', JSON.stringify(ui)); } catch (e) { /* storage unavailable */ } }
let mainView = 'map', openPanelName = null;

// ---------- Small DOM helpers ----------

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function icon(name, cls = 'i') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  return svg;
}
function iconButton(name, title, act) {
  const b = el('button');
  b.type = 'button';
  b.title = title;
  b.setAttribute('aria-label', title);
  if (act) b.dataset.act = act;
  b.append(icon(name));
  return b;
}

// ---------- Formatting helpers ----------

function fmt(v, unit = '', digits = 1) {
  return v === null || v === undefined ? '—' : typeof v === 'number' ? v.toFixed(digits) + unit : String(v) + unit;
}
function compass(deg) {
  if (deg === null || deg === undefined) return '—';
  const points = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  return `${Math.round(deg)}° ${points[Math.round(deg / 45) % 8]}`;
}
function ago(seconds) {
  if (seconds < 60) return Math.round(seconds) + ' s ago';
  return Math.floor(seconds / 60) + ' min ago';
}
function metric(label, value, level) {
  const n = el('div', 'metric' + (level ? ' ' + level : ''));
  n.append(el('small', '', label), el('span', '', value));
  return n;
}
const LEVEL_LABEL = {critical: 'CRITICAL', warning: 'WARNING', notice: 'EVENT', info: 'INFO'};

// ---------- Top tiles ----------

const tiles = {};
AIRCRAFT.forEach((a, i) => {
  const t = el('div', 'tile');
  t.id = a.id; // also used by the command preview to highlight its platform
  t.tabIndex = 0;
  t.setAttribute('role', 'button');
  t.setAttribute('aria-label', `${a.name} — select (key ${i + 1})`);
  t.style.setProperty('--c', a.color);
  const top = el('div', 'tile-name');
  top.append(el('b', '', a.name), el('span', 'tile-state', 'WAITING'), el('kbd', '', String(i + 1)));
  const acts = el('div', 'tile-acts');
  acts.append(iconButton('center', `Center map on ${a.name} (G)`, 'center'));
  if (a.video) acts.append(iconButton('video', `Swap ${a.name} video with the map (S)`, 'video'));
  t.append(top, acts, el('div', 'tile-mode', a.route), el('div', 'tile-vals'));
  t.addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'center') { select(a.id); centerOn(a.id); return; }
    if (act === 'video') { select(a.id); swapMain(a.id); return; }
    if (ui.selected === a.id && openPanelName === 'aircraft') closeDrawer();
    else { select(a.id); openPanel('aircraft'); }
  });
  t.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target === t) { e.preventDefault(); t.click(); }
  });
  tiles[a.id] = t;
  $('#tiles').append(t);
});

function batteryLevel(v, alertLevel) {
  if (alertLevel) return alertLevel;
  return v.battery_percent !== null && v.battery_percent !== undefined && v.battery_percent < 25 ? 'warning' : '';
}

function renderTile(v) {
  const a = byId[v.name], t = tiles[v.name];
  if (!t) return;
  const state = t.querySelector('.tile-state'), mode = t.querySelector('.tile-mode'), vals = t.querySelector('.tile-vals');
  const alerts = v.alerts || [];
  const crit = alerts.some(x => x.level === 'critical');
  t.classList.toggle('unconfigured', !v.configured);
  t.classList.toggle('has-critical', crit);
  t.classList.toggle('has-warning', !crit && alerts.length > 0);
  state.className = 'tile-state';
  if (!v.configured) {
    state.textContent = 'NOT CONFIGURED';
    mode.textContent = a.route;
    vals.replaceChildren();
    return;
  }
  const last = !v.online && v.last_known;
  const d = last ? v.last_known : v;
  if (v.online && v.armed) { state.textContent = 'ARMED'; state.classList.add('armed'); }
  else if (v.online) { state.textContent = 'LIVE'; state.classList.add('live'); }
  else { state.textContent = last ? 'LINK LOST' : 'NO LINK'; state.classList.add('stale'); }

  mode.replaceChildren();
  if (alerts.length) {
    const top = alerts.find(x => x.level === 'critical') || alerts[0];
    const txt = el('span', 'alert-txt ' + top.level, (top.level === 'critical' ? '⛔ ' : '⚠ ') + top.text + (alerts.length > 1 ? `  +${alerts.length - 1}` : ''));
    mode.append(txt);
  } else if (last) {
    mode.append(el('span', '', `Last data ${ago(v.last_known.age_seconds)} · ${d.mode ?? '—'}`));
  } else if (!v.online) {
    mode.append(el('span', '', v.error || 'Waiting for a flight-controller heartbeat'));
  } else {
    mode.append(el('span', '', `${d.mode ?? '—'} · ${d.armed ? 'ARMED' : 'Disarmed'}${v.landed_state ? ' · ' + v.landed_state : ''}`));
  }

  const codes = Object.fromEntries(alerts.map(x => [x.code, x.level]));
  const stale = last ? 'stale' : '';
  const item = (label, text, level) => {
    const s = el('span', level || stale);
    s.append(el('small', '', label), document.createTextNode(text));
    return s;
  };
  const bl = batteryLevel(d, codes.battery);
  const batt = el('span', bl || stale);
  const gauge = el('i', 'batt ' + bl), fill = el('i');
  fill.style.width = Math.max(0, Math.min(100, d.battery_percent ?? 0)) * 0.18 + 'px';
  gauge.append(fill);
  batt.append(gauge, document.createTextNode(`${fmt(d.battery_voltage, 'V', 1)} ${fmt(d.battery_percent, '%', 0)}`));
  const alt = last ? d.altitude_relative_m : v.position?.altitude_relative_m;
  const useAs = a.fixedWing && d.airspeed_m_s !== null && d.airspeed_m_s !== undefined;
  const gps = v.gps ? (v.gps.fix_type >= 3 ? `3D·${v.gps.satellites ?? '?'}` : `NO FIX·${v.gps.satellites ?? 0}`) : '—';
  vals.replaceChildren(
    batt,
    item('ALT ', fmt(alt, 'm', 0)),
    item(useAs ? 'AS ' : 'GS ', fmt(useAs ? d.airspeed_m_s : d.groundspeed_m_s, '', 1), useAs ? codes.airspeed : ''),
    item('GPS ', gps, codes.gps || (v.gps && v.gps.fix_type < 3 ? 'warning' : '')),
  );
}

// ---------- Aircraft detail panels (drawer) ----------

const panels = {};
AIRCRAFT.forEach(a => {
  const tab = el('button', '', '');
  tab.type = 'button';
  tab.setAttribute('role', 'tab');
  tab.dataset.id = a.id;
  const sw = el('i', 'sw');
  sw.style.background = a.color;
  tab.append(sw, document.createTextNode(a.name));
  tab.onclick = () => select(a.id);
  $('#ac-tabs').append(tab);

  const p = el('div', 'acp');
  p.dataset.id = a.id;
  p.setAttribute('role', 'tabpanel');
  const head = el('div', 'acp-head'), who = el('div');
  who.append(el('h2', '', a.name), el('small', '', a.route));
  head.append(who, el('span', 'badge', 'WAITING'));
  const actions = el('div', 'acp-actions');
  const center = el('button'); center.append(icon('center'), document.createTextNode('Center map')); center.onclick = () => centerOn(a.id);
  actions.append(center);
  if (a.video) {
    const vid = el('button'); vid.dataset.act = 'swap'; vid.append(icon('swap'), el('span', '', 'Video to main view')); vid.onclick = () => swapMain(a.id);
    actions.append(vid);
  }
  const pfd = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  pfd.setAttribute('class', 'pfd');
  pfd.setAttribute('viewBox', '0 0 360 150');
  pfd.setAttribute('role', 'img');
  p.append(head, actions, el('div', 'card-alerts'), pfd, el('div', 'metrics'), el('div', 'charts'), el('div', 'mission'), el('div', 'details'));
  if (!a.video) p.querySelector('.details').before(el('p', 'placeholder', 'Video not configured for this aircraft.'));
  panels[a.id] = p;
  $('#ac-panels').append(p);
});

// Primary flight display: speed, attitude, altitude and heading at a glance.
function drawPfd(svg, id, d, stale) {
  const roll = d.roll_deg, pitch = d.pitch_deg;
  const have = Number.isFinite(roll) && Number.isFinite(pitch);
  const r = have ? -roll : 0, shift = have ? Math.max(-40, Math.min(40, pitch * 2)) : 0;
  const sky = have && !stale ? '#2c6a96' : '#2d3b46', ground = have && !stale ? '#7a5532' : '#3a3530';
  const n = (v, digits = 0) => Number.isFinite(v) ? v.toFixed(digits) : '—';
  const a = byId[id];
  const speed = a.fixedWing && Number.isFinite(d.airspeed_m_s) ? d.airspeed_m_s : d.groundspeed_m_s;
  const ladder = [-20, -10, 10, 20].map(p => `<line x1="${180 - (Math.abs(p) === 10 ? 18 : 28)}" x2="${180 + (Math.abs(p) === 10 ? 18 : 28)}" y1="${72 - p * 2}" y2="${72 - p * 2}" stroke="#fff" stroke-width="1.2" opacity=".8"/><text x="${180 + 34}" y="${76 - p * 2}" font-size="9" fill="#fff" opacity=".8">${Math.abs(p)}</text>`).join('');
  const hdg = Number.isFinite(d.heading_deg) ? ((Math.round(d.heading_deg) % 360) + 360) % 360 : null;
  svg.setAttribute('aria-label', have ? `Roll ${n(roll)} degrees, pitch ${n(pitch)} degrees` : 'No attitude data');
  svg.innerHTML = `
    <defs><clipPath id="pfd-clip-${id}"><circle cx="180" cy="72" r="60"/></clipPath></defs>
    <g clip-path="url(#pfd-clip-${id})">
      <g transform="rotate(${r.toFixed(1)} 180 72) translate(0 ${shift.toFixed(1)})">
        <rect x="60" y="-128" width="240" height="200" fill="${sky}"/>
        <rect x="60" y="72" width="240" height="200" fill="${ground}"/>
        <line x1="60" x2="300" y1="72" y2="72" stroke="#fff" stroke-width="1.6"/>
        ${have ? ladder : ''}
      </g>
    </g>
    <circle cx="180" cy="72" r="60" fill="none" stroke="#45657a" stroke-width="2"/>
    <path d="M150 72h18l6 7 6-7h18" fill="none" stroke="#ffd34d" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="180" cy="72" r="2.5" fill="#ffd34d"/>
    <path d="M180 8l-5 8h10z" fill="#ffd34d"/>
    ${have ? '' : '<text x="180" y="104" text-anchor="middle" font-size="11" font-weight="700" fill="#ffb0b6">NO ATTITUDE</text>'}
    <g font-size="10" fill="#8da6b8"><text x="8" y="20">${a.fixedWing && Number.isFinite(d.airspeed_m_s) ? 'AIRSPEED' : 'GND SPEED'}</text><text x="352" y="20" text-anchor="end">ALT REL</text></g>
    <rect x="6" y="52" width="92" height="40" rx="5" fill="#13212c" stroke="#385466"/>
    <rect x="262" y="52" width="92" height="40" rx="5" fill="#13212c" stroke="#385466"/>
    <text x="52" y="80" text-anchor="middle" font-size="22" font-weight="600" fill="${stale ? '#7f97a9' : '#fff'}">${n(speed, 1)}</text>
    <text x="308" y="80" text-anchor="middle" font-size="22" font-weight="600" fill="${stale ? '#7f97a9' : '#fff'}">${n(d.altitude, 0)}</text>
    <text x="52" y="106" text-anchor="middle" font-size="10" fill="#8da6b8">m/s</text>
    <text x="308" y="106" text-anchor="middle" font-size="10" fill="#8da6b8">m · VS ${n(d.climb_m_s, 1)}</text>
    <text x="52" y="128" text-anchor="middle" font-size="10" fill="#8da6b8">THR ${n(d.throttle_pct)}%</text>
    <rect x="146" y="134" width="68" height="15" rx="3" fill="#13212c" stroke="#385466"/>
    <text x="180" y="145.5" text-anchor="middle" font-size="11" font-weight="600" fill="${stale ? '#7f97a9' : '#fff'}">HDG ${hdg === null ? '—' : String(hdg).padStart(3, '0') + '°'}</text>
    <text x="308" y="128" text-anchor="middle" font-size="10" fill="#8da6b8">R ${n(roll)}° P ${n(pitch)}°</text>`;
}

// ---------- Small line graphs (one measure each, no second axis) ----------

let W = 300; const H = 74, PAD = {l: 30, r: 8, t: 8, b: 16};
function chart(container, key, title, unit, color, history, digits = 0) {
  let box = container.querySelector(`[data-chart="${key}"]`);
  if (!box) {
    box = document.createElement('figure');
    box.className = 'chart';
    box.dataset.chart = key;
    box.innerHTML = `<figcaption><span class="title"></span><span class="now"></span></figcaption>
      <svg viewBox="0 0 ${W} ${H}" role="img"></svg><div class="tip" hidden></div>`;
    box.querySelector('.title').textContent = title;
    container.append(box);
    const svg = box.querySelector('svg'), tip = box.querySelector('.tip');
    svg.addEventListener('pointermove', e => {
      const pts = box._points || [];
      if (!pts.length) return;
      const r = svg.getBoundingClientRect(), w = box._w || W, x = (e.clientX - r.left) / r.width * w;
      const p = pts.reduce((a, b) => Math.abs(b.x - x) < Math.abs(a.x - x) ? b : a);
      svg.querySelector('.cross').setAttribute('x1', p.x);
      svg.querySelector('.cross').setAttribute('x2', p.x);
      svg.querySelector('.cross').style.display = '';
      tip.hidden = false;
      tip.textContent = `${fmt(p.v, ' ' + unit, digits === 0 ? 1 : digits)} · ${ago(p.age)}`;
      tip.style.left = Math.min(r.width - 90, Math.max(0, p.x / w * r.width - 45)) + 'px';
    });
    svg.addEventListener('pointerleave', () => {
      tip.hidden = true;
      const c = svg.querySelector('.cross');
      if (c) c.style.display = 'none';
    });
  }
  const svg = box.querySelector('svg');
  // Draw in real pixels so text and lines are never stretched.
  W = Math.max(160, Math.round(svg.clientWidth || 300));
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  box._w = W;
  const data = history.filter(p => p[key] !== null && p[key] !== undefined);
  const latest = data.length ? data[data.length - 1][key] : null;
  box.querySelector('.now').textContent = fmt(latest, ' ' + unit, digits);
  svg.setAttribute('aria-label', `${title}, last 5 minutes, latest ${fmt(latest, ' ' + unit, digits)}`);
  if (data.length < 2) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="empty">No data yet</text>`;
    box._points = [];
    return;
  }
  const values = data.map(p => p[key]);
  let lo = Math.min(...values), hi = Math.max(...values);
  if (hi - lo < 2) { lo -= 1; hi += 1; }
  const span = 300; // seconds shown
  const x = age => PAD.l + (1 - age / span) * (W - PAD.l - PAD.r);
  const y = v => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const pts = data.map(p => ({x: x(p.age), y: y(p[key]), v: p[key], age: p.age}));
  box._points = pts;
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p.x.toFixed(1) + ' ' + p.y.toFixed(1)).join(' ');
  const last = pts[pts.length - 1];
  svg.innerHTML = `
    <line class="grid" x1="${PAD.l}" x2="${W - PAD.r}" y1="${PAD.t}" y2="${PAD.t}"/>
    <line class="grid" x1="${PAD.l}" x2="${W - PAD.r}" y1="${H - PAD.b}" y2="${H - PAD.b}"/>
    <text class="axis" x="${PAD.l - 4}" y="${PAD.t + 4}" text-anchor="end">${Math.round(hi)}</text>
    <text class="axis" x="${PAD.l - 4}" y="${H - PAD.b + 3}" text-anchor="end">${Math.round(lo)}</text>
    <text class="axis" x="${PAD.l}" y="${H - 3}">−5 min</text>
    <text class="axis" x="${W - PAD.r}" y="${H - 3}" text-anchor="end">now</text>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <circle cx="${last.x}" cy="${last.y}" r="3" fill="${color}"/>
    <line class="cross" x1="0" x2="0" y1="${PAD.t}" y2="${H - PAD.b}" style="display:none"/>`;
}

// ---------- Aircraft status ----------

function renderVehicle(v) {
  const c = panels[v.name];
  if (!c) return;
  renderTile(v);
  renderVideoHud(v);
  const badge = c.querySelector('.badge');
  badge.classList.toggle('live', v.online);
  badge.textContent = !v.configured ? 'UNCONFIGURED' : v.online ? 'TELEMETRY LIVE' : 'TELEMETRY STALE';
  if (!v.configured) return;

  const alerts = v.alerts || [];
  c.querySelector('.card-alerts').replaceChildren(...alerts.map(a => {
    const row = el('div', 'alert ' + a.level);
    row.append(el('b', '', a.level === 'critical' ? '⛔ CRITICAL' : '⚠ WARNING'), el('span', '', a.text));
    return row;
  }));

  const codes = new Set(alerts.map(a => a.code));
  const flag = code => codes.has(code) ? (alerts.find(a => a.code === code).level) : '';
  const sensors = v.sensors_unhealthy || [];
  // After a link loss, keep showing the last values received, dimmed and
  // labelled, instead of blanking them: that is when they matter most.
  const last = !v.online && v.last_known;
  const d = last ? {...v.last_known, position: {altitude_relative_m: v.last_known.altitude_relative_m}} : v;
  const old = last ? 'stale' : '';
  drawPfd(c.querySelector('.pfd'), v.name, {
    roll_deg: v.roll_deg, pitch_deg: v.pitch_deg, heading_deg: d.heading_deg, airspeed_m_s: d.airspeed_m_s,
    groundspeed_m_s: d.groundspeed_m_s, altitude: d.position?.altitude_relative_m, climb_m_s: d.climb_m_s, throttle_pct: d.throttle_pct,
  }, Boolean(last));
  const fields = [
    ['Mode', d.mode ?? '—', old],
    ['Arming', d.armed === null || d.armed === undefined ? '—' : d.armed ? 'ARMED' : 'Disarmed', d.armed ? 'armed ' + old : old],
    ['Battery', fmt(d.battery_voltage, ' V', 2) + ' / ' + fmt(d.battery_percent, '%', 0), flag('battery') || old],
    ['Relative altitude', fmt(d.position?.altitude_relative_m, ' m'), old],
    ['Airspeed', fmt(d.airspeed_m_s, ' m/s'), flag('airspeed') || old],
    ['Ground speed', fmt(d.groundspeed_m_s, ' m/s'), old],
    ['Heading', compass(d.heading_deg), old],
    ['Climb rate', fmt(d.climb_m_s, ' m/s'), old],
    ['Throttle', fmt(d.throttle_pct, '%', 0), old],
    ['From ' + (v.home?.reference ?? 'home'), v.home ? `${Math.round(v.home.distance_m)} m · ${compass(v.home.bearing_deg)}` : '—'],
    ['GPS', v.gps ? `Fix ${v.gps.fix_type} · ${fmt(v.gps.satellites, ' sats', 0)}` : '—', flag('gps')],
    ['Roll / pitch', fmt(v.roll_deg, '°') + ' / ' + fmt(v.pitch_deg, '°')],
    ['Sensors', !v.online ? '—' : sensors.length ? sensors.join(', ') + ' unhealthy' : 'All reported healthy',
      sensors.length ? (codes.has('rc') ? flag('rc') : 'warning') : ''],
    ['FC heartbeat', fmt(v.heartbeat_age, ' s ago'), flag('link')],
  ];
  const box = c.querySelector('.metrics');
  box.replaceChildren(...fields.map(([k, val, level]) => metric(k, val, level)));
  if (last) box.prepend(el('p', 'stale-note', `Link lost — dimmed values were last received ${ago(v.last_known.age_seconds)} and may no longer be true.`));
  // When a link drops, bring that aircraft's details forward once — unless the
  // operator is busy in another panel.
  // Only for an aircraft last seen armed (critical alert): a powered-down
  // aircraft on the bench should not take over the drawer on every page load.
  const justLost = last && !c._linkLost && alerts.some(a => a.code === 'link' && a.level === 'critical');
  c._linkLost = Boolean(last);
  if (justLost && (!openPanelName || openPanelName === 'aircraft')) {
    setTimeout(() => { select(v.name); openPanel('aircraft', true); });
  }

  if (openPanelName === 'aircraft' && ui.selected === v.name) {
    const charts = c.querySelector('.charts'), history = v.history || [];
    chart(charts, 'altitude', 'Altitude', 'm', colors[v.name], history);
    chart(charts, 'airspeed', 'Airspeed', 'm/s', colors[v.name], history, 1);
  }

  const m = v.mission || {};
  c.querySelector('.mission').textContent =
    `Mission item: ${fmt(m.current_seq, '', 0)} · Total: ${fmt(m.total, '', 0)}` +
    `\nState: ${m.state ?? '—'} · Last reached: ${fmt(m.last_reached_seq, '', 0)}` +
    `${m.last_reached_age !== null && m.last_reached_age !== undefined ? ' (' + fmt(m.last_reached_age, ' s ago', 0) + ')' : ''}` +
    (v.landed_state ? ` · ${v.landed_state}` : '') +
    (v.prearm_ok === false && !v.armed ? '\nPre-arm checks failing (aircraft not ready to arm)' : '');
  c.querySelector('.details').textContent = v.error || (v.position
    ? `${v.position.latitude.toFixed(6)}, ${v.position.longitude.toFixed(6)} · ${fmt(v.position_age, ' s old')}`
    : v.online ? 'Waiting for a valid, current GPS position.' : 'Waiting for a fresh flight-controller heartbeat.');
}

// ---------- Selection and drawer ----------

function select(id) {
  if (!byId[id]) return;
  ui.selected = id;
  save();
  for (const a of AIRCRAFT) {
    tiles[a.id].classList.toggle('selected', a.id === id);
    tiles[a.id].setAttribute('aria-pressed', a.id === id);
    panels[a.id].hidden = a.id !== id;
    vwins[a.id]?.classList.toggle('selected', a.id === id);
  }
  for (const tab of document.querySelectorAll('#ac-tabs button')) tab.setAttribute('aria-selected', tab.dataset.id === id);
  window.fleetMap?.select?.(id);
  if (lastFleet.length) lastFleet.forEach(renderVehicle);
}
function centerOn(id) {
  if (!window.fleetMap?.focusAircraft?.(id)) flash(`${byId[id].name} has no position to center on yet`);
}

const PANEL_TITLES = {aircraft: 'Aircraft', messages: 'Messages', layers: 'Map layers', preview: 'Command workflow · preview only', help: 'Help & shortcuts'};
function openPanel(name, keepOpen = false) {
  if (openPanelName === name && !keepOpen) { closeDrawer(); return; }
  openPanelName = name;
  $('#drawer').hidden = false;
  $('#drawer-title').textContent = PANEL_TITLES[name];
  for (const p of document.querySelectorAll('.drawer .panel')) p.hidden = p.dataset.panel !== name;
  for (const b of document.querySelectorAll('.rail [data-panel]')) b.classList.toggle('active', b.dataset.panel === name);
  if (name === 'messages') { ui.msgSeen = Date.now() / 1000; save(); renderMessages(lastFleet); }
  if (name === 'aircraft' && lastFleet.length) lastFleet.forEach(renderVehicle);
}
function closeDrawer() {
  openPanelName = null;
  $('#drawer').hidden = true;
  for (const b of document.querySelectorAll('.rail [data-panel]')) b.classList.remove('active');
}
for (const b of document.querySelectorAll('.rail [data-panel]')) b.onclick = () => openPanel(b.dataset.panel);
$('#drawer-close').onclick = closeDrawer;

let flashTimer = null;
function flash(text) {
  const chip = $('#measure-readout');
  if (window.fleetTools?.measuring?.()) return;
  chip.hidden = false;
  chip.textContent = text;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { if (!window.fleetTools?.measuring?.()) chip.hidden = true; }, 2500);
}

// ---------- Picture-in-picture video ----------

const vwins = {};
const videos = $('#videos');
videos.dataset.size = ui.size;
for (const a of AIRCRAFT.filter(a => a.video)) {
  const w = el('div', 'vwin');
  w.id = 'vwin-' + a.id;
  w.style.setProperty('--c', a.color);
  const bar = el('div', 'vbar'), name = el('b', '', a.name);
  name.style.cursor = 'pointer';
  name.title = `Select ${a.name}`;
  name.onclick = () => { select(a.id); openPanel('aircraft', true); };
  bar.append(name, el('span', 'vrate', 'Waiting for video'),
    iconButton('swap', `Swap ${a.name} video with the map (S)`, 'swap'),
    iconButton('expand', 'Fullscreen video', 'full'),
    iconButton('min', 'Minimize', 'min'));
  const body = el('div', 'vbody'), frame = el('iframe');
  frame.title = a.name + ' live video';
  frame.allow = 'autoplay; fullscreen; picture-in-picture';
  frame.src = VIDEO_URL(a.id);
  body.append(frame, el('div', 'overlay', 'Video paused'), el('div', 'vhud'));
  body.querySelector('.overlay').hidden = true;
  w.append(bar, body);
  bar.addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'swap') swapMain(a.id);
    else if (act === 'full') w.requestFullscreen().catch(() => {});
    else if (act === 'min') toggleMin(a.id);
  });
  if (ui.minimized.includes(a.id)) w.classList.add('min');
  vwins[a.id] = w;
  videos.append(w);
}

function setMinButton(id) {
  const w = vwins[id], b = w.querySelector('[data-act="min"]'), min = w.classList.contains('min');
  b.title = min ? 'Restore video' : 'Minimize';
  b.setAttribute('aria-label', b.title);
  b.querySelector('use').setAttribute('href', min ? '#i-restore' : '#i-min');
}
function toggleMin(id, force) {
  const w = vwins[id];
  if (!w || mainView === id) return;
  w.classList.toggle('min', force);
  ui.minimized = Object.keys(vwins).filter(k => vwins[k].classList.contains('min'));
  save();
  setMinButton(id);
  layoutVideos();
}
function swapMain(id) {
  const next = id === 'map' || mainView === id ? 'map' : id;
  if (next !== 'map' && !vwins[next]) return;
  mainView = next;
  $('#stage').dataset.main = next;
  for (const [k, w] of Object.entries(vwins)) {
    w.classList.toggle('main', k === next);
    if (k === next) w.classList.remove('min');
    const b = w.querySelector('[data-act="swap"]');
    b.title = k === next ? 'Return the map to the main view (S)' : `Swap ${byId[k].name} video with the map (S)`;
    b.setAttribute('aria-label', b.title);
    setMinButton(k);
  }
  for (const b of document.querySelectorAll('.acp [data-act="swap"] span')) {
    b.textContent = b.closest('.acp').dataset.id === next ? 'Map to main view' : 'Video to main view';
  }
  layoutVideos();
}
$('#map-swap').onclick = () => swapMain('map');

// Stack the floating windows bottom-up in the lower-right corner, starting a
// new column when one runs out of height.
function layoutVideos() {
  const stage = $('#stage'), mapEl = $('#map'), tools = $('.map-tools');
  // Keep clear of the map view buttons in the top-right corner.
  const toolsBottom = mainView === 'map' && tools.offsetParent ? tools.offsetTop + tools.offsetHeight + 8 : 10;
  const stageH = stage.clientHeight - toolsBottom + 10, gap = 8;
  const base = mainView === 'map' ? 10 : mapEl.offsetHeight + 20;
  let bottom = base, right = 10, colW = 0;
  for (const [id, w] of Object.entries(vwins)) {
    if (id === mainView) { w.style.bottom = ''; w.style.right = ''; continue; }
    const h = w.offsetHeight;
    if (bottom > base && bottom + h > stageH - 10) { right += colW + gap; bottom = base; colW = 0; }
    w.style.bottom = bottom + 'px';
    w.style.right = right + 'px';
    bottom += h + gap;
    colW = Math.max(colW, w.offsetWidth);
  }
}
new ResizeObserver(layoutVideos).observe($('#stage'));
for (const w of Object.values(vwins)) new ResizeObserver(layoutVideos).observe(w);
Object.keys(vwins).forEach(setMinButton);

function setSize(size) {
  ui.size = size;
  save();
  videos.dataset.size = size;
  for (const b of document.querySelectorAll('#video-size button')) b.classList.toggle('on', b.dataset.size === size);
  requestAnimationFrame(layoutVideos);
}
for (const b of document.querySelectorAll('#video-size button')) b.onclick = () => setSize(b.dataset.size);
setSize(ui.size);

function renderVideoHud(v) {
  const w = vwins[v.name];
  if (!w) return;
  const hud = w.querySelector('.vhud');
  if (!v.configured || (!v.online && !v.last_known)) { hud.replaceChildren(el('span', 'critical', v.online ? '' : 'NO TELEMETRY')); return; }
  const last = !v.online && v.last_known, d = last ? v.last_known : v;
  const codes = Object.fromEntries((v.alerts || []).map(a => [a.code, a.level]));
  const part = (label, text, cls) => { const s = el('span', cls || ''); s.append(el('small', '', label), document.createTextNode(text)); return s; };
  const alt = last ? d.altitude_relative_m : v.position?.altitude_relative_m;
  hud.replaceChildren(
    el('span', d.armed ? 'armed' : '', `${d.mode ?? '—'}${d.armed ? ' · ARMED' : ''}`),
    part('ALT', ' ' + fmt(alt, ' m', 0)),
    part(byId[v.name].fixedWing ? 'AS' : 'GS', ' ' + fmt(byId[v.name].fixedWing ? d.airspeed_m_s : d.groundspeed_m_s, ' m/s', 1), codes.airspeed),
    part('HDG', ' ' + (Number.isFinite(d.heading_deg) ? String(Math.round(d.heading_deg) % 360).padStart(3, '0') + '°' : '—')),
    part('BAT', ' ' + fmt(d.battery_voltage, ' V', 1), codes.battery),
    ...(last ? [el('span', 'critical', `LINK LOST ${ago(v.last_known.age_seconds)}`)] : []),
  );
}

// ---------- Messages from all aircraft ----------

const filters = [['all', 'All'], ...AIRCRAFT.map(a => [a.id, a.name])];
for (const [id, label] of filters) {
  const b = el('button', '', label);
  b.type = 'button';
  b.dataset.id = id;
  if (byId[id]) { const sw = el('i', 'sw'); sw.style.background = byId[id].color; b.prepend(sw); }
  b.onclick = () => { ui.msgFilter = id; save(); renderMessages(lastFleet); };
  $('#msg-filter').append(b);
}
function renderMessages(fleet) {
  const now = Date.now() / 1000, all = [];
  for (const v of fleet) for (const e of v.events || []) all.push({...e, who: v.name, t: now - e.age_seconds});
  all.sort((a, b) => a.age_seconds - b.age_seconds);
  // Unread badge on the rail: anything newer than when the panel was last opened.
  if (openPanelName === 'messages') ui.msgSeen = now;
  const unread = all.filter(e => e.t > ui.msgSeen + 1 && e.level !== 'info');
  const badge = $('#msg-unread');
  badge.hidden = !unread.length;
  badge.textContent = unread.length > 99 ? '99+' : unread.length;
  badge.className = unread.some(e => e.level === 'critical' || e.level === 'warning') ? '' : 'notice';
  for (const b of document.querySelectorAll('#msg-filter button')) b.classList.toggle('on', b.dataset.id === ui.msgFilter);
  if (openPanelName !== 'messages') return;
  const shown = all.filter(e => ui.msgFilter === 'all' || e.who === ui.msgFilter).slice(0, 150);
  $('#msg-log').replaceChildren(...(shown.length ? shown : [{level: 'info', text: 'No messages yet', age_seconds: null}]).map(e => {
    const li = el('li', 'lvl-' + e.level);
    const lvl = el('b', '', LEVEL_LABEL[e.level] || e.level);
    const when = el('time', '', e.age_seconds === null ? '' : ago(e.age_seconds));
    li.append(lvl, el('span', '', e.text + (e.count > 1 ? `  ×${e.count}` : '')), when);
    if (e.who) { const who = el('span', 'who', byId[e.who]?.name || e.who); who.style.color = colors[e.who]; li.append(who); }
    return li;
  }));
}

// ---------- Fleet-wide alert strip and sound ----------

let soundOn = false, audio = null, lastBeep = {}, silenced = new Set();
const soundButton = $('#sound');
function toggleSound() {
  soundOn = !soundOn;
  soundButton.setAttribute('aria-pressed', soundOn);
  soundButton.querySelector('span').textContent = 'Sound ' + (soundOn ? 'on' : 'off');
  soundButton.querySelector('use').setAttribute('href', soundOn ? '#i-sound' : '#i-mute');
  if (soundOn) {
    // Browsers only allow audio after a click or key press, so the context is created here.
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    audio.resume();
    beep('warning');
  }
}
soundButton.onclick = toggleSound;
function beep(level) {
  if (!soundOn || !audio) return;
  const tones = level === 'critical' ? [880, 660, 880] : [660];
  tones.forEach((freq, i) => {
    const osc = audio.createOscillator(), gain = audio.createGain();
    const t = audio.currentTime + i * 0.22;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
    osc.connect(gain).connect(audio.destination);
    osc.start(t);
    osc.stop(t + 0.2);
  });
}
function renderBanner(fleet) {
  const banner = $('#alerts');
  const all = [];
  for (const v of fleet) for (const a of v.alerts || []) all.push({...a, aircraft: names[v.name]?.[0] || v.name, key: v.name + '|' + a.code + '|' + a.level + (a.code === 'message' ? '|' + a.text : '')});
  // Keys ignore changing numbers (e.g. "lost 12 s ago") so silencing sticks; a
  // new aircraft message or an escalation to critical makes a new key.
  all.sort((a, b) => (a.level !== 'critical') - (b.level !== 'critical'));
  const keys = new Set(all.map(a => a.key));
  for (const k of [...silenced]) if (!keys.has(k)) silenced.delete(k);
  for (const k of Object.keys(lastBeep)) if (!keys.has(k)) delete lastBeep[k];
  banner.hidden = !all.length;
  banner.className = all.some(a => a.level === 'critical') ? 'critical' : 'warning';
  // The browser tab's title shows alerts too, so they are visible from another tab.
  document.title = (!all.length ? '' : all[0].level === 'critical' ? '⛔ CRITICAL · ' : '⚠ WARNING · ') + 'Cruza / RTIC Fleet';
  if (!all.length) { banner.replaceChildren(); return; }

  // New alerts beep once; critical ones repeat every 10 s until silenced.
  const now = performance.now();
  let loudest = null;
  for (const a of all) {
    if (silenced.has(a.key)) continue;
    const due = lastBeep[a.key] === undefined || (a.level === 'critical' && now - lastBeep[a.key] > 10000);
    if (due) { lastBeep[a.key] = now; loudest = loudest === 'critical' ? loudest : a.level; }
  }
  if (loudest) beep(loudest);

  const list = el('ul');
  for (const a of all) {
    const li = el('li', a.level);
    li.append(el('b', '', a.level === 'critical' ? '⛔ CRITICAL' : '⚠ WARNING'), el('strong', '', a.aircraft), el('span', '', a.text));
    list.append(li);
  }
  const mute = el('button');
  const unsilenced = all.filter(a => !silenced.has(a.key));
  mute.textContent = unsilenced.length ? 'Silence these alerts' : 'Silenced';
  mute.disabled = !unsilenced.length;
  mute.onclick = () => { all.forEach(a => silenced.add(a.key)); renderBanner(fleet); };
  banner.replaceChildren(list, mute);
}

// ---------- Polling loop ----------

function drawMap(fleet) { window.fleetMap.update(fleet); }

function offline() {
  $('#connection').textContent = 'Dashboard disconnected — telemetry unavailable';
  for (const a of AIRCRAFT) {
    const t = tiles[a.id], c = panels[a.id];
    const s = t.querySelector('.tile-state');
    s.className = 'tile-state stale';
    s.textContent = 'OFFLINE';
    t.querySelector('.tile-mode').textContent = 'Dashboard server not responding';
    t.querySelector('.tile-vals').replaceChildren();
    t.classList.remove('has-critical', 'has-warning');
    c.querySelector('.badge').textContent = 'DASHBOARD OFFLINE';
    c.querySelector('.badge').classList.remove('live');
    c.querySelector('.metrics').replaceChildren(metric('Status', 'Unavailable'));
    c.querySelector('.mission').textContent = 'Mission status unavailable';
    c.querySelector('.details').textContent = '';
    c.querySelector('.card-alerts').replaceChildren();
    if (vwins[a.id]) vwins[a.id].querySelector('.vhud').replaceChildren(el('span', 'critical', 'DASHBOARD OFFLINE'));
  }
  renderBanner([{name: 'dashboard', alerts: [{level: 'warning', code: 'dashboard', text: 'Dashboard server not responding — no telemetry is being shown'}]}]);
  drawMap([]);
}

async function tick() {
  if (busy) return;
  busy = true;
  try {
    const res = await fetch('/status?watch=' + (watching ? '1' : '0'), {signal: AbortSignal.timeout(5000)});
    if (!res.ok) throw Error('Dashboard unavailable');
    const status = await res.json(), now = performance.now();
    lastFleet = status.fleet;
    status.fleet.forEach(renderVehicle);
    renderBanner(status.fleet);
    renderMessages(status.fleet);
    drawMap(status.fleet);
    for (const f of status.feeds) {
      const prev = previous[f.name];
      const rate = prev ? Math.round(Math.max(0, f.bytes - prev.bytes) * 8 / (now - prev.time)) : 0;
      const span = vwins[f.name]?.querySelector('.vrate');
      if (span) {
        span.textContent = !watching ? 'Video paused' : f.receiving ? `Receiving · ${rate} kb/s` : 'Waiting for video';
        span.classList.toggle('live', watching && f.receiving);
      }
      previous[f.name] = {bytes: f.bytes, time: now};
    }
    const cruzaFeed = status.feeds.find(f => f.name === 'cruza');
    $('#connection').textContent = `Updated ${new Date().toLocaleTimeString()}` +
      (cruzaFeed ? ` · Cruza extra video ${(cruzaFeed.bytes / 1e6).toFixed(1)} MB this session` : '');
    failures = 0;
  } catch (e) {
    if (++failures >= 2) offline();
  } finally {
    busy = false;
  }
}

function toggleVideo() {
  watching = !watching;
  const b = $('#toggle');
  b.querySelector('span').textContent = watching ? 'Pause video' : 'Resume video';
  b.querySelector('use').setAttribute('href', watching ? '#i-pause' : '#i-play');
  b.classList.toggle('paused', !watching);
  for (const [id, w] of Object.entries(vwins)) {
    w.querySelector('.overlay').hidden = watching;
    w.querySelector('iframe').src = watching ? VIDEO_URL(id) : 'about:blank';
  }
  if (!watching) fetch('/pause', {method: 'POST'}).catch(() => {});
  tick();
}
$('#toggle').onclick = toggleVideo;

// ---------- Clock (local and UTC, like a GCS) ----------

function clock() {
  const d = new Date();
  $('#clock-local').textContent = d.toLocaleTimeString([], {hour12: false});
  $('#clock-utc').textContent = d.toISOString().slice(11, 19) + 'Z';
}
clock();
setInterval(clock, 1000);

// ---------- Keyboard shortcuts ----------

document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t.closest && t.closest('input, select, textarea, [contenteditable]')) return;
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (key === 'Escape') {
    // Map point picking for the preview handles its own Escape.
    if ($('#map').classList.contains('pick-point')) return;
    if (window.fleetTools?.measuring?.()) { window.fleetTools.stopMeasure(); e.preventDefault(); return; }
    if (openPanelName) { closeDrawer(); e.preventDefault(); return; }
    if (mainView !== 'map') { swapMain('map'); e.preventDefault(); }
    return;
  }
  const actions = {
    '1': () => { select('cruza'); openPanel('aircraft', true); },
    '2': () => { select('quadpi'); openPanel('aircraft', true); },
    '3': () => { select('rn03'); openPanel('aircraft', true); },
    d: () => openPanel('aircraft'), m: () => openPanel('messages'), l: () => openPanel('layers'),
    c: () => openPanel('preview'), '?': () => openPanel('help'), h: () => openPanel('help'),
    r: () => window.fleetTools?.toggleMeasure(),
    f: () => $('#fit-fleet').disabled ? flash('No aircraft positions to fit yet') : $('#fit-fleet').click(),
    g: () => centerOn(ui.selected),
    s: () => byId[ui.selected].video ? swapMain(mainView === 'map' ? ui.selected : 'map') : swapMain('map'),
    v: () => { const ids = Object.keys(vwins).filter(id => id !== mainView); const minAll = ids.some(id => !vwins[id].classList.contains('min')); ids.forEach(id => toggleMin(id, minAll)); },
    p: toggleVideo,
    a: toggleSound,
  };
  if (actions[key]) { e.preventDefault(); actions[key](); }
});

// ---------- Start ----------

select(ui.selected);
tick();
// Browsers slow timers in background tabs to as little as once a minute, which
// would delay alerts. Timers inside a worker are not slowed that way, so the
// worker sets the pace. Without worker support, fall back to a normal timer.
let ticker = null, fallbackTimer = null;
const fallback = () => { fallbackTimer = fallbackTimer || setInterval(tick, 1500); };
try {
  ticker = new Worker('/ticker.js');
  ticker.onmessage = tick;
  ticker.onerror = fallback;
} catch (e) {
  fallback();
}
// Map margins for "Fit aircraft" / "Follow fleet", so aircraft are not
// placed under the tool rail, an open drawer or the video windows.
function mapPadding() {
  const st = $('#stage').getBoundingClientRect();
  if (mainView !== 'map') return {padding: [30, 30]};
  let left = 80, right = 60;
  if (!$('#drawer').hidden && innerWidth > 720) left = $('#drawer').getBoundingClientRect().right - st.left + 30;
  let minLeft = st.right;
  for (const w of Object.values(vwins)) if (w.offsetParent) minLeft = Math.min(minLeft, w.getBoundingClientRect().left);
  right = Math.max(right, st.right - minLeft + 30);
  if (st.width - left - right < 240) { left = 50; right = 50; }
  return {paddingTopLeft: [left, 60], paddingBottomRight: [right, 40]};
}
window.fleetUI = {select, selected: () => ui.selected, swapMain, openPanel, flash, mapPadding};
