'use strict';

/** Mobile shell for the phone breakpoint (<=740px): Natural-Language-first home,
    map-first layout, and the existing bottom sheets (collapsed / half / full,
    drag + tap, one sheet open at a time) driven by ONE view state:

      body[data-mview] = home | typing | busy | plan | customize | results | urban | layers
      (live navigation is body.nav-mode, owned by nav-ui.js — it overrides all of these)

    This file never re-implements planning, routing, navigation or Explore logic.
    It moves a few real DOM nodes (#intentText, its mic, #conversationSection,
    #explorePanel, #exploreInspector) into phone containers and calls the same
    functions the desktop buttons call (handlePlan, generateRoutes / planJourney,
    selectRoute, setExploreMode via #modeExplore/#modeNavigate). Every node is put
    back exactly where it was when leaving the breakpoint, so desktop and tablet
    (>740px) are untouched: this script no-ops there. **/
(function () {
  const BREAKPOINT = '(max-width: 740px)';
  const PEEK_PX = 64;      // visible strip when "collapsed" — the drag handle + label
  const HALF_FRACTION = 0.5; // fraction of viewport height visible when "half"
  const PANEL_IDS = { left: 'leftPanel', right: 'rightPanel', explore: 'exploreSheet' };
  const PANEL_SELECTOR = '.left-panel,.right-panel,.explore-sheet';
  // The sample request that ships pre-filled in #intentText for the desktop page.
  // On phones the composer must show its placeholder instead, so it is cleared once
  // (only while it is still that untouched sample — never a user's own text).
  const DESKTOP_SAMPLE_REQUEST = "I'd like a greener, quieter walk with interesting architecture.";
  const PHONE_PLACEHOLDER = 'Describe your ideal walk...';

  const mq = window.matchMedia(BREAKPOINT);
  let active = null;   // 'left' | 'right' | 'explore' | null
  let dragState = null;
  let wired = false;

  const panelFor = (which) => $(PANEL_IDS[which]);
  const whichFor = (panel) => Object.keys(PANEL_IDS).find((k) => $(PANEL_IDS[k]) === panel);
  const hasRoutes = () => typeof state !== 'undefined' && Array.isArray(state.routes) && state.routes.length > 0;

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
      setLevel(which, panel.dataset.level === 'full' ? 'half' : 'full');
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
    document.body.dataset.msheet = active ? `${active}-${panelFor(active).dataset.level}` : 'none';
  }

  const TAP_SLOP = 8, TAP_MS = 350;

  function onHandlePointerDown(e) {
    const panel = e.currentTarget.closest(PANEL_SELECTOR);
    if (!panel || !mq.matches) return;
    if (e.target.closest('button') && e.target.closest('.m-sheet-bar')) return;
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
      // A tap on the handle (not a drag): toggle half <-> full.
      setLevel(which, panel.dataset.level === 'full' ? 'half' : 'full');
      return;
    }
    const total = sheetTotalHeight(panel);
    const visible = total - ((parseFloat((panel.style.transform.match(/-?\d+(\.\d+)?/) || [0])[0])) || 0);
    // Snap to whichever of the four resting levels is closest to where the drag ended.
    const targets = { hidden: 0, collapsed: PEEK_PX, half: Math.round(window.innerHeight * HALF_FRACTION), full: total };
    let best = 'collapsed', bestDist = Infinity;
    for (const level in targets) { const d = Math.abs(visible - targets[level]); if (d < bestDist) { bestDist = d; best = level; } }
    setLevel(which, best);
    // Swiping a view's own sheet fully away is the same as pressing its Back.
    if (best === 'hidden') onSheetDismissed(which);
  }

  /* ------------------------------------------------------------------ */
  /* View state                                                         */
  /* ------------------------------------------------------------------ */
  const SECONDARY = new Set(['plan', 'customize', 'urban', 'layers']);
  let view = 'home';
  let returnView = 'home';        // where Back from a secondary view goes
  let historyPushed = false;      // one history entry per secondary view, so the phone's Back gesture works
  let lastSubmitted = '';         // the request text that was last sent to the Agent
  let customizeFromPlan = false;  // Back from Customize returns to Plan when that is where it was opened

  /** The "base" view the user returns to: results when real routes exist, otherwise home. */
  const baseView = () => (hasRoutes() ? 'results' : 'home');

  function setView(next, opts = {}) {
    if (!mq.matches) return;
    const prev = view;
    if (SECONDARY.has(next) && !SECONDARY.has(prev)) { returnView = prev === 'typing' || prev === 'busy' ? 'home' : prev; customizeFromPlan = false; }
    if (next === 'customize' && prev === 'plan') customizeFromPlan = true;
    if (next === 'plan') customizeFromPlan = false;
    view = next;
    document.body.dataset.mview = next;
    // Leaving Urban Data goes through the real Navigate toggle, never a reimplementation.
    if (prev === 'urban' && next !== 'urban' && typeof exploreMap !== 'undefined' && exploreMap.active) $('modeNavigate')?.click();
    if (prev === 'layers' && next !== 'layers') { const ul = $('urbanLayers'); if (ul) ul.open = false; }

    if (next === 'home' || next === 'typing' || next === 'busy') {
      for (const w of Object.keys(PANEL_IDS)) setLevel(w, 'hidden');
    } else if (next === 'plan' || next === 'customize') {
      $('leftPanel').dataset.lp = next;
      $('mSheetTitle').textContent = next === 'plan' ? 'Plan walk' : 'Customize';
      $('mSheetAlt').textContent = next === 'plan' ? '⚙ Prefs' : '☷ Route';
      $('mSheetAlt').setAttribute('aria-label', next === 'plan' ? 'Customize walk: preferences, time and 12 dimensions' : 'Back to start and destination');
      setLevel('left', opts.level || (next === 'plan' ? 'half' : 'full'));
      $('leftPanel').querySelector('.panel-scroll')?.scrollTo({ top: 0 });
      if (next === 'customize') renderQuickPrefs();
    } else if (next === 'results') {
      renderRouteFromTo();
      setLevel('right', opts.level || 'half');
    } else if (next === 'urban') {
      if (typeof exploreMap === 'undefined' || !exploreMap.active) $('modeExplore')?.click();
      else setLevel('explore', 'half');
    } else if (next === 'layers') {
      for (const w of Object.keys(PANEL_IDS)) setLevel(w, 'hidden');
      const ul = $('urbanLayers'); if (ul && !ul.open) ul.open = true;
    }

    if (SECONDARY.has(next) && !SECONDARY.has(prev) && !opts.fromPop) {
      try { history.pushState({ strollaneMview: next }, ''); historyPushed = true; } catch (_) {}
    }
    renderComposer();
    if (next === 'home' || next === 'typing') renderQuickPrefs();
  }
  /** Back from a secondary view (button, Escape, swipe-away or the phone's Back gesture). */
  function closeSecondary() {
    if (!SECONDARY.has(view)) return;
    if (view === 'customize' && customizeFromPlan) { setView('plan'); return; }
    if (historyPushed) { historyPushed = false; history.back(); return; } // popstate finishes it
    setView(returnView === 'results' && !hasRoutes() ? 'home' : returnView);
  }
  function onPopState() {
    if (!mq.matches) return;
    if (SECONDARY.has(view)) { historyPushed = false; setView(returnView === 'results' && !hasRoutes() ? 'home' : returnView, { fromPop: true }); }
  }
  function onSheetDismissed(which) {
    if ((which === 'left' && (view === 'plan' || view === 'customize')) || (which === 'explore' && view === 'urban')) closeSecondary();
    else if (which === 'right' && view === 'results') { view = 'home'; document.body.dataset.mview = 'home'; renderComposer(); }
  }

  /* ------------------------------------------------------------------ */
  /* Composer (the real #intentText, moved)                             */
  /* ------------------------------------------------------------------ */
  let composerMoved = false;
  const composerHome = {};        // original parent/nextSibling of every moved node
  function moveNode(id, target) {
    const el = typeof id === 'string' ? $(id) : id; if (!el || !target) return;
    composerHome[el.id || `mic-${el.dataset.mic}`] = { el, parent: el.parentNode, next: el.nextSibling };
    target.appendChild(el);
  }
  function restoreNodes() {
    for (const k of Object.keys(composerHome)) {
      const { el, parent, next } = composerHome[k];
      if (next && next.parentNode === parent) parent.insertBefore(el, next); else parent.appendChild(el);
      delete composerHome[k];
    }
  }
  function moveComposerIn() {
    if (composerMoved) return; composerMoved = true;
    const ta = $('intentText');
    moveNode('intentText', $('mComposerSlot'));
    moveNode(document.querySelector('[data-mic="intentText"]'), $('mMicSlot'));
    // Follow-up conversation belongs with the results on phones (§12.3).
    moveNode('conversationSection', $('mRefineSlot'));
    if (ta) {
      ta.dataset.desktopPlaceholder = ta.getAttribute('placeholder') || '';
      ta.setAttribute('placeholder', PHONE_PLACEHOLDER);
      if (ta.value.trim() === DESKTOP_SAMPLE_REQUEST) ta.value = '';
    }
  }
  function moveComposerOut() {
    if (!composerMoved) return; composerMoved = false;
    const ta = $('intentText');
    if (ta && ta.dataset.desktopPlaceholder != null) ta.setAttribute('placeholder', ta.dataset.desktopPlaceholder);
    restoreNodes();
  }

  function contextText() {
    const a = typeof getPlace === 'function' ? getPlace('start') : null;
    const mode = typeof journey !== 'undefined' ? journey.endMode : 'fixed';
    const b = typeof getPlace === 'function' ? getPlace('end') : null;
    const to = mode === 'open' ? 'Discover for me' : mode === 'round' ? 'Back to start' : mode === 'hotel' ? 'Back to hotel' : (b?.name || 'choose destination');
    return { from: a?.name || 'choose start', to };
  }
  function renderComposer() {
    if (!mq.matches) return;
    const c = contextText();
    $('mContextText').textContent = `${c.from} → ${c.to}`;
    const req = ($('intentText')?.value || lastSubmitted || '').trim();
    $('mCompactText').textContent = req || 'Refine or start a new walk';
  }
  function renderRouteFromTo() {
    const el = $('mRouteFromTo'); if (!el) return;
    const c = contextText();
    el.innerHTML = '';
    const line = document.createElement('div'); line.className = 'm-ft-line';
    line.innerHTML = '<span class="place-dot start"></span><span class="m-ft-from"></span><span class="m-ft-arrow" aria-hidden="true">→</span><span class="place-dot end"></span><span class="m-ft-to"></span>';
    line.querySelector('.m-ft-from').textContent = c.from; line.querySelector('.m-ft-to').textContent = c.to;
    const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'm-ft-edit'; edit.textContent = 'Edit';
    edit.setAttribute('aria-label', 'Edit start and destination'); edit.addEventListener('click', () => setView('plan'));
    el.append(line, edit);
  }

  // Real progress only: the labels come from what planner/state say is running right now.
  let statusTimer = null;
  function statusLabel() {
    if (typeof planner !== 'undefined' && planner.parsing) return 'Understanding your walk…';
    const cta = $('ctaLabel')?.textContent || '';
    if (typeof state !== 'undefined' && state.routingBusy) return /Finding places/.test(cta) ? 'Resolving places · calculating walking routes…' : 'Calculating walking routes…';
    return null;
  }
  function showStatus(text, kind) {
    const el = $('mStatus'); if (!el) return;
    el.classList.toggle('hidden', !text);
    el.className = `m-status ${kind || ''}${text ? '' : ' hidden'}`;
    el.innerHTML = '';
    if (!text) return;
    const msg = document.createElement('span'); msg.textContent = text; el.appendChild(msg);
    if (kind === 'error' || kind === 'clarify') {
      const acts = document.createElement('span'); acts.className = 'm-status-actions';
      const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = 'Edit request';
      edit.addEventListener('click', () => { showStatus(null); $('intentText')?.focus(); });
      const plan = document.createElement('button'); plan.type = 'button'; plan.textContent = 'Set start & destination';
      plan.addEventListener('click', () => { showStatus(null); setView('plan'); });
      acts.append(edit, plan); el.appendChild(acts);
    }
  }
  function startStatusLoop() {
    clearInterval(statusTimer);
    statusTimer = setInterval(() => { const t = statusLabel(); if (t) showStatus(t, 'busy'); }, 200);
  }
  function stopStatusLoop() { clearInterval(statusTimer); statusTimer = null; }

  let planning = false;
  /** Shared finish step for both planning paths (Natural Language and manual Plan walk). */
  async function runPlan(fn) {
    if (planning) return; // no duplicate requests while one is in flight
    planning = true;
    const chatBefore = typeof planner !== 'undefined' ? planner.conversations.length : 0;
    const toastBefore = $('toast')?.textContent || '';
    const createBtn = $('mCreate'); createBtn.disabled = true; $('mSheetGo').disabled = true;
    setView('busy'); startStatusLoop(); showStatus('Understanding your walk…', 'busy');
    try { await fn(); }
    catch (err) { console.warn('mobile plan failed', err); }
    finally {
      stopStatusLoop(); planning = false; createBtn.disabled = false; $('mSheetGo').disabled = false;
    }
    // What happened is read back from the app's own state and messages — never invented here.
    const newMsgs = (typeof planner !== 'undefined' ? planner.conversations.slice(chatBefore) : []).filter((m) => m.role === 'assistant');
    const lastMsg = newMsgs.length ? newMsgs[newMsgs.length - 1].content : null;
    const toastNow = $('toast')?.textContent || '';
    // handlePlan() marks a clarification with "The displayed previous route has not been recalculated."
    const clarified = Boolean(lastMsg && /has not been recalculated/.test(lastMsg));
    if (hasRoutes() && !clarified) { confirmStart(); showStatus(null); setView('results'); renderQuickPrefs(); return; }
    setView('home');
    const reason = lastMsg || (toastNow && toastNow !== toastBefore ? toastNow : '') || 'No route was calculated. Check the start and destination, then try again.';
    showStatus(reason, clarified ? 'clarify' : 'error');
  }
  function placesConfirmed() {
    // Same rule as handlePlan(): a typed-but-unchosen search box is not a place.
    for (const kind of ['start', 'end']) {
      if (kind === 'end' && typeof journey !== 'undefined' && journey.endMode !== 'fixed') continue;
      const typed = $(kind === 'start' ? 'searchStart' : 'searchEnd').value.trim(), chosen = getPlace(kind);
      if (typed !== chosen?.name) { toast(`Search and choose a ${kind === 'start' ? 'starting point' : 'destination'} result first, or use a preset.`); return false; }
    }
    return true;
  }
  // Starting point (§4.4): 1) a start named in the request, 2) a start the user chose this session,
  // 3) GPS only after the user taps it, 4) otherwise ask. The page ships with a preset start (Bryant Park)
  // that the user never chose; it is never used silently — the user confirms it, picks GPS, or picks a place.
  let startConfirmed = false;
  const REQUEST_NAMES_START = /\bstart(?:ing)?\s+(?:at|from|in|near)\b|\bbegin(?:ning)?\s+(?:at|from)\b|\bleav(?:e|ing)\s+from\b|\bfrom\s+(?:my\s+(?:hotel|location)|here|[A-Z0-9])|\bnear\s+me\b|从|出发|起点/;
  function confirmStart() { startConfirmed = true; }
  function askForStart(text) {
    const a = getPlace('start');
    const el = $('mStatus'); el.className = 'm-status clarify'; el.innerHTML = '';
    const msg = document.createElement('span');
    msg.textContent = `Where should this walk start? Your request doesn't name a start, and ${a?.name || 'no place'} is only the preset.`;
    const acts = document.createElement('span'); acts.className = 'm-status-actions';
    const mk = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.addEventListener('click', fn); acts.appendChild(b); };
    if (a) mk(`Start at ${a.name}`, () => { confirmStart(); showStatus(null); createFromText(); });
    mk('◎ Use my location', async () => {
      showStatus('Waiting for location permission…', 'busy');
      $('gpsStart').click(); // the existing GPS flow: asks permission, never invents a position
      const t0 = Date.now();
      while (Date.now() - t0 < 15000 && state.start !== 'gps') await new Promise((r) => setTimeout(r, 250));
      if (state.start === 'gps' && getPlace('start')) { confirmStart(); showStatus(null); renderComposer(); createFromText(); }
      else showStatus('Location is unavailable or was not allowed. Choose a start instead.', 'error');
    });
    mk('Choose start', () => { showStatus(null); setView('plan'); });
    el.append(msg, acts);
  }
  /** Path A — Natural Language: the existing Agent (handlePlan -> /api/interpret -> routing). */
  function createFromText() {
    const text = ($('intentText').value || '').trim();
    if (!text) { showStatus('Describe the walk you want — for example “a quiet 45-minute walk with interesting architecture”.', 'hint'); $('intentText').focus(); return; }
    // A map-picked point or a real GPS fix is itself an explicit choice; the untouched preset is not.
    if (!startConfirmed && !['gps', 'custom'].includes(state.start) && !hasRoutes() && !REQUEST_NAMES_START.test(text)) { setView('home'); askForStart(text); return; }
    lastSubmitted = text;
    $('intentText').blur();
    runPlan(() => handlePlan(text, hasRoutes()));
  }
  /** Path B — manual FROM / TO: same validation and the same routing calls, no text required. */
  function createFromForm() {
    confirmStart(); // the user is looking at the FROM field and pressed Find routes: that is an explicit choice
    const text = ($('intentText').value || '').trim();
    if (text && text !== lastSubmitted) { createFromText(); return; } // an unsent request is still the user's intent
    if (!placesConfirmed()) return;
    runPlan(() => (typeof journeyMode === 'function' && journeyMode() ? planJourney(false) : generateRoutes(null, false)));
  }

  /* ------------------------------------------------------------------ */
  /* Quick preferences (Customize) — verified mappings only            */
  /* ------------------------------------------------------------------ */
  // Each chip maps to something that already exists. Dimensions are the exact
  // names in app.js DIMENSIONS; "Coffee stop" is the journey planner's existing
  // café food stop (the same request refineWalk('coffee') makes), not a dimension.
  // "Hidden gems" has no supporting data or capability, so it is not offered.
  const QUICK_DIMS = [
    { key: 'architecture', label: 'Architecture', dim: 'Architecture' },
    { key: 'quiet', label: 'Quiet', dim: 'Quiet & Relax' },
    { key: 'nature', label: 'Nature', dim: 'Nature' },
    { key: 'scenic', label: 'Scenic', dim: 'Scenic & Visual' },
    { key: 'culture', label: 'Culture', dim: 'Culture' },
  ];
  const QUICK_WEIGHT = 80;
  let coffeePrevActive = null;
  const coffeeOn = () => typeof journey !== 'undefined' && journey.food.some((f) => f.category === 'cafes');
  // One renderer for both places the chips appear (home composer row and Customize), always drawn from the
  // live planner/journey state — so a chip is "on" exactly when that preference is really set, whoever set it
  // (the chip, the Agent's parse of the request, or a dimension slider).
  function renderQuickPrefs() {
    if (typeof planner === 'undefined') return;
    for (const root of [$('quickPrefs'), $('mQuickPrefs')]) {
      if (!root) continue;
      root.innerHTML = '';
      for (const q of QUICK_DIMS) {
        if (!DIMENSIONS.some((d) => d.name === q.dim)) continue; // registry check: never offer a dimension that does not exist
        const on = planner.origins[q.dim] !== 'default' && planner.weights[q.dim] >= 70 && planner.directions[q.dim] !== 'low';
        root.appendChild(chip(q.label, on, `Sets the ${q.dim} dimension to ${QUICK_WEIGHT}`, () => toggleDim(q.dim, !on)));
      }
      if (typeof applyJourney === 'function') root.appendChild(chip('☕ Coffee stop', coffeeOn(), 'Adds a café stop through the journey planner (real NYC place data)', toggleCoffee));
    }
  }
  function chip(label, on, title, onClick) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'quick-pref'; b.textContent = label;
    b.title = title; b.setAttribute('aria-pressed', String(on));
    b.addEventListener('click', async () => { await onClick(); renderQuickPrefs(); renderComposer(); });
    return b;
  }
  function toggleDim(dim, on) {
    planner.weights[dim] = on ? QUICK_WEIGHT : 50;
    planner.origins[dim] = on ? 'manual' : 'default';
    planner.directions[dim] = 'high';
    renderPreferenceSummary();
    if (hasRoutes() && typeof queueMapReplan === 'function') queueMapReplan(); // same as moving the dimension slider
  }
  async function toggleCoffee() {
    if (coffeeOn()) {
      journey.food = journey.food.filter((f) => f.category !== 'cafes');
      if (coffeePrevActive === false) journey.active = false;
      coffeePrevActive = null;
      renderJourneyPanel();
      toast('Café stop removed.');
    } else {
      coffeePrevActive = journey.active;
      const changes = await applyJourney({ interests: [], named_stops: [], food: [{ category: 'cafes', item: null, required: true }], services: [], more: {}, remove: [] });
      toast(`Added to your plan: ${changes.join(' · ') || 'café stop'}. A real café is chosen when the route is calculated.`);
    }
  }

  /* ------------------------------------------------------------------ */
  /* Menu, Explore Urban Data, misc wiring                              */
  /* ------------------------------------------------------------------ */
  // Header menu (<details>): proxies to the real #openInfo/#openKepler/#toggleData buttons
  // (hidden on phones, see styles.css) so their existing app.js listeners are reused
  // untouched — this never duplicates their behavior, it only relocates the trigger.
  let moreWired = false;
  function wireMoreMenu() {
    if (moreWired) return; moreWired = true;
    const more = $('mobileMore'); if (!more) return;
    more.querySelectorAll('[data-more-proxy]').forEach((btn) => {
      btn.addEventListener('click', () => { $(btn.dataset.moreProxy)?.click(); more.open = false; });
    });
    more.querySelectorAll('[data-mview-go]').forEach((btn) => {
      btn.addEventListener('click', () => { more.open = false; setView(btn.dataset.mviewGo); });
    });
    document.addEventListener('pointerdown', (e) => { if (more.open && !more.contains(e.target)) more.open = false; });
  }

  // Explore Urban Data (§14): on phones, the dimension/chip picker (#explorePanel)
  // and its street-segment inspector (#exploreInspector) live in the SAME sheet
  // mechanism as Plan/Results. explore-map.js's own logic is unchanged — these DOM
  // nodes just get a new parent on phones, and are put back exactly where they
  // were (inside #mapWorkspace) when leaving the breakpoint. (#urbanLayers /
  // #urbanInspector — the GIS dataset catalog — are a different system, shown in
  // the "layers" view.)
  const EXPLORE_CHILD_IDS = ['explorePanel', 'exploreInspector'];
  let exploreMoved = false;
  function moveExploreIntoSheet() {
    if (exploreMoved) return; exploreMoved = true;
    const sheet = $('exploreSheet'); const scroll = sheet && sheet.querySelector('.explore-sheet-scroll');
    if (!sheet || !scroll) return;
    for (const id of EXPLORE_CHILD_IDS) { const el = $(id); if (el) scroll.appendChild(el); }
    // explore-map.js auto-collapses #explorePanel to a header-only card on narrow
    // screens; inside a real sheet that is redundant — undo it via its own toggle.
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
    // explore-map.js's setExploreMode() is the single place that toggles this class.
    new MutationObserver(() => {
      if (!mq.matches) return;
      const exploreOn = !explorePanel.classList.contains('hidden');
      if (exploreOn) {
        if (view !== 'urban') { view = 'urban'; document.body.dataset.mview = 'urban'; }
        setLevel('explore', 'half'); renderComposer(); return;
      }
      if ($('exploreSheet').dataset.level && $('exploreSheet').dataset.level !== 'hidden') setLevel('explore', 'hidden');
      // Leaving Explore must restore a reachable resting state (the route results
      // when a route exists, otherwise home) — never leave the user with no sheet
      // and no way back. The current route is never cleared by Explore.
      if (view === 'urban') { if (historyPushed) { historyPushed = false; history.back(); } else setView(baseView()); }
    }).observe(explorePanel, { attributes: true, attributeFilter: ['class'] });
    // Tapping a street segment surfaces the inspector instead of leaving it below the fold.
    const exploreInspector = $('exploreInspector');
    if (exploreInspector) new MutationObserver(() => {
      if (!mq.matches) return;
      const open = !exploreInspector.classList.contains('hidden');
      if (!open) return;
      if ($('exploreSheet').dataset.level === 'collapsed') setLevel('explore', 'half');
      exploreInspector.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }).observe(exploreInspector, { attributes: true, attributeFilter: ['class'] });
  }

  // Swipeable route cards: a native scroll-snap list; a settled swipe selects the
  // card through selectRoute(), the one real route-selection path.
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

  let composerWired = false;
  function wireComposer() {
    if (composerWired) return; composerWired = true;
    const ta = $('intentText');
    ta.addEventListener('focus', () => { if (mq.matches && (view === 'home' || view === 'results')) { showStatus(null); setView('typing'); } });
    ta.addEventListener('blur', () => {
      if (!mq.matches || view !== 'typing') return;
      // Let a tap on Create/context register before collapsing focus mode.
      setTimeout(() => { if (view === 'typing' && document.activeElement !== ta) setView(baseView()); }, 180);
    });
    ta.addEventListener('keydown', (e) => {
      if (!mq.matches) return;
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); createFromText(); }
      if (e.key === 'Escape') ta.blur();
    });
    ta.addEventListener('input', renderComposer);
    $('mCreate').addEventListener('click', createFromText);
    $('mContext').addEventListener('click', () => setView('plan'));
    $('mCompactEdit').addEventListener('click', () => { setView('typing'); ta.focus(); });
    $('mNewWalk').addEventListener('click', () => { ta.value = ''; lastSubmitted = ''; showStatus(null); setView('typing'); ta.focus(); });
    $('mSheetBack').addEventListener('click', closeSecondary);
    $('mSheetAlt').addEventListener('click', () => setView(view === 'plan' ? 'customize' : 'plan'));
    $('mSheetGo').addEventListener('click', createFromForm);
    $('mViewExit').addEventListener('click', closeSecondary);
    $('mUrbanBtn').addEventListener('click', () => setView('urban'));
    window.addEventListener('popstate', onPopState);
    document.addEventListener('keydown', (e) => { if (mq.matches && e.key === 'Escape' && SECONDARY.has(view)) closeSecondary(); });
    // Map pick: the plan sheet steps aside while the user taps the map, then comes back.
    const notice = $('pickNotice');
    if (notice) new MutationObserver(() => {
      if (!mq.matches || (view !== 'plan' && view !== 'customize')) return;
      setLevel('left', notice.classList.contains('hidden') ? 'half' : 'collapsed');
      if (notice.classList.contains('hidden')) renderComposer();
    }).observe(notice, { attributes: true, attributeFilter: ['class'] });
    // Place choices change the context line (start/destination/end mode).
    for (const id of ['startSelect', 'endSelect', 'searchStart', 'searchEnd']) $(id)?.addEventListener('change', renderComposer);
    for (const id of ['startSelect', 'searchStart']) $(id)?.addEventListener('change', confirmStart);
    document.querySelectorAll('[data-end-mode]').forEach((b) => b.addEventListener('click', () => setTimeout(renderComposer, 0)));
  }

  function wire() {
    if (wired) return; wired = true;
    wireMoreMenu();
    moveExploreIntoSheet();
    moveComposerIn();
    ensureHandle($('leftPanel'), 'Plan your walk');
    ensureHandle($('rightPanel'), 'Your routes');
    ensureHandle($('exploreSheet'), 'Explore Urban Data');
    wireExploreSheet();
    wireRouteCardSwipe();
    wireComposer();
    $('mobilePlan').addEventListener('click', () => setView('plan'));
    $('mobileResults').addEventListener('click', () => setView(hasRoutes() ? 'results' : 'home'));
    // Tapping the map lowers a full sheet to half — the map stays the primary surface.
    $('map').addEventListener('pointerdown', () => {
      if (!mq.matches) return;
      if (active && panelFor(active).dataset.level === 'full') setLevel(active, 'half');
      if (view === 'typing') $('intentText').blur();
    });
    // Real routes appearing by any path (follow-up, chip re-plan, nav reroute) surface the results.
    const navStart = $('navStart');
    if (navStart) new MutationObserver(() => {
      if (!mq.matches || planning || document.body.classList.contains('nav-mode')) return;
      if (!navStart.classList.contains('hidden') && (view === 'home' || view === 'results')) setView('results');
    }).observe(navStart, { attributes: true, attributeFilter: ['class'] });
    // Leaving live navigation returns to the route results (or home).
    new MutationObserver(() => {
      if (!mq.matches) return;
      if (!document.body.classList.contains('nav-mode') && document.body.dataset.wasNav === '1') { delete document.body.dataset.wasNav; setView(baseView()); }
      else if (document.body.classList.contains('nav-mode')) { document.body.dataset.wasNav = '1'; for (const w of Object.keys(PANEL_IDS)) setLevel(w, 'hidden'); }
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    window.addEventListener('resize', () => { if (mq.matches && active) setLevel(active, panelFor(active).dataset.level); });
  }
  function unwire() {
    if (!wired) return; wired = false;
    for (const which of Object.keys(PANEL_IDS)) {
      const panel = panelFor(which); if (!panel) continue;
      panel.style.transform = ''; panel.style.transition = ''; delete panel.dataset.level;
      panel.inert = false; panel.removeAttribute('aria-hidden');
    }
    delete $('leftPanel').dataset.lp;
    delete document.body.dataset.mview; delete document.body.dataset.msheet;
    moveExploreBack();
    moveComposerOut();
    active = null;
    if (routeSwipeWired) renderRouteDots(); // re-hides immediately rather than waiting for the next card re-render
  }

  function init() {
    if (mq.matches) {
      wire();
      // A restored navigation session (nav-ui.js) owns the screen; otherwise home, never a pre-opened sheet.
      if (document.body.classList.contains('nav-mode')) { document.body.dataset.wasNav = '1'; for (const w of Object.keys(PANEL_IDS)) setLevel(w, 'hidden'); }
      else setView(hasRoutes() ? 'results' : 'home');
    } else unwire();
  }
  mq.addEventListener('change', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
