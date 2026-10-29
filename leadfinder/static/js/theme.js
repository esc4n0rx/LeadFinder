/* Theme is applied before styles load; no server state or inline scripts. */
(() => {
  'use strict';
  const storageKey = 'leadfinder-theme';
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = null;
  try { preference = localStorage.getItem(storageKey); } catch { /* Storage may be unavailable. */ }
  if (!['light', 'dark'].includes(preference)) preference = null;

  function applyTheme() {
    const dark = preference ? preference === 'dark' : systemTheme.matches;
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    const control = document.getElementById('theme-toggle');
    if (control) control.setAttribute('aria-checked', String(dark));
  }

  applyTheme();
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme();
    document.getElementById('theme-toggle').addEventListener('click', () => {
      preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(storageKey, preference); } catch { /* The current tab still works. */ }
      applyTheme();
    });
  });
  systemTheme.addEventListener('change', () => { if (!preference) applyTheme(); });
  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = ['dark', 'light'].includes(event.newValue) ? event.newValue : null;
    applyTheme();
  });
})();
