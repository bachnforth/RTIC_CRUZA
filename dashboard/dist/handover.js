'use strict';
// Mission handover: approve or deny handing an observer's cue to an aircraft.
// The queue and every decision live on the server (handover.py), so all open
// pages agree and each decision is logged with the image looked at.
// Approving transmits nothing. For an aircraft whose live link takes a point
// command it prefills that aircraft's command workflow, where the command is
// still reviewed and sent as usual. For any other aircraft it is decision only:
// the approved point is marked on the map (its own marker, never the workflow's
// selected point) for the safety pilot to fly by hand if wanted.
(function () {
  const list = document.querySelector('#handover-list');
  const status = document.querySelector('#handover-status');
  const badge = document.querySelector('#handover-badge');
  if (!list) return;
  const names = {cruza: 'Cruza', quadpi: 'quadpi', rn03: 'TFW drone'};
  // Aircraft a cue can be handed to, and the commands an approval can name.
  const TARGETS = ['quadpi', 'rn03'];
  const HANDOVER_ACTIONS = ['goto', 'loiter', 'arm_mission'];
  const ACTION_LABELS = {goto: 'Fly to point & hold', loiter: 'Loiter (circle)', arm_mission: 'Arm & fly mission'};
  // arm_mission flies the mission already on the aircraft: the cue's point is
  // not used, so a stale position does not block it.
  const POINT_ACTIONS = ['goto', 'loiter'];
  const REASONS = ['False detection', 'Not a priority', 'Unsafe or airspace', 'Duplicate'];
  const cards = new Map();   // request id -> {li, parts}
  let controls = {}, busy = false;
  // The drawer is hidden until there is a request. While one awaits a decision
  // it moves above the map and takes over the top of the page; once none is
  // pending it goes back to its place under the map.
  const drawer = list.closest('details');
  const home = {parent: drawer.parentNode, next: drawer.nextSibling};
  const workspace = document.querySelector('.workspace');
  const announced = new Set();   // pending ids already scrolled to

  const label = id => names[id] || id;
  // Live means the control link takes a point command (the bench link does not).
  const isLive = id => (controls[id]?.actions || []).some(a => HANDOVER_ACTIONS.includes(a.id));
  const coords = d => `${d.lat.toFixed(6)}, ${d.lon.toFixed(6)}`;
  const fmt = n => n.toFixed(6);

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  async function post(body) {
    const res = await fetch('/handover', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body), signal: AbortSignal.timeout(8000)});
    if (!res.ok) throw Error(`Dashboard refused the request (${res.status})`);
    return res.json();
  }

  function prefill(r, actionId) {
    const d = r.decision;
    if (!POINT_ACTIONS.includes(actionId)) {
      const note = `Handover ${r.id} approved (${r.cls}, from ${label(r.src)}): ${label(d.target)}'s ` +
        'own mission is selected. Check it, confirm props and area, then send — nothing has been sent yet.';
      return window.commandWorkflow?.prefill(d.target, actionId, null, note);
    }
    const note = `Handover ${r.id} approved (${r.cls}, from ${label(r.src)}): point prefilled. ` +
      'Set the altitude, review and send — nothing has been sent yet.';
    return window.commandWorkflow?.prefill(d.target, actionId,
      {latitude: d.lat, longitude: d.lon}, note);
  }

  async function decide(r, card, decision) {
    if (busy) return;
    busy = true;
    const p = card.parts;
    p.message.className = 'ho-message';
    p.message.textContent = decision === 'approve' ? 'Approving…' : 'Denying…';
    try {
      const body = {id: r.id, decision};
      if (decision === 'approve') Object.assign(body, {target: p.target.value, action: p.action.value});
      else body.reason = p.reason.value;
      const out = await post(body);
      p.message.textContent = out.message;
      p.message.classList.add(out.ok ? 'ok' : 'failed');
      if (out.ok && decision === 'approve') {
        const d = out.request.decision;
        if (d.mode === 'live') {
          if (!prefill(out.request, d.action)) {
            p.message.textContent += ' The command workflow could not be prefilled; pick the point by hand.';
          }
        } else {
          window.fleetMap?.focusPoint(d.lat, d.lon);
          p.message.textContent = `Recorded for ${label(d.target)} — nothing was sent. ` +
            `Approved point ${coords(d)} is marked ◎ on the map for the safety pilot.`;
        }
      }
    } catch (e) {
      p.message.textContent = `✗ ${e.message}`;
      p.message.classList.add('failed');
    } finally {
      busy = false;
    }
  }

  // Build a card once; later updates only change its text, so selections and
  // the image survive the once-a-second refresh.
  function build(r) {
    const li = el('li', 'ho');
    const figure = el('div', 'ho-figure');
    const img = el('img');
    img.alt = `Image of the ${r.cls} detection`;
    img.hidden = true;
    const noImage = el('span', 'ho-noimage', 'No image received');
    figure.append(img, noImage);

    const body = el('div', 'ho-body');
    const head = el('div', 'ho-head');
    const cls = el('strong'), src = el('span', 'aoi-src'), score = el('span', 'aoi-score');
    const state = el('span', 'ho-state');
    head.append(cls, src, score, state);
    const where = el('p', 'ho-detail'), when = el('p', 'ho-detail');

    const actions = el('div', 'ho-actions');
    const target = el('select'); target.setAttribute('aria-label', 'Aircraft to hand over to');
    const action = el('select'); action.setAttribute('aria-label', 'Command to prefill');
    const approve = el('button', 'ho-approve', 'Approve handover');
    const reason = el('select'); reason.setAttribute('aria-label', 'Reason for denial');
    reason.append(new Option('Deny reason (optional)', ''), ...REASONS.map(x => new Option(x, x)));
    const deny = el('button', 'ho-deny', 'Deny');
    const again = el('button', '', 'Prefill workflow again');
    const copy = el('button', '', 'Copy coordinates');
    actions.append(target, action, approve, reason, deny, again, copy);
    const approved = el('p', 'ho-coords');
    const message = el('p', 'ho-message');

    body.append(head, where, when, approved, actions, message);
    li.append(figure, body);
    const card = {li, parts: {img, noImage, cls, src, score, state, where, when, target, action,
                              approve, reason, deny, again, copy, approved, message}, rev: 0, targetsKey: ''};
    approve.onclick = () => decide(card.request, card, 'approve');
    deny.onclick = () => decide(card.request, card, 'deny');
    again.onclick = () => {
      const d = card.request.decision;
      if (d.mode !== 'live') { window.fleetMap?.focusPoint(d.lat, d.lon); return; }
      if (!prefill(card.request, d.action)) message.textContent = `${label(d.target)} is no longer live.`;
    };
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(coords(card.request.decision));
        message.textContent = 'Coordinates copied.';
      } catch {
        message.textContent = `Copy not allowed here; read them off: ${coords(card.request.decision)}`;
      }
    };
    target.onchange = () => fillActions(card);
    return card;
  }

  function fillActions(card) {
    const id = card.parts.target.value, keep = card.parts.action.value;
    // A live link lists its own commands; decision only names the intent.
    const offered = isLive(id) ? controls[id].actions.filter(a => HANDOVER_ACTIONS.includes(a.id))
      : HANDOVER_ACTIONS.map(a => ({id: a, label: ACTION_LABELS[a]}));
    card.parts.action.replaceChildren(...offered.map(a => new Option(a.label, a.id)));
    if ([...card.parts.action.options].some(o => o.value === keep)) card.parts.action.value = keep;
    card.parts.approve.textContent = isLive(id) ? 'Approve handover' : 'Approve (decision only)';
  }

  function update(card, r) {
    card.request = r;
    const p = card.parts, pending = r.status === 'pending';
    const decisionOnly = r.status === 'approved' && r.decision?.mode !== 'live';
    card.li.className = 'ho ho-' + r.status + (decisionOnly ? ' ho-decision-only' : '');
    p.cls.textContent = r.cls;
    p.src.textContent = r.sources.map(label).join(' + ');
    p.score.textContent = Math.round(r.score * 100) + '%';
    p.state.textContent = pending ? 'AWAITING DECISION'
      : r.status === 'approved' ? `APPROVED → ${label(r.decision.target)}` + (decisionOnly ? ' · DECISION ONLY' : '')
      : r.status === 'denied' ? 'DENIED' + (r.decision?.reason ? ` · ${r.decision.reason}` : '')
      : 'EXPIRED';
    const range = r.range_m === null ? 'range unknown, placed at a default distance' : `est. ${r.range_m} m`;
    p.where.textContent = `${fmt(r.lat)}, ${fmt(r.lon)} · bearing ${r.bearing_deg ?? '?'}° from ${label(r.src)} · ${range}` +
      (r.estimated ? ' · LOCATION ESTIMATED' : '');
    p.when.textContent = `Last seen ${r.age_s.toFixed(0)} s ago · ${r.sightings} sighting${r.sightings === 1 ? '' : 's'} · open ${Math.round(r.open_s)} s` +
      (r.decided_s !== null ? ` · decided ${Math.round(r.decided_s)} s ago` : '');
    if (r.image_rev && r.image_rev !== card.rev) {
      card.rev = r.image_rev;
      p.img.src = `/handover-image/${r.id}?r=${r.image_rev}`;
      p.img.hidden = false; p.noImage.hidden = true;
    }
    // Target menu, marked live or decision only; rebuilt only when that changes.
    const key = TARGETS.map(id => id + (isLive(id) ? ':live' : '')).join(',');
    if (key !== card.targetsKey) {
      card.targetsKey = key;
      const keep = p.target.value || 'quadpi';
      p.target.replaceChildren(...TARGETS.map(id =>
        new Option(`${label(id)} · ${isLive(id) ? 'live' : 'decision only'}`, id)));
      p.target.value = keep;
      fillActions(card);
    }
    for (const x of [p.target, p.action, p.approve, p.reason, p.deny]) x.hidden = !pending;
    const d = r.status === 'approved' ? r.decision : null;
    p.again.hidden = !d || (d.mode === 'live' && !controls[d.target]);
    p.again.textContent = d && d.mode !== 'live' ? 'Show point on map' : 'Prefill workflow again';
    p.copy.hidden = !d;
    p.approved.hidden = !d;
    if (d) p.approved.textContent = (POINT_ACTIONS.includes(d.action)
      ? `Approved point ${coords(d)} · ${ACTION_LABELS[d.action] || d.action}`
      : `Approved: ${ACTION_LABELS[d.action] || d.action} on ${label(d.target)} · cue at ${coords(d)}`) +
      (d.mode === 'live' ? '' : ' · nothing sent');
    const why = r.age_s > 60 && POINT_ACTIONS.includes(p.action.value)
      ? 'Position is over 60 s old; wait for a fresh sighting or deny it.' : '';
    p.approve.disabled = busy || !!why;
    p.approve.title = why;
    // Say on the button itself why it does nothing, not only in the note below.
    p.approve.textContent = why ? 'Approve: waiting for a fresh sighting'
      : isLive(p.target.value) ? 'Approve handover' : 'Approve (decision only)';
    p.deny.disabled = busy;
    if (pending && why && !p.message.textContent.startsWith('Position is over')) {
      p.message.className = 'ho-message failed';
      p.message.textContent = why;
    }
    if (pending && !why && p.message.textContent.startsWith('Position is over')) {
      p.message.className = 'ho-message';
      p.message.textContent = '';
    }
  }

  function render(requests) {
    const seen = new Set();
    for (const r of requests) {
      seen.add(r.id);
      let card = cards.get(r.id);
      if (!card) { card = build(r); cards.set(r.id, card); }
      update(card, r);
    }
    for (const [id, card] of cards) if (!seen.has(id)) { card.li.remove(); cards.delete(id); }
    window.fleetMap?.showHandovers?.(requests
      .filter(r => r.status === 'approved' && r.decision.mode !== 'live')
      .map(r => ({lat: r.decision.lat, lon: r.decision.lon,
                  label: `${r.id} ${r.cls} → ${label(r.decision.target)} · decision only`})));
    // Keep server order: pending (newest first), then decided. Only move cards
    // when the order changes: re-inserting a card closes any menu open in it.
    const order = requests.map(r => cards.get(r.id).li);
    if (order.some((li, i) => list.children[i] !== li) || list.children.length !== order.length) {
      list.replaceChildren(...order);
    }
    const pending = requests.filter(r => r.status === 'pending').length;
    badge.textContent = pending ? `${pending} AWAITING DECISION` : 'NONE PENDING';
    badge.classList.toggle('ho-badge-pending', pending > 0);
    status.textContent = !requests.length ? 'No handover requests. Geolocated observer cues appear here for approval.'
      : `${pending} pending · ${requests.length - pending} recently decided`;
    takeover(requests, pending);
  }

  function takeover(requests, pending) {
    drawer.hidden = !requests.length;
    const atTop = drawer.parentNode !== home.parent;
    if (pending && !atTop && workspace) {
      workspace.before(drawer);
    } else if (!pending && atTop) {
      home.parent.insertBefore(drawer, home.next);
    }
    drawer.classList.toggle('handover-takeover', pending > 0);
    if (pending) drawer.open = true;
    // Bring a new request into view, unless the operator is busy with a command.
    const fresh = requests.filter(r => r.status === 'pending' && !announced.has(r.id));
    fresh.forEach(r => announced.add(r.id));
    if (fresh.length && !document.activeElement?.closest('#command-workflow')) {
      drawer.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
  }

  document.addEventListener('fleet-status', event => {
    controls = event.detail.controls || {};
    render(event.detail.handover || []);
  });
  render([]);
})();
