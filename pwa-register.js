'use strict';
/* Registers sw.js (same-origin app-shell cache only — see sw.js) and offers a
   gentle, deferred "Add to Home Screen" prompt: never on first load, only
   after the user has actually generated a route. Chromium: captures the real
   beforeinstallprompt. iOS Safari (no such event): a one-time dismissible tip
   pointing at the Share-sheet flow, since Safari has no programmatic install. **/
(function () {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('./sw.js').catch((err) => {
        console.warn('STROLLANE: service worker registration failed (app still works online):', err);
      });
    });
  }

  const zh = (navigator.language || '').toLowerCase().startsWith('zh');
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (isStandalone) return; // already installed

  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
  });

  function showBanner(onInstall) {
    if (localStorage.getItem('strollane.installBanner.dismissed') === '1') return;
    if (document.getElementById('installBanner')) return;
    const bar = document.createElement('div');
    bar.id = 'installBanner';
    bar.className = 'install-banner';
    bar.setAttribute('role', 'status');
    const msg = isIOS
      ? (zh ? '将 STROLLANE 添加到主屏幕：点击分享图标 → “添加到主屏幕”。' : 'Add STROLLANE to your Home Screen: tap Share, then “Add to Home Screen”.')
      : (zh ? '把 STROLLANE 安装到手机主屏幕，像 App 一样打开。' : 'Install STROLLANE on your home screen for a faster, full-screen view.');
    bar.innerHTML = `<span>${msg}</span>`;
    if (!isIOS) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'install-banner-btn';
      btn.textContent = zh ? '安装' : 'Install';
      btn.addEventListener('click', onInstall);
      bar.appendChild(btn);
    }
    const close = document.createElement('button');
    close.type = 'button'; close.className = 'install-banner-close'; close.setAttribute('aria-label', zh ? '关闭' : 'Dismiss');
    close.textContent = '✕';
    close.addEventListener('click', () => { bar.remove(); localStorage.setItem('strollane.installBanner.dismissed', '1'); });
    bar.appendChild(close);
    document.body.appendChild(bar);
  }

  async function onInstallClick() {
    const banner = document.getElementById('installBanner');
    if (!deferredPrompt) { banner?.remove(); return; }
    deferredPrompt.prompt();
    try { await deferredPrompt.userChoice; } catch (_) {}
    deferredPrompt = null;
    banner?.remove();
    localStorage.setItem('strollane.installBanner.dismissed', '1');
  }

  // Gate on a real signal of engagement (a generated route), via the same
  // non-invasive MutationObserver pattern mobile-ui.js uses — never touches
  // route/journey business logic.
  function armEngagementGate() {
    const navStart = document.getElementById('navStart');
    if (!navStart) return;
    const check = () => { if (!navStart.classList.contains('hidden')) { showBanner(onInstallClick); observer.disconnect(); } };
    const observer = new MutationObserver(check);
    observer.observe(navStart, { attributes: true, attributeFilter: ['class'] });
    check();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', armEngagementGate); else armEngagementGate();
})();
