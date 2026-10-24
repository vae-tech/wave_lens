/* wavelens/bus.js — bus transactions on the waves (stage 11): AXI4 / AXI4-Lite / AXI3, AXI4-Stream, APB, AHB, Avalon-MM,
   Avalon-ST, Wishbone (classic and pipelined), OBI. A plugin of wavelens.js, on its plugin API only.

   The interfaces of a viewer are found by the names of their signals in each module (the signals of one port share a
   prefix: s_axi_awvalid, m_axi_awvalid; a trailing _i / _o is ignored) or listed in the setting "buses"; each is
   sampled at the rising edges of its clock and taken apart into transactions (address to response, a burst, a packet)
   and the beats of its channels. On the waves: a group "⇄ name · protocol · counts" under its module, folded at first
   with the transactions on its header row; open, a row of transactions and one row per channel. A click on a
   transaction: the cursor at its start, its range measured, its signals highlighted. */
(() => {
const G = window, W = G.WaveLens;
if (!W || !W.plugin) return;
const U = W.util, esc = U.esc;

/* ---------------- protocols: the names of their signals ---------------- */
// roles: the signal names after the port's prefix (lower case); need: one of these sets makes a port; clock: the
// clock's names (with the prefix, else in the module)
const PROTO = {
  axi: { label: 'AXI4', clock: ['aclk', 'clk'], need: [['awvalid', 'awready', 'bvalid'], ['arvalid', 'arready', 'rvalid']],
    roles: ['awvalid', 'awready', 'awaddr', 'awid', 'awlen', 'wvalid', 'wready', 'wdata', 'wstrb', 'wlast', 'wid', 'bvalid', 'bready', 'bresp', 'bid',
      'arvalid', 'arready', 'araddr', 'arid', 'arlen', 'rvalid', 'rready', 'rdata', 'rresp', 'rlast', 'rid'] },
  axis: { label: 'AXI4-Stream', clock: ['aclk', 'clk'], need: [['tvalid', 'tdata'], ['tvalid', 'tlast']],
    roles: ['tvalid', 'tready', 'tdata', 'tlast', 'tkeep', 'tuser', 'tid', 'tdest'] },
  apb: { label: 'APB', clock: ['pclk', 'clk'], need: [['psel', 'penable']], roles: ['psel', 'penable', 'pready', 'paddr', 'pwrite', 'pwdata', 'prdata',
    'pslverr', 'pstrb'] },
  ahb: { label: 'AHB', clock: ['hclk', 'clk'], need: [['htrans', 'haddr']], roles: ['htrans', 'haddr', 'hwrite', 'hburst', 'hsize', 'hwdata', 'hrdata',
    'hready', 'hreadyout', 'hresp', 'hsel'] },
  avmm: { label: 'Avalon-MM', clock: ['clk'], need: [['address', 'waitrequest'], ['address', 'readdatavalid']],
    roles: ['address', 'read', 'write', 'writedata', 'readdata', 'readdatavalid', 'waitrequest', 'byteenable', 'burstcount', 'response'] },
  avst: { label: 'Avalon-ST', clock: ['clk'], need: [['valid', 'data', 'startofpacket', 'endofpacket']],
    roles: ['valid', 'ready', 'data', 'startofpacket', 'endofpacket', 'channel', 'error'] },
  wb: { label: 'Wishbone', clock: ['clk', 'clk_i'], need: [['cyc', 'stb', 'ack']],
    roles: ['cyc', 'stb', 'ack', 'err', 'rty', 'stall', 'adr', 'we', 'sel', 'dat_i', 'dat_o'] },
  obi: { label: 'OBI', clock: ['clk'], need: [['req', 'gnt', 'rvalid']], roles: ['req', 'gnt', 'addr', 'we', 'be', 'wdata', 'rvalid', 'rready', 'rdata',
    'err'] },
};
const DIRS = ['', '_i', '_o', '_in', '_out'];
const ANCHORS = Object.fromEntries(Object.entries(PROTO).map(([k, p]) => [k, [...new Set(p.need.map(s => s[0]))].map(a =>
  new RegExp(`^(.*?)${a}(_i|_o|_in|_out)?$`))]));
const leafOf = r => String(r.src && r.src.path ? r.src.path.split('.').pop() : r.name).toLowerCase();

/* ---------------- finding the ports ---------------- */
// the signal rows of the model by their scope in the dump (the path without the name; rows without a path: '', the
// whole diagram, so the channels of a hand-made view in groups of their own make one port)
const scopeOf = r => (r.src && r.src.path && r.src.path.includes('.') ? r.src.path.slice(0, r.src.path.lastIndexOf('.')) : '');
function byScope(M) {
  const out = new Map();
  for (const r of M.rows) {
    if (r.type !== 'sig' || !r.tr || r.x || r.bus) continue;
    const k = scopeOf(r);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(r);
  }
  return out;
}
// the group a scope's ports go under: the group of that path (a generated hierarchy), else the top
const groupOf = (M, scope) => (scope ? Object.values(M.groups).find(g => g.path === scope) || null : null);
// the role -> row of a port with this prefix among rows (the names with a direction suffix too); of two names that differ
// only in case (RDATA, rdata) the one written like the port's first signal
function rolesOf(rows, proto, prefix, upper = null) {
  const by = new Map(), got = {};
  for (const r of rows) { const l = leafOf(r); if (!by.has(l)) by.set(l, []); by.get(l).push(r); }
  const pick = l => { const rs = by.get(l); if (!rs) return null; if (rs.length === 1 || upper == null) return rs[0];
    return rs.find(r => isUpper(r) === upper) || rs[0]; };
  for (const role of PROTO[proto].roles) for (const d of /_[io]$/.test(role) ? [''] : DIRS) { const r = pick(prefix + role + d);
    if (r) { got[role] = r; break; } }
  return got;
}
const isUpper = r => { const n = String(r.src && r.src.path ? r.src.path.split('.').pop() : r.name); return n === n.toUpperCase(); };
const complete = (proto, got) => PROTO[proto].need.some(set => set.every(r => got[r]));
// the clock of a port: its prefix + a clock name, a clock name in its scope, else one in the scopes above
function clockOf(scope, rows, proto, prefix, scopes) {
  const names = PROTO[proto].clock, look = (rs, pfx) => { const by = new Map(rs.map(r => [leafOf(r), r]));
    for (const n of names) for (const d of DIRS) { const r = by.get(pfx + n + d); if (r) return r; } return null; };
  let r = look(rows, prefix) || look(rows, '');
  for (let s = scope; !r && s; ) { s = s.includes('.') ? s.slice(0, s.lastIndexOf('.')) : ''; r = look(scopes.get(s) || [], ''); if (!s) break; }
  return r || (rows.find(x => /(^|_)(a|h|p)?clk(_i)?$|^clock$/.test(leafOf(x)) && x.width === 1) || null);
}
// every port of a model: the ones its names show (busDetect) and the ones the setting "buses" lists
// -> [{key, proto, name, scope, g (its group, null: the top), prefix, sig: {role: row}, clk}]
function findPorts(M, S) {
  const scopes = byScope(M), out = new Map();
  const add = p => { if (!out.has(p.key)) out.set(p.key, Object.assign(p, { g: groupOf(M, p.scope) })); };
  for (const b of Array.isArray(S.buses) ? S.buses : []) {   // the listed ones first: their names win
    const proto = String(b.protocol || '').toLowerCase(); if (!PROTO[proto]) continue;
    const scope = b.scope || '', rows = scopes.get(scope) || [], prefix = String(b.prefix || '').toLowerCase();
    let sig;
    if (b.map) { const by = new Map(rows.map(r => [leafOf(r), r])); sig = {}; for (const [role,
      n] of Object.entries(b.map)) { const r = by.get(String(n).toLowerCase()); if (r) sig[role] = r; } }
    else sig = rolesOf(rows, proto, prefix);
    if (!complete(proto, sig)) continue;
    const clk = b.clock ? rows.find(r => leafOf(r) === String(b.clock).toLowerCase()) ||
      M.rows.find(r => r.full === b.clock) : clockOf(scope, rows, proto, prefix, scopes);
    if (clk) add({ key: `${proto}:${scope}:${prefix}`, proto, name: b.name, scope, prefix, sig, clk });
  }
  if (S.busDetect === false) return [...out.values()];
  for (const [scope, rows] of scopes) for (const proto of Object.keys(PROTO)) {
    for (const r of rows) {
      const leaf = leafOf(r);
      for (const rx of ANCHORS[proto]) {
        const m = leaf.match(rx);
        if (!m || (m[1] && !m[1].endsWith('_'))) continue;
        const prefix = m[1], key = `${proto}:${scope}:${prefix}`;
        if (out.has(key)) continue;
        const sig = rolesOf(rows, proto, prefix, isUpper(r));
        if (!complete(proto, sig) || Object.values(sig).every(x => x.same || (x.src && x.src.same))) continue;   // the same port seen from another level: once
        const clk = clockOf(scope, rows, proto, prefix, scopes);
        if (clk) add({ key, proto, scope, prefix, sig, clk });
      }
    }
  }
  return [...out.values()];
}
const join = (a, b) => (a && b ? a + '.' + b : a || b);

/* ---------------- sampling ---------------- */
// the rising edges of a clock row (WaveLens.util.isEdge: IEEE 1800-2017 9.4.2, as sva.js and the sva CLI)
function edges(r) {
  const out = []; let prev = null;
  for (const o of r.tr) { const k = o.k === '0' || o.k === '1' || o.k === 'z' ? o.k : 'x'; if (U.isEdge('posedge', prev, k)) out.push(o.t); prev = k; }
  return out;
}
// the value of a transition: '0' '1' 'x' for a bit; a bus: hex (no 0x), a number label as hex, else its label
function val(o) {
  if (!o) return null;
  if (o.k === '0' || o.k === '1') return o.k;
  if (o.k !== '=') return null;
  if (o.raw != null) return /^[0-9a-f]+$/i.test(o.raw) ? o.raw.toLowerCase().replace(/^0+(?=.)/, '') : null;
  if (o.hex != null) return String(o.hex).toLowerCase().replace(/^0+(?=.)/, '');
  const v = String(o.v).trim();
  if (/^0x[0-9a-f_]+$/i.test(v)) return v.slice(2).replace(/_/g, '').toLowerCase().replace(/^0+(?=.)/, '');
  if (/^\d+$/.test(v)) return BigInt(v).toString(16);
  return v;
}
// the values of a row just before every edge (what a flop samples there)
function column(r, E) {
  if (!r) return null;
  const out = new Array(E.length), a = r.tr; let k = -1;
  for (let i = 0; i < E.length; i++) { while (k + 1 < a.length && a[k + 1].t < E[i]) k++; out[i] = val(a[k]); }
  return out;
}
const hex = v => (v == null ? '?' : /^[0-9a-f]+$/.test(v) ? '0x' + v : v);
const num = v => (v != null && /^[0-9a-f]+$/.test(v) ? parseInt(v, 16) : 0);

/* ---------------- decoders ---------------- */
// a port -> {tx: [{t0, t1, kind: R | W | P (packet) | T, label, tip, err, open, rows}], ch: [{name, beats: [{t0, t1, label}]}]}
// t0: the start of the cycle the transaction began in, t1: the edge it ended at; c(k): the start of cycle k
function decode(p, view) {
  const E = edges(p.clk), n = E.length; if (n < 2) { p.name = p.name || join(p.scope.split('.').pop(), p.prefix || PROTO[p.proto].label);
    return { tx: [], ch: [], E, lanes: 1, maxDur: 0, tip: () => '' }; }
  const per = (E[n - 1] - E[0]) / (n - 1), c = k => (k > 0 ? E[k - 1] : E[0] - per), V = {};
  for (const [role, r] of Object.entries(p.sig)) V[role] = column(r, E);
  const on = (role, k, dflt = false) => (V[role] ? V[role][k] === '1' : dflt);
  const at = (role, k) => (V[role] ? V[role][k] : null);
  const when = t => (view ? view.when(t) : String(t));
  const D = { tx: [], ch: [], E };
  const chan = name => { const ch = { name, beats: [] }; D.ch.push(ch); return ch; };
  // the beats of a valid / ready channel: from the cycle valid came to the edge of the handshake
  const beats = (vName, rName, fields, ch) => {
    const out = []; let s = null;
    for (let k = 0; k < n; k++) {
      if (!on(vName, k)) { s = null; continue; }
      if (s == null) s = k;
      if (on(rName, k, true)) { const b = { k0: s, k, t0: c(s), t1: E[k] }; for (const f of fields) b[f] = at(f, k); out.push(b); s = null; }
    }
    if (ch) ch.beats.push(...out);
    return out;
  };
  const fin = (tx, k0, k1, more) => Object.assign(tx, { t0: c(k0), t1: k1 == null ? E[n - 1] : E[k1], open: k1 == null, lat: k1 == null ? null : k1 - k0 + 1 },
    more);
  DECODE[p.proto]({ p, n, E, c, V, on, at, D, chan, beats, fin });
  D.tx.sort((a, b) => a.t0 - b.t0 || a.t1 - b.t1);
  // its name: the one given, else the module and the prefix (none: the protocol)
  if (!p.name) p.name = join(p.scope.split('.').pop(), p.prefix.replace(/_$/, '') || p.label || PROTO[p.proto].label);
  // lanes: a transaction on the first of three lanes free at its start (more overlap: the third)
  const ends = [];
  for (const x of D.tx) { let l = ends.findIndex(e => e <= x.t0); if (l < 0) l = ends.length < 3 ? ends.length : 2;
    ends[l] = Math.max(ends[l] ?? -Infinity, x.t1); x.lane = l; }
  D.lanes = Math.max(1, ends.length); D.maxDur = D.tx.reduce((m, x) => Math.max(m, x.t1 - x.t0), 0);
  D.tip = x => `${x.tip}${x.lat != null ? ` · ${x.lat} cycle${x.lat === 1 ? '' : 's'}, ${when(x.t0)} → ${when(x.t1)}` : ' · not ended'}`;
  return D;
}
// one decoder per protocol: the transactions (D.tx) and the channels (D.ch) of a port from its signals sampled at the
// clock edges; the context is decode's: n edges E, c(k) the start of cycle k, V the columns, on / at a role at an
// edge, chan a new channel, beats the handshakes of a valid / ready pair, fin a transaction from cycle k0 to edge k1
const DECODE = {
  axi({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const lite = !p.sig.awlen && !p.sig.arlen;
    const aw = chan('AW'), w = chan('W'), b = chan('B'), ar = chan('AR'), r = chan('R');
    const AW = beats('awvalid', 'awready', ['awaddr', 'awid', 'awlen'], aw), Wb = beats('wvalid', 'wready', ['wdata', 'wlast', 'wid'], w);
    const B = beats('bvalid', 'bready', ['bresp', 'bid'], b), AR = beats('arvalid', 'arready', ['araddr', 'arid', 'arlen'], ar),
      R = beats('rvalid', 'rready', ['rdata', 'rresp', 'rlast', 'rid'], r);
    for (const x of AW) x.label = hex(x.awaddr); for (const x of Wb) x.label = hex(x.wdata);
      for (const x of B) x.label = ['OKAY', 'EXOKAY', 'SLVERR', 'DECERR'][num(x.bresp)] || hex(x.bresp);
    for (const x of AR) x.label = hex(x.araddr); for (const x of R) x.label = hex(x.rdata);
    // writes: the W bursts (to wlast, or len + 1 beats, or one) in order to the AWs, a B by ID to the oldest complete one;
    // AXI3 (WID): the beats of different IDs may interleave, so a burst per ID, to the AWs of that ID in their order
    const lenOf = a => (lite ? 1 : num(a && a.awlen) + 1), byId = !!p.sig.wid;
    const idOf = v => (byId ? num(v) : 0), awOf = new Map(), open = new Map(), done = new Map();
    for (const a of AW) { const i = idOf(a.awid); if (!awOf.has(i)) awOf.set(i, []); awOf.get(i).push(a); }
    for (const x of Wb) {
      const i = idOf(x.wid), cur = open.get(i) || [], fin1 = done.get(i) || [];
      cur.push(x); open.set(i, cur); done.set(i, fin1);
      if ((p.sig.wlast ? x.wlast === '1' : cur.length >= lenOf((awOf.get(i) || [])[fin1.length])) || lite) { fin1.push(cur); open.set(i, []); }
    }
    const writes = AW.map(a => { const i = idOf(a.awid); return { a, d: done.get(i) ? done.get(i)[awOf.get(i).indexOf(a)] || null : null, id: a.awid }; });
    for (const x of B) { const wr = writes.find(q => !q.b && q.d && (x.bid == null || q.id == null || q.id === x.bid) && q.d[q.d.length - 1].k <= x.k &&
      q.a.k <= x.k); if (wr) wr.b = x; }
    for (const q of writes) {
      const k0 = Math.min(q.a.k0, q.d ? q.d[0].k0 : q.a.k0), nb = q.d ? q.d.length : 0, rsp = q.b ? num(q.b.bresp) : 0;
      D.tx.push(fin({ kind: 'W', err: rsp >= 2, label: `W ${hex(q.a.awaddr)} ← ${q.d ? hex(q.d[0].wdata) : '?'}${nb > 1 ? ' ×' + nb : ''}`,
        tip: (`write ${hex(q.a.awaddr)}${q.id != null ? ' id ' + hex(q.id) : ''}: ` +
            `${q.d ? q.d.map(x => hex(x.wdata)).join(' ') : 'no data'}${q.b ? ' → ' + q.b.label : ' (no response)'}`),
        phases: [q.a, ...(q.d || []), ...(q.b ? [q.b] : [])] }, k0, q.b ? q.b.k : null));
    }
    // reads: R beats by ID to the oldest open AR, to rlast (or len + 1 beats)
    const reads = AR.map(a => ({ a, d: [], id: a.arid, want: lite ? 1 : num(a.arlen) + 1 }));
    for (const x of R) {
      const rd = reads.find(q => !q.done && q.a.k <= x.k && (x.rid == null || q.id == null || q.id === x.rid)); if (!rd) continue;
      rd.d.push(x); if ((p.sig.rlast ? x.rlast === '1' : rd.d.length >= rd.want) || lite) rd.done = true;
    }
    for (const q of reads) {
      const last = q.d[q.d.length - 1], err = q.d.some(x => num(x.rresp) >= 2);
      D.tx.push(fin({ kind: 'R', err, label: `R ${hex(q.a.araddr)} → ${q.d.length ? hex(q.d[0].rdata) : '?'}${q.d.length > 1 ? ' ×' + q.d.length : ''}`,
        tip: `read ${hex(q.a.araddr)}${q.id != null ? ' id ' + hex(q.id) : ''}: ${q.d.map(x => hex(x.rdata)).join(' ') || 'no data'}${err ? ' (error)' : ''}`,
          phases: [q.a, ...q.d] }, q.a.k0, q.done ? last.k : null));
    }
    p.label = p.sig.wid ? 'AXI3' : lite ? 'AXI4-Lite' : 'AXI4';
  },
  axis({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const s = p.proto === 'axis', ch = chan('beats');
    const bs = beats(s ? 'tvalid' : 'valid', s ? 'tready' : 'ready', s ? ['tdata', 'tlast'] : ['data', 'endofpacket', 'startofpacket'], ch);
    const last = x => (s ? x.tlast === '1' : x.endofpacket === '1'), hasLast = s ? !!p.sig.tlast : true;
    for (const x of bs) x.label = hex(s ? x.tdata : x.data);
    let pk = [];
    const flush = open => { if (!pk.length) return; D.tx.push(fin({ kind: 'P', label: `${pk.length === 1 ? '' : pk.length + ' beats '}${pk[0].label}`,
      tip: `${pk.length} beat${pk.length === 1 ? '' : 's'}: ${pk.slice(0, 16).map(x => x.label).join(' ')}${pk.length > 16 ? ' …' : ''}`, phases: pk.slice() },
      pk[0].k0, open ? null : pk[pk.length - 1].k)); pk = []; };
    for (const x of bs) { if (!s && x.startofpacket === '1') flush(true); pk.push(x); if (!hasLast || last(x)) flush(false); }
    flush(true);
  },
  apb({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const ph = chan('phase'); let ks = null;
    for (let k = 0; k < n; k++) {
      if (!on('psel', k)) { if (ks != null) aborted(k - 1); ks = null; continue; }
      if (!on('penable', k)) { ks = k; ph.beats.push({ t0: c(k), t1: E[k], label: 'setup' }); continue; }
      if (ks == null) ks = k;
      if (!on('pready', k, true)) continue;
      const wr = on('pwrite', k), d = at(wr ? 'pwdata' : 'prdata', k), err = on('pslverr', k), waits = k - ks - 1;
      ph.beats.push({ t0: E[ks], t1: E[k], label: waits ? `access +${waits}` : 'access' });
      D.tx.push(fin({ kind: wr ? 'W' : 'R', err, label: `${wr ? 'W' : 'R'} ${hex(at('paddr', k))} ${wr ? '←' : '→'} ${hex(d)}`,
        tip: (`${wr ? 'write' : 'read'} ${hex(at('paddr', k))} ${wr ? '←' : '→'} ${hex(d)}, ${waits} wait ` +
            `state${waits === 1 ? '' : 's'}${err ? ', PSLVERR' : ''}`) }, ks, k));
      ks = null;
    }
    // a transfer that does not end: PSEL dropped before PREADY (an error), or still waiting when the dump ends (open)
    function aborted(k1) {
      const wr = on('pwrite', ks), a = hex(at('paddr', ks)), d = wr ? ` ← ${hex(at('pwdata', ks))}` : ' → ?';
      D.tx.push(fin({ kind: wr ? 'W' : 'R', err: k1 != null, label: `${wr ? 'W' : 'R'} ${a}${d}`,
        tip: `${wr ? 'write' : 'read'} ${a}${d}: ${k1 != null ? 'PSEL dropped before PREADY' : 'no PREADY by the end of the dump'}` }, ks, k1));
    }
    if (ks != null) aborted(null);
  },
  ahb({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const ad = chan('address'), da = chan('data'), rdy = k => (p.sig.hready ? on('hready', k) : on('hreadyout', k, true));
    let dp = null, burst = null, as = null;
    const close = () => { if (!burst) return; const x = burst, wr = x.wr, nb = x.d.length;
      D.tx.push(fin({ kind: wr ? 'W' : 'R', err: x.err, label:
        `${wr ? 'W' : 'R'} ${hex(x.addr)} ${wr ? '←' : '→'} ${nb ? hex(x.d[0]) : '?'}${nb > 1 ? ' ×' + nb : ''}`,
        tip: `${wr ? 'write' : 'read'} ${hex(x.addr)}${nb > 1 ? ` burst of ${nb}` : ''}: ${x.d.map(hex).join(' ')}${x.err ? ' (ERROR)' : ''}` }, x.k0, x.k1));
          burst = null; };
    for (let k = 0; k < n; k++) {
      const tr = num(at('htrans', k)), act = (tr === 2 || tr === 3) && on('hsel', k, true);
      if (act && as == null) as = k;
      if (rdy(k) && dp) {   // the data phase of the address before ends here
        const v = at(dp.wr ? 'hwdata' : 'hrdata', k), err = num(at('hresp', k)) === 1;
        da.beats.push({ t0: E[dp.k], t1: E[k], label: hex(v) });
        if (burst) { burst.d.push(v); burst.k1 = k; burst.err = burst.err || err; }
        dp = null;
      }
      if (rdy(k) && act) {   // an address phase accepted: NONSEQ starts a transfer, SEQ goes on with it
        if (tr === 2 || !burst) { close(); burst = { addr: at('haddr', k), wr: on('hwrite', k), d: [], k0: as, k1: null, err: false }; }
        ad.beats.push({ t0: c(as), t1: E[k], label: hex(at('haddr', k)) });
        dp = { k, wr: on('hwrite', k) }; as = null;
      } else if (!act) { as = null; if (!dp) close(); }
    }
    close();
  },
  avmm({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const cmd = chan('command'), rsp = chan('response'), pend = []; let ks = null;
    for (let k = 0; k < n; k++) {
      const rd = on('read', k), wr = on('write', k);
      if (V.readdatavalid && on('readdatavalid', k) && pend.length) {   // a read beat to the oldest read
        const q = pend[0], v = at('readdata', k); q.d.push(v); rsp.beats.push({ t0: c(k), t1: E[k], label: hex(v) });
        if (q.d.length >= q.want) { pend.shift(); D.tx.push(fin({ kind: 'R', label:
          `R ${hex(q.addr)} → ${hex(q.d[0])}${q.d.length > 1 ? ' ×' + q.d.length : ''}`, tip: `read ${hex(q.addr)}: ${q.d.map(hex).join(' ')}` }, q.k0, k)); }
      }
      if (!rd && !wr) { ks = null; continue; }
      if (ks == null) ks = k;
      if (on('waitrequest', k)) continue;
      const a = at('address', k);
      cmd.beats.push({ t0: c(ks), t1: E[k], label: `${wr ? 'W' : 'R'} ${hex(a)}` });
      if (wr) D.tx.push(fin({ kind: 'W', label: `W ${hex(a)} ← ${hex(at('writedata', k))}`, tip: `write ${hex(a)} ← ${hex(at('writedata', k))}` }, ks, k));
      else if (V.readdatavalid) pend.push({ addr: a, k0: ks, d: [], want: Math.max(1, num(at('burstcount', k)) || 1) });
      else D.tx.push(fin({ kind: 'R', label: `R ${hex(a)} → ${hex(at('readdata', k))}`, tip: `read ${hex(a)} → ${hex(at('readdata', k))}` }, ks, k));
      ks = null;
    }
    for (const q of pend) D.tx.push(fin({ kind: 'R', label: `R ${hex(q.addr)} → ?`, tip: `read ${hex(q.addr)}: no data yet` }, q.k0, null));
  },
  wb({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const slave = /_i$/.test(leafOf(p.sig.cyc)), wd = slave ? 'dat_i' : 'dat_o', rdn = slave ? 'dat_o' : 'dat_i';
    const req = chan('request'), ack = chan('ack'), pipe = !!p.sig.stall, pend = []; let ks = null;
    const done = k => on('ack', k) || on('err', k) || on('rty', k);
    // requests without their ack: CYC dropped (an error at k1), or the dump ended (open)
    const unacked = (qs, k1) => { for (const q of qs) D.tx.push(fin({ kind: q.wr ? 'W' : 'R', err: k1 != null,
      label: `${q.wr ? 'W' : 'R'} ${hex(q.a)} ${q.wr ? '← ' + hex(q.d) : '→ ?'}`,
      tip: `${q.wr ? 'write' : 'read'} ${hex(q.a)}: ${q.stalled ? 'stalled, never accepted' : 'no ack'}` +
        (k1 != null ? ', CYC dropped' : ' by the end of the dump') },
      q.k0, k1)); };
    const cur = () => ({ a: at('adr', ks), wr: on('we', ks), d: at(wd, ks), k0: ks, stalled: pipe });   // the strobe waiting since ks
    for (let k = 0; k < n; k++) {
      if (!on('cyc', k)) { unacked(pend.splice(0), k - 1); if (ks != null) unacked([cur()], k - 1); ks = null; continue; }
      if (pipe) {   // pipelined: a request goes when not stalled; the acks in order (a request and its ack in one cycle too)
        if (on('stb', k)) { if (ks == null) ks = k;
          if (!on('stall', k)) { const wr = on('we', k), a = at('adr', k); req.beats.push({ t0: c(ks), t1: E[k], label: `${wr ? 'W' : 'R'} ${hex(a)}` });
            pend.push({ a, wr, d: at(wd, k), k0: ks }); ks = null; } } else ks = null;
        if (done(k) && pend.length) {
          const q = pend.shift(), v = q.wr ? q.d : at(rdn, k), err = !on('ack', k);
          ack.beats.push({ t0: c(k), t1: E[k], label: on('ack', k) ? 'ack' : on('err', k) ? 'err' : 'rty' });
          D.tx.push(fin({ kind: q.wr ? 'W' : 'R', err, label: `${q.wr ? 'W' : 'R'} ${hex(q.a)} ${q.wr ? '←' : '→'} ${hex(v)}`,
            tip: `${q.wr ? 'write' : 'read'} ${hex(q.a)} ${q.wr ? '←' : '→'} ${hex(v)}${err ? ' (' + (on('err', k) ? 'ERR' : 'RTY') + ')' : ''}` }, q.k0, k));
        }
        continue;
      }
      if (!on('stb', k)) { ks = null; continue; }
      if (ks == null) ks = k;
      const wr = on('we', k), a = at('adr', k);
      if (!done(k)) continue;   // classic: the strobe until ack / err / rty
      const v = at(wr ? wd : rdn, k), err = !on('ack', k);
      req.beats.push({ t0: c(ks), t1: E[k], label: `${wr ? 'W' : 'R'} ${hex(a)}` });
      D.tx.push(fin({ kind: wr ? 'W' : 'R', err, label: `${wr ? 'W' : 'R'} ${hex(a)} ${wr ? '←' : '→'} ${hex(v)}`,
        tip: (`${wr ? 'write' : 'read'} ${hex(a)} ${wr ? '←' : '→'} ${hex(v)}, ${k - ks} wait ` +
          `state${k - ks === 1 ? '' : 's'}${err ? ' (' + (on('err', k) ? 'ERR' : 'RTY') + ')' : ''}`) }, ks, k));
      ks = null;
    }
    unacked(pend, null); if (ks != null) unacked([cur()], null);
    p.label = pipe ? 'Wishbone pipelined' : 'Wishbone';
  },
  obi({ p, n, E, c, V, on, at, D, chan, beats, fin }) {
    const A = beats('req', 'gnt', ['addr', 'we', 'wdata'], chan('request')), Rb = beats('rvalid', 'rready', ['rdata', 'err'], chan('response'));
    for (const x of A) x.label = `${x.we === '1' ? 'W' : 'R'} ${hex(x.addr)}`; for (const x of Rb) x.label = hex(x.rdata);
    let i = 0;
    for (const x of Rb) {   // responses in the order of the requests
      const q = A[i]; if (!q || q.k > x.k) continue;
      i++;
      const wr = q.we === '1', v = wr ? q.wdata : x.rdata;
      D.tx.push(fin({ kind: wr ? 'W' : 'R', err: x.err === '1', label: `${wr ? 'W' : 'R'} ${hex(q.addr)} ${wr ? '←' : '→'} ${hex(v)}`,
        tip: `${wr ? 'write' : 'read'} ${hex(q.addr)} ${wr ? '←' : '→'} ${hex(v)}${x.err === '1' ? ' (err)' : ''}` }, q.k0, x.k));
    }
    for (; i < A.length; i++) D.tx.push(fin({ kind: A[i].we === '1' ? 'W' : 'R', label: A[i].label + ' …', tip: 'no response yet' }, A[i].k0, null));
  },
};
DECODE.avst = DECODE.axis;
const summary = D => {
  const k = t => D.tx.filter(x => x.kind === t).length, e = D.tx.filter(x => x.err).length, r = k('R'), w = k('W'), pk = k('P');
  return [r && `${r} R`, w && `${w} W`, pk && `${pk} packet${pk === 1 ? '' : 's'}`, e && `${e} err`].filter(Boolean).join(' · ') || 'no transfers';
};

/* ---------------- drawing ---------------- */
const COL = { W: 'bus-w', R: 'bus-r', P: 'bus-w', T: 'bus-r' };
W.registerTokens && W.registerTokens({ 'bus-w': '--bus-write', 'bus-r': '--bus-read', 'bus-e': '--bus-error', 'bus-ch': '--bus-channel' });
// the settings of this plugin (wavelens.config.js lists them): the ports found by their names, ports of your own
W.registerDefaults && W.registerDefaults({ busDetect: true, buses: null });
// boxes from t0 to t1 in [y, y + h], a label inside when it fits; -> hits [x0, x1, y0, y1, item]
function boxes(P, items, { y, h, X, tA, tB, xL, xR }, maxDur, colOf, sel) {
  const hits = [], cx = x => Math.min(Math.max(x, xL - 2), xR + 2);
  const i0 = Math.max(0, U.lastBefore(items.length, i => items[i].t0, tA - maxDur, true));
  let lastX = -1e9;
  for (let i = i0; i < items.length && items[i].t0 <= tB; i++) {
    const it = items[i]; if (it.t1 < tA) continue;
    const a = cx(X(it.t0)), b = Math.max(cx(X(it.t1)), a + 2), col = colOf(it), yy = it.y != null ? y + it.y : y, hh = it.h != null ? it.h : h;
    if (b < lastX + 0.5 && b - a < 2) continue;   // crowded: one mark per pixel
    P.rect(a, yy, b - a, hh, col, it === sel ? 0.45 : 0.18);
    P.path([['M', a, yy], ['L', b, yy], ['L', b, yy + hh], ['L', a, yy + hh], ['Z']], { stroke: col, w: it === sel ? 2 : 1, dash: it.open ? [3, 2] : null });
    if (b - a > 24 && hh >= 10) { const t = it.label || '', lab = { size: Math.min(10.5, hh - 2) }; let s = t;
      while (s && P.measure(s, lab) > b - a - 6) s = s.slice(0, -2); if (s) P.text((a + b) / 2, yy + hh / 2, s === t ? s : s + '…',
      Object.assign({ anchor: 'middle', fill: 'fg' }, lab)); }
    hits.push([a, b, yy - y, yy - y + hh, it]); lastX = b;
  }
  return hits;
}
// the label of the last item (sorted by t0, none longer than maxDur) that covers time t: a search, not a pass over all
const covering = (items, t, maxDur) => {
  for (let i = U.lastBefore(items.length, k => items[k].t0, t, false); i >= 0 && items[i].t0 >= t - maxDur; i--) if (items[i].t1 >= t) return items[i].label;
  return '';
};
const hitAt = (hits, x, y) => hits.filter(([a, b, y0, y1]) => x >= a - 1 && x <= b + 1 && y >= y0 - 1 && y <= y1 + 1).pop();
// the rows of a port: its group (the transactions on its header) and, open, the transactions row and a row per channel
function portRows(st, p, D, opt) {
  const S = opt.S, rh = S.rowHeight || 26, base = opt.base;
  if (!st.gid) st.gid = W.rowId();
  const g = st.g || (st.g = { type: 'group', id: st.gid });
  const colOf = x => (x.err ? 'bus-e' : COL[x.kind] || 'bus-r'), sel = () => opt.sel && opt.sel();
  const name = `⇄ ${p.name} · ${p.label || PROTO[p.proto].label} · ${summary(D)}`, full = `${p.key}`;
  const txDraw = (lanes, pad) => function (P, a) {
    const lh = (a.h - pad * 2) / lanes; for (const x of D.tx) { x.y = pad + Math.min(x.lane, lanes - 1) * lh; x.h = lh - 1; }
    this.hits = boxes(P, D.tx, a, D.maxDur, colOf, sel());
  };
  const click = function (x, y) { const h = hitAt(this.hits || [], x, y); if (!h) return false; opt.pick(h[4]); return true; };
  const tip = function (x, y) { const h = hitAt(this.hits || [], x, y); return h ? D.tip(h[4]) : ''; };
  const value = t => covering(D.tx, t, D.maxDur);
  Object.assign(g, { name, full, path: full, anc: base.anc, depth: base.depth, cls: 'bus-g',
    title: `${PROTO[p.proto].label} port ${p.prefix || ''} in ${p.scope || '(top)'}, sampled at the rising edges of ${p.clk.name}`,
    draw: opt.svg ? null : function (P, a) { if (opt.folded()) txDraw(D.lanes, 3).call(this, P, a); else this.hits = []; }, click, tip,
      legend: [{ text: `⇄ ${p.name} (${p.label || PROTO[p.proto].label}): ${summary(D)}`, bold: true }] });
  const kid = { anc: base.anc.concat(st.gid), depth: base.depth + 1 };
  const tx = st.tx || (st.tx = { type: 'sig', tr: [] });
  Object.assign(tx, kid, { name: 'transactions', full: full + '/tx', cls: 'bus-lane', height: Math.max(rh, D.lanes * 16 + 6), draw: txDraw(D.lanes, 3), click,
    tip, value });
  st.ch = st.ch || {};
  const chs = opt.svg ? [] : D.ch.map(ch => {
    const r = st.ch[ch.name] || (st.ch[ch.name] = { type: 'sig', tr: [] });
    ch.beats.sort((a, b) => a.t0 - b.t0); const md = ch.beats.reduce((m, x) => Math.max(m, x.t1 - x.t0), 0);
    return Object.assign(r, kid, { name: ch.name, full: `${full}/${ch.name}`, cls: 'bus-ch', height: rh,
      draw(P, a) { for (const x of ch.beats) { x.y = 5; x.h = a.h - 10; } this.hits = boxes(P, ch.beats, a, md, () => 'bus-ch', null); },
      tip(x, y) { const h = hitAt(this.hits || [], x, y); return h ? `${ch.name}: ${h[4].label} (${opt.when(h[4].t0)} → ${opt.when(h[4].t1)})` : ''; },
      value: t => covering(ch.beats, t, md) });
  });
  return [g, tx, ...chs];
}

/* ---------------- a viewer's buses ---------------- */
class Buses {
  constructor(v) {
    this.v = v; v.buses = this; this.st = new Map(); this.sel = null;
    v.extraRows.push(g => this.rowsFor(g));
    v.addKey(']t', () => this.step(1), ']t [t next / previous bus transaction').addKey('[t', () => this.step(-1));
    v.root.addEventListener('wavelens:reset', () => { this.sel = null; });
    // the selected transaction in a saved viewer state: its port and its start
    v.extraState.push({ key: 'bus', get: () => (this.sel && this.selPort ? { port: this.selPort.key, t0: this.sel.t0 } : undefined),
      set: s => { const p = s && this.list().find(q => q.key === s.port), x = p && p.D.tx.find(q => q.t0 === s.t0); if (x) this.select(p, x); } });
    v.root.addEventListener('wavelens:settings', () => { this.ports = null; });
  }
  // the ports and their transactions, found once (again when the settings change)
  list() {
    if (!this.ports) {
      const v = this.v;
      this.ports = findPorts(v.M, v.S).map(p => { p.D = decode(p, v); return p; });
    }
    return this.ports;
  }
  rowsFor(g) {
    const k = g ? g.id : -1, out = [];
    for (const p of this.list()) {
      if ((p.g ? p.g.id : -1) !== k) continue;
      const st = this.st.get(p.key) || {}, first = !st.gid; this.st.set(p.key, st);
      out.push(...portRows(st, p, p.D, { S: this.v.S, folded: () => this.v.collapsed.has(st.gid),
        base: { anc: g ? g.anc.concat(g.id) : [], depth: g ? g.depth + 1 : 0 }, when: t => this.v.when(t),
        sel: () => this.sel, pick: x => this.select(p, x) }));
      if (first) this.v.fold(st.gid, true, true);   // folded at first: the transactions on its header row
    }
    return out;
  }
  // a transaction: the cursor at its start, its range measured, the port's signals highlighted
  select(p, x) {
    const v = this.v; this.sel = x; this.selPort = p;
    v.extraPicks = new Map(Object.values(p.sig).concat(p.clk).map(r => [r, 'hl8']));
    v.moveTo(x.t0, x.t0 < v.t0 || x.t1 > v.t0 + v.span ? { left: x.t0 - v.span * 0.2 } : {});
    v.renderNames(); v.setRange(x.t0, x.t1);
    v.toast(`${p.name}: ${x.label}${x.lat != null ? ` · ${x.lat} cycles` : ''}${x.err ? ' · error' : ''}`);
  }
  // ]t / [t: the next / previous transaction of every port from the cursor (round the ends)
  step(dir) {
    const all = this.list().flatMap(p => p.D.tx.map(x => [p, x])).sort((a, b) => a[1].t0 - b[1].t0);
      if (!all.length) { this.v.toast('no bus transaction'); return; }
    const [p, x] = all[U.stepTo(all.map(([, q]) => q.t0), this.v.cursor, dir)], g = this.st.get(p.key);
    this.select(p, x);
    if (g && g.g) this.v.centerRow(this.v.collapsed.has(g.gid) ? g.g : g.tx);
  }
}
W.plugin(v => new Buses(v));

/* ---------------- static SVG: the groups with their transactions ---------------- */
const SVGST = new WeakMap();
if (W.svgPlugin) W.svgPlugin((M, S) => {
  if (S.busDetect === false && !(Array.isArray(S.buses) && S.buses.length)) return null;
  let k = SVGST.get(M.src);
  if (!k) SVGST.set(M.src, k = { ports: findPorts(M, S).map(p => { p.D = decode(p, null); return p; }), st: new Map() });
  if (!k.ports.length) return null;
  return [g => k.ports.filter(p => (p.g ? p.g.id : -1) === (g ? g.id : -1)).flatMap(p => {
    const st = k.st.get(p.key) || {}; k.st.set(p.key, st);
    return portRows(st, p, p.D, { S, svg: true, base: { anc: g ? g.anc.concat(g.id) : [], depth: g ? g.depth + 1 : 0 }, when: String, sel: () => null,
      pick: () => {} });
  })];
});
G.WaveBus = { PROTO, findPorts, decode, summary, rolesOf, byScope, clockOf, ANCHORS };
})();
