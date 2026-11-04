/* vscode/userconfig.js — your configuration of the viewer in VS Code (WaveLens: Open the configuration): a JSONC file in the
   extension's global storage, every key of wavelens/wavelens.config.js with its default and its comment. Pure: the extension
   (node) requires it, tests/smoke.py loads it in a page.
   template(defaults, notes) -> the file's text; parse(text) -> {value} or {error, line, col}; check(value, defaults) ->
   {config, problems: [{key, message}]}: what is wrong is left out (the rest applies, the defaults stand for it); notesOf(js)
   -> {key: comment} of wavelens.config.js. */
(function (root) {
  // keys VS Code sets in its own way: the theme (wavelens.theme), the keys left to VS Code (wavelens.keysToVSCode)
  const VSCODE_OWN = { theme: 'the setting wavelens.theme', keysLeft: 'the setting wavelens.keysToVSCode' };
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
    const keys = Object.keys(defaults).filter(k => !(k in VSCODE_OWN));
    const lines = keys.map((k, i) => (notes[k] ? `  // ${notes[k]}\n` : '') +
      `  ${JSON.stringify(k)}: ${JSON.stringify(defaults[k])}${i < keys.length - 1 ? ',' : ''}`);
    return HEAD.join('\n') + '\n{\n' + lines.join('\n') + '\n}\n';
  }
  // JSON with comments and trailing commas -> {value} | {error, line, col} (1-based, where it stopped)
  function parse(text) {
    const s = String(text == null ? '' : text);
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
    try { return { value: JSON.parse(out) }; } catch (e) {
      const msg = String(e.message || e), p = /position (\d+)/.exec(msg), lc = /line (\d+) column (\d+)/.exec(msg);
      let line = 1, col = 1;
      if (lc) { line = +lc[1]; col = +lc[2]; }
      else if (p) { const before = s.slice(0, +p[1]).split('\n'); line = before.length; col = before[before.length - 1].length + 1; }
      else { const ls = s.split('\n'); line = ls.length; col = ls[ls.length - 1].length + 1; }
      return { error: msg, line, col };
    }
  }
  const kind = v => (v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v);
  // what the file says against the defaults: each key of a known kind kept, the rest left out with why
  function check(value, defaults) {
    const problems = [], config = {};
    if (kind(value) !== 'object') return { config, problems: [{ key: null, message: `the file is ${kind(value)}: an object {"key": value, …}` }] };
    for (const [k, v] of Object.entries(value)) {
      if (k in VSCODE_OWN) { problems.push({ key: k, message: `"${k}" is VS Code's here: ${VSCODE_OWN[k]}` }); continue; }
      if (!(k in defaults)) { problems.push({ key: k, message: `"${k}" is no setting of the viewer (have: rowHeight, colors, radix, …)` }); continue; }
      const d = defaults[k], want = kind(d), got = kind(v);
      if (v === null || want === 'null' || got === want) {
        if (got === 'number' && !isFinite(v)) { problems.push({ key: k, message: `"${k}": a finite number` }); continue; }
        config[k] = v; continue;
      }
      if (want === 'object' && got === 'array') { problems.push({ key: k, message: `"${k}": an object {…}, not a list` }); continue; }
      const what = want === 'array' ? 'a list' : want === 'object' ? 'an object' : 'a ' + want;
      problems.push({ key: k, message: `"${k}": ${what} (its default ${JSON.stringify(d)}), not ${JSON.stringify(v)}` });
    }
    return { config, problems };
  }
  // the configuration a tab applies: the defaults, then yours over them (a key you took out: its default again)
  const effective = (defaults, config) => Object.assign({}, ...Object.keys(defaults).filter(k => !(k in VSCODE_OWN)).map(k => ({ [k]: defaults[k] })), config);
  const api = { notesOf, template, parse, check, effective, VSCODE_OWN };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.WaveLensUserConfig = api;
})(typeof window !== 'undefined' ? window : this);
