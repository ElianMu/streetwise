'use strict';

/** Mobile bottom-sheet shell for the phone breakpoint (<=740px).
    Replaces the old side-drawer toggle (leftPanel/rightPanel sliding in from the
    edges) with a real bottom sheet: collapsed / half / full, drag + tap to move,
    one sheet open at a time. Does not touch route/journey/nav business logic —
    it only changes how the existing #leftPanel / #rightPanel are shown on phones.
    Desktop and tablet (>740px) are untouched: this script no-ops there. **/
(function () {
  const BREAKPOINT = '(max-width: 740px)';
  const PEEK_PX = 64;      // visible strip when "collapsed" — the drag handle + label
  const HALF_FRACTION = 0.5; // fraction of viewport height visible when "half"

  const mq = window.matchMedia(BREAKPOINT);
  let active = null;   // 'left' | 'right' | null
  let dragState = null;
  let wired = false;

  const panelFor = (which) => $(which === 'left' ? 'leftPanel' : 'rightPanel');

  // A tap that handled a toggle marks itself here so the button's own
  // synthesized `click` (which always follows pointerup) doesn't re-toggle it
  // a second time; a real keyboard activation (Enter/Space with no preceding
  // pointerdown) is unaffected and still works.
  let suppressClickUntil = 0;

  function ensureHandle(panel, label) {
    if (panel.querySelector('.sheet-handle')) return;
    const handle = document.createElement('div');
    handle.className = 'sheet-handle';
    handle.innerHTML = `<span class="sheet-grip" aria-hidden="true"></span><button type="button" class="sheet-toggle">${label}</button>`;
    panel.insertBefore(handle, panel.firstChild);
    handle.addEventListener('pointerdown', onHandlePointerDown);
    handle.querySelector('.sheet-toggle').addEventListener('click', () => {
      if (Date.now() < suppressClickUntil) return;
      const which = panel === $('leftPanel') ? 'left' : 'right';
      setLevel(which, panel.dataset.level === 'full' ? 'collapsed' : 'full');
    });
  }

  function sheetTotalHeight(panel) {
    return panel.getBoundingClientRect().height || Math.round(window.innerHeight * 0.88);
  }
  function pxForLevel(panel, level) {
    const total = sheetTotalHeight(panel);
    if (level === 'hidden') return total + 40;
    if (level === 'collapsed') return Math.max(0, total - PEEK_PX);
    if (level === 'half') return Math.max(0, total - Math.round(window.innerHeight * HALF_FRACTION));
    return 0; // full
  }
  function applyTransform(panel, px) { panel.style.transform = `translateY(${Math.max(0, px)}px)`; }

  function setLevel(which, level) {
    if (!mq.matches) return;
    const panel = panelFor(which);
    const other = panelFor(which === 'left' ? 'right' : 'left');
    panel.dataset.level = level;
    panel.style.transition = '';
    applyTransform(panel, pxForLevel(panel, level));
    const open = level !== 'hidden';
    panel.inert = !open; panel.setAttribute('aria-hidden', String(!open));
    const btn = panel.querySelector('.sheet-toggle'); if (btn) btn.setAttribute('aria-expanded', String(level === 'full'));
    active = open ? which : (active === which ? null : active);
    // One sheet at a time: opening one hides the other.
    if (open && other.dataset.level !== 'hidden') { other.dataset.level = 'hidden'; applyTransform(other, pxForLevel(other, 'hidden')); other.inert = true; other.setAttribute('aria-hidden', 'true'); }
  }

  const TAP_SLOP = 8, TAP_MS = 350;

  function onHandlePointerDown(e) {
    const panel = e.currentTarget.closest('.left-panel,.right-panel');
    if (!panel || !mq.matches) return;
    const current = parseFloat((panel.style.transform.match(/-?\d+(\.\d+)?/) || [0])[0]) || pxForLevel(panel, panel.dataset.level || 'collapsed');
    dragState = { panel, startY: e.clientY, startPx: current, startT: Date.now(), moved: false };
    panel.style.transition = 'none';
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
    e.currentTarget.addEventListener('pointermove', onHandlePointerMove);
    e.currentTarget.addEventListener('pointerup', onHandlePointerUp, { once: true });
    e.currentTarget.addEventListener('pointercancel', onHandlePointerUp, { once: true });
  }
  function onHandlePointerMove(e) {
    if (!dragState) return;
    const dy = e.clientY - dragState.startY;
    if (Math.abs(dy) > TAP_SLOP) dragState.moved = true;
    applyTransform(dragState.panel, Math.max(0, dragState.startPx + dy));
  }
  function onHandlePointerUp(e) {
    e.currentTarget.removeEventListener('pointermove', onHandlePointerMove);
    if (!dragState) return;
    const { panel, moved, startT } = dragState; dragState = null;
    panel.style.transition = '';
    const which = panel === $('leftPanel') ? 'left' : 'right';
    suppressClickUntil = Date.now() + 400; // the button's own `click` follows right after — ignore it, we already acted
    if (!moved && Date.now() - startT < TAP_MS) {
      // A tap on the handle (not a drag): toggle collapsed <-> full, same as the button.
      setLevel(which, panel.dataset.level === 'full' ? 'collapsed' : 'full');
      return;
    }
    const total = sheetTotalHeight(panel);
    const visible = total - ((parseFloat((panel.style.transform.match(/-?\d+(\.\d+)?/) || [0])[0])) || 0);
    // Snap to whichever of the four resting levels is closest to where the drag ended.
    const targets = { hidden: 0, collapsed: PEEK_PX, half: Math.round(window.innerHeight * HALF_FRACTION), full: total };
    let best = 'collapsed', bestDist = Infinity;
    for (const level in targets) { const d = Math.abs(visible - targets[level]); if (d < bestDist) { bestDist = d; best = level; } }
    setLevel(which, best);
  }

  function wire() {
    if (wired) return; wired = true;
    ensureHandle($('leftPanel'), 'Plan your walk');
    ensureHandle($('rightPanel'), 'Your routes');
    $('mobilePlan').addEventListener('click', () => setLevel('left', $('leftPanel').dataset.level && $('leftPanel').dataset.level !== 'hidden' && $('leftPanel').dataset.level !== 'collapsed' ? 'collapsed' : 'half'));
    $('mobileResults').addEventListener('click', () => setLevel('right', $('rightPanel').dataset.level && $('rightPanel').dataset.level !== 'hidden' && $('rightPanel').dataset.level !== 'collapsed' ? 'collapsed' : 'half'));
    // Tapping the map collapses (not hides) whichever sheet is open — keeps the
    // map as the primary interactive surface without losing the user's place.
    $('map').addEventListener('pointerdown', () => { if (active && panelFor(active).dataset.level === 'full') setLevel(active, 'collapsed'); });
    // Auto-surface the results sheet once real routes exist (observes the
    // existing #navStart visibility toggle; does not touch route/journey logic).
    const navStart = $('navStart');
    if (navStart) new MutationObserver(() => { if (!navStart.classList.contains('hidden') && mq.matches) setLevel('right', 'half'); }).observe(navStart, { attributes: true, attributeFilter: ['class'] });
    window.addEventListener('resize', () => { if (mq.matches && active) setLevel(active, panelFor(active).dataset.level); });
  }
  function unwire() {
    if (!wired) return; wired = false;
    for (const which of ['left', 'right']) {
      const panel = panelFor(which);
      panel.style.transform = ''; panel.style.transition = ''; delete panel.dataset.level;
      panel.inert = false; panel.removeAttribute('aria-hidden');
    }
    active = null;
  }

  function init() {
    if (mq.matches) { wire(); setLevel('left', 'collapsed'); setLevel('right', 'hidden'); }
    else unwire();
  }
  mq.addEventListener('change', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
