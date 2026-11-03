/* vscode/links.js — times and signals in a line of a log or the terminal as links to the dump's WaveLens tab (extension.js), and a
   page's Copy link from the tab ("dump.vcd#t=1234ns&sel=tb.u.sig"). Pure: the extension (node) requires it, tests/smoke.py loads it
   in a page. linksOf(text, patterns) -> [{start, end, ps, sig, dump, hash}]: ps the time in ps (null: none), sig a signal's path of
   the line (the first dotted name that is no file), dump / hash a link of a tab's Copy link. */
(function (root) {
  const UNIT_PS = { fs: 1e-3, ps: 1, ns: 1e3, us: 1e6, 'µs': 1e6, ms: 1e9, s: 1e12 };
  const NUM = '(?<t>\\d+(?:\\.\\d+)?(?:e[-+]?\\d+)?)', UNIT = '\\s*(?<unit>fs|ps|ns|us|µs|ms|s)\\b';
  // a time as simulators and testbenches say it: "@ 1234 ns", "@1234ns", "at 1.234 us", "time=1234ns", "t = 5 ns", and a bare "1234 ns" — the
  // bare one in fs / ps / ns / us only ("Finished in 3 s", "100 ms timeout" are no times of a dump); none after a minus ("at -5 ns")
  const TIMES = [`@\\s*${NUM}${UNIT}`, `\\bat\\s+${NUM}${UNIT}`, `\\b(?:time|t)\\s*[=:]\\s*${NUM}${UNIT}`,
    `(?<![\\w.\\-])${NUM}\\s*(?<unit>fs|ps|ns|us|µs)\\b`];
  // a dump's link: what Copy link gives in the tab
  const DUMP = /(?<dump>(?:[A-Za-z]:)?[\w./\\~-]*\.(?:vcd|fst))(?<hash>#[^\s'"<>)\]]+)/gi;
  // a signal: a path of two names or more (tb.u_dma.req, top.data[3], top.gen[2].u_dma.req: an index in the middle too); a file's name
  // is not one, nor a logger's ("cocotb.regression", "logging.x", "self.x", "uvm_…")
  const SIG = /(?<![\w.$])(?<sig>[A-Za-z_][\w$]*(?:\[\d+\])?(?:\.[A-Za-z_][\w$]*(?:\[\d+\])?)+(?:\[\d+(?::\d+)?\])?)/g;
  const NOT_SIG = /^(?:cocotb|logging|self|uvm_\w*)\./i;
  const FILES = /\.(?:py|pyc|sv|svh|v|vh|vhd|vcd|fst|log|txt|json|html?|c|cc|cpp|h|hpp|tcl|do|f|yaml|yml|md|so|o|sh|js|wlf)$/i;
  const toPs = (t, unit) => (unit && Object.prototype.hasOwnProperty.call(UNIT_PS, unit.toLowerCase()) ? +t * UNIT_PS[unit.toLowerCase()] : null);
  // the user's patterns -> regexes; bad: the ones that are no regex, or have no group "t" (said by the extension, once)
  function compile(list, bad = []) {
    const out = [];
    for (const p of Array.isArray(list) ? list : []) {
      try { const rx = p instanceof RegExp ? new RegExp(p.source, p.flags.includes('g') ? p.flags : p.flags + 'g') : new RegExp(String(p), 'gi');
        if (!/\(\?<t>/.test(rx.source)) { bad.push(`${p}: no group "t" (the time)`); continue; }
        out.push(rx); } catch (e) { bad.push(`${p}: ${e.message}`); }
    }
    return out;
  }
  // the signal of the line: the first dotted name after the time (at: where the time ends), else the first of the line; files and loggers
  // are none
  function sigOf(text, at = 0) {
    const all = []; SIG.lastIndex = 0;
    for (let m; (m = SIG.exec(text));) if (!FILES.test(m.groups.sig) && !/^\d/.test(m.groups.sig) && !NOT_SIG.test(m.groups.sig)) all.push(m);
    const after = all.find(m => m.index >= at) || all[0];
    return after ? after.groups.sig : null;
  }
  // own: the user's patterns (wavelens.logLinks), each with the groups t and unit (and sig), tried first
  function linksOf(text, own = []) {
    const s = String(text || ''), out = [], taken = [];
    const free = (a, b) => !taken.some(([p, q]) => a < q && b > p);
    const put = o => { if (free(o.start, o.end)) { taken.push([o.start, o.end]); out.push(o); } };
    DUMP.lastIndex = 0;
    for (let m; (m = DUMP.exec(s));) put({ start: m.index, end: m.index + m[0].length, ps: null, sig: null, dump: m.groups.dump, hash: m.groups.hash });
    for (const rx of compile(own).concat(compile(TIMES))) {
      rx.lastIndex = 0;
      for (let m; (m = rx.exec(s));) {
        if (!m[0]) { rx.lastIndex++; continue; }
        const g = m.groups || {}, ps = g.unit ? toPs(g.t, g.unit) : +g.t;   // a pattern of the user without a unit: ps
        if (ps == null || !isFinite(ps)) continue;
        put({ start: m.index, end: m.index + m[0].length, ps, sig: g.sig || sigOf(s, m.index + m[0].length), dump: null, hash: null });
      }
    }
    return out.sort((a, b) => a.start - b.start);
  }
  // a hash of Copy link -> the goto command's arguments
  function hashArgs(hash) {
    const o = {};
    for (const part of String(hash || '').replace(/^#/, '').split('&')) {
      const k = part.indexOf('='), key = k < 0 ? '' : part.slice(0, k);
      if (['t', 'sel', 'view', 'bm'].includes(key)) try { o[key] = decodeURIComponent(part.slice(k + 1)); } catch (e) { o[key] = part.slice(k + 1); }
    }
    delete o.view;   // the tab has one viewer
    return o;
  }
  // a link -> the goto command
  const gotoOf = l => (l.hash ? hashArgs(l.hash) : Object.assign({ t: `${l.ps}ps` }, l.sig ? { sel: l.sig } : {}));
  const badPatterns = list => { const bad = []; compile(list, bad); return bad; };
  const api = { linksOf, hashArgs, gotoOf, toPs, sigOf, badPatterns };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.WaveLensLinks = api;
})(typeof window !== 'undefined' ? window : this);
