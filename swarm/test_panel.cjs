// Areas-of-interest panel, driven the way the browser drives it.
// Checks the one thing that would quietly mislead an operator: a cue from the
// quad or the TFW drone must never be placed using the Cruza's telemetry.
// Run: node swarm/test_panel.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = path.join(__dirname, '..', 'dashboard', 'dist', 'observations.js');

// --- the smallest DOM the panel actually touches --------------------------
function element(tag) {
  return {
    tag, className: '', textContent: '', children: [], disabled: false,
    title: '', onclick: null,
    append(...kids) { this.children.push(...kids); },
    replaceChildren(...kids) { this.children = kids; },
    get text() {
      return [this.textContent, ...this.children.map(c => c.text)].join(' ').trim();
    },
  };
}

function run() {
  const list = element('ul');
  const status = element('p');
  const nodes = {'#aoi-list': list, '#aoi-status': status};
  const aois = [];
  const candidates = [];
  const sandbox = {
    document: {querySelector: s => nodes[s] || null, createElement: element},
    window: {fleetMap: {setAOIs: a => aois.push(a),
                        setCandidate: (lat, lon) => candidates.push([lat, lon])}},
    console,
  };
  sandbox.window.document = sandbox.document;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, 'utf8'), sandbox,
                  {filename: 'observations.js'});
  return {list, status, aois, candidates, api: sandbox.window.observations};
}

const cue = (src, cls, extra = {}) => ({
  id: `${src}/${cls}@0`, src, cls, score: 0.8, az_rel_deg: 0, el_rel_deg: -5,
  count: 3, last_seen_age: 2, bbox: [0.4, 0.4, 0.1, 0.1], ...extra,
});
const vehicle = (name, lat, lon, agl, heading) => ({
  name, online: true, heading_deg: heading, pitch_deg: 0,
  position: {latitude: lat, longitude: lon, altitude_relative_m: agl,
             heading_deg: heading},
});

const CRUZA = vehicle('cruza', 33.7235577, -85.9070862, 100, 90);
const QUADPI = vehicle('quadpi', 33.7232, -85.9035, 60, 90);

// 1. A Cruza cue with no server picture still works: the local fallback.
{
  const {list, api} = run();
  api.update({items: [cue('cruza', 'person')], connected: true, error: ''},
             [CRUZA], null);
  assert.equal(list.children.length, 1);
  const text = list.children[0].text;
  assert.match(text, /person/);
  assert.match(text, /Bearing 90/, 'cruza fallback should give a bearing');
  assert.match(text, /est\. \d+ m/, 'and a range from its own depression');
  console.log('1. cruza cue, no server picture: placed by the local fallback');
}

// 2. A quadpi cue with no server picture must NOT borrow Cruza telemetry.
{
  const {list, api} = run();
  api.update({items: [cue('quadpi', 'car')], connected: true, error: ''},
             [CRUZA, QUADPI], null);
  assert.equal(list.children.length, 1);
  const text = list.children[0].text;
  assert.match(text, /car/);
  assert.match(text, /Bearing unavailable/,
               'a quadpi cue must stay unlocated without a server position');
  assert.doesNotMatch(text, /Bearing 90/);
  console.log('2. quadpi cue, no server picture: left unlocated, not misplaced');
}

// 3. With the server picture, each cue uses its own aircraft's position.
{
  const {list, aois, api} = run();
  const swarmPicture = {
    cues: [cue('cruza', 'person', {bearing_deg: 90, range_m: 373,
                                   lat: 33.72356, lon: -85.90350, estimated: false}),
           cue('quadpi', 'person', {bearing_deg: 270, range_m: 104,
                                    lat: 33.72358, lon: -85.90352, estimated: false})],
    tracks: [], sources: ['cruza', 'quadpi'], cross_cued: 0, fuse_radius_m: 120,
  };
  api.update({items: [cue('cruza', 'person'), cue('quadpi', 'person')],
              connected: true, error: ''}, [CRUZA, QUADPI], swarmPicture);
  assert.equal(list.children.length, 2);
  assert.match(list.children[0].text, /Bearing 90/);
  assert.match(list.children[1].text, /Bearing 270/,
               'the quadpi row must use the server bearing, not the Cruza one');
  assert.match(list.children[1].text, /est\. 104 m/);
  console.log('3. server picture: each row uses its own reporting aircraft');
}

// 4. A cross-cued track says which other aircraft saw it, and how far apart.
{
  const {list, api} = run();
  const ids = ['cruza/person@0', 'quadpi/person@0'];
  const swarmPicture = {
    cues: [cue('cruza', 'person', {bearing_deg: 90, range_m: 373,
                                   lat: 33.72356, lon: -85.9035, estimated: false}),
           cue('quadpi', 'person', {bearing_deg: 270, range_m: 104,
                                    lat: 33.72358, lon: -85.90352, estimated: false})],
    tracks: [{id: ids.join('+'), cls: 'person', score: 0.8,
              sources: ['cruza', 'quadpi'], cross_cued: true, span_m: 37.4,
              located: true, lat: 33.72357, lon: -85.90351, estimated: false,
              contributors: [{src: 'cruza'}, {src: 'quadpi'}]}],
    sources: ['cruza', 'quadpi'], cross_cued: 1, fuse_radius_m: 120,
  };
  api.update({items: [cue('cruza', 'person'), cue('quadpi', 'person')],
              connected: true, error: ''}, [CRUZA, QUADPI], swarmPicture);
  assert.match(list.children[0].text, /also seen by quadpi/);
  assert.match(list.children[0].text, /37 m apart/);
  assert.match(list.children[1].text, /also seen by cruza/);
  console.log('4. cross-cued rows name the other aircraft and the disagreement');
}

// 5. Every row still names its source, and dispatch stays operator-gated.
{
  const {list, candidates, api} = run();
  const located = cue('quadpi', 'person', {bearing_deg: 270, range_m: 104,
                                           lat: 33.72358, lon: -85.90352,
                                           estimated: false});
  api.update({items: [cue('quadpi', 'person')], connected: true, error: ''},
             [QUADPI], {cues: [located], tracks: [], sources: ['quadpi'],
                        cross_cued: 0, fuse_radius_m: 120});
  const row = list.children[0];
  assert.ok(row.text.includes('quadpi'), 'the row must say which aircraft saw it');
  const buttons = row.children.flatMap(c => c.children).filter(c => c.tag === 'button');
  const labels = buttons.map(b => b.textContent);
  assert.deepEqual(labels, ['Confirm', 'Dismiss']);
  assert.equal(candidates.length, 0, 'nothing may be dispatched unprompted');
  // Confirm, then dispatch: still two deliberate operator actions.
  buttons[0].onclick();
  const after = list.children[0].children.flatMap(c => c.children)
    .filter(c => c.tag === 'button');
  const send = after.find(b => b.textContent === 'Send to dispatch');
  assert.ok(send, 'confirming should offer dispatch');
  assert.equal(candidates.length, 0);
  send.onclick();
  assert.equal(candidates.length, 1, 'dispatch only on the operator click');
  console.log('5. source shown; dispatch needs confirm then send, nothing automatic');
}

console.log('\nAll panel checks passed');
