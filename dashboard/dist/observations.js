'use strict';
// Areas of interest from the fleet's observers. Advisory only: the operator
// confirms or dismisses each cue, and even a confirmed one only drops a
// candidate point into the preview panel below. Nothing here tasks or moves an
// aircraft, and no decision is transmitted anywhere.
//
// Positions come from the server (swarm.py) whenever /status carries the swarm
// picture: it geolocates each cue from the aircraft that actually reported it,
// and tells us when two aircraft are looking at the same thing. The local maths
// below is only a fallback for a Cruza cue served by an older build, which is
// why it is Cruza-specific - a quadpi or TFW drone cue must never be resolved
// with the Cruza's heading and height.
(function () {
  // Camera mounting assumptions used to turn a detection's angles-off-boresight
  // into a map bearing and a rough ground point. These are estimates for
  // cueing, NOT a calibrated sensor model — measure them on the airframe and
  // correct here. Field of view lives in the Pi observer config (hfov/vfov).
  const MOUNT_YAW_DEG = 0;         // camera points along the nose
  const MOUNT_PITCH_DOWN_DEG = 25; // boresight tilted this far below level
                                   // (nose sled design: AI Camera in the chin,
                                   // 25 deg down, 52 deg vertical view)
  const MAX_RANGE_M = 1500;        // never project an area of interest past this
  const DEFAULT_RANGE_M = 150;     // used only when depression can't give a range
  const R = 6371000;

  const list = document.querySelector('#aoi-list');
  const status = document.querySelector('#aoi-status');
  if (!list) return;
  const decisions = new Map();   // id -> 'confirmed' | 'dismissed'
  let latest = [];               // last items shown (for button handlers)
  let located = new Map();       // cue id -> server-geolocated position
  let shared = new Map();        // cue id -> the correlated track it belongs to

  const rad = d => d * Math.PI / 180;
  const deg = r => r * 180 / Math.PI;
  const DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const compass = b => DIRS[Math.round((b % 360) / 45) % 8];

  function cruzaFrom(fleet) {
    const v = (fleet || []).find(a => a.name === 'cruza');
    if (!v || !v.online) return null;
    return {pos: v.position, heading: v.heading_deg, pitch: v.pitch_deg};
  }

  // Project a point d metres along true bearing from a lat/lon (great circle).
  function project(lat, lon, bearing, d) {
    const dr = d / R, br = rad(bearing), la = rad(lat), lo = rad(lon);
    const la2 = Math.asin(Math.sin(la) * Math.cos(dr) + Math.cos(la) * Math.sin(dr) * Math.cos(br));
    const lo2 = lo + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(la),
                                Math.cos(dr) - Math.sin(la) * Math.sin(la2));
    return {lat: deg(la2), lon: ((deg(lo2) + 540) % 360) - 180};
  }

  // Where the server put this cue, or - only for a Cruza cue on an older
  // server - the local estimate. A cue from another aircraft with no server
  // position stays unlocated rather than being placed with the wrong telemetry.
  function locate(obs, cruza) {
    const s = located.get(obs.id);
    if (s && Number.isFinite(s.lat)) {
      return {bearing: s.bearing_deg, lat: s.lat, lon: s.lon,
              range: s.range_m, estimated: s.estimated};
    }
    if (s) return {bearing: s.bearing_deg, lat: null, lon: null, range: null, estimated: true};
    if ((obs.src || 'cruza') !== 'cruza') {
      return {bearing: null, lat: null, lon: null, range: null, estimated: true};
    }
    return geo(obs, cruza);
  }

  // Estimate where an observation is, from the Cruza's current telemetry.
  function geo(obs, cruza) {
    const out = {bearing: null, lat: null, lon: null, range: null, estimated: false};
    if (!cruza) return out;
    const heading = Number.isFinite(cruza.heading) ? cruza.heading : null;
    if (heading !== null) out.bearing = (heading + MOUNT_YAW_DEG + obs.az_rel_deg + 360) % 360;
    const pos = cruza.pos;
    if (!pos || out.bearing === null) return out;
    const agl = pos.altitude_relative_m;
    const pitch = Number.isFinite(cruza.pitch) ? cruza.pitch : 0;
    const depression = MOUNT_PITCH_DOWN_DEG - pitch - obs.el_rel_deg;
    let range = null;
    if (Number.isFinite(agl) && agl > 3 && depression > 2 && depression < 85) {
      range = Math.min(MAX_RANGE_M, agl / Math.tan(rad(depression)));
    }
    out.range = range;
    out.estimated = range === null;
    const useRange = range === null ? DEFAULT_RANGE_M : range;
    const p = project(pos.latitude, pos.longitude, out.bearing, useRange);
    out.lat = p.lat; out.lon = p.lon;
    return out;
  }

  function decide(id, verdict) {
    if (verdict === 'reset') decisions.delete(id); else decisions.set(id, verdict);
    render(latest.items, latest.fleet);
  }

  function dispatch(g) {
    if (g.lat === null || !window.fleetMap?.setCandidate) return;
    window.fleetMap.setCandidate(g.lat, g.lon);
    status.textContent = g.estimated
      ? 'Candidate dropped at an estimated bearing/range — confirm or re-pick it on the map before previewing.'
      : 'Candidate dropped at the estimated location — review it on the map before previewing.';
  }

  function row(obs, cruza) {
    const g = locate(obs, cruza);
    const verdict = decisions.get(obs.id);
    const li = document.createElement('li');
    li.className = 'aoi' + (verdict ? ' aoi-' + verdict : '');

    const head = document.createElement('div');
    head.className = 'aoi-head';
    const cls = document.createElement('strong'); cls.textContent = obs.cls;
    const who = document.createElement('span'); who.className = 'aoi-src';
    who.textContent = obs.src || 'cruza';
    const score = document.createElement('span'); score.className = 'aoi-score';
    score.textContent = Math.round(obs.score * 100) + '%';
    head.append(cls, who, score);
    const track = shared.get(obs.id);
    if (track && track.sources.length > 1) {
      // Two aircraft placing the same class within the fusion radius. Worth
      // saying out loud, with how far apart they put it.
      const also = document.createElement('span'); also.className = 'aoi-cross';
      const others = track.sources.filter(x => x !== (obs.src || 'cruza'));
      also.textContent = 'also seen by ' + others.join(', ') +
        (Number.isFinite(track.span_m) ? ` · ${Math.round(track.span_m)} m apart` : '');
      head.append(also);
    }

    const detail = document.createElement('p'); detail.className = 'aoi-detail';
    let where;
    if (g.bearing === null) where = 'Bearing unavailable (no Cruza heading)';
    else where = `Bearing ${Math.round(g.bearing)}° ${compass(g.bearing)}` +
      (g.range !== null ? ` · est. ${Math.round(g.range)} m` : ' · range unknown');
    detail.textContent = `${where} · seen ${obs.last_seen_age.toFixed(0)}s ago ·` +
      ` ${obs.count}×` + (g.estimated && g.lat !== null ? ' · location estimated' : '');

    const actions = document.createElement('div'); actions.className = 'aoi-actions';
    if (verdict !== 'confirmed') {
      const ok = document.createElement('button'); ok.textContent = 'Confirm';
      ok.onclick = () => decide(obs.id, 'confirmed'); actions.append(ok);
    }
    if (verdict === 'confirmed') {
      const send = document.createElement('button'); send.textContent = 'Send to dispatch';
      send.disabled = g.lat === null;
      send.title = g.lat === null ? 'No position estimate yet' : '';
      send.onclick = () => dispatch(g); actions.append(send);
    }
    const no = document.createElement('button'); no.className = 'aoi-dismiss';
    no.textContent = verdict === 'dismissed' ? 'Restore' : 'Dismiss';
    no.onclick = () => decide(obs.id, verdict === 'dismissed' ? 'reset' : 'dismissed');
    actions.append(no);

    li.append(head, detail, actions);
    return {li, g, confirmed: verdict === 'confirmed'};
  }

  function render(items, fleet) {
    latest = {items: items || [], fleet: fleet || []};
    const cruza = cruzaFrom(fleet);
    // Forget decisions for areas that have expired out of the feed.
    const live = new Set((items || []).map(o => o.id));
    for (const id of [...decisions.keys()]) if (!live.has(id)) decisions.delete(id);

    const visible = (items || []).filter(o => decisions.get(o.id) !== 'dismissed');
    list.replaceChildren();
    const aois = [];
    for (const obs of visible) {
      const {li, g, confirmed} = row(obs, cruza);
      list.append(li);
      if (confirmed && g.lat !== null) {
        aois.push({id: obs.id, lat: g.lat, lon: g.lon,
                   label: `${obs.cls} · ${Math.round(obs.score * 100)}%`});
      }
    }
    window.fleetMap?.setAOIs?.(aois);

    const dismissed = (items || []).length - visible.length;
    if (!items || !items.length) {
      status.textContent = latest.connectedText || 'No areas of interest.';
    } else {
      status.textContent = `${visible.length} area${visible.length === 1 ? '' : 's'} of interest` +
        (dismissed ? ` · ${dismissed} dismissed` : '') +
        (cruza ? '' : ' · Cruza telemetry offline, bearings unavailable');
    }
  }

  window.observations = {
    update(payload, fleet, swarm) {
      payload = payload || {items: [], connected: false, error: ''};
      located = new Map((swarm?.cues || []).map(c => [c.id, c]));
      // A track's id is its contributing cue ids joined by '+', so index every
      // cue to the track it was correlated into.
      shared = new Map();
      for (const t of swarm?.tracks || []) {
        for (const id of String(t.id || '').split('+')) if (id) shared.set(id, t);
      }
      latest.connectedText = payload.connected
        ? 'Observer connected — no areas of interest in view.'
        : (payload.error ? 'Observer: ' + payload.error : 'Observer not connected.');
      render(payload.items, fleet);
    },
  };
  render([], []);
})();
