# Mobile Design System (phone breakpoint, ≤740px)

This documents the actual rules implemented in `mobile-ui.js` + `styles.css`, not a
proposal. It covers only what changed; the existing color tokens, type scale and
`urban-style.js` cartographic system (route = the only lime accent on the map, etc.)
are unchanged and documented in `README.md`'s "Cartographic design system" section.

## Breakpoints (unchanged, just clarified)

- `≤740px` — phone. The bottom-sheet system in this doc applies here only.
- `741–1060px` — tablet. Still the pre-existing drawer for `#rightPanel`
  (`position:absolute`, slides in from the right); `#leftPanel` stays a normal grid
  column. Not touched in this pass.
- `>1060px` — desktop three-column grid. Not touched.

## The bottom sheet

`#leftPanel` (Plan) and `#rightPanel` (Results) become fixed-position sheets pinned
to the bottom of the viewport, `88dvh` tall (capped at `calc(100% - 64px)` so there's
always at least a 64px map sliver under the topbar even at full), moved with a single
`transform: translateY()` — never animating `height`, so it's one GPU-composited
property.

Three snap levels, expressed as "pixels of the sheet's own height left visible":

| Level | Visible height | Use |
|---|---|---|
| `hidden` | 0 (pushed fully off-screen) | the non-active sheet |
| `collapsed` | 64px | default resting state — handle + one-line label, map is primary |
| `half` | 50% of the viewport height | auto-opened when routes are generated |
| `full` | the sheet's full `88dvh` | user explicitly expanded it |

Interaction:

- **Drag** the handle (not the panel body) to move between any two levels; release
  snaps to whichever of the four targets is numerically closest to where you let go.
- **Tap** the handle (movement under 8px, under 350ms) toggles `collapsed ↔ full`.
- **Tap the map** while a sheet is `full` collapses it to `collapsed` — it never jumps
  straight to `hidden` from a map tap, so the user doesn't lose their place.
- Opening one sheet (`mobilePlan`/`mobileResults` buttons, or the auto-open on route
  generation) always sets the other to `hidden`.
- The scrollable form/results content (`.panel-scroll` / `.right-scroll`) is
  untouched — only the handle has pointer listeners, so scrolling a long form never
  fights a drag gesture, and dragging the handle never scrolls the content.

## Z-index (phone breakpoint)

```
20  topbar, nav-overlay (full-screen live navigation)
19  the open bottom sheet
18  .mobile-bottom (Plan/Results buttons) — correctly hidden under an open sheet
17  (unused, was the old tablet drawer's layer; left as-is on tablet)
5   left/right panel on desktop (grid item, not a sheet there)
```

`body.nav-mode` (pre-existing, unchanged) still force-hides the sheet, topbar, and
`.mobile-bottom` with `display:none!important` — navigation takes the whole screen
regardless of z-index.

## Safe area

`env(safe-area-inset-top)` is added to the topbar's padding and to `.app-layout`'s
height calculation; `env(safe-area-inset-bottom)` is added to the sheet's own
bottom padding, to `.mobile-bottom`'s offset, and is already present (pre-existing)
on `.nav-overlay`'s bottom bar. Verified by reading computed `env()` resolution
isn't available to test without a real notched device/simulator — see
`MOBILE_TEST_REPORT.md` for what was and wasn't checked here.

## Motion

One transition rule, applied to the sheet's `transform`:
`transition: transform .28s cubic-bezier(.22,.61,.36,1)`, turned off entirely under
`@media(prefers-reduced-motion: reduce)`. During an active drag the transition is set
to `none` so the sheet tracks the finger with zero lag, then restored on release.

## Install banner

A fixed bar under the topbar (`z-index:21`, above everything), shown only after a
real route exists (see `PWA_IMPLEMENTATION.md`), dismissible, remembers dismissal in
`localStorage`, hidden during `body.nav-mode`.

## What this system does not cover yet

Explore Urban Data's mobile layout (§12 of the original brief) — the 13-map panel,
Street Segment Inspector and Urban Data Layers catalog — still use their own,
pre-existing `position:absolute` phone CSS, not this sheet system. See
`MOBILE_IMPLEMENTATION_REPORT.md` §3 for why this was deferred.
