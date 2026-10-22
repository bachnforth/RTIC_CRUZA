'use strict';
// Local interaction preview only. No transport, persistence or command sender.
(function () {
  const panel = document.querySelector('#command-preview');
  const platform = panel.querySelector('#preview-platform');
  const command = panel.querySelector('#preview-command');
  const altitude = panel.querySelector('#preview-altitude');
  const review = panel.querySelector('#preview-review');
  const result = panel.querySelector('#preview-result');
  const destination = panel.querySelector('#preview-destination');
  const names = {cruza: 'Cruza', quadpi: 'quadpi', rn03: 'TFW drone'};
  const actions = {
    rtl: {label: 'RTL', point: false, text: 'Return using the aircraft’s configured home and RTL settings.'},
    loiter: {label: 'Loiter at point', point: true, altitude: true, text: 'Preview a destination and altitude for loitering.'},
    land: {label: 'Fly to point and land', point: true, altitude: true, text: 'Preview a destination and transit altitude for landing.'},
    arm: {label: 'Arm flight motors', point: false, text: 'Motor arming applies to the aircraft; it does not initiate takeoff.'},
    disarm: {label: 'Disarm flight motors', point: false, text: 'Motor disarming applies to the aircraft, not a location. In-flight disarming can cause a crash.'},
  };
  let candidate = null, reviewed = false;
  const coordinates = p => `${p.latitude.toFixed(6)}, ${p.longitude.toFixed(6)}`;
  function invalidate() {
    reviewed = false;
    review.hidden = true;
    result.textContent = '';
    panel.querySelector('#preview-confirm').disabled = true;
  }
  function render() {
    const action = actions[command.value];
    destination.textContent = candidate ? `Candidate point: ${coordinates(candidate)}` : 'No candidate point selected.';
    panel.querySelector('#preview-clear').disabled = !candidate;
    panel.querySelector('#preview-pick').textContent = candidate ? 'Change point on map' : 'Pick point on map';
    panel.querySelector('#preview-point-note').textContent = action ? (action.point ? 'This preview uses the selected point.' : 'This action ignores the candidate point. RTL does not change home.') : 'You can save a candidate point before choosing an aircraft.';
    panel.querySelector('#preview-action-note').textContent = action ? action.text : 'Select an aircraft, then an action.';
    panel.querySelector('#preview-altitude-label').hidden = !action?.altitude;
    const validAltitude = !action?.altitude || (altitude.value.trim() !== '' && Number.isFinite(Number(altitude.value)) && Number(altitude.value) > 0);
    panel.querySelector('#preview-build').disabled = !platform.value || !action || (action.point && !candidate) || !validAltitude;
    panel.querySelector('#preview-altitude-note').textContent = action?.altitude ? 'Enter a positive altitude in metres relative to home. No default altitude is assumed; terrain clearance is not evaluated.' : '';
  }
  platform.onchange = () => {
    invalidate();
    command.replaceChildren(new Option('Choose an action…', ''));
    // Illustrative menu only; actual aircraft capabilities have not been verified.
    if (platform.value) {
      for (const [id, action] of Object.entries(actions)) {
        if (id === 'land' && platform.value === 'cruza') continue;
        command.add(new Option(action.label, id));
      }
    }
    command.disabled = !platform.value;
    for (const id of Object.keys(names)) document.getElementById(id)?.classList.toggle('preview-selected', id === platform.value);
    document.dispatchEvent(new CustomEvent('fleet-preview-platform', {detail: platform.value}));
    render();
  };
  command.onchange = () => { invalidate(); render(); };
  altitude.oninput = () => { invalidate(); render(); };
  panel.querySelector('#preview-pick').onclick = () => {
    invalidate();
    window.fleetMap.startPick();
    result.textContent = 'Select a point on the map. Escape cancels point selection.';
  };
  document.addEventListener('fleet-candidate', event => {
    candidate = event.detail;
    invalidate(); render();
  });
  document.addEventListener('fleet-pick-cancelled', () => { result.textContent = 'Point selection cancelled.'; });
  panel.querySelector('#preview-clear').onclick = () => {
    candidate = null;
    window.fleetMap.clearCandidate();
    invalidate(); render();
  };
  panel.querySelector('#preview-build').onclick = () => {
    if (panel.querySelector('#preview-build').disabled) return;
    window.fleetMap.cancelPick();
    const action = actions[command.value];
    let sentence = `${names[platform.value]} — ${action.label}. `;
    sentence += action.point ? `Destination ${coordinates(candidate)}. Altitude ${Number(altitude.value)} m relative to home. ` : 'No map destination is used. ';
    sentence += 'PREVIEW ONLY — nothing will be sent to an aircraft.';
    panel.querySelector('#preview-summary').textContent = sentence;
    review.hidden = false;
    reviewed = true;
    result.textContent = '';
    panel.querySelector('#preview-confirm').disabled = false;
  };
  panel.querySelector('#preview-confirm').onclick = () => {
    if (!reviewed) return;
    result.textContent = 'Preview completed locally. Nothing was transmitted; aircraft state has not changed.';
    panel.querySelector('#preview-confirm').disabled = true;
  };
  panel.querySelector('#preview-cancel').onclick = () => { invalidate(); render(); };
  render();
})();
