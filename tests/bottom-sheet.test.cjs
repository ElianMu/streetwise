'use strict';
// Bottom-sheet geometry (bottom-sheet.js): free positions, no snap points, safe-area-aware bounds, dismiss.
const assert = require('node:assert/strict');
const S = require('../bottom-sheet.js');

const g = { maxH: 700, viewportH: 844, safeBottom: 34 };   // iPhone 14-ish portrait
const b = S.bounds(g);
assert.equal(b.min, 64 + 34, 'peek strip clears the home indicator');
assert.equal(b.max, 700);

// Any release height inside the usable range rests exactly there — 20/35/50/65/80 % and arbitrary values.
for (const frac of [0.2, 0.35, 0.5, 0.65, 0.8, 0.237, 0.555, 0.913]) {
  const h = Math.round(frac * g.viewportH);
  const r = S.release(h, g);
  assert.equal(r.dismiss, false);
  assert.equal(r.height, Math.min(h, b.max), `released at ${h}px rests at ${Math.min(h, b.max)}px, not at a snap point`);
}
// Never beyond the usable screen.
assert.equal(S.release(5000, g).height, b.max);
assert.equal(S.release(b.min - 5, g).height, b.min);
// Far below the peek strip: dismissed (swipe away = Back), not snapped.
assert.equal(S.release(10, g).dismiss, true);
// Dragging follows the finger 1:1 in both directions, clamped to [0, max].
assert.equal(S.dragHeight(400, -50, g), 450);
assert.equal(S.dragHeight(400, 120, g), 280);
assert.equal(S.dragHeight(400, -999, g), 700);
assert.equal(S.dragHeight(400, 999, g), 0);
// Presets are only where the app opens a sheet.
assert.equal(S.presetHeight('full', g), 700);
assert.equal(S.presetHeight('collapsed', g), 98);
assert.equal(S.presetHeight('half', g), 422);
assert.equal(S.levelFor(700, g), 'full');
assert.equal(S.levelFor(98, g), 'collapsed');
assert.equal(S.levelFor(333, g), 'custom');
// A tiny screen never produces min > max.
const tiny = S.bounds({ maxH: 60, safeBottom: 34 });
assert.ok(tiny.min <= tiny.max);
console.log('BOTTOM SHEET PASS: free release heights (20–80 % and arbitrary), clamped to safe bounds, 1:1 drag, dismiss below the peek strip, presets only for opening');
