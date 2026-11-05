/* vscode/userconfig.js — your configuration of the viewer in VS Code (WaveLens: Open the configuration): a JSONC file in the
   extension's global storage, every key of wavelens/wavelens.config.js with its default and its comment. Pure: the extension
   (node) requires it, tests/smoke.py loads it in a page.
   template(defaults, notes) -> the file's text; parse(text) -> {value, keys: [{key, line, col}]} (the top level's keys where
   they are) or {error, line, col}; check(value, defaults) -> {config, problems: [{key, message}]}: what is wrong is left out
   (the rest applies, the defaults stand for it); notesOf(js) -> {key: comment} of wavelens.config.js. */
(function (root) {
  // keys VS Code sets in its own way: the theme (wavelens.theme), the keys left to VS Code (wavelens.keysToVSCode)
  const VSCODE_OWN = { theme: 'the setting wavelens.theme', keysLeft: 'the setting wavelens.keysToVSCode' };
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);   // "constructor", "__proto__": no key of these
  // the keys whose comment in wavelens.config.js names more than one kind, or whose default (null) names none: the kinds the
  // viewer takes; every other key: the kind of its default
  const KINDS = {
    log: ['string', 'boolean'],             // 'auto' | true | false
    keyHints: ['number', 'boolean'],        // ms | false
    gapIdle: ['number', 'string'],          // cycles | a time ('2us')
    gapKeep: ['number', 'string'],
    themeButton: ['string', 'boolean'],     // 'auto' | true | false
    svaSignals: ['string', 'boolean'],      // 'view' | true | false
    fontMono: ['string'], fontBody: ['string'],
    enumColors: ['object'], groupColors: ['object'], buses: ['array'],
    fold: ['boolean', 'number', 'array', 'string'],   // true | a depth | ['group.path', …] (or "a, b")
    highlight: ['array', 'string'], svaShow: ['array', 'string'], gapSignals: ['array', 'string'], gapAux: ['array', 'string'],
    gapClock: ['string'], cycleClock: ['string'],
    cycleZero: ['number', 'string'],        // ps | a time ('20ns')
    maxHeight: ['string', 'number'],        // '80vh' | px
  };
  const KIND_SAID = { string: 'a string', boolean: 'true / false', number: 'a number', array: 'a list', object: 'an object {…}' };
  const HEAD = ['// WaveLens: your configuration of the viewer in VS Code (every tab). Saved: checked and applied at once.',
    '// Each key is one of wavelens.config.js, with its default: change the value; a key taken out goes back to its default.',
    '// What is wrong (a value of the wrong kind, a key that is none) is left out and marked here; the rest still applies.',
    '// WaveLens: Reset the configuration to the defaults writes this file anew. JSON with comments (// and /* */).'];

  // wavelens.config.js -> the comment of each key ("rowHeight: 26,   // px: signal row" -> {rowHeight: 'px: signal row'})
  function notesOf(js) {
    const out = {};
    for (const l of String(js || '').split('\n')) { const m = /^\s{2}(\w+):.*?\/\/\s?(.*)$/.exec(l); if (m && !(m[1] in out)) out[m[1]] = m[2].trim(); }
    return out;
  }
  // the defaults as a JSONC text, a key a line with its comment above it
  function template(defaults, notes = {}) {
    const keys = Object.keys(defaults).filter(k => !own(VSCODE_OWN, k));
    const lines = keys.map((k, i) => (notes[k] ? `  // ${notes[k]}\n` : '') +
      `  ${JSON.stringify(k)}: ${JSON.stringify(defaults[k])}${i < keys.length - 1 ? ',' : ''}`);
    return HEAD.join('\n') + '\n{\n' + lines.join('\n') + '\n}\n';
  }
  // JSON with comments and trailing commas -> {value, keys} | {error, line, col} (1-based, where it stopped); a byte order mark
  // (a Windows tool's "UTF-8 with BOM") left out: VS Code's editor does not show it
  function parse(text) {
    const s = String(text == null ? '' : text).replace(/^\uFEFF/, '');
    let out = '', i = 0;
    while (i < s.length) {   // comments and commas before } ] out, the strings kept, the offsets the same (blanks)
      const c = s[i];
      if (c === '"') { let j = i + 1; while (j < s.length && s[j] !== '"') j += s[j] === '\\' ? 2 : 1; out += s.slice(i, j + 1); i = j + 1; continue; }
      if (c === '/' && s[i + 1] === '/') { const j = s.indexOf('\n', i); const e = j < 0 ? s.length : j; out += ' '.repeat(e - i); i = e; continue; }
      if (c === '/' && s[i + 1] === '*') {
        const j = s.indexOf('*/', i + 2), e = j < 0 ? s.length : j + 2; out += s.slice(i, e).replace(/[^\n]/g, ' '); i = e; continue; }
      if (c === ',') { const m = /^,(\s*)([}\]])/.exec(s.slice(i).replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, x => ' '.repeat(x.length)));
        if (m) { out += ' '; i++; continue; } }
      out += c; i++;
    }
    try { return { value: JSON.parse(out), keys: keysAt(out) }; } catch (e) {
      const msg = String(e.message || e), p = /position (\d+)/.exec(msg), lc = /line (\d+) column (\d+)/.exec(msg);
      let line = 1, col = 1;
      if (lc) { line = +lc[1]; col = +lc[2]; }
      else if (p) { const before = s.slice(0, +p[1]).split('\n'); line = before.length; col = before[before.length - 1].length + 1; }
      else { const ls = s.split('\n'); line = ls.length; col = ls[ls.length - 1].length + 1; }
      return { error: msg, line, col };
    }
  }
  // the top level's keys in a text without comments (the offsets of the file): [{key, line, col}] (1-based), in their order
  function keysAt(t) {
    const keys = [];
    let depth = 0, line = 1, bol = 0;
    for (let i = 0; i < t.length; i++) {
      const c = t[i];
      if (c === '\n') { line++; bol = i + 1; }
      else if (c === '{' || c === '[') depth++;
      else if (c === '}' || c === ']') depth--;
      else if (c === '"') {
        let j = i + 1; while (j < t.length && t[j] !== '"') j += t[j] === '\\' ? 2 : 1;
        let n = j + 1; while (n < t.length && /\s/.test(t[n])) n++;   // (the lines counted on from j)
        if (depth === 1 && t[n] === ':') keys.push({ key: JSON.parse(t.slice(i, j + 1)), line, col: i - bol + 1 });
        i = j;
      }
    }
    return keys;
  }
  const kind = v => (v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v);
  // what the file says against the defaults: each key of a known kind kept, the rest left out with why
  function check(value, defaults) {
    const problems = [], config = {};
    if (kind(value) !== 'object') return { config, problems: [{ key: null, message: `the file is ${kind(value)}: an object {"key": value, …}` }] };
    for (const [k, v] of Object.entries(value)) {
      if (own(VSCODE_OWN, k)) { problems.push({ key: k, message: `"${k}" is VS Code's here: ${VSCODE_OWN[k]}` }); continue; }
      if (!own(defaults, k)) { problems.push({ key: k, message: `"${k}" is no setting of the viewer (have: rowHeight, colors, radix, …)` }); continue; }
      const d = defaults[k], want = own(KINDS, k) ? KINDS[k] : [kind(d)], got = kind(v);
      if (v === null || want[0] === 'null' || want.includes(got)) {
        if (got === 'number' && !isFinite(v)) { problems.push({ key: k, message: `"${k}": a finite number` }); continue; }
        config[k] = v; continue;
      }
      if (want.join() === 'object' && got === 'array') { problems.push({ key: k, message: `"${k}": an object {…}, not a list` }); continue; }
      const what = want.map(w => KIND_SAID[w] || 'a ' + w).join(' or ');
      problems.push({ key: k, message: `"${k}": ${what} (its default ${JSON.stringify(d)}), not ${JSON.stringify(v)}` });
    }
    return { config, problems };
  }
  // the configuration a tab applies: the defaults, then yours over them (a key you took out: its default again)
  const effective = (defaults, config) => Object.assign({}, ...Object.keys(defaults).filter(k => !own(VSCODE_OWN, k)).map(k => ({ [k]: defaults[k] })), config);
  const api = { notesOf, template, parse, check, effective, VSCODE_OWN, KINDS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.WaveLensUserConfig = api;
})(typeof window !== 'undefined' ? window : this);
