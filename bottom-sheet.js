'use strict';
/* Bottom-sheet geometry shared by every phone sheet (mobile-ui.js: Plan, Your routes, Explore Urban Data).

   A sheet is described by ONE number: its visible height in px, measured from the bottom of the viewport. The
   sheet element is given exactly that height (bottom-anchored, position:fixed), so its scroll container always
   ends at the bottom of the screen and every section — down to Technical details — can be scrolled into view at
   any height. There are no snap points: a drag ends where the finger is released. The named levels below are only
   the heights the app itself opens a sheet at (and the handle tap toggles between); the user can leave a sheet
   anywhere between the peek strip and the maximum.

   Pure functions, no DOM, so they can be unit-tested in Node (tests/bottom-sheet.test.cjs). */
const BottomSheet = (() => {
  const PEEK_PX = 64;            // handle + label strip of a collapsed sheet (plus the bottom safe area)
  const HALF_FRACTION = 0.5;     // the "half" preset: half of the visible viewport
  const DISMISS_FRACTION = 0.6;  // released below 60 % of the peek strip = swiped away
  const EDGE_PX = 2;             // within 2 px of an edge counts as that edge (sub-pixel rounding)

  const clamp = (h, min, max) => Math.min(max, Math.max(min, h));

  /** Height bounds for an open sheet. maxH = the sheet's CSS maximum (below the header, safe areas included),
      safeBottom = bottom safe-area inset, which the peek strip must clear. */
  function bounds({ maxH, safeBottom = 0 }) {
    const min = Math.min(PEEK_PX + Math.max(0, safeBottom), maxH);
    return { min, max: Math.max(min, maxH) };
  }

  /** Height the app opens a sheet at for a named level. */
  function presetHeight(level, { maxH, viewportH, safeBottom = 0 }) {
    const b = bounds({ maxH, safeBottom });
    if (level === 'full') return b.max;
    if (level === 'collapsed') return b.min;
    if (level === 'half') return clamp(Math.round(viewportH * HALF_FRACTION), b.min, b.max);
    return null;
  }

  /** Height while the finger is down: follows it 1:1, allowed below the peek strip (to show a dismiss) but never
      above the maximum or below 0. */
  function dragHeight(startH, dy, { maxH }) { return clamp(startH - dy, 0, maxH); }

  /** Where a released drag ends: exactly where it was released, clamped to the usable range; a release far
      below the peek strip dismisses the sheet. */
  function release(h, { maxH, safeBottom = 0 }) {
    const b = bounds({ maxH, safeBottom });
    if (h < b.min * DISMISS_FRACTION) return { dismiss: true, height: 0 };
    return { dismiss: false, height: Math.round(clamp(h, b.min, b.max)) };
  }

  /** The level name a height reads as: full / collapsed at the edges, otherwise "custom" (a free position). */
  function levelFor(h, { maxH, safeBottom = 0 }) {
    const b = bounds({ maxH, safeBottom });
    if (h >= b.max - EDGE_PX) return 'full';
    if (h <= b.min + EDGE_PX) return 'collapsed';
    return 'custom';
  }

  return { PEEK_PX, HALF_FRACTION, DISMISS_FRACTION, clamp, bounds, presetHeight, dragHeight, release, levelFor };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = BottomSheet;
