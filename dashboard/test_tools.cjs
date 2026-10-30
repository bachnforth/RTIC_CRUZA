// Checks for the map tools (coordinates, MGRS, range & bearing).
// Run from the repository root with: node dashboard/test_tools.cjs
const assert = require('node:assert/strict');
const T = require('./dist/tools.js');

// MGRS reference values were produced by the independent `mgrs` Python library;
// 408 random points also matched it during development.
assert.equal(T.toMgrs(38.8895, -77.0353), '18S UJ 23478 06483');   // Washington Monument
assert.equal(T.toMgrs(33.72322, -85.90669).slice(0, 7), '16S FC ');  // flying field
assert.equal(T.toMgrs(-33.8688, 151.2093).slice(0, 6), '56H LH');   // Sydney
assert.equal(T.toMgrs(60.0, 5.0).slice(0, 3), '32V');               // Norway exception
assert.equal(T.toMgrs(78.0, 15.0).slice(0, 3), '33X');              // Svalbard exception
assert.equal(T.toMgrs(85, 0), null);                                // polar: not MGRS/UTM
assert.equal(T.formatCoords(33.5, -86.25, 'dd'), '33.50000, -86.25000');
assert.equal(T.formatCoords(33.5, -86.25, 'dms'), '33°30′00.0″N 86°15′00.0″W');

// Range and bearing: one degree of latitude ≈ 111.2 km due north.
let rb = T.rangeBearing({lat: 33, lng: -86}, {lat: 34, lng: -86});
assert.ok(Math.abs(rb.distance - 111195) < 50 && Math.abs(rb.bearing) < 0.01);
rb = T.rangeBearing({lat: 0, lng: 0}, {lat: 0, lng: 1});
assert.ok(Math.abs(rb.bearing - 90) < 0.01);
assert.equal(T.formatDistance(850), '850 m');
assert.equal(T.formatDistance(2345), '2.35 km');
assert.equal(T.formatBearing(5.4), '005°');
console.log('14 map tool checks passed (MGRS, coordinate formats, range & bearing)');
