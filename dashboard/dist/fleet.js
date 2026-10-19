'use strict';
// Fleet dashboard page: video panels, aircraft status, alerts, graphs.
// Everything here is read-only; the page never sends anything to an aircraft.

const names = {
  cruza: ['Cruza', 'Fixed wing · LTE / VPN'],
  quadpi: ['quadpi', '10-inch quad · RN03 wearable / mesh'],
  rn03: ['RN03 aircraft', 'Separate Mini · awaiting connection'],
};
const colors = {cruza: '#7ce1ba', quadpi: '#7dbcf4', rn03: '#d3a9ed'};
const cards = {};
let watching = true, previous = {}, failures = 0, busy = false;

// ---------- Cards ----------

for (const [id, [name, route]] of Object.entries(names)) {
  const card = document.createElement('article');
  card.className = 'card';
  card.id = id;
  card.innerHTML = '<div class="head"><div><h2></h2><small></small></div><span class="badge">WAITING</span></div>';
  card.querySelector('h2').textContent = name;
  card.querySelector('small').textContent = route;
  if (id === 'rn03') {
    card.innerHTML += '<div class="placeholder">Aircraft source not configured.<br>The RN03 wearable is a network relay. Its connection does not establish telemetry or video from RN03’s separate aircraft.</div>';
  } else {
    card.innerHTML += `
      <div class="card-alerts"></div>
      <div class="video"><iframe allow="autoplay; fullscreen; picture-in-picture"></iframe><div class="overlay" hidden>Video paused</div></div>
      <div class="videofoot"><span>Waiting for video</span><button>Expand</button></div>
      <details class="telemetry"><summary>Aircraft status</summary>
        <div class="metrics"></div>
        <div class="charts"></div>
        <div class="mission"></div>
        <div class="details"></div>
      </details>
      <details class="events"><summary>Messages <span class="count"></span></summary><ol class="log"></ol></details>`;
    card.querySelector('.telemetry').open = window.matchMedia('(min-width:1050px)').matches;
    const frame = card.querySelector('iframe');
    frame.title = name + ' live video';
    frame.src = `http://127.0.0.1:8889/${id}?controls=false&muted=true`;
    card.querySelector('.videofoot button').onclick = () => card.requestFullscreen().catch(() => {});
  }
  cards[id] = card;
  document.querySelector('#fleet').append(card);
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
  const n = document.createElement('div');
  n.className = 'metric' + (level ? ' ' + level : '');
  const s = document.createElement('small'), v = document.createElement('span');
  s.textContent = label;
  v.textContent = value;
  n.append(s, v);
  return n;
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

const LEVEL_LABEL = {critical: 'CRITICAL', warning: 'WARNING', notice: 'EVENT', info: 'INFO'};

function renderVehicle(v) {
  const c = cards[v.name];
  if (!c) return;
  const badge = c.querySelector('.badge');
  badge.classList.toggle('live', v.online);
  badge.textContent = !v.configured ? 'UNCONFIGURED' : v.online ? 'TELEMETRY LIVE' : 'TELEMETRY STALE';
  if (!v.configured) return;

  const alerts = v.alerts || [];
  c.classList.toggle('has-critical', alerts.some(a => a.level === 'critical'));
  c.classList.toggle('has-warning', !alerts.some(a => a.level === 'critical') && alerts.length > 0);
  const strip = c.querySelector('.card-alerts');
  strip.replaceChildren(...alerts.map(a => {
    const row = document.createElement('div');
    row.className = 'alert ' + a.level;
    row.innerHTML = '<b></b><span></span>';
    row.querySelector('b').textContent = a.level === 'critical' ? '⛔ CRITICAL' : '⚠ WARNING';
    row.querySelector('span').textContent = a.text;
    return row;
  }));

  const codes = new Set(alerts.map(a => a.code));
  const flag = code => codes.has(code) ? (alerts.find(a => a.code === code).level) : '';
  const sensors = v.sensors_unhealthy || [];
  const fields = [
    ['Mode', v.mode ?? '—'],
    ['Arming', v.armed === null ? '—' : v.armed ? 'ARMED' : 'Disarmed', v.armed ? 'armed' : ''],
    ['Battery', fmt(v.battery_voltage, ' V', 2) + ' / ' + fmt(v.battery_percent, '%', 0), flag('battery')],
    ['Relative altitude', fmt(v.position?.altitude_relative_m, ' m')],
    ['Airspeed', fmt(v.airspeed_m_s, ' m/s'), flag('airspeed')],
    ['Ground speed', fmt(v.groundspeed_m_s, ' m/s')],
    ['Heading', compass(v.heading_deg)],
    ['Climb rate', fmt(v.climb_m_s, ' m/s')],
    ['Throttle', fmt(v.throttle_pct, '%', 0)],
    ['From ' + (v.home?.reference ?? 'home'), v.home ? `${Math.round(v.home.distance_m)} m · ${compass(v.home.bearing_deg)}` : '—'],
    ['GPS', v.gps ? `Fix ${v.gps.fix_type} · ${fmt(v.gps.satellites, ' sats', 0)}` : '—', flag('gps')],
    ['Roll / pitch', fmt(v.roll_deg, '°') + ' / ' + fmt(v.pitch_deg, '°')],
    ['Sensors', !v.online ? '—' : sensors.length ? sensors.join(', ') + ' unhealthy' : 'All reported healthy',
      sensors.length ? (codes.has('rc') ? flag('rc') : 'warning') : ''],
    ['FC heartbeat', fmt(v.heartbeat_age, ' s ago'), flag('link')],
  ];
  const box = c.querySelector('.metrics');
  box.replaceChildren(...fields.map(([k, val, level]) => metric(k, val, level)));

  const charts = c.querySelector('.charts');
  const history = v.history || [];
  chart(charts, 'altitude', 'Altitude', 'm', colors[v.name], history);
  chart(charts, 'airspeed', 'Airspeed', 'm/s', colors[v.name], history, 1);

  const m = v.mission;
  c.querySelector('.mission').textContent =
    `Mission item: ${fmt(m.current_seq, '', 0)} · Total: ${fmt(m.total, '', 0)}` +
    `\nState: ${m.state ?? '—'} · Last reached: ${fmt(m.last_reached_seq, '', 0)}` +
    `${m.last_reached_age !== null ? ' (' + fmt(m.last_reached_age, ' s ago', 0) + ')' : ''}` +
    (v.landed_state ? ` · ${v.landed_state}` : '') +
    (v.prearm_ok === false && !v.armed ? '\nPre-arm checks failing (aircraft not ready to arm)' : '');
  c.querySelector('.details').textContent = v.error || (v.position
    ? `${v.position.latitude.toFixed(6)}, ${v.position.longitude.toFixed(6)} · ${fmt(v.position_age, ' s old')}`
    : v.online ? 'Waiting for a valid, current GPS position.' : 'Waiting for a fresh flight-controller heartbeat.');

  const events = v.events || [];
  c.querySelector('.events .count').textContent = events.length ? `(${events.length})` : '';
  c.querySelector('.log').replaceChildren(...(events.length ? events : [{level: 'info', text: 'No messages yet', age_seconds: null}]).map(e => {
    const li = document.createElement('li');
    li.className = 'lvl-' + e.level;
    const lvl = document.createElement('b'), txt = document.createElement('span'), when = document.createElement('time');
    lvl.textContent = LEVEL_LABEL[e.level] || e.level;
    txt.textContent = e.text + (e.count > 1 ? `  ×${e.count}` : '');
    when.textContent = e.age_seconds === null ? '' : ago(e.age_seconds);
    li.append(lvl, txt, when);
    return li;
  }));
}

// ---------- Fleet-wide alert banner and sound ----------

let soundOn = false, audio = null, lastBeep = {}, silenced = new Set();
const soundButton = document.querySelector('#sound');
soundButton.onclick = () => {
  soundOn = !soundOn;
  soundButton.setAttribute('aria-pressed', soundOn);
  soundButton.textContent = 'Sound alerts: ' + (soundOn ? 'on' : 'off');
  if (soundOn) {
    // Browsers only allow audio after a click, so the context is created here.
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    audio.resume();
    beep('warning');
  }
};
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
  const banner = document.querySelector('#alerts');
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

  const list = document.createElement('ul');
  for (const a of all) {
    const li = document.createElement('li');
    li.className = a.level;
    const tag = document.createElement('b'), who = document.createElement('strong'), txt = document.createElement('span');
    tag.textContent = a.level === 'critical' ? '⛔ CRITICAL' : '⚠ WARNING';
    who.textContent = a.aircraft;
    txt.textContent = a.text;
    li.append(tag, who, txt);
    list.append(li);
  }
  const mute = document.createElement('button');
  const unsilenced = all.filter(a => !silenced.has(a.key));
  mute.textContent = unsilenced.length ? 'Silence these alerts' : 'Silenced';
  mute.disabled = !unsilenced.length;
  mute.onclick = () => { all.forEach(a => silenced.add(a.key)); renderBanner(fleet); };
  banner.replaceChildren(list, mute);
}

