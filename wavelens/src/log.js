/* wavelens/src/log.js — the log under the viewer: what the page did (a dump read, the types or the sources taken, a state
   loaded or saved, a compare) and what went wrong; an error in a JSON file (a types file, a saved state) with its place:
   the line, a caret under the column. A strip folded to one line (the last entry, the count of errors and warnings) that a
   click opens; an error opens it. Kept on the viewer's element: a dump opened again or Sources… (a new viewer on it) keep
   it. The setting "log": "auto" shows it from the first thing done in the page, true always, false never. */

const LOG_MAX = 500, LOG_ITEMS = 200;   // entries kept (the oldest go); the lines under one entry shown (Copy has them all)
const LOG_ICON = { ok: '✔', info: '·', warning: '⚠', error: '✖' };
const logTime = d => d.toTimeString().slice(0, 8);
const logLine = x => `${x.line ? `line ${x.line}: ` : ''}${x.text}`;   // a note of the VCD reader ({level, line, text})
// a line of a JSON file around a column (a long one: 100 characters of it) and a caret under the column
function logCaret(j) {
  const s = String(j.text || '').replace(/\t/g, ' '), a = Math.max(0, j.col - 61), b = Math.min(s.length, a + 100), pre = a ? '…' : '';
  return `${pre}${s.slice(a, b)}${b < s.length ? '…' : ''}\n${' '.repeat(pre.length + Math.max(0, j.col - 1 - a))}^`;
}
// an entry as text (Copy, the VS Code tab's log): its time, level, text, the place of a JSON error, its lines
function logPlain(e) {
  const out = [`${logTime(e.t)} ${e.level}: ${e.text}`];
  if (e.json && e.json.line) out.push(`  ${e.json.name}:${e.json.line}:${e.json.col}`, ...logCaret(e.json).split('\n').map(x => '    ' + x));
  for (const x of e.items || []) out.push('  ' + x);
  return out.join('\n');
}

Object.assign(WaveView.prototype, {
  // an entry: level ok | info | warning | error, its text; more: {items: [lines under it, folded], what: their summary
  // ("the list"), json: an error's place (jsonParse's .json), quiet: the strip not shown for it ("log": "auto")} -> this
  log(level, text, more = {}) {
    const L = this.logList(), e = Object.assign({ t: new Date(), level, text: String(text) }, more);
    if (e.items && !e.items.length) delete e.items;
    L.push(e); if (L.length > LOG_MAX) L.splice(0, L.length - LOG_MAX);
    if (!e.quiet) this.root.wlLogSeen = true;
    if (level === 'error') this.root.wlLogOpen = true;
    this.root.dispatchEvent(new CustomEvent('wavelens:log', { detail: Object.assign({ plain: logPlain(e) }, e) }));
    this.logRender(); return this;
  },
  // what went wrong (an Error): its text, and its place when it is one of a JSON file
  logError(e, text) { return this.log('error', text || e.message, e && e.json && e.json.line ? { json: e.json } : {}); },
  logList() { return this.root.wlLog || (this.root.wlLog = []); },
  logOpen(on = !this.root.wlLogOpen) { this.root.wlLogOpen = !!on; this.root.wlLogSeen = true; this.logRender(); return this; },
  logClear() { this.logList().length = 0; this.logRender(); return this; },
  logText() { return this.logList().map(logPlain).join('\n'); },
  logMount() {
    const el = this.logEl = this.root.querySelector('.wlog'); if (!el) return;
    el.addEventListener('click', e => {
      const b = e.target.closest('button'), a = b && b.dataset.l;
      if (a === 'clear') this.logClear();
      else if (a === 'only') { this.root.wlLogOnly = !this.root.wlLogOnly; this.logRender(); }
      else if (a === 'copy') { const t = this.logText(), n = t ? t.split('\n').length : 0;
        try { navigator.clipboard.writeText(t).then(() => this.toast(`the log copied: ${n} lines`), () => this.toast('cannot copy the log')); }
        catch (x) { this.toast('cannot copy the log'); } }
      else if (a === 'fold' || (!b && e.target.closest('.lh'))) this.logOpen();
    }, { signal: this.ac.signal });
    this.logRender();
  },
  logRender() {
    const el = this.logEl; if (!el || !el.isConnected) return;
    const L = this.logList(), S = this.S, show = S.log === true || (S.log !== false && !!this.root.wlLogSeen);
    el.hidden = !show; if (!show) { el.innerHTML = ''; return; }
    const ne = L.filter(e => e.level === 'error').length, nw = L.filter(e => e.level === 'warning').length;
    const open = !!this.root.wlLogOpen, only = !!this.root.wlLogOnly, last = L[L.length - 1];
    const cnt = (ne ? `<span class="lc le" title="errors">✖ ${ne}</span>` : '') + (nw ? `<span class="lc lw" title="warnings">⚠ ${nw}</span>` : '');
    let h = `<div class="lh"><button type="button" data-l="fold" class="lf" aria-expanded="${open}" title="${open ? 'Fold the log' :
      'Open the log: what the page did, and what went wrong'}">${open ? '▾' : '▸'} Log</button>${cnt}` + (open ? '<span class="lsp"></span>' +
      `<button type="button" data-l="only" aria-pressed="${only}" title="Only the errors and warnings">Problems</button>` +
      '<button type="button" data-l="copy" title="The whole log as text">Copy</button><button type="button" data-l="clear">Clear</button>' :
      `<span class="ll lv-${last ? last.level : 'info'}">${last ? esc(last.text) : 'nothing yet'}</span>`) + '</div>';
    if (open) {
      const rows = L.filter(e => !only || e.level === 'error' || e.level === 'warning');
      const none = `<li class="lv-info">${only ? 'no errors or warnings' : 'nothing yet'}</li>`;
      h += `<ol class="lb" role="log">${rows.map(e => this.logRow(e)).join('') || none}</ol>`;
    }
    el.innerHTML = h;
    const b = el.querySelector('.lb'); if (b) b.scrollTop = b.scrollHeight;   // the latest in sight
  },
  logRow(e) {
    let h = `<li class="lv-${e.level}"><span class="lt">${logTime(e.t)}</span><span class="li">${LOG_ICON[e.level] || '·'}</span><span class="lx">${
      esc(e.text)}</span>`;
    if (e.json && e.json.line) h += `<pre class="lj">${esc(`${e.json.name}:${e.json.line}:${e.json.col}\n${logCaret(e.json)}`)}</pre>`;
    const it = e.items || [];
    if (it.length) h += `<details><summary>${esc(e.what || `${it.length} more`)}</summary><ul>${
      it.slice(0, LOG_ITEMS).map(x => `<li>${esc(x)}</li>`).join('')}${
      it.length > LOG_ITEMS ? `<li>… ${it.length - LOG_ITEMS} more (Copy has them all)</li>` : ''}</ul></details>`;
    return h + '</li>';
  },
});
