/**
 * PortfolioManager — app.js
 * Shared utilities loaded on every page.
 */

"use strict";

// ── Dark / light mode toggle ───────────────────────────────────────────────
function toggleTheme() {
  var html = document.documentElement;
  var current = html.getAttribute('data-theme');
  var next = current === 'light' ? 'dark' : 'light';
  html.setAttribute('data-theme', next);
  localStorage.setItem('pm-theme', next);
  window.dispatchEvent(new CustomEvent('pm-theme-changed'));
}

// Apply saved theme immediately (default: dark)
(function () {
  var t = localStorage.getItem('pm-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

// ── Language toggle (nl / en) ────────────────────────────────────────────
// Stored in a cookie, not localStorage: every page is server-rendered, so
// the server has to know the language before it renders any text — a
// client-side attribute flip (like the theme toggle) can't retranslate
// text that's already baked into the HTML. A full reload picks the new
// cookie up server-side. 1-year max-age so it's still there "next time you
// open the app", same as the theme preference.
function toggleLanguage() {
  var current = getCookie('pm_lang') || 'nl';
  var next = current === 'nl' ? 'en' : 'nl';
  document.cookie = 'pm_lang=' + next + '; path=/; max-age=31536000; samesite=lax';
  location.reload();
}

function getCookie(name) {
  var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

function toggleMobileMenu() {
  var drawer = document.getElementById('mobileNavDrawer');
  if (drawer) drawer.classList.toggle('open');
}

// Close desktop navigation dropdowns when focus moves elsewhere, while
// retaining native <details> keyboard and no-JavaScript behaviour.
document.addEventListener('click', function (event) {
  document.querySelectorAll('.topnav-dropdown[open]').forEach(function (dropdown) {
    if (!dropdown.contains(event.target)) dropdown.removeAttribute('open');
  });
});

document.addEventListener('keydown', function (event) {
  if (event.key !== 'Escape') return;
  document.querySelectorAll('.topnav-dropdown[open]').forEach(function (dropdown) {
    dropdown.removeAttribute('open');
  });
});

// ── Instrument logos ──────────────────────────────────────────────────────
// Logo.dev supports ISINs and tickers, including ETFs. The publishable key is
// optional: without it, the compact monogram remains as a local fallback.
function createInstrumentLogo({ isin = '', symbol = '', name = '' } = {}) {
  // Database joins intentionally yield null for unmapped/legacy instruments.
  // Normalise here because this helper is also used by popup rows, where a
  // missing ticker must still render the name fallback instead of aborting
  // the entire dialog on `symbol.replace(...)`.
  isin = typeof isin === 'string' ? isin : '';
  symbol = typeof symbol === 'string' ? symbol : '';
  name = typeof name === 'string' ? name : '';

  const logo = document.createElement('span');
  logo.className = 'instrument-logo';
  logo.setAttribute('aria-hidden', 'true');
  logo.title = name;

  const fallback = document.createElement('span');
  fallback.className = 'instrument-logo-fallback';
  fallback.textContent = (name.trim().match(/[\p{L}\p{N}]/u) || ['?'])[0].toUpperCase();
  logo.appendChild(fallback);

  // Yahoo symbols can include exchange suffixes (IWDA.AS) or an index
  // prefix (^AEX). Logo.dev often resolves the base ticker instead, so try
  // both forms before falling back to the brand name.
  const normalizedTicker = symbol.replace(/^\^/, '');
  const baseTicker = normalizedTicker.includes('.')
    ? normalizedTicker.split('.')[0]
    : normalizedTicker;
  const candidates = [
    ...(isin ? [{ mode: 'isin', value: isin }] : []),
    ...(symbol ? [{ mode: 'ticker', value: symbol }] : []),
    ...(normalizedTicker && normalizedTicker !== symbol ? [{ mode: 'ticker', value: normalizedTicker }] : []),
    ...(baseTicker && baseTicker !== symbol && baseTicker !== normalizedTicker ? [{ mode: 'ticker', value: baseTicker }] : []),
    ...(name ? [{ mode: 'name', value: name }] : []),
  ];
  if (!candidates.length) return logo;

  const image = document.createElement('img');
  image.alt = '';
  image.loading = 'lazy';
  let candidateIndex = 0;
  const loadCandidate = () => {
    const candidate = candidates[candidateIndex];
    image.src = `/logos/${candidate.mode}?value=${encodeURIComponent(candidate.value)}`;
  };
  image.addEventListener('error', () => {
    candidateIndex += 1;
    if (candidateIndex < candidates.length) loadCandidate();
    else image.remove();
  });
  loadCandidate();
  logo.appendChild(image);
  return logo;
}

function initInstrumentLogos(root = document) {
  root.querySelectorAll('[data-instrument-logo]').forEach(el => {
    if (el.childElementCount) return;
    el.appendChild(createInstrumentLogo({
      isin: el.dataset.isin || '',
      symbol: el.dataset.symbol || '',
      name: el.dataset.name || '',
    }));
  });
}

// Instrumentnamen in tabellen zijn onderdeel van een klikbare rij. Hierdoor
// voelt de interactie overal hetzelfde: een subtiele hover en een klik op
// de rij openen de instrumentdetailpagina, niet alleen een klik op de naam.
function initClickableInstrumentRows() {
  document.querySelectorAll('tbody tr').forEach(row => {
    const link = row.querySelector('a[href^="/instrument/"]');
    if (!link || row.classList.contains('clickable')) return;

    const openInstrument = () => { window.location = link.href; };
    row.classList.add('clickable');
    row.tabIndex = 0;
    row.setAttribute('role', 'link');
    row.setAttribute('aria-label', `Bekijk ${link.textContent.trim()}`);
    row.addEventListener('click', event => {
      if (!event.target.closest('a')) openInstrument();
    });
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openInstrument();
      }
    });
  });
}

// Instrument details stay in reach without taking the user away from the
// current table or dashboard. The server still renders a normal detail page
// for direct links, bookmarks and the "full details" escape hatch.
let instrumentPanelTrigger = null;

function instrumentIdFromLink(link) {
  const match = new URL(link.href, window.location.origin).pathname.match(/^\/instrument\/(\d+)$/);
  return match ? match[1] : null;
}

function ensureInstrumentPanel() {
  let panel = document.getElementById('instrumentSidePanel');
  if (panel) return panel;
  panel = document.createElement('div');
  panel.id = 'instrumentSidePanel';
  panel.className = 'instrument-side-panel';
  panel.innerHTML = '<div class="instrument-panel-backdrop" data-instrument-panel-close></div><aside class="instrument-panel-sheet" role="dialog" aria-modal="true" aria-busy="true"></aside>';
  document.body.appendChild(panel);
  return panel;
}

function closeInstrumentPanel() {
  const panel = document.getElementById('instrumentSidePanel');
  if (!panel) return;
  panel.classList.remove('open');
  document.body.classList.remove('instrument-panel-open');
  if (instrumentPanelTrigger) instrumentPanelTrigger.focus();
}

async function openInstrumentPanel(instrumentId, trigger) {
  const panel = ensureInstrumentPanel();
  const sheet = panel.querySelector('.instrument-panel-sheet');
  instrumentPanelTrigger = trigger || document.activeElement;
  sheet.setAttribute('aria-busy', 'true');
  sheet.innerHTML = '<div class="instrument-panel-loading"></div>';
  panel.classList.add('open');
  document.body.classList.add('instrument-panel-open');

  try {
    const response = await fetch(`/instrument/${instrumentId}/panel`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!response.ok) throw new Error('Could not load instrument');
    sheet.innerHTML = await response.text();
    sheet.removeAttribute('aria-busy');
    initInstrumentLogos(sheet);
    sheet.querySelector('[data-instrument-panel-close]')?.focus();
  } catch (_error) {
    closeInstrumentPanel();
    window.location.assign(`/instrument/${instrumentId}`);
  }
}

function initInstrumentPanelLinks() {
  document.addEventListener('click', event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (event.target.closest('#instrumentSidePanel')) return;

    const link = event.target.closest('a[href^="/instrument/"]');
    const row = event.target.closest('tr');
    const fallbackLink = row?.querySelector('a[href^="/instrument/"]');
    const instrumentLink = link || fallbackLink;
    const instrumentId = instrumentLink && instrumentIdFromLink(instrumentLink);
    if (!instrumentId) return;

    event.preventDefault();
    event.stopPropagation();
    openInstrumentPanel(instrumentId, instrumentLink);
  }, true);

  document.addEventListener('click', event => {
    if (event.target.closest('[data-instrument-panel-close]')) closeInstrumentPanel();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.getElementById('instrumentSidePanel')?.classList.contains('open')) {
      closeInstrumentPanel();
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initClickableInstrumentRows();
  initInstrumentLogos();
  initInstrumentPanelLinks();
});


// Used by login.html and register.html (loaded before this script, but these
// helpers are referenced from inline scripts there, so we define them globally).

/**
 * Convert a base64url string to an ArrayBuffer.
 * @param {string} b64url
 * @returns {ArrayBuffer}
 */
function b64ToBuffer(b64url) {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/');
  const padded = b64 + '=='.slice(0, (4 - b64.length % 4) % 4);
  const binary = atob(padded);
  const buf = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    buf[i] = binary.charCodeAt(i);
  }
  return buf.buffer;
}