// ---------- Polling loop ----------

function drawMap(fleet) { window.fleetMap.update(fleet); }

function offline() {
  document.querySelector('#connection').textContent = 'Dashboard disconnected — telemetry unavailable';
  for (const id of ['cruza', 'quadpi']) {
    const c = cards[id];
    c.querySelector('.badge').textContent = 'DASHBOARD OFFLINE';
    c.querySelector('.badge').classList.remove('live');
    c.querySelector('.metrics').replaceChildren(metric('Status', 'Unavailable'));
    c.querySelector('.mission').textContent = 'Mission status unavailable';
    c.querySelector('.details').textContent = '';
    c.querySelector('.card-alerts').replaceChildren();
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
    status.fleet.forEach(renderVehicle);
    renderBanner(status.fleet);
    drawMap(status.fleet);
    for (const f of status.feeds) {
      const prev = previous[f.name];
      const rate = prev ? Math.round(Math.max(0, f.bytes - prev.bytes) * 8 / (now - prev.time)) : 0;
      cards[f.name].querySelector('.videofoot span').textContent =
        !watching ? 'Video paused' : f.receiving ? `Video receiving · ${rate} kb/s` : 'Waiting for video';
      previous[f.name] = {bytes: f.bytes, time: now};
    }
    document.querySelector('#connection').textContent =
      `Updated ${new Date().toLocaleTimeString()} · Cruza extra video ${(status.feeds.find(f => f.name === 'cruza').bytes / 1e6).toFixed(1)} MB this session`;
    failures = 0;
  } catch (e) {
    if (++failures >= 2) offline();
  } finally {
    busy = false;
  }
}

document.querySelector('#toggle').onclick = () => {
  watching = !watching;
  document.querySelector('#toggle').textContent = watching ? 'Pause video' : 'Resume video';
  for (const id of ['cruza', 'quadpi']) {
    cards[id].querySelector('.overlay').hidden = watching;
    cards[id].querySelector('iframe').src = watching ? `http://127.0.0.1:8889/${id}?controls=false&muted=true` : 'about:blank';
  }
  if (!watching) fetch('/pause', {method: 'POST'}).catch(() => {});
  tick();
};
tick();
setInterval(tick, 1500);
