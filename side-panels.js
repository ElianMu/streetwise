'use strict';
/* Side panels (desktop): hide or show the planning panel (left) and the walk panel (right) so the map can use the width.

   With both panels open the map keeps under half of a 1440 px window, and in Explore Urban Data the dimension picker
   and the street inspector then float over what is left. This adds one small tab on each edge of the map:
     - each tab hides / shows its panel; nothing inside a panel is removed, changed or re-rendered;
     - entering Explore hides both panels (neither is used there) and leaving it restores exactly what the visitor had;
       a tab pressed while in Explore still works, so a panel can be brought back at any time.
   Phones are untouched: there the same panels are bottom sheets driven by mobile-ui.js, and the CSS for the
   collapsed state only applies from 741 px up. */

const sidePanels = {left: false, right: false, beforeExplore: null};
const SIDE_PANEL_TEXT = {left: ['Hide planning panel', 'Show planning panel'], right: ['Hide walk panel', 'Show walk panel']};

function applySidePanels() {
 for (const side of ['left', 'right']) {
  const collapsed = sidePanels[side];
  document.body.classList.toggle(side + '-collapsed', collapsed);
  const b = document.getElementById(side === 'left' ? 'toggleLeftPanel' : 'toggleRightPanel');
  if (!b) continue;
  b.setAttribute('aria-expanded', String(!collapsed));
  b.setAttribute('aria-label', SIDE_PANEL_TEXT[side][collapsed ? 1 : 0]); b.title = SIDE_PANEL_TEXT[side][collapsed ? 1 : 0];
  b.textContent = (side === 'left') === collapsed ? '›' : '‹';
 }
 // the map canvas must follow its container; once now and once after the layout has settled
 const resize = () => { try { if (typeof state !== 'undefined' && state.map) state.map.resize(); } catch (_) { /* map not ready */ } };
 resize(); setTimeout(resize, 60);
}
function setSidePanel(side, collapsed) {
 if (side !== 'left' && side !== 'right') return;
 sidePanels[side] = Boolean(collapsed);
 applySidePanels();
}
/** Explore mode: both panels step aside; leaving Explore restores what was open before. Called by setExploreMode(). */
function sidePanelsForExplore(on) {
 if (on) {
  if (!sidePanels.beforeExplore) sidePanels.beforeExplore = {left: sidePanels.left, right: sidePanels.right};
  sidePanels.left = true; sidePanels.right = true;
 } else if (sidePanels.beforeExplore) {
  sidePanels.left = sidePanels.beforeExplore.left; sidePanels.right = sidePanels.beforeExplore.right; sidePanels.beforeExplore = null;
 }
 applySidePanels();
}
if (typeof window !== 'undefined') {
 Object.assign(window, {sidePanels, setSidePanel, sidePanelsForExplore, applySidePanels});
 const boot = () => {
  document.getElementById('toggleLeftPanel')?.addEventListener('click', () => setSidePanel('left', !sidePanels.left));
  document.getElementById('toggleRightPanel')?.addEventListener('click', () => setSidePanel('right', !sidePanels.right));
 };
 if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else setTimeout(boot, 0);
}
