'use strict';
// One workflow for every platform: platform → command → location/altitude →
// review → send. A platform is LIVE only when the server reports a control
// link for it (quadpi with -QuadControl, TFW drone with -TfwControl); every other platform stays
// PREVIEW ONLY and nothing is transmitted for it. Hold, RTL and Land for a
// live platform also sit in a one-click row that skips review.
(function () {
  const panel = document.querySelector('#command-workflow');
  const $ = selector => panel.querySelector(selector);
  const platform = $('#wf-platform'), command = $('#wf-command'), altitude = $('#wf-altitude');
  const result = $('#wf-result');
  const names = {cruza: 'Cruza', quadpi: 'quadpi', rn03: 'TFW drone'};
  const kinds = {cruza: 'fixed wing', quadpi: 'quad', rn03: 'partner aircraft'};
  // Illustrative only; actual aircraft capabilities have not been verified.
  const previewActions = [
    {id: 'rtl', label: 'RTL', point: false, text: 'Return using the aircraft’s configured home and RTL settings.'},
    {id: 'loiter', label: 'Loiter at point', point: true, altitude: true, text: 'Preview a destination and altitude for loitering.'},
    {id: 'land', label: 'Fly to point and land', point: true, altitude: true, text: 'Preview a destination and transit altitude for landing.', skip: ['cruza']},
    {id: 'arm', label: 'Arm flight motors', point: false, text: 'Motor arming applies to the aircraft; it does not initiate takeoff.'},
    {id: 'disarm', label: 'Disarm flight motors', point: false, text: 'Motor disarming applies to the aircraft, not a location. In-flight disarming can cause a crash.'},
  ];
  const REVIEW_SECONDS = 20;
  let controls = {}, candidate = null, reviewed = null, reviewTimer = null, sending = false, liveKey = '';
  const coordinates = p => `${p.latitude.toFixed(6)}, ${p.longitude.toFixed(6)}`;
  const live = () => controls[platform.value];
  const actionsFor = id => controls[id] ? controls[id].actions : previewActions.filter(a => !a.skip?.includes(id));
  const action = () => actionsFor(platform.value).find(a => a.id === command.value);

  // Whether the aircraft's current state allows a live command right now.
  function blocker(a, link) {
    if (!link?.online) return `No heartbeat from ${names[platform.value]} on the control link.`;
    if (a.id === 'arm' && link.armed) return 'Already armed.';
    if (a.id === 'arm' && ![0, 2, 5, 16].includes(link.mode_id)) return `Mode is ${link.mode}: set the Pocket switch to STABILIZE first.`;
    if (a.id === 'arm_takeoff' && link.armed) return 'Already armed. Use Fly to point & hold, Hold, RTL or Land.';
    if (a.id === 'arm_takeoff' && !link.position) return 'No position fix yet; GUIDED takeoff needs GPS.';
    if (a.id === 'goto' && (!link.armed || link.in_air === false)) return 'Take off first.';
    if (a.id === 'arm_mission') {
      const m = live()?.mission;
      if (link.armed) return 'Already armed: the mission launch starts from the ground.';
      if (!link.position) return 'No position fix yet; the mission needs GPS.';
      if (!m?.known) return `Reading the mission from the aircraft…${m?.error ? ' (' + m.error + ')' : ''}`;
      if (m.first !== 'NAV_TAKEOFF') return `The mission must start with a takeoff (first item is ${m.first}).`;
      if (m.farthest_m == null) return 'Mission home is not set yet (needs a GPS fix).';
    }
    if (a.id === 'loiter') {
      const c = live()?.circle;
      if (!link.armed || link.in_air === false) return 'Take off first.';
      if (!c?.known) return 'Circle settings not read from the aircraft yet.';
      if (c.throttle_pwm == null) return 'No Pocket throttle reading.';
      if (c.throttle_pwm < c.throttle_centre[0] || c.throttle_pwm > c.throttle_centre[1])
        return `Pocket throttle is ${c.throttle_pwm} µs: centre it first (CIRCLE uses it to climb or sink).`;
    }
    if (a.id === 'disarm' && link.armed && link.in_air === true) return 'In the air: use Land, not Disarm.';
    if (a.id === 'disarm' && !link.armed) return 'Already disarmed.';
    return '';
  }
  // point: true (required) or 'optional'; altitude: true or 'with-point'.
  const usesPoint = a => a?.point === true || (a?.point === 'optional' && !!candidate);
  const needsAltitude = a => a?.altitude === true || (a?.altitude === 'with-point' && !!candidate);
  function altitudeValue(a) {
    if (!needsAltitude(a)) return null;
    const value = Number(altitude.value), max = live()?.max_altitude_m ?? Infinity;
    return altitude.value.trim() !== '' && Number.isFinite(value) && value >= (live() ? 1 : 0) && value > 0 && value <= max ? value : undefined;
  }
  function invalidate() {
    reviewed = null;
    clearTimeout(reviewTimer);
    $('#wf-review').hidden = true;
    $('#wf-confirm').disabled = true;
  }
  function fillPlatforms() {
    for (const option of platform.options) {
      if (!option.value) continue;
      option.textContent = `${names[option.value]} · ${kinds[option.value]} · ${controls[option.value] ? 'LIVE' : 'preview only'}`;
    }
  }
  // Always starts with no command, so nothing carries over to another aircraft
  // or from preview to live.
  function fillCommands() {
    command.replaceChildren(new Option('Choose a command…', ''));
    for (const a of actionsFor(platform.value)) if (!a.immediate) command.add(new Option(a.label, a.id));
    // Immediate commands also appear in the menu for completeness.
    for (const a of actionsFor(platform.value)) if (a.immediate) command.add(new Option(a.label, a.id));
    command.disabled = !platform.value;
  }
  function render() {
    const a = action(), control = live(), link = control?.link;
    const isLive = !!control;
    $('#wf-mode').textContent = !platform.value ? (Object.keys(controls).length ? 'LIVE FOR ' + Object.keys(controls).map(id => names[id]).join(', ') : 'PREVIEW ONLY') : isLive ? 'LIVE · SENDS TO AIRCRAFT' : 'PREVIEW ONLY';
    panel.classList.toggle('wf-live', isLive);
    $('#wf-intro').textContent = isLive
      ? `Commands for ${names[platform.value]} are sent to the aircraft via ${control.target}. The aircraft must accept each one. The Pocket stays the override.`
      : platform.value ? `${names[platform.value]} is preview only: no command path exists and nothing is transmitted.`
        : 'Choose an aircraft. LIVE platforms send real commands; the others are preview only.';
    const state = $('#wf-state');
    state.hidden = !isLive;
    if (isLive) {
      const p = link?.position;
      state.textContent = !link?.online ? `${names[platform.value]}: no heartbeat on the control link`
        : `${names[platform.value]}: ${link.armed ? 'ARMED' : 'disarmed'} · ${link.mode}` +
          (link.in_air === null ? '' : link.in_air ? ' · in the air' : ' · on the ground') +
          (p ? ` · ${p.altitude_relative_m.toFixed(1)} m above home` : ' · no position');
      state.classList.toggle('wf-armed', !!link?.armed);
    }
    $('#wf-destination').textContent = candidate ? `Point: ${coordinates(candidate)}` : 'No point selected.';
    $('#wf-clear').disabled = !candidate;
    $('#wf-pick').textContent = candidate ? 'Change point on map' : 'Pick point on map';
    $('#wf-point-note').textContent = !a ? 'You can pick a point before choosing a command.'
      : a.point === 'optional' ? (candidate ? 'It will fly to this point and circle it.' : 'Optional: pick a point to circle it; otherwise it circles where it is now.')
      : a.point ? 'This command uses the selected point.' : 'This command ignores the selected point.';
    const why = isLive && a ? blocker(a, link) : '';
    $('#wf-action-note').textContent = a ? a.text + (why ? ` — ${why}` : '') : 'Select an aircraft, then a command.';
    $('#wf-altitude-label').hidden = !needsAltitude(a);
    $('#wf-altitude-note').textContent = needsAltitude(a)
      ? (isLive ? `Metres above home, 1–${control.max_altitude_m}. Terrain clearance is not checked.` : 'Enter a positive altitude in metres relative to home. No default altitude is assumed; terrain clearance is not evaluated.')
      : '';
    $('#wf-build').disabled = sending || !platform.value || !a || (a.point === true && !candidate) || altitudeValue(a) === undefined || !!why;
    $('#wf-build').textContent = isLive ? '4 · Review command' : '4 · Review preview';
    // One-click row for the live platform.
    // Show the loaded mission's route while its launch is selected.
    const m = control?.mission;
    if (isLive && a?.id === 'arm_mission' && m?.known && m.route?.length) window.fleetMap.showRoute(m.route, m.home);
    else window.fleetMap.clearRoute();
    // Only the immediate commands this link offers (the bench link has none).
    const quick = $('#wf-quick'), offered = new Set((control?.actions || []).map(x => x.id));
    quick.hidden = !isLive || !quick.querySelector('button[data-action]') ||
      ![...quick.querySelectorAll('button[data-action]')].some(b => offered.has(b.dataset.action));
    quick.querySelectorAll('button[data-action]').forEach(b => {
      b.hidden = !offered.has(b.dataset.action);
      b.disabled = sending || !!control?.busy || !link?.online;
    });
    const log = $('#wf-log');
    log.replaceChildren(...(control?.history || []).slice().reverse().map(e => {
      const li = document.createElement('li');
      li.className = e.ok ? 'ok' : 'failed';
      li.textContent = `${e.time} · ${e.action} · ${e.result}`;
      return li;
    }));
  }
  async function send(id, extra = {}) {
    const a = actionsFor(platform.value).find(x => x.id === id), target = platform.value;
    const body = Object.assign({platform: target, action: id}, extra);
    if (needsAltitude(a)) body.altitude_m = altitudeValue(a);
    if (usesPoint(a)) Object.assign(body, {latitude: candidate.latitude, longitude: candidate.longitude});
    sending = true; invalidate(); render();
    result.className = '';
    result.textContent = `Sending ${a.label} to ${names[target]}…`;
    try {
      const res = await fetch('/control', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: AbortSignal.timeout(15000)});
      if (!res.ok) throw Error(`Dashboard refused the request (${res.status})`);
      const entry = await res.json();
      result.textContent = `${entry.ok ? '✓' : '✗'} ${names[target]} · ${a.label}: ${entry.result}`;
      result.className = entry.ok ? 'ok' : 'failed';
    } catch (e) {
      result.textContent = `✗ ${e.message}. Check the aircraft before trying again.`;
      result.className = 'failed';
    } finally {
      sending = false; render();
    }
  }

  platform.onchange = () => {
    invalidate();
    fillCommands();
    for (const id of Object.keys(names)) document.getElementById(id)?.classList.toggle('preview-selected', id === platform.value);
    document.dispatchEvent(new CustomEvent('fleet-preview-platform', {detail: platform.value}));
    result.textContent = '';
    render();
  };
  command.onchange = () => { invalidate(); result.textContent = ''; render(); };
  altitude.oninput = () => { invalidate(); render(); };
  $('#wf-pick').onclick = () => {
    invalidate();
    window.fleetMap.startPick();
    result.className = '';
    result.textContent = 'Select a point on the map. Escape cancels point selection.';
  };
  document.addEventListener('fleet-candidate', event => { candidate = event.detail; invalidate(); result.textContent = ''; render(); });
  document.addEventListener('fleet-pick-cancelled', () => { result.textContent = 'Point selection cancelled.'; });
  $('#wf-clear').onclick = () => { candidate = null; window.fleetMap.clearCandidate(); invalidate(); render(); };
  $('#wf-build').onclick = () => {
    if ($('#wf-build').disabled) return;
    window.fleetMap.cancelPick();
    const a = action(), isLive = !!live();
    let sentence = `${names[platform.value]} — ${a.label}. `;
    if (a.id === 'arm_mission' && isLive) {
      const m = live().mission;
      sentence += `Mission on the aircraft (read ${m.age_s} s ago): ${m.count} items, ${m.waypoints} waypoints. ` +
        `Takes off to ${m.takeoff_m} m, highest ${m.max_alt_m} m above home, farthest ${m.farthest_m} m from home, ` +
        `ends with ${m.last}. The route is shown on the map. Pocket throttle low to arm; take over with the mode switch. `;
      if (m.non_rel_alt) sentence += `${m.non_rel_alt} items use absolute or terrain altitude; check them in your GCS. `;
    } else if (a.id === 'loiter' && isLive) {
      const c = live().circle;
      sentence += candidate ? `Fly to ${coordinates(candidate)} at ${altitudeValue(a)} m above home, then circle. `
        : 'Circle where it is now, at its current altitude. ';
      sentence += `Aircraft circle: ${c.radius_m} m radius, ${c.direction}, ${Math.abs(c.rate_deg_s)}°/s. `;
      sentence += c.centred ? 'Centred on that position. '
        : `CIRCLE_OPTIONS does not start at centre: the circle's centre will be ${c.radius_m} m ahead of the aircraft. `;
      sentence += 'Keep the Pocket throttle centred. ';
    } else {
      if (usesPoint(a)) sentence += `Destination ${coordinates(candidate)}. `;
      if (needsAltitude(a)) sentence += `Altitude ${altitudeValue(a)} m above home. `;
      if (!usesPoint(a) && !needsAltitude(a)) sentence += 'No map destination is used. ';
    }
    if (a.id === 'arm') sentence += `Current mode: ${live().link?.mode ?? 'unknown'} (set by the Pocket). `;
    sentence += isLive ? 'THIS WILL BE SENT TO THE AIRCRAFT.' : 'PREVIEW ONLY — nothing will be sent to an aircraft.';
    $('#wf-summary').textContent = sentence;
    $('#wf-confirm').textContent = isLive ? `Send to ${names[platform.value]}` : 'Complete preview · no transmission';
    $('#wf-review').hidden = false;
    $('#wf-confirm').disabled = false;
    reviewed = {platform: platform.value, action: a.id, live: isLive,
                // The server refuses the launch if the aircraft's mission no longer matches this.
                extra: a.id === 'arm_mission' && isLive ? {mission_signature: live().mission.signature} : {}};
    result.className = '';
    result.textContent = isLive ? `Review expires in ${REVIEW_SECONDS} s.` : '';
    if (isLive) reviewTimer = setTimeout(() => { invalidate(); result.textContent = 'Review expired; nothing sent.'; }, REVIEW_SECONDS * 1000);
  };
  $('#wf-confirm').onclick = () => {
    if (!reviewed) return;
    if (reviewed.live && controls[reviewed.platform]) { send(reviewed.action, reviewed.extra); return; }
    invalidate();
    result.className = '';
    result.textContent = 'Preview completed locally. Nothing was transmitted; aircraft state has not changed.';
  };
  $('#wf-cancel').onclick = () => { invalidate(); result.textContent = ''; render(); };
  $('#wf-quick').querySelectorAll('button[data-action]').forEach(button => {
    button.onclick = () => { if (live()) send(button.dataset.action); };
  });
  document.addEventListener('fleet-status', event => {
    controls = event.detail.controls || {};
    const key = Object.keys(controls).sort().join(',');
    if (key !== liveKey) {
      // A platform went live or stopped being live: rebuild menus, drop any review.
      liveKey = key;
      invalidate();
      fillPlatforms();
      fillCommands();
      const drawer = panel.closest('details');
      if (key && drawer) drawer.open = true;
      document.querySelector('#wf-badge-text').textContent = key ? 'LIVE' : 'PREVIEW ONLY';
      const notice = document.querySelector('.notice');
      notice.textContent = key ? `Live control ON for ${Object.keys(controls).map(id => names[id]).join(', ')} · each safety pilot's RC is the override · other aircraft are read-only` : 'Read-only · Pilot QGroundControl connections remain independent';
      notice.classList.toggle('notice-control', !!key);
      document.querySelector('footer p:last-child').textContent = key
        ? 'Pause stops extra video; telemetry continues. Live control is ON for the platforms marked LIVE; the rest have no flight controls.'
        : 'Pause stops extra video; telemetry continues. Closing this page stops both optional laptop copies. Video delays differ between aircraft. No flight controls.';
    }
    render();
  });
  // Used by the mission handover panel after an approval: selects the aircraft
  // and command. With a point (fly to / loiter) it drops the approved point and
  // the operator still sets the altitude, reviews and sends. Without one (Arm &
  // fly mission) it opens the review of the aircraft's own mission, leaving
  // only Send. Nothing is transmitted from here.
  window.commandWorkflow = {
    prefill(target, actionId, point, note) {
      if (!controls[target]) return false;
      platform.value = target;
      platform.onchange();
      if (![...command.options].some(o => o.value === actionId)) return false;
      command.value = actionId;
      command.onchange();
      if (point) window.fleetMap.setCandidate(point.latitude, point.longitude);
      const drawer = panel.closest('details');
      if (drawer) drawer.open = true;
      if (!point) $('#wf-build').onclick();
      const reviewing = !point && !$('#wf-review').hidden;
      result.className = '';
      // Keep the review's own expiry notice after the handover note.
      result.textContent = note + (reviewing ? ` ${result.textContent}`
        : point ? '' : ` Not ready to review yet: ${$('#wf-action-note').textContent}`);
      panel.scrollIntoView({block: 'nearest', behavior: 'smooth'});
      (reviewing ? $('#wf-confirm') : point ? altitude : command).focus({preventScroll: true});
      return true;
    },
  };
  fillPlatforms();
  render();
})();
