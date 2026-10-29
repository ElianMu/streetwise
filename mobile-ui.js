'use strict';

/** Mobile bottom-sheet shell for the phone breakpoint (<=740px).
    Replaces the old side-drawer toggle (leftPanel/rightPanel sliding in from the
    edges) with a real bottom sheet: collapsed / half / full, drag + tap to move,
    one sheet open at a time. Does not touch route/journey/nav/explore business
    logic — it only changes how the existing panels are shown on phones.
    Desktop and tablet (>740px) are untouched: this script no-ops there. **/
(function () {
  const BREAKPOINT = '(max-width: 740px)';
  const PEEK_PX = 64;      // visible strip when "collapsed" — the drag handle + label
  const HALF_FRACTION = 0.5; // fraction of viewport height visible when "half"
  const PANEL_IDS = { left: 'leftPanel', right: 'rightPanel', explore: 'exploreSheet' };
  const PANEL_SELECTOR = '.left-panel,.right-panel,.explore-sheet';

  const mq = window.matchMedia(BREAKPOINT);
  let active = null;   // 'left' | 'right' | 'explore' | null
  let dragState = null;
  let wired = false;

  const panelFor = (which) => $(PANEL_IDS[which]);
  const whichFor = (panel) => Object.keys(PANEL_IDS).find((k) => $(PANEL_IDS[k]) === panel);

  // A tap that handled a toggle marks itself here so the button's own
  // synthesized `click` (which always follows pointerup) doesn't re-toggle it
  // a second time; a real keyboard activation (Enter/Space with no preceding
  // pointerdown) is unaffected and still works.
  let suppressClickUntil = 0;

  function ensureHandle(panel, label) {
    if (!panel || panel.querySelector('.sheet-handle')) return;
    const handle = document.createElement('div');
    handle.className = 'sheet-handle';
    handle.innerHTML = `<span class="sheet-grip" aria-hidden="true"></span><button type="button" class="sheet-toggle">${label}</button>`;
    panel.insertBefore(handle, panel.firstChild);
    handle.addEventListener('pointerdown', onHandlePointerDown);
    handle.querySelector('.sheet-toggle').addEventListener('click', () => {
      if (Date.now() < suppressClickUntil) return;
      const which = whichFor(panel);
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
    if (!panel) return;
    panel.dataset.level = level;
    panel.style.transition = '';
    applyTransform(panel, pxForLevel(panel, level));
    const open = level !== 'hidden';
    panel.inert = !open; panel.setAttribute('aria-hidden', String(!open));
    const btn = panel.querySelector('.sheet-toggle'); if (btn) btn.setAttribute('aria-expanded', String(level === 'full'));
    active = open ? which : (active === which ? null : active);
    // One sheet at a time: opening one hides every other one.
    if (open) {
      for (const other of Object.keys(PANEL_IDS)) {
        if (other === which) continue;
        const o = panelFor(other);
        if (o && o.dataset.level !== 'hidden') { o.dataset.level = 'hidden'; applyTransform(o, pxForLevel(o, 'hidden')); o.inert = true; o.setAttribute('aria-hidden', 'true'); }
      }
    }
  }

  const TAP_SLOP = 8, TAP_MS = 350;

  function onHandlePointerDown(e) {
    const panel = e.currentTarget.closest(PANEL_SELECTOR);
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
    const which = whichFor(panel);
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

  // Header "More" menu (<details>): proxies to the real #openInfo/#openKepler buttons
  // (hidden on phones, see styles.css) so their existing app.js listeners are reused
  // untouched — this never duplicates their behavior, it only relocates the trigger.
  let moreWired = false;
  function wireMoreMenu() {
    if (moreWired) return; moreWired = true;
    const more = $('mobileMore'); if (!more) return;
    more.querySelectorAll('[data-more-proxy]').forEach((btn) => {
      btn.addEventListener('click', () => { $(btn.dataset.moreProxy)?.click(); more.open = false; });
    });
    document.addEventListener('pointerdown', (e) => { if (more.open && !more.contains(e.target)) more.open = false; });
  }

  // Explore Urban Data (§12 of the brief): on phones, the dimension/chip picker
  // (#explorePanel) and its street-segment inspector (#exploreInspector) move
  // into the SAME sheet mechanism as Plan/Results, rather than keeping their own
  // separate floating-card overlay system. Nothing about explore-map.js's own
  // logic changes — these DOM nodes just get a new parent on phones, and are put
  // back exactly where they were (inside #mapWorkspace) when leaving the
  // breakpoint, so desktop/tablet CSS and behavior are completely untouched.
  // (#urbanLayers / #urbanInspector — the separate GIS dataset catalog used in
  // Navigate mode — are a different system and are not moved here.)
  const EXPLORE_CHILD_IDS = ['explorePanel', 'exploreInspector'];
  let exploreMoved = false;
  function moveExploreIntoSheet() {
    if (exploreMoved) return; exploreMoved = true;
    const sheet = $('exploreSheet'); const scroll = sheet && sheet.querySelector('.explore-sheet-scroll');
    if (!sheet || !scroll) return;
    for (const id of EXPLORE_CHILD_IDS) { const el = $(id); if (el) scroll.appendChild(el); }
    // explore-map.js auto-collapses #explorePanel to a header-only card on narrow
    // screens (setupExploreControls(), a pre-existing accommodation for when it
    // was a small floating card). Now that it lives in a real sheet with its own
    // collapsed/half/full levels, that old collapse is redundant and just hides
    // content the sheet was just opened to show — undo it via the panel's own
    // real toggle (not a reimplementation) so exploreMap.collapsed stays in sync.
    if (typeof exploreMap !== 'undefined' && exploreMap.collapsed) $('exploreCollapse')?.click();
  }
  function moveExploreBack() {
    if (!exploreMoved) return; exploreMoved = false;
    const workspace = $('mapWorkspace');
    if (!workspace) return;
    for (const id of EXPLORE_CHILD_IDS) { const el = $(id); if (el) workspace.appendChild(el); }
  }
  let exploreWired = false;
  function wireExploreSheet() {
    if (exploreWired) return; exploreWired = true;
    const explorePanel = $('explorePanel'); if (!explorePanel) return;
    // explore-map.js's setExploreMode() is the single place that toggles this
    // class — observing it (not reimplementing mode-switch logic) is the same
    // pattern already used for #navStart below.
    new MutationObserver(() => {
      if (!mq.matches) return;
      const exploreOn = !explorePanel.classList.contains('hidden');
      if (exploreOn) setLevel('explore', 'half');
      else if ($('exploreSheet').dataset.level && $('exploreSheet').dataset.level !== 'hidden') setLevel('explore', 'hidden');
    }).observe(explorePanel, { attributes: true, attributeFilter: ['class'] });
    // Tapping a street segment on the map selects it (exploreMap.selected) and
    // renderExploreInspector() un-hides #exploreInspector — same signal, same
    // observer pattern, so the sheet surfaces to show what the tap just did
    // instead of leaving the result invisible below a collapsed sheet.
    const exploreInspector = $('exploreInspector');
    if (exploreInspector) new MutationObserver(() => {
      if (!mq.matches) return;
      const open = !exploreInspector.classList.contains('hidden');
      if (!open) return;
      if ($('exploreSheet').dataset.level === 'collapsed') setLevel('explore', 'half');
      // The inspector renders after the dimension grid in the same scroll
      // container — without this, a tapped segment's detail is off-screen
      // below the fold and looks like nothing happened.
      exploreInspector.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }).observe(exploreInspector, { attributes: true, attributeFilter: ['class'] });
  }

  // Priority 3: swipeable route cards. #routeCards is a native horizontal
  // scroll-snap list (CSS only — see styles.css); this just (a) keeps a dots
  // indicator in sync with however many cards route-client.js rendered, and
  // (b) when a swipe settles on a different card, selects it the exact same
  // way a tap already does — selectRoute() is the one real route-selection
  // path, so no state can exist here that route-client.js doesn't already own.
  let routeSwipeWired = false;
  let routeScrollTimer = null;
  function renderRouteDots() {
    const cards = $('routeCards').querySelectorAll('.route-card');
    const dots = $('routeDots');
    if (!dots) return;
    dots.classList.toggle('hidden', !mq.matches || cards.length < 2);
    if (!mq.matches || cards.length < 2) return;
    dots.innerHTML = Array.from(cards).map((c) => `<span class="${c.classList.contains('selected') ? 'active' : ''}"></span>`).join('');
  }
  function onRouteCardsScroll() {
    clearTimeout(routeScrollTimer);
    routeScrollTimer = setTimeout(() => {
      const root = $('routeCards'); if (!mq.matches || !root) return;
      const mid = root.scrollLeft + root.clientWidth / 2;
      let closest = null, closestDist = Infinity;
      root.querySelectorAll('.route-card').forEach((c) => {
        const d = Math.abs((c.offsetLeft + c.offsetWidth / 2) - mid);
        if (d < closestDist) { closestDist = d; closest = c; }
      });
      if (closest && !closest.classList.contains('selected') && typeof selectRoute === 'function') selectRoute(closest.dataset.route);
    }, 120);
  }
  function wireRouteCardSwipe() {
    if (routeSwipeWired) return; routeSwipeWired = true;
    const root = $('routeCards'); if (!root) return;
    root.addEventListener('scroll', onRouteCardsScroll, { passive: true });
    new MutationObserver(renderRouteDots).observe(root, { childList: true, attributes: true, subtree: true, attributeFilter: ['class'] });
    renderRouteDots();
  }

  function wire() {
    if (wired) return; wired = true;
    wireMoreMenu();
    moveExploreIntoSheet();
    ensureHandle($('leftPanel'), 'Plan your walk');
    ensureHandle($('rightPanel'), 'Your routes');
    ensureHandle($('exploreSheet'), 'Explore Urban Data');
    wireExploreSheet();
    wireRouteCardSwipe();
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
    for (const which of Object.keys(PANEL_IDS)) {
      const panel = panelFor(which); if (!panel) continue;
      panel.style.transform = ''; panel.style.transition = ''; delete panel.dataset.level;
      panel.inert = false; panel.removeAttribute('aria-hidden');
    }
    moveExploreBack();
    active = null;
    if (routeSwipeWired) renderRouteDots(); // re-hides immediately rather than waiting for the next card re-render
  }

  function init() {
    if (mq.matches) { wire(); setLevel('left', 'collapsed'); setLevel('right', 'hidden'); setLevel('explore', 'hidden'); }
    else unwire();
  }
  mq.addEventListener('change', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
