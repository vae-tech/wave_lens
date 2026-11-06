/* vscode/protocol.js — the messages between a tab's page (media/host.js, in the webview) and the extension (extension.js,
   on the host): the one definition of them (review 2026-11-05 runs, A-05). Pure: the extension requires it and checks
   every message of a page against it (an unknown type, a key missing: an error answered, not a throw); tests/smoke.py
   loads it in its page and its fake host answers by it; tests/unit/test_protocol.py walks every type of it through the
   real extension and every type the two sources name.
   PAGE: what the page sends -> { ask: its keys (k? may be left out), reply: the answers it gets (each a set of keys, ''
   none; null: no answer), ops: for runs, the same per its op }. Every answer may be { error } instead. A key of an answer
   ending in ? may be left out; the id of a request comes back in its answer.
   HOST: what the extension sends the page by itself -> its keys.
   check(m) -> null, or why the message is not one of PAGE; spec(m) -> its entry (runs: its op's); answers(m, r) -> whether
   r is one of the answers m may get. */
(function (root) {
  const PAGE = {
    page: { ask: '', reply: null },                                // a page starts (again: a tab moved to a window): the streams before closed
    source: { ask: '', reply: ['src name lazy store'] },           // the dump's URI now (an FST: its VCD text; lazy: its header), its store
    bytes: { ask: '', reply: ['data'] },                           // what source named, as bytes (a URI the webview could not fetch)
    codes: { ask: 'codes', reply: ['text'] },                      // a lazy dump's signals by their id codes: sva vcd --codes
    store: { ask: 'key value', reply: null },                      // a localStorage key of this dump (value null: removed)
    save: { ask: 'name b64', reply: ['path', 'cancel'] },          // a download: a save dialog on the host
    pick: { ask: 'accept multiple? state?', reply: ['files'] },    // a file picker: an open dialog on the host
    'state-kept': { ask: '', reply: null },                        // the state picked is loaded: Reload reads it
    'state-read': { ask: '', reply: ['name mtime b64'] },          // Reload (r): the last state read on the host
    compare: { ask: 'signals from to', reply: ['result', ''] },    // Compare…: a dump picked, sva diff --page ('' the dialog closed)
    runs: { ask: 'op', ops: {                                      // the Runs panel: sva runs
      list: { ask: '', reply: ['dir runs others?'] },
      keep: { ask: 'name? tags? comment? cases?', reply: ['run'] },
      set: { ask: 'run name? tags? comment?', reply: ['run'] },
      rm: { ask: 'run', reply: ['removed', 'cancelled'] },
      diff: { ask: 'signals from to case?', reply: ['runs wavelens? version? unit? dump? dir? from? to? others? case?'] },
      compare: { ask: 'run signals from to case?', reply: ['result'] },
      cancel: { ask: '', reply: ['ok'] },
    } },
    sources: { ask: '', reply: ['texts', 'types typesName texts'] },   // the workspace's .sv sources, or the types beside the dump
    config: { ask: '', reply: ['config'] },                        // your configuration now
    clip: { ask: 'text', reply: ['ok'] },                          // navigator.clipboard.writeText
    theme: { ask: '', reply: null },                               // the bar's ◐: VS Code's list of themes
    result: { ask: 'rid results', reply: null },                   // the answer to a host's run
    ready: { ask: 'title? name? shown? total? log? info?', reply: null },   // the page is up, the dump read
    loaded: { ask: 'name? shown? total? log? info?', reply: null },        // a dump read (again)
    dumperror: { ask: 'name? error? line? log?', reply: null },            // a dump not read
    log: { ask: 'text', reply: null },
    configerror: { ask: 'text', reply: null },                     // your configuration broke the viewer
    'es-open': { ask: 'sid url', reply: null },                    // the live link's EventSource (its events come as "es")
    'es-close': { ask: 'sid', reply: null },
    http: { ask: 'url method? body?', reply: ['status text', 'status'] },   // the live link's POST (sendBeacon: id 0, no answer)
  };
  const HOST = {
    laststate: 'path', changed: 'auto', reload: '', 'runs-panel': '', 'runs-changed': '', run: 'rid ops', es: 'sid event data?',
    live: 'link', theme: 'theme', keys: 'keysLeft', config: 'config',
  };
  const words = s => String(s).split(' ').filter(Boolean);
  const need = s => words(s).filter(k => !k.endsWith('?'));
  const all = s => words(s).map(k => k.replace(/\?$/, ''));
  const own = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);
  const isObj = m => !!m && typeof m === 'object' && !Array.isArray(m);
  const spec = m => {
    const p = isObj(m) && typeof m.type === 'string' && own(PAGE, m.type) ? PAGE[m.type] : null;
    return p && p.ops ? (own(p.ops, m.op) ? p.ops[m.op] : null) : p;
  };
  function check(m) {
    if (!isObj(m) || typeof m.type !== 'string') return 'a message without a type';
    if (!own(PAGE, m.type)) return `no message ${m.type}`;
    const p = PAGE[m.type], gone = need(p.ask).filter(k => !own(m, k));
    if (gone.length) return `${m.type}: without ${gone.join(', ')}`;
    if (!p.ops) return null;
    if (!own(p.ops, m.op)) return `${m.type}: no operation ${m.op}`;
    const lack = need(p.ops[m.op].ask).filter(k => !own(m, k));
    return lack.length ? `${m.type} ${m.op}: without ${lack.join(', ')}` : null;
  }
  // r (an answer, its id aside) one of the answers m may get: an error, or every key of one of them there and no other
  function answers(m, r) {
    const p = spec(m);
    if (!p || !p.reply || !isObj(r)) return false;
    const keys = Object.keys(r).filter(k => k !== 'id' && r[k] !== undefined);
    if (keys.length === 1 && keys[0] === 'error' && typeof r.error === 'string') return true;
    return p.reply.some(s => need(s).every(k => keys.includes(k)) && keys.every(k => all(s).includes(k)));
  }
  const api = { PAGE, HOST, check, spec, answers, words, need, all };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.WaveLensProtocol = api;
})(typeof window !== 'undefined' ? window : this);