/**
 * Convert an ArrayBuffer to a base64url string.
 * @param {ArrayBuffer} buf
 * @returns {string}
 */
function bufferToB64(buf) {
  const bytes = new Uint8Array(buf);
  let str = '';
  for (const b of bytes) {
    str += String.fromCharCode(b);
  }
  return btoa(str)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

// ── Dutch number formatting (client-side mirror of Jinja2 filters) ─────────

/**
 * Format a number as Dutch EUR: € 1.234,56
 * @param {number|string} value
 * @param {boolean} showSymbol
 * @returns {string}
 */
function formatEur(value, showSymbol = true) {
  if (value === null || value === undefined) return '—';
  const n = parseFloat(value);
  if (isNaN(n)) return String(value);
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString('nl-NL', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const sign = n < 0 ? '-' : '';
  return showSymbol ? `${sign}€\u00a0${formatted}` : `${sign}${formatted}`;
}

/**
 * Format a number as a Dutch percentage: +12,34% or -5,67% (mirrors _format_pct).
 * @param {number|string} value
 * @returns {string}
 */
function formatPct(value) {
  if (value === null || value === undefined) return '—';
  const n = parseFloat(value);
  if (isNaN(n)) return String(value);
  const formatted = Math.abs(n).toLocaleString('nl-NL', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return (n >= 0 ? '+' : '-') + formatted + '%';
}

// ── Period range selector (1D/1M/YTD/1J/Custom/Alles) ──────────────────────
// Shared by any page with a .range-selector + optional #customRangeDialog
// (dashboard.html, dividends.html, benchmark.html). Each page keeps its own
// `customRange` state and thin setRange/openCustomRange/applyCustomRange
// wrappers (since each is a full page load, not a shared JS context) — only
// the actual date-math is centralized here to avoid three copies drifting.

/**
 * @param {string} range - '1D' | '1M' | 'YTD' | '1Y' | 'ALL' | 'CUSTOM'
 * @param {{start: string, end: string}|null} customRange - only used when range === 'CUSTOM'
 * @returns {{start: Date|null, end: Date}}
 */
function getRangeBounds(range, customRange) {
  const today = new Date();
  today.setHours(23, 59, 59, 999);
  let start = null;
  if (range === '1D') { start = new Date(today); start.setDate(start.getDate() - 1); }
  else if (range === '1M') { start = new Date(today); start.setDate(start.getDate() - 31); }
  else if (range === 'YTD') { start = new Date(today.getFullYear(), 0, 1); }
  else if (range === '1Y') { start = new Date(today); start.setDate(start.getDate() - 366); }
  else if (range === 'CUSTOM' && customRange) {
    start = new Date(customRange.start + 'T00:00:00');
    const end = new Date(customRange.end + 'T23:59:59');
    return { start, end };
  }
  return { start, end: today }; // ALL -> start stays null
}

/**
 * @param {string} dateStr
 * @param {Date|null} start
 * @param {Date} end
 * @returns {boolean}
 */
function inDateRange(dateStr, start, end) {
  const d = new Date(dateStr);
  if (start && d < start) return false;
  if (end && d > end) return false;
  return true;
}

// ── Chart.js theming (shared by dashboard/dividends/benchmark) ─────────────
// Categorical slot order is fixed and never cycled — the same category keeps
// the same hue, and a chart with more categories than slots folds the tail
// into "Overig" server-side (see portfolio.py's allocation folding, cap
// raised to match this palette's size) instead of repeating a color. Twelve
// slots covers every realistic bucket count in this app (the worst case is
// the sector chart: 11 GICS-style sectors from ETF weightings + Cash, with
// Unclassified folding in only in the rare case all 13 show up at once).
//
// Built with the dataviz skill's palette validator (OKLCH lightness band,
// chroma floor, CVD separation under simulated protan/deutan, a normal-vision
// floor, contrast) against this app's actual glass surfaces (~#11172b dark /
// ~#f5f8ff light) — every slot passes every hard check. Twelve is close to
// the practical ceiling for this method: teal/cyan hues can't clear the
// chroma floor in this lightness band without going out of sRGB gamut, and
// beyond ~12-13 hues spread around the wheel, protan/deutan simulation
// collapses enough of the warm (red/orange/olive/green) side that some pair
// is always forced adjacent — more slots than that would need duplicate-
// reading hues for colorblind readers. Slot 1 is a corrected-lightness
// version of the brand blue (dark mode's --primary is lighter than the
// categorical band allows) — it's the palette's "this is the top category"
// blue, not literally the same pixels as a hero line's --primary elsewhere.
const CHART_PALETTE = {
  dark:  ['#2c81dc', '#c94f7c', '#5a9313', '#9962ca', '#8c8300', '#7071dd', '#ce514b', '#0d9298', '#c46007', '#02985f', '#b656a9', '#a77603'],
  light: ['#397fdd', '#a06602', '#0d8966', '#ba5000', '#ab4998', '#6d7e00', '#bb4271', '#89730b', '#9353b7', '#c04446', '#7260cb', '#2b8b2a'],
};

function chartMode() {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

/** Fixed-order categorical palette for the current theme — index by category rank, never reassign. */
function chartPalette() {
  return CHART_PALETTE[chartMode()];
}

/** Live CSS custom properties for the current theme, for chart grid/tick/status colors. */
function chartTokens() {
  const s = getComputedStyle(document.documentElement);
  const v = name => s.getPropertyValue(name).trim();
  return {
    text: v('--text'),
    muted: v('--text-muted'),
    border: v('--border'),
    surface: v('--surface'),
    primary: v('--primary'),
    green: v('--green'),
    red: v('--red'),
  };
}

// Grid/tick colors are resolved live from the current theme rather than
// hardcoded, so charts follow the light/dark toggle instead of staying
// baked in from first paint.
function chartGridColor() { return chartTokens().border; }
function chartTickColor() { return chartTokens().muted; }

/** '#rrggbb' -> 'rgba(r, g, b, alpha)', for translucent glass fills. */
function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16), g = parseInt(h.substring(2, 4), 16), b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Vertical glow-gradient fill for a line chart's area — brightest just under
 * the line, fading to transparent toward the axis, like light through glass.
 * `chartArea` is null on the very first layout pass; fall back to a flat
 * translucent fill for that one frame.
 */
function glassGradient(ctx, chartArea, hex) {
  if (!chartArea) return hexToRgba(hex, 0.12);
  const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
  gradient.addColorStop(0, hexToRgba(hex, 0.34));
  gradient.addColorStop(1, hexToRgba(hex, 0.01));
  return gradient;
}

/** Shared Chart.js tooltip options: translucent dark panel, rounded to match the glass cards. */
function glassTooltipOptions() {
  const t = chartTokens();
  return {
    backgroundColor: hexToRgba('#0b0f22', chartMode() === 'light' ? 0.92 : 0.88),
    titleColor: '#f1f5ff',
    bodyColor: '#dbe4ff',
    borderColor: t.border,
    borderWidth: 1,
    cornerRadius: 10,
    padding: 10,
    boxPadding: 4,
  };
}

// A shared crosshair for the time-series charts. Chart.js exposes the active
// item at the current cursor position; drawing from the chart area's top to
// bottom makes it easy to compare values without obscuring the tooltip.
const hoverGuideLine = {
  id: 'hoverGuideLine',
  afterDatasetsDraw(chart, _args, options) {
    if (!options || !options.enabled) return;
    const active = chart.getActiveElements();
    if (!active.length || !chart.chartArea) return;

    const point = chart.getDatasetMeta(active[0].datasetIndex).data[active[0].index];
    if (!point) return;

    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.strokeStyle = options.color;
    ctx.lineWidth = options.width || 1;
    ctx.setLineDash(options.dash || [3, 3]);
    ctx.beginPath();
    ctx.moveTo(point.x, chartArea.top);
    ctx.lineTo(point.x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

Chart.register(hoverGuideLine);

function hoverGuideLineOptions() {
  return { enabled: true, color: hexToRgba(chartTokens().text, 0.5), width: 1, dash: [3, 3] };
}

/** Register a chart-rebuild callback to run whenever the theme toggle fires. */
function onChartThemeChange(cb) {
  window.addEventListener('pm-theme-changed', cb);
}

// ── Page loading overlay ─────────────────────────────────────────────────
// For forms whose submit triggers a slow, data-heavy page reload (e.g. the
// benchmark page fetching price history for one or more indices) — call
// right before form.submit() so the user sees a spinner instead of a
// seemingly-frozen page during the gap.
function showPageLoadingOverlay() {
  let el = document.getElementById('pageLoadingOverlay');
  if (!el) {
    el = document.createElement('div');
    el.id = 'pageLoadingOverlay';
    el.className = 'page-loading-overlay';
    el.innerHTML = '<div class="page-loading-spinner"></div>';
    document.body.appendChild(el);
  }
  el.classList.remove('hidden');
}

/** Prefill today's date into #customStart/#customEnd (if empty) and open the dialog. */
function openCustomRangeDialog(dialogId = 'customRangeDialog') {
  const dialog = document.getElementById(dialogId);
  const today = new Date().toISOString().slice(0, 10);
  const startInput = dialog.querySelector('#customStart');
  const endInput = dialog.querySelector('#customEnd');
  if (!startInput.value) startInput.value = today;
  if (!endInput.value) endInput.value = today;
  dialog.showModal();
}

// Remember the last-selected range per page (dashboard/dividends/benchmark
// each have their own independent memory — you might want the dashboard on
// "1J" but dividends on "Alles") so it doesn't reset every time you open
// the app, the same way the dark/light theme is remembered.

/**
 * @param {string} pageKey - e.g. 'dashboard', 'dividends', 'benchmark'
 * @param {string} range
 * @param {{start: string, end: string}|null} customRange
 */
function saveRangePreference(pageKey, range, customRange) {
  try {
    localStorage.setItem('pm-range-' + pageKey, JSON.stringify({ range, customRange }));
  } catch (e) { /* localStorage unavailable — ignore, just won't persist */ }
}

/** @param {string} pageKey @returns {{range: string, customRange: object|null}|null} */
function loadRangePreference(pageKey) {
  try {
    const raw = localStorage.getItem('pm-range-' + pageKey);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

/**
 * Activate the correct .range-selector button for a restored preference
 * (falls back to whatever button already has .active, e.g. '1Y', if there's
 * no saved preference or its button no longer exists).
 * @param {string} pageKey
 * @returns {string} the range to apply
 */
function restoreRangeSelection(pageKey) {
  const saved = loadRangePreference(pageKey);
  const selector = document.querySelector('.range-selector');
  if (!saved || !selector) return selector ? selector.querySelector('button.active').dataset.range : '1Y';
  const btn = selector.querySelector(`button[data-range="${saved.range}"]`);
  if (!btn) return selector.querySelector('button.active').dataset.range;
  selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  return saved.range;
}

// ── Flash messages via sessionStorage ─────────────────────────────────────
(function initFlash() {
  const msg = sessionStorage.getItem('pm_flash');
  if (msg) {
    sessionStorage.removeItem('pm_flash');
    const el = document.createElement('div');
    el.className = 'notice success';
    el.textContent = msg;
    const main = document.querySelector('.main-content');
    if (main) main.prepend(el);
  }
})();

// ── CSRF-safe form submits via fetch ───────────────────────────────────────
// (Not needed for this app — forms use standard POST. Kept for future use.)

// ── Price refresh (available on all pages) ────────────────────────────────
async function refreshPrices(btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '↻ Bezig… (kan ~1 min duren)';
  try {
    const r = await fetch('/api/refresh-prices', { method: 'POST' });
    const d = await r.json();
    if (d.error) {
      btn.textContent = `✗ Fout: ${d.error}`;
      btn.disabled = false;
      setTimeout(() => { btn.textContent = origText; btn.disabled = false; }, 5000);
    } else {
      const failMsg = d.failed && d.failed.length ? ` (${d.failed.length} mislukt)` : '';
      btn.textContent = `✓ ${d.refreshed} vernieuwd${failMsg}`;
      setTimeout(() => location.reload(), 1500);
    }
  } catch (e) {
    btn.textContent = '✗ Fout';
    btn.disabled = false;
    setTimeout(() => { btn.textContent = origText; btn.disabled = false; }, 3000);
  }
}
const LAN_WARNING_HIDE_KEY = 'pm-hide-lan-mode-warning-until';

function hideLanModeWarning(durationMs) {
  localStorage.setItem(LAN_WARNING_HIDE_KEY, String(Date.now() + durationMs));
  document.getElementById('lan-mode-banner')?.setAttribute('hidden', '');
  updateLanModeBannerOffset();
}

function openLanModeWarningDialog() {
  const banner = document.getElementById('lan-mode-banner');
  if (!banner) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'lan-hide-dialog';
  const article = document.createElement('article');
  const header = document.createElement('header');
  const title = document.createElement('strong');
  title.textContent = banner.dataset.hideTitle;
  const close = document.createElement('button');
  close.type = 'button';
  close.setAttribute('rel', 'prev');
  close.setAttribute('aria-label', banner.dataset.close);
  close.addEventListener('click', () => dialog.close());
  header.append(title, close);
  const description = document.createElement('p');
  description.textContent = banner.dataset.hideDescription;
  const options = document.createElement('div');
  options.className = 'lan-hide-options';
  [[86400000, 'data-hide-1d'], [2592000000, 'data-hide-1m'], [7776000000, 'data-hide-3m'], [31536000000, 'data-hide-1y']]
    .forEach(([duration, labelAttribute]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'outline secondary btn-sm';
      button.textContent = banner.getAttribute(labelAttribute);
      button.addEventListener('click', () => {
        hideLanModeWarning(duration);
        dialog.close();
      });
      options.append(button);
    });
  const footer = document.createElement('footer');
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'outline secondary btn-sm';
  cancel.textContent = banner.dataset.cancel;
  cancel.addEventListener('click', () => dialog.close());
  footer.append(cancel);
  article.append(header, description, options, footer);
  dialog.append(article);
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

function updateLanModeBannerOffset() {
  const banner = document.getElementById('lan-mode-banner');
  const active = Boolean(banner && !banner.hidden);
  document.body.classList.toggle('lan-mode-active', active);
  document.documentElement.style.setProperty(
    '--lan-mode-banner-height', active ? `${banner.offsetHeight}px` : '0px'
  );
}

const lanModeBanner = document.getElementById('lan-mode-banner');
const lanWarningHiddenUntil = Number(localStorage.getItem(LAN_WARNING_HIDE_KEY) || 0);
if (localStorage.getItem('pm-hide-lan-mode-warning') === '1') localStorage.removeItem('pm-hide-lan-mode-warning');
lanModeBanner?.toggleAttribute('hidden', lanWarningHiddenUntil > Date.now());
updateLanModeBannerOffset();
window.addEventListener('resize', updateLanModeBannerOffset);
