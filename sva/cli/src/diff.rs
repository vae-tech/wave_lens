//! `sva diff A B`: two dumps of the same test compared change by change, the way the viewer's Compare… compares them,
//! without a page and without either dump in memory: each is streamed by wellen in a thread of its own, one time step
//! at a time through a bounded channel, and the main thread merges the two by time (B's times less --offset). What it
//! holds is the current value of each compared signal on either side.
//!
//! A signal of A is paired with the one of B at its path after --map (the longest prefix of a scope pair, or an exact
//! pair of paths; two dumps with one top scope each, named apart, pair their tops by themselves). Values compare as the
//! viewer's `cmpKey`: bit for bit (x and z apart, x before the first value), a real as a number (inf, -inf, nan three
//! values), a string as its text; a pair of another width or kind differs over the whole window. A change is a time a
//! compared signal changes in A or in B (both at once: one); it differs when the two values differ after it, and so
//! does the start of the window, or of a segment, where they differ already.
//!
//! --segment SIGNAL cuts the window at each change of that signal in A (a test case number): the counts per segment.
//! --align compares segment k of B, which starts at the k-th change of the signal in B, with segment k of A, on the
//! length both have: the same case run alone and inside a group of cases.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::io::{BufReader, Read, Seek, SeekFrom};
use std::process::ExitCode;
use std::sync::mpsc::{sync_channel, Receiver};
use std::thread::JoinHandle;
use serde_json::{json, Value};
use wellen::stream::{self, Filter, StreamError, StreamingWaveform};
use wellen::{Hierarchy, LoadOptions, SignalEncoding, SignalRef, SignalValueRef, VarRef, VarType};

/// A line on stdout; a closed stdout ends the output, not the run (`sva diff … | head`).
macro_rules! outln {
    ($($t:tt)*) => { crate::write_out(format_args!($($t)*), true) };
}

const USAGE: &str = "usage: sva diff A B [--signals PAT,...] [--signals-from FILE] [--scope S] [--from T] [--to T] [--offset [-]T] [--map A=B ...]
                [--segment SIGNAL [--align]] [--json [FILE|-]] [--junit FILE] [--limit N] [--spans N] [--quiet]
Two dumps (VCD or FST) compared change by change, streamed: neither is held in memory. A signal of A pairs with the one
of B at its path; --map A=B renames A's paths for B: a scope (the longest one that matches) or one signal's path (an
exact pair wins); no `=` in a name. Two dumps with one top scope each, named apart, pair their tops without a map.
--signals: paths (under --scope) or * ? patterns of A's paths; default every signal of A that B has (under --scope).
--signals-from FILE (- stdin): the paths of A to compare, one a line (a page's rows): one not in A, or without its pair
in B, is listed (not_in_a, only_a), not an error.
--from/--to: the window in A's time (default: the time both dumps cover), the changes at both ends included;
--offset: B's time is A's time plus this. --segment: the counts per segment, a segment from each change of that signal
in A; --align: segment k of B starts at the k-th change of the signal in B and compares on the length both have (the
rest of a longer segment is not compared). --json: the result as JSON (times in ps) to FILE, or stdout instead of the
text; --junit: a JUnit XML report, a test case per segment. --limit: differences listed (default 20, 0 all); --spans:
per signal its stretches that differ in the JSON (default 0: none). TIME is a number with a unit (100ns, 2.5us; ps without one).
Exit status: 0 the dumps are equal over the window; 1 they differ; 2 usage, a dump that does not read, a signal not
in it, no time in common.";

/// A signal's values as compared: bits of a width, a real, a text.
#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    Bits(u32),
    Real,
    Text,
}

impl Kind {
    fn of(h: &Hierarchy, v: VarRef) -> Kind {
        match h[v].signal_encoding(h) {
            SignalEncoding::String => Kind::Text,
            SignalEncoding::Real => Kind::Real,
            SignalEncoding::BitVector(w) => Kind::Bits(w),
        }
    }
    fn word(self) -> String {
        match self {
            Kind::Bits(w) => format!("{w} bits"),
            Kind::Real => "real".into(),
            Kind::Text => "string".into(),
        }
    }
    /// The value before the first one: x on every bit; a real or a text none of its values.
    fn unknown(self) -> String {
        match self {
            Kind::Bits(w) => "x".repeat(w.max(1) as usize),
            _ => "\u{0}?".into(),
        }
    }
}

/// A value as compared (and shown): the bits at the variable's width (a shorter one extended as VCD extends it), a real
/// as `%.16g` (0 for -0), a text as it is; None for an event.
fn key(kind: Kind, v: SignalValueRef) -> Option<String> {
    match v {
        SignalValueRef::Event => None,
        SignalValueRef::Real(x) => Some(if x == 0.0 { "0".into() } else { crate::vcd::real(x) }),
        SignalValueRef::String(s) => Some(s.to_string()),
        SignalValueRef::BitVec(_) => {
            let b = v.to_bit_string().unwrap_or_default();
            Some(match kind {
                Kind::Bits(w) if b.len() < w as usize => {
                    let fill = match b.as_bytes().first() {
                        Some(c @ (b'x' | b'X' | b'z' | b'Z')) => *c as char,
                        _ => '0',
                    };
                    let mut o: String = std::iter::repeat_n(fill, w as usize - b.len()).collect();
                    o.push_str(&b);
                    o
                }
                _ => b,
            })
        }
    }
}

/// A value as the output shows it: a real or a text never given as `-`.
fn shown(v: &str) -> &str {
    if v == "\u{0}?" { "-" } else { v }
}

/// A value as the text shows it: a bus of known bits in hex (`0xcafe0001`; the JSON keeps the bits), else as `shown`.
fn pretty(v: &str) -> String {
    if v.len() > 4 && v.bytes().all(|c| c == b'0' || c == b'1') {
        let pad = (4 - v.len() % 4) % 4;
        let bits: Vec<u8> = std::iter::repeat_n(b'0', pad).chain(v.bytes()).collect();
        let hex: String = bits.chunks(4).map(|c| char::from_digit(c.iter().fold(0, |n, b| n * 2 + u32::from(b - b'0')), 16).unwrap()).collect();
        return format!("0x{hex}");
    }
    shown(v).to_string()
}

/// `*` and `?` over a whole path.
pub(crate) fn glob(p: &[u8], s: &[u8]) -> bool {
    match (p.first(), s.first()) {
        (None, None) => true,
        (Some(b'*'), _) => glob(&p[1..], s) || (!s.is_empty() && glob(p, &s[1..])),
        (Some(b'?'), Some(_)) => glob(&p[1..], &s[1..]),
        (Some(a), Some(b)) if a == b => glob(&p[1..], &s[1..]),
        _ => false,
    }
}

#[derive(Default)]
struct Opt {
    a: String,
    b: String,
    signals: Vec<String>,
    signals_from: Option<String>,
    scope: String,
    from: Option<u64>,
    to: Option<u64>,
    offset: i64,
    map: Vec<(String, String)>,
    segment: Option<String>,
    align: bool,
    json: Option<String>,
    junit: Option<String>,
    limit: usize,
    spans: usize,
    quiet: bool,
}

fn opts(args: &[String]) -> Result<Opt, String> {
    let mut o = Opt { limit: 20, ..Opt::default() };
    let mut files = Vec::new();
    let mut i = 0;
    let val = |i: &mut usize, f: &str| -> Result<String, String> {
        *i += 1;
        args.get(*i).cloned().ok_or_else(|| format!("{f} needs a value\n{USAGE}"))
    };
    while i < args.len() {
        let a = args[i].as_str();
        match a {
            "-h" | "--help" => return Err(USAGE.into()),
            "--signals" => o.signals.extend(val(&mut i, a)?.split(',').map(str::trim).filter(|s| !s.is_empty()).map(String::from)),
            "--scope" => o.scope = val(&mut i, a)?.trim_end_matches('.').to_string(),
            "--signals-from" => o.signals_from = Some(val(&mut i, a)?),
            "--from" => o.from = Some(crate::time(&val(&mut i, a)?)?),
            "--to" => o.to = Some(crate::time(&val(&mut i, a)?)?),
            "--offset" => {
                let v = val(&mut i, a)?;
                let (neg, t) = match v.strip_prefix('-') {
                    Some(t) => (true, t),
                    None => (false, v.strip_prefix('+').unwrap_or(&v)),
                };
                let t = crate::time(t)? as i64;
                o.offset = if neg { -t } else { t };
            }
            "--map" => {
                let v = val(&mut i, a)?;
                let (x, y) = v.split_once('=').filter(|(x, y)| !x.is_empty() && !y.is_empty()).ok_or_else(|| format!("--map {v}: A=B, a path of A and its path in B"))?;
                o.map.push((x.trim().to_string(), y.trim().to_string()));
            }
            "--segment" => o.segment = Some(val(&mut i, a)?),
            "--align" => o.align = true,
            "--json" => {
                // a file only when it is one: `-`, or a name ending with .json (else the dumps follow)
                let f = args.get(i + 1).filter(|f| f.as_str() == "-" || f.ends_with(".json"));
                o.json = Some(f.cloned().unwrap_or_else(|| "-".into()));
                if f.is_some() {
                    i += 1;
                }
            }
            "--junit" => o.junit = Some(val(&mut i, a)?),
            "--limit" => o.limit = crate::count(&val(&mut i, a)?, "--limit")? as usize,
            "--spans" => o.spans = crate::count(&val(&mut i, a)?, "--spans")? as usize,
            "--quiet" | "-q" => o.quiet = true,
            s if s.starts_with('-') && s.len() > 1 => return Err(format!("unknown option {s}\n{USAGE}")),
            s => files.push(s.to_string()),
        }
        i += 1;
    }
    let [a, b] = <[String; 2]>::try_from(files).map_err(|f| format!("two dumps, A and B ({} given)\n{USAGE}", f.len()))?;
    (o.a, o.b) = (a, b);
    if o.align && o.segment.is_none() {
        return Err("--align aligns the segments of --segment: give --segment SIGNAL".into());
    }
    if o.align && o.offset != 0 {
        return Err("--align and --offset, not together: --align sets B's offset at each segment".into());
    }
    if let (Some(f), Some(t)) = (o.from, o.to) {
        if t < f {
            return Err(format!("--to {} is before --from {}", crate::ns(t), crate::ns(f)));
        }
    }
    Ok(o)
}

// ------------------------------------------------------------------------------------------------------------ dumps

/// One dump: its streaming reader (the header read), its time unit in ps, its end, its size.
struct Dump {
    file: String,
    w: StreamingWaveform<BufReader<std::fs::File>>,
    ps: f64,
    end: Option<i64>,
    bytes: u64,
    _tmp: Option<crate::fst::TempFst>,
}

/// A time of the dump in ps.
fn to_ps(t: u64, ps: f64) -> i64 {
    if ps.fract() == 0.0 { (t as i64).saturating_mul(ps as i64) } else { (t as f64 * ps).round() as i64 }
}

/// The last time of a dump: an FST's header (its last block), a VCD's last `#time` (its tail read); None when there
/// is none to read there (then the last change counts).
pub(crate) fn end_time(path: &str) -> Option<u64> {
    let mut f = BufReader::new(std::fs::File::open(path).ok()?);
    if fst_reader::is_fst_file(&mut f) {
        let r = fst_reader::FstReader::open_and_read_time_table(f).ok()?;
        let last = r.get_time_table().and_then(|t| t.last().copied()).unwrap_or(0);
        return Some(r.get_header().end_time.max(last));
    }
    let len = f.seek(SeekFrom::End(0)).ok()?;
    let k = len.min(1 << 16);
    f.seek(SeekFrom::Start(len - k)).ok()?;
    let mut tail = Vec::new();
    f.read_to_end(&mut tail).ok()?;
    let text = String::from_utf8_lossy(&tail);
    let mut words = text.split_ascii_whitespace().collect::<Vec<_>>();
    if k < len && !words.is_empty() {
        words.remove(0);   // the first word may be cut
    }
    words.iter().rev().find_map(|w| w.strip_prefix('#').and_then(|n| n.parse().ok()))
}

fn open(file: &str, quiet: bool) -> Result<Dump, String> {
    let bytes = std::fs::metadata(file).map_err(|e| format!("{file}: {e}"))?.len();
    // a VCD whose vectors are glued to their codes (Questa 2023's integers): wellen stops at one, its FST is read instead
    let tmp = crate::fst::glued_fst(file)?;
    if tmp.is_some() && !quiet {
        eprintln!("sva: {file}: values written without b, glued to their codes (Questa 2023's integers): read through an FST of it");
    }
    let path = tmp.as_ref().map_or(file.to_string(), |g| g.0.to_string_lossy().into_owned());
    let w = stream::read_from_file(&path, &LoadOptions::default()).map_err(|e| format!("{file}: {e}"))?;
    let h = w.hierarchy();
    let ps = h.timescale().and_then(|t| t.unit.to_exponent().map(|e| t.factor as f64 * 10f64.powi(e as i32 + 12))).unwrap_or(1.0);
    let end = end_time(&path).map(|t| to_ps(t, ps));
    Ok(Dump { file: file.to_string(), w, ps, end, bytes, _tmp: tmp })
}

/// A time step of one dump: its time in ps, the changes (index into the side's signals, value).
type Step = (i64, Vec<(u32, String)>);

/// The reader of one dump in a thread of its own: its changes of `refs`, a time step at a time, into a bounded channel.
/// It stops when the receiver is gone (the merge had enough).
fn spawn(d: Dump, refs: Vec<SignalRef>, kinds: Vec<Kind>) -> (Receiver<Result<Step, String>>, JoinHandle<()>, Option<crate::fst::TempFst>) {
    let (tx, rx) = sync_channel::<Result<Step, String>>(64);
    let Dump { file, mut w, ps, _tmp, .. } = d;
    let h = std::thread::spawn(move || {
        let mut at = vec![u32::MAX; refs.iter().map(|r| r.index() + 1).max().unwrap_or(0)];
        for (i, r) in refs.iter().enumerate() {
            at[r.index()] = i as u32;
        }
        let mut now: Option<u64> = None;
        let mut batch: Vec<(u32, String)> = Vec::new();
        let r = w.stream_changes(Filter::include_signals(&refs), |t, s, v| -> Result<(), ()> {
            let i = at.get(s.index()).copied().unwrap_or(u32::MAX);
            if i == u32::MAX {
                return Ok(());
            }
            if now != Some(t) {
                if let Some(n) = now.filter(|_| !batch.is_empty()) {
                    tx.send(Ok((to_ps(n, ps), std::mem::take(&mut batch)))).map_err(|_| ())?;
                }
                now = Some(t);
            }
            if let Some(k) = key(kinds[i as usize], v) {
                batch.push((i, k));
            }
            Ok(())
        });
        match r {
            Ok(()) => {
                if let Some(n) = now.filter(|_| !batch.is_empty()) {
                    let _ = tx.send(Ok((to_ps(n, ps), batch)));
                }
            }
            Err(StreamError::Callback(())) => {}
            Err(StreamError::Wellen(e)) => {
                let _ = tx.send(Err(format!("{file}: {e}")));
            }
        }
    });
    (rx, h, _tmp)
}

/// The receiving end of one dump's reader: the next time step held until the merge takes it.
struct Stream {
    rx: Receiver<Result<Step, String>>,
    join: Option<JoinHandle<()>>,
    next: Option<Step>,
    done: bool,
    last: Option<i64>,
    file: String,
}

impl Stream {
    /// The next time step into `next` (none: the dump is read to its end); a reader's error or panic is an error.
    fn fill(&mut self) -> Result<(), String> {
        if self.next.is_some() || self.done {
            return Ok(());
        }
        match self.rx.recv() {
            Ok(Ok(s)) => {
                self.last = Some(s.0);
                self.next = Some(s);
            }
            Ok(Err(e)) => return Err(e),
            Err(_) => {
                self.done = true;
                if let Some(j) = self.join.take() {
                    if j.join().is_err() {
                        return Err(format!("{}: the dump does not read", self.file));
                    }
                }
            }
        }
        Ok(())
    }
    fn peek(&self) -> Option<i64> {
        self.next.as_ref().map(|s| s.0)
    }
    fn take(&mut self) -> Vec<(u32, String)> {
        self.next.take().map(|s| s.1).unwrap_or_default()
    }
}

// ------------------------------------------------------------------------------------------------------------ pairs

/// A rule of --map, or the tops paired by themselves; the signals it paired.
struct Rule {
    a: String,
    b: String,
    auto: bool,
    used: u64,
}

/// One compared pair: A's variable and B's, their kinds, the indices of their signals among each side's streamed
/// ones, and what was counted.
struct Pair {
    a: String,
    b: String,
    kind: Kind,
    other: Option<String>,
    ia: u32,
    ib: u32,
    changes: u64,
    differ: u64,
    first: Option<Diff>,
    open: Option<i64>,
    spans: Vec<(i64, i64)>,
    more: u64,
}

#[derive(Clone)]
struct Diff {
    t: i64,
    pair: usize,
    a: String,
    b: String,
}

/// Every variable of a dump but events: path -> variable (the first one of a path seen twice), and the paths in order.
fn vars(h: &Hierarchy) -> (HashMap<String, VarRef>, Vec<(String, VarRef)>) {
    let mut by = HashMap::new();
    let mut list = Vec::new();
    for v in h.all_vars() {
        if matches!(h[v].var_type(), VarType::Event | VarType::EventParameter) {
            continue;
        }
        let p = h[v].full_name(h);
        if by.contains_key(&p) {
            continue;
        }
        by.insert(p.clone(), v);
        list.push((p, v));
    }
    (by, list)
}

/// `p` of A in B, by the rules (an exact pair, else the longest scope that is a prefix of it) -> its path and the rule.
fn mapped(p: &str, rules: &[Rule]) -> Option<(String, usize)> {
    if let Some(k) = rules.iter().position(|r| !r.auto && r.a == p) {
        return Some((rules[k].b.clone(), k));
    }
    let under = |r: &Rule| p.len() > r.a.len() && p.starts_with(&r.a) && p.as_bytes()[r.a.len()] == b'.';
    let k = rules.iter().enumerate().filter(|(_, r)| under(r)).max_by_key(|(_, r)| (r.a.len(), !r.auto)).map(|(k, _)| k)?;
    Some((format!("{}{}", rules[k].b, &p[rules[k].a.len()..]), k))
}

fn tops(h: &Hierarchy) -> Vec<String> {
    h.scopes().map(|s| h[s].name(h).to_string()).collect()
}

// ------------------------------------------------------------------------------------------------------------ merge

struct Segment {
    n: u64,
    value: String,
    from: i64,
    to: i64,
    b_from: Option<i64>,
    compared_to: Option<i64>,
    changes: u64,
    differ: u64,
    first: Option<Diff>,
    diffs: Vec<Diff>,
}

/// The state of the merge: the current values of both sides, the pairs, the segments, what was counted.
struct Merge {
    pairs: Vec<Pair>,
    va: Vec<String>,
    vb: Vec<String>,
    by_a: Vec<Vec<u32>>,
    by_b: Vec<Vec<u32>>,
    stamp: Vec<u64>,
    step: u64,
    from: i64,
    to: i64,
    started: bool,
    compared: u64,
    differ: u64,
    diffs: Vec<Diff>,
    limit: usize,
    spans: usize,
    /// --segment: its index among A's signals, the segments, a function giving a value its text (enum label, number)
    seg: Option<u32>,
    segs: Vec<Segment>,
    seg_label: Box<dyn Fn(&str) -> String>,
}

impl Merge {
    fn cur(&mut self) -> Option<&mut Segment> {
        self.segs.last_mut()
    }

    /// A difference of pair `p` at `t` counted: in the pair, the totals, the segment; listed while there is room.
    fn count_differ(&mut self, p: usize, t: i64) {
        let d = Diff { t, pair: p, a: self.va[self.pairs[p].ia as usize].clone(), b: self.vb[self.pairs[p].ib as usize].clone() };
        let pr = &mut self.pairs[p];
        pr.differ += 1;
        if pr.first.is_none() {
            pr.first = Some(d.clone());
        }
        self.differ += 1;
        let room = |n: usize, limit: usize| limit == 0 || n < limit;
        if room(self.diffs.len(), self.limit) {
            self.diffs.push(d.clone());
        }
        let limit = self.limit;
        if let Some(s) = self.cur() {
            s.differ += 1;
            if s.first.is_none() {
                s.first = Some(d.clone());
            }
            if room(s.diffs.len(), limit) {
                s.diffs.push(d);
            }
        }
    }

    fn close(&mut self, p: usize, at: i64) {
        let cap = self.spans;
        let pr = &mut self.pairs[p];
        if let Some(s) = pr.open.take() {
            if pr.spans.len() < cap {
                pr.spans.push((s, at));
            } else {
                pr.more += 1;
            }
        }
    }

    /// The values compared where nothing changed (the start of the window, of a segment): a pair that differs there
    /// counts once, its stretch opens. Pairs changed in this step (`stamp`) were counted already.
    fn start(&mut self, t: i64) {
        for p in 0..self.pairs.len() {
            if self.pairs[p].other.is_some() || self.stamp[p] == self.step {
                continue;
            }
            if self.va[self.pairs[p].ia as usize] != self.vb[self.pairs[p].ib as usize] {
                self.count_differ(p, t);
                if self.pairs[p].open.is_none() {
                    self.pairs[p].open = Some(t);
                }
            }
        }
    }

    /// One time step at `t` (A's time): A's changes and B's applied; within the window the pairs they touched counted
    /// (`tail`: past the length both segments have — A's changes counted, not compared; B's applied only). A change of
    /// the segment signal in A starts a segment (not in `tail`: --align starts them itself).
    fn step(&mut self, t: i64, ba: Vec<(u32, String)>, bb: Vec<(u32, String)>, tail: bool, align: bool) {
        self.step += 1;
        let inside = t >= self.from && t <= self.to;
        if inside && !self.started && t > self.from {
            self.started = true;
            self.start(self.from);
        }
        let mut new_seg = None;
        if let Some(sa) = self.seg {
            if let Some((_, v)) = ba.iter().rev().find(|(i, _)| *i == sa) {
                if *v != self.va[sa as usize] && (!align || !tail) {
                    new_seg = Some(v.clone());
                }
            }
        }
        if let Some(v) = new_seg {
            if let Some(s) = self.cur() {
                s.to = t;
            }
            let n = self.segs.last().map_or(1, |s| s.n + 1);
            let label = (self.seg_label)(&v);
            self.segs.push(Segment { n, value: label, from: t, to: t, b_from: None, compared_to: None, changes: 0, differ: 0, first: None, diffs: Vec::new() });
        }
        let mut touched: Vec<usize> = Vec::new();
        for (i, v) in ba {
            if self.va[i as usize] != v {
                self.va[i as usize] = v;
                for &p in &self.by_a[i as usize] {
                    if self.stamp[p as usize] != self.step {
                        self.stamp[p as usize] = self.step;
                        touched.push(p as usize);
                    }
                }
            }
        }
        for (i, v) in bb {
            if self.vb[i as usize] != v {
                self.vb[i as usize] = v;
                if tail {
                    continue;
                }
                for &p in &self.by_b[i as usize] {
                    if self.stamp[p as usize] != self.step {
                        self.stamp[p as usize] = self.step;
                        touched.push(p as usize);
                    }
                }
            }
        }
        if !inside {
            return;
        }
        for p in touched {
            if self.pairs[p].other.is_some() {
                continue;
            }
            self.pairs[p].changes += 1;
            self.compared += 1;
            if let Some(s) = self.cur() {
                s.changes += 1;
            }
            if tail {
                continue;
            }
            if self.va[self.pairs[p].ia as usize] != self.vb[self.pairs[p].ib as usize] {
                self.count_differ(p, t);
                if self.pairs[p].open.is_none() {
                    self.pairs[p].open = Some(t);
                }
            } else {
                self.close(p, t);
            }
        }
        if !self.started {
            self.started = true;
            if !tail {
                self.start(self.from);   // t is the window's first time: the pairs that did not change there
            }
        } else if !tail && self.segs.last().is_some_and(|s| s.from == t && t > self.from) {
            self.start(t);
        }
    }
}

// ------------------------------------------------------------------------------------------------------------- run

fn t_text(t: i64) -> String {
    if t < 0 { format!("-{}", crate::ns(t.unsigned_abs())) } else { crate::ns(t as u64) }
}

pub fn diff_cmd(args: &[String]) -> ExitCode {
    let o = match opts(args) {
        Ok(o) => o,
        Err(e) if e == USAGE => {
            println!("{USAGE}");
            return ExitCode::SUCCESS;
        }
        Err(e) => {
            eprintln!("sva: {e}");
            return ExitCode::from(2);
        }
    };
    match run(&o) {
        Ok(equal) => ExitCode::from(if equal { 0 } else { 1 }),
        Err(e) if e.is_empty() => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("sva: {e}");
            ExitCode::from(2)
        }
    }
}

/// The comparison -> the dumps are equal over the window.
fn run(o: &Opt) -> Result<bool, String> {
    crate::reading(&format!("{} or {}", o.a, o.b));
    let da = open(&o.a, o.quiet)?;
    let db = open(&o.b, o.quiet)?;
    let (ha, hb) = (da.w.hierarchy(), db.w.hierarchy());
    let (a_by, a_list) = vars(ha);
    let (b_by, b_list) = vars(hb);

    // the rules: --map, then the tops paired by themselves (one each, named apart)
    let mut rules: Vec<Rule> = o.map.iter().map(|(a, b)| Rule { a: a.clone(), b: b.clone(), auto: false, used: 0 }).collect();
    let (ta, tb) = (tops(ha), tops(hb));
    if ta.len() == 1 && tb.len() == 1 && ta[0] != tb[0] && !rules.iter().any(|r| r.a == ta[0]) {
        rules.push(Rule { a: ta[0].clone(), b: tb[0].clone(), auto: true, used: 0 });
    }
    let partner = |p: &str, rules: &[Rule]| -> (String, Option<usize>) {
        match mapped(p, rules) {
            Some((q, k)) => (q, Some(k)),
            None => (p.to_string(), None),
        }
    };

    // A's signals compared: --signals, else all (under --scope)
    let under = |p: &str| o.scope.is_empty() || p == o.scope || p.starts_with(&format!("{}.", o.scope));
    // a name: its path under --scope, or as it is, else the one path of A that ends with it (more: ambiguous)
    let named = |n: &str| -> Result<String, String> {
        let exact = [if o.scope.is_empty() { None } else { Some(format!("{}.{n}", o.scope)) }, Some(n.to_string())].into_iter().flatten().find(|p| a_by.contains_key(p));
        if let Some(p) = exact {
            return Ok(p);
        }
        let tail = format!(".{n}");
        let hits: Vec<&String> = a_list.iter().map(|(p, _)| p).filter(|p| p.ends_with(&tail) && under(p)).collect();
        match hits.as_slice() {
            [p] => Ok((*p).clone()),
            [] => Err(format!("{}: no signal {n}{}", o.a, if o.scope.is_empty() { String::new() } else { format!(" under {}", o.scope) })),
            _ => Err(format!("{}: {n} is ambiguous: {} (give its path)", o.a, hits.iter().take(4).map(|p| p.as_str()).collect::<Vec<_>>().join(", "))),
        }
    };
    let mut chosen: Vec<String> = Vec::new();
    let mut explicit: Vec<String> = Vec::new();
    let mut not_in_a: Vec<String> = Vec::new();
    if let Some(f) = &o.signals_from {
        let text = if f == "-" {
            let mut t = String::new();
            std::io::stdin().read_to_string(&mut t).map(|_| t)
        } else {
            std::fs::read_to_string(f)
        }.map_err(|e| format!("{f}: {e}"))?;
        for p in text.lines().map(str::trim).filter(|l| !l.is_empty()) {
            if a_by.contains_key(p) { chosen.push(p.to_string()) } else { not_in_a.push(p.to_string()) }
        }
    }
    if o.signals_from.is_some() && o.signals.is_empty() {
        // the listed paths only
    } else if o.signals.is_empty() {
        chosen.extend(a_list.iter().map(|(p, _)| p.clone()).filter(|p| under(p)));
    } else {
        for s in &o.signals {
            if s.contains(['*', '?']) {
                let pat = if o.scope.is_empty() || s.starts_with('*') { s.clone() } else { format!("{}.{s}", o.scope) };
                let hit: Vec<String> = a_list.iter().map(|(p, _)| p.clone()).filter(|p| glob(pat.as_bytes(), p.as_bytes())).collect();
                if hit.is_empty() {
                    return Err(format!("{}: no signal matches {s}", o.a));
                }
                chosen.extend(hit);
            } else {
                let p = named(s)?;
                explicit.push(p.clone());
                chosen.push(p);
            }
        }
    }
    let mut seen = std::collections::HashSet::new();
    chosen.retain(|p| seen.insert(p.clone()));
    // the segment signal: compared too, when B has it
    let seg_a = match &o.segment {
        Some(s) => {
            let p = named(s).map_err(|e| format!("{e} (--segment)"))?;
            if !chosen.contains(&p) {
                chosen.push(p.clone());
            }
            Some(p)
        }
        None => None,
    };

    let mut rules_used = vec![0u64; rules.len()];
    let mut pairs: Vec<Pair> = Vec::new();
    let mut only_a: Vec<String> = Vec::new();
    let mut paired_b = std::collections::HashSet::new();
    let (mut refs_a, mut kinds_a, mut refs_b, mut kinds_b): (Vec<SignalRef>, Vec<Kind>, Vec<SignalRef>, Vec<Kind>) = Default::default();
    let mut ix_a: HashMap<SignalRef, u32> = HashMap::new();
    let mut ix_b: HashMap<SignalRef, u32> = HashMap::new();
    let index = |h: &Hierarchy, v: VarRef, refs: &mut Vec<SignalRef>, kinds: &mut Vec<Kind>, ix: &mut HashMap<SignalRef, u32>| -> u32 {
        let s = h[v].signal_ref();
        *ix.entry(s).or_insert_with(|| {
            refs.push(s);
            kinds.push(Kind::of(h, v));
            (refs.len() - 1) as u32
        })
    };
    for p in &chosen {
        let va = a_by[p];
        let (q, rule) = partner(p, &rules);
        let Some(&vb) = b_by.get(&q) else {
            if explicit.contains(p) {
                return Err(format!("{}: no signal {q} (the pair of {p} of {})", o.b, o.a));
            }
            if seg_a.as_deref() == Some(p.as_str()) && o.align {
                return Err(format!("{}: no signal {q} (--segment {p} of {}, which --align needs in B)", o.b, o.a));
            }
            only_a.push(p.clone());
            continue;
        };
        if let Some(k) = rule {
            rules_used[k] += 1;
        }
        paired_b.insert(q.clone());
        let (ka, kb) = (Kind::of(ha, va), Kind::of(hb, vb));
        let other = (ka != kb).then(|| kb.word());
        let (ia, ib) = if other.is_some() {
            (u32::MAX, u32::MAX)
        } else {
            (index(ha, va, &mut refs_a, &mut kinds_a, &mut ix_a), index(hb, vb, &mut refs_b, &mut kinds_b, &mut ix_b))
        };
        pairs.push(Pair { a: p.clone(), b: q, kind: ka, other, ia, ib, changes: 0, differ: 0, first: None, open: None, spans: Vec::new(), more: 0 });
    }
    for (r, n) in rules.iter_mut().zip(&rules_used) {
        r.used = *n;
    }
    // B's signals nobody paired (all of B, or under the scope --scope maps to); none listed for --signals
    let b_scope = if o.scope.is_empty() { String::new() } else { partner(&o.scope, &rules).0 };
    let only_b: Vec<String> = if o.signals.is_empty() && o.signals_from.is_none() {
        b_list.iter().map(|(p, _)| p.clone())
            .filter(|p| !paired_b.contains(p) && (b_scope.is_empty() || p == &b_scope || p.starts_with(&format!("{b_scope}."))))
            .collect()
    } else {
        Vec::new()
    };
    if pairs.is_empty() {
        return Err(format!("no signal of {} has its pair in {} (--map A=B renames A's paths for B; {} has {})", o.a, o.b, o.b,
            tops(hb).join(", ")));
    }
    // the segment signal on both sides
    let seg_ia = seg_a.as_ref().map(|p| index(ha, a_by[p], &mut refs_a, &mut kinds_a, &mut ix_a));
    let seg_ib = match (&seg_a, o.align) {
        (Some(p), true) => Some(index(hb, b_by[&partner(p, &rules).0], &mut refs_b, &mut kinds_b, &mut ix_b)),
        _ => None,
    };
    // a segment's value as its text: the enum label of A's table, else a number when the bits are known, else the bits
    let seg_label: Box<dyn Fn(&str) -> String> = match &seg_a {
        Some(p) => {
            let v = a_by[p];
            let table: Vec<(String, String)> = ha[v].enum_type(ha).map(|(_, t)| t.iter().map(|(b, l)| (b.to_string(), l.to_string())).collect()).unwrap_or_default();
            Box::new(move |s: &str| {
                if let Some((_, l)) = table.iter().find(|(b, _)| b == s) {
                    return l.clone();
                }
                if s.len() > 1 && s.len() <= 128 && s.bytes().all(|c| c == b'0' || c == b'1') {
                    return u128::from_str_radix(s, 2).map_or(s.to_string(), |n| n.to_string());
                }
                shown(s).to_string()
            })
        }
        None => Box::new(|s: &str| s.to_string()),
    };
    let summary_a = json!({"file": o.a, "signals": a_list.len()});
    let summary_b = json!({"file": o.b, "signals": b_list.len()});
    let (end_a, end_b) = (da.end, db.end);
    let big = !o.quiet && da.bytes + db.bytes >= 64 << 20;
    let files = (da.file.clone(), db.file.clone());

    let mut by_a = vec![Vec::new(); refs_a.len()];
    let mut by_b = vec![Vec::new(); refs_b.len()];
    for (k, p) in pairs.iter().enumerate() {
        if p.other.is_none() {
            by_a[p.ia as usize].push(k as u32);
            by_b[p.ib as usize].push(k as u32);
        }
    }
    let va: Vec<String> = kinds_a.iter().map(|k| k.unknown()).collect();
    let vb: Vec<String> = kinds_b.iter().map(|k| k.unknown()).collect();
    let (rxa, ja, tmp_a) = spawn(da, refs_a, kinds_a);
    let (rxb, jb, tmp_b) = spawn(db, refs_b, kinds_b);
    let mut a = Stream { rx: rxa, join: Some(ja), next: None, done: false, last: None, file: files.0.clone() };
    let mut b = Stream { rx: rxb, join: Some(jb), next: None, done: false, last: None, file: files.1.clone() };
    a.fill()?;
    b.fill()?;
    let (Some(sa), Some(sb)) = (a.peek(), b.peek()) else {
        return Err(format!("{}: no value change to compare", if a.peek().is_none() { &files.0 } else { &files.1 }));
    };

    // the window, in A's time: what both dumps cover (with --align: all of A), within --from / --to
    let ea = end_a.unwrap_or(i64::MAX);
    let eb = end_b.map_or(i64::MAX, |e| e.saturating_sub(o.offset));
    let mut from = if o.align { sa } else { sa.max(sb - o.offset) };
    let mut to = if o.align { ea } else { ea.min(eb) };
    if let Some(f) = o.from {
        from = from.max(f as i64);
    }
    if let Some(t) = o.to {
        to = to.min(t as i64);
    }
    if from > to {
        return Err(format!("no time in common (A {} … {}, B {} … {}{}{})", t_text(sa), end_a.map_or("?".into(), t_text), t_text(sb),
            end_b.map_or("?".into(), t_text), if o.offset != 0 { format!(", --offset {}", t_text(o.offset)) } else { String::new() },
            match (o.from, o.to) { (None, None) => String::new(), _ => format!(", asked {} … {}", o.from.map_or("start".into(), crate::ns), o.to.map_or("end".into(), crate::ns)) }));
    }

    let n_pairs = pairs.len();
    let mut m = Merge { pairs, va, vb, by_a, by_b, stamp: vec![0; n_pairs], step: 0, from, to, started: false, compared: 0, differ: 0, diffs: Vec::new(),
        limit: o.limit, spans: o.spans, seg: seg_ia, segs: Vec::new(), seg_label };
    if seg_ia.is_some() && !o.align {
        // before the first change of the segment signal: segment 0
        m.segs.push(Segment { n: 0, value: "before".into(), from: sa, to: sa, b_from: None, compared_to: None, changes: 0, differ: 0, first: None, diffs: Vec::new() });
    }
    let mut notes: Vec<String> = Vec::new();
    let mut shift = o.offset;   // B's time less A's
    let mut next_tenth = 1;
    // --align: each side held at the change of the segment signal that starts its next segment
    let at_bound = |s: &Stream, ix: Option<u32>, vals: &[String]| -> bool {
        match (ix, &s.next) {
            (Some(i), Some((_, ch))) => ch.iter().rev().find(|(k, _)| *k == i).is_some_and(|(_, v)| *v != vals[i as usize]),
            _ => false,
        }
    };
    let (mut a_seg_start, mut b_seg_start): (Option<i64>, Option<i64>) = (None, None);
    let mut b_out = false;   // --align: B has no more segments
    let (mut segs_a, mut segs_b) = (0u64, 0u64);
    loop {
        a.fill()?;
        b.fill()?;
        // a dump whose end its file does not say ends at its last change
        if a.done && end_a.is_none() {
            m.to = m.to.min(a.last.unwrap_or(m.to));
        }
        if b.done && end_b.is_none() && !o.align {
            m.to = m.to.min(b.last.map_or(m.to, |l| l - o.offset));
        }
        let (mut ta, mut tb) = (a.peek(), b.peek().map(|t| t - shift));
        let mut cut: Option<i64> = None;
        if o.align {
            let ah = at_bound(&a, seg_ia, &m.va);
            let bh = !b_out && at_bound(&b, seg_ib, &m.vb);
            if ah && (bh || b.done || b_out) {
                // both at the start of their next segment (or B has none): the segments start together
                let t = ta.unwrap();
                let was_out = b_out;
                if !was_out {
                    let close_at = cut_of(a_seg_start, b_seg_start, t, b.peek(), b.done, b.last.max(end_b)).min(t);
                    for p in 0..m.pairs.len() {
                        m.close(p, close_at);
                    }
                    if let Some(s) = m.cur() {
                        s.compared_to = Some(close_at);
                    }
                }
                segs_a += 1;
                let bb = if bh {
                    segs_b += 1;
                    let tb_raw = b.peek().unwrap();
                    shift = tb_raw - t;
                    b_seg_start = Some(tb_raw);
                    b.take()
                } else {
                    b_out = true;
                    Vec::new()
                };
                a_seg_start = Some(t);
                let ba = a.take();
                m.step(t, ba, bb, b_out, false);   // B has no more segments: A's counted, not compared
                if let Some(s) = m.cur() {
                    s.b_from = if b_out { None } else { b_seg_start };
                }
                continue;
            }
            if bh && a.done {
                break;
            }
            if ah {
                cut = ta;
                ta = None;
            }
            if bh {
                cut = Some(cut.map_or(tb.unwrap(), |c| c.min(tb.unwrap())));
                tb = None;
            }
            if b_out {
                tb = None;
            } else if b.done {
                // B read to its end in this segment: A's changes after it are not compared
                let e = b.last.max(end_b).map_or(i64::MAX, |e| e - shift);
                cut = Some(cut.map_or(e, |c| c.min(e)));
            }
        }
        let t = match (ta, tb) {
            (Some(x), Some(y)) => x.min(y),
            (Some(x), None) => x,
            (None, Some(y)) => y,
            (None, None) => break,
        };
        if t > m.to {
            break;
        }
        let tail = b_out || cut.is_some_and(|c| t >= c);
        let ba = if ta == Some(t) { a.take() } else { Vec::new() };
        let bb = if tb == Some(t) { b.take() } else { Vec::new() };
        m.step(t, ba, bb, tail, o.align);
        if big && m.to > m.from && m.to != i64::MAX {
            let tenth = ((t - m.from).max(0) as f64 / (m.to - m.from) as f64 * 10.0) as i64;
            if tenth >= next_tenth && tenth < 10 {
                eprintln!("sva: {} ~ {}: progress: {tenth}/10 ({})", files.0, files.1, t_text(t));
                next_tenth = tenth + 1;
            }
        }
    }
    let b_end = b.last.max(end_b);
    drop(a);
    drop(b);
    drop((tmp_a, tmp_b));
    if m.to == i64::MAX {
        m.to = from;
    }
    if !m.started {
        m.started = true;
        m.start(m.from);
    }
    let to = m.to;
    for p in 0..m.pairs.len() {
        m.close(p, to);
    }
    if let Some(s) = m.segs.last_mut() {
        s.to = to;
        if o.align && !b_out {
            s.compared_to = Some(cut_of(a_seg_start, b_seg_start, to, None, true, b_end).min(to));
        }
    }
    if o.align && segs_a != segs_b {
        notes.push(format!("{} segments in A, {} in B: {}", segs_a, segs_b,
            if segs_a > segs_b { "the last ones of A are not compared" } else { "the last ones of B are not compared" }));
    }
    for r in &rules {
        if !r.auto && r.used == 0 {
            notes.push(format!("--map {}={}: no signal paired by it", r.a, r.b));
        }
    }
    // the segments in the window
    let (from, to) = (m.from, m.to);
    m.segs.retain(|s| s.to >= from && s.from <= to && !(s.n == 0 && s.changes == 0 && s.differ == 0));
    for s in &mut m.segs {
        s.from = s.from.max(from);
        s.to = s.to.min(to);
    }
    let other = m.pairs.iter().filter(|p| p.other.is_some()).count();
    let signals_differ = m.pairs.iter().filter(|p| p.differ > 0 || p.other.is_some()).count();
    let equal = signals_differ == 0;

    let diff_json = |d: &Option<Diff>| -> Value {
        d.as_ref().map_or(Value::Null, |d| json!({"t": d.t, "signal": m.pairs[d.pair].a, "a": shown(&d.a), "b": shown(&d.b)}))
    };
    let doc = json!({
        "wavelens": "diff", "version": 1, "unit": "ps",
        "a": {"file": summary_a["file"], "start": sa, "end": end_a.unwrap_or(to), "signals": summary_a["signals"]},
        "b": {"file": summary_b["file"], "start": sb, "end": end_b.unwrap_or(to + o.offset), "signals": summary_b["signals"]},
        "from": from, "to": to, "offset": o.offset,
        "map": rules.iter().filter(|r| r.used > 0 || !r.auto).map(|r| {
            let mut x = json!({"a": r.a, "b": r.b, "signals": r.used});
            if r.auto { x["auto"] = true.into(); }
            x
        }).collect::<Vec<_>>(),
        "signals_compared": m.pairs.len(), "signals_differ": signals_differ, "compared": m.compared, "differ": m.differ,
        "first": diff_json(&m.diffs.first().cloned()),
        "differences": m.diffs.iter().map(|d| diff_json(&Some(d.clone()))).collect::<Vec<_>>(),
        "more": m.differ - m.diffs.len() as u64,
        "signals": m.pairs.iter().map(|p| {
            let mut x = json!({"path": p.a, "b": p.b, "kind": match p.kind { Kind::Bits(_) => "bits", Kind::Real => "real", Kind::Text => "string" },
                "width": match p.kind { Kind::Bits(w) => Value::from(w), _ => Value::Null },
                "changes": p.changes, "differ": p.differ, "first": diff_json(&p.first), "other": p.other});
            if o.spans > 0 {
                let spans = if p.other.is_some() { vec![(from, to)] } else { p.spans.clone() };
                x["spans"] = spans.iter().map(|(s, u)| json!([s, u])).collect::<Vec<_>>().into();
                x["more"] = p.more.into();
            }
            x
        }).collect::<Vec<_>>(),
        "only_a": limited(&only_a, o.limit), "only_b": limited(&only_b, o.limit),
        "only_a_count": only_a.len(), "only_b_count": only_b.len(), "not_in_a": not_in_a,
        "segments": m.segs.iter().map(|s| {
            let mut x = json!({"n": s.n, "value": s.value, "from": s.from, "to": s.to, "changes": s.changes, "differ": s.differ, "first": diff_json(&s.first)});
            if o.align {
                x["b_from"] = s.b_from.map_or(Value::Null, Value::from);
                x["compared_to"] = s.compared_to.map_or(Value::Null, Value::from);
            }
            x
        }).collect::<Vec<_>>(),
        "notes": notes,
    });
    if let Some(f) = &o.junit {
        write_file(f, &junit(&doc, &m, o))?;
    }
    match o.json.as_deref() {
        Some("-") => {
            outln!("{}", serde_json::to_string_pretty(&doc).unwrap_or_default());
        }
        Some(f) => {
            write_file(f, &(serde_json::to_string_pretty(&doc).unwrap_or_default() + "\n"))?;
            text(&doc, &m, other, o);
        }
        None => text(&doc, &m, other, o),
    }
    Ok(equal)
}

/// The cut between the segments of --align: A's segment start plus the length both have.
fn cut_of(a0: Option<i64>, b0: Option<i64>, a_next: i64, b_next: Option<i64>, b_done: bool, b_last: Option<i64>) -> i64 {
    match (a0, b0) {
        (Some(a0), Some(b0)) => {
            let lb = match (b_next, b_done) {
                (Some(n), _) => n - b0,
                (None, true) => b_last.unwrap_or(b0) - b0,
                _ => i64::MAX,
            };
            a0.saturating_add((a_next - a0).min(lb))
        }
        _ => a_next,
    }
}

fn plural(n: u64, what: &str) -> String {
    format!("{n} {what}{}", if n == 1 { "" } else { "s" })
}

fn limited(v: &[String], limit: usize) -> Vec<String> {
    v.iter().take(if limit == 0 { usize::MAX } else { limit }).cloned().collect()
}

fn write_file(f: &str, text: &str) -> Result<(), String> {
    std::fs::write(f, text).map_err(|e| format!("{f}: {e}"))
}

/// The result as text, as `sva eval` writes its own: the dumps, the pairs, the counts, the first differences, the segments.
fn text(d: &Value, m: &Merge, other: usize, o: &Opt) {
    let n = |v: &Value| v.as_u64().unwrap_or(0);
    let t = |v: &Value| v.as_i64().map_or("?".into(), t_text);
    outln!("A: {}  {} … {}, {} signals", d["a"]["file"].as_str().unwrap_or(""), t(&d["a"]["start"]), t(&d["a"]["end"]), n(&d["a"]["signals"]));
    outln!("B: {}  {} … {}, {} signals", d["b"]["file"].as_str().unwrap_or(""), t(&d["b"]["start"]), t(&d["b"]["end"]), n(&d["b"]["signals"]));
    for r in d["map"].as_array().into_iter().flatten() {
        outln!("map: {} → {} ({}{})", r["a"].as_str().unwrap_or(""), r["b"].as_str().unwrap_or(""),
            if r["auto"] == true { "the tops, " } else { "" }, plural(n(&r["signals"]), "signal"));
    }
    let only = |k: &str, side: &str| if n(&d[k]) > 0 { format!(", {} only in {side}", n(&d[k])) } else { String::new() };
    outln!("{} signals compared{}{}, {} … {}{}", n(&d["signals_compared"]), only("only_a_count", "A"), only("only_b_count", "B"), t(&d["from"]), t(&d["to"]),
        if o.offset != 0 { format!(" (B {})", if o.offset > 0 { format!("+{}", t_text(o.offset)) } else { t_text(o.offset) }) } else { String::new() });
    let first = &d["first"];
    outln!("{} changes compared, {} differ{}", n(&d["compared"]), n(&d["differ"]),
        if first.is_null() { String::new() } else { format!(" in {}; the first at {}: {} A={} B={}", plural(n(&d["signals_differ"]) - other as u64, "signal"), t(&first["t"]),
            first["signal"].as_str().unwrap_or(""), pretty(first["a"].as_str().unwrap_or("")), pretty(first["b"].as_str().unwrap_or(""))) });
    if other > 0 {
        for p in m.pairs.iter().filter(|p| p.other.is_some()) {
            outln!("  {}: {} in A, {} in B (differs everywhere)", p.a, p.kind.word(), p.other.as_deref().unwrap_or(""));
        }
    }
    if m.diffs.len() > 1 || (m.diffs.len() == 1 && n(&d["more"]) > 0) {
        for x in &m.diffs {
            outln!("  {:>14}  {}  A={} B={}", t_text(x.t), m.pairs[x.pair].a, pretty(&x.a), pretty(&x.b));
        }
        if n(&d["more"]) > 0 {
            outln!("  … and {} more (--limit)", n(&d["more"]));
        }
    }
    for s in &m.segs {
        let extra = match (o.align, s.b_from, s.compared_to) {
            (true, Some(b), Some(c)) if c < s.to => format!(" (B from {}, compared to {})", t_text(b), t_text(c)),
            (true, Some(b), _) => format!(" (B from {})", t_text(b)),
            (true, None, _) => " (not in B)".into(),
            _ => String::new(),
        };
        let first = s.first.as_ref().map_or(String::new(), |f| format!("; the first at {}: {} A={} B={}", t_text(f.t), m.pairs[f.pair].a, pretty(&f.a), pretty(&f.b)));
        outln!("segment {} ({} = {}): {} … {}{extra}: {} changes, {} differ{first}", s.n, o.segment.as_deref().unwrap_or(""), s.value, t_text(s.from),
            t_text(s.to), s.changes, s.differ);
    }
    for x in d["notes"].as_array().into_iter().flatten() {
        outln!("note: {}", x.as_str().unwrap_or(""));
    }
}

/// The JUnit report: a test case per segment (none: one, `all`), a failure with its first differences; the signals
/// of another width or kind a test case of their own.
fn junit(d: &Value, m: &Merge, o: &Opt) -> String {
    let x = sva_core::xml_text;
    // a test case: its name, changes, differences, the first one, those listed
    type Case<'a> = (String, u64, u64, Option<&'a Diff>, &'a [Diff]);
    let mut cases: Vec<Case> = Vec::new();
    if m.segs.is_empty() {
        cases.push(("all".into(), m.compared, m.differ, m.diffs.first(), &m.diffs));
    } else {
        for s in &m.segs {
            cases.push((format!("segment {} ({} = {})", s.n, o.segment.as_deref().unwrap_or(""), s.value), s.changes, s.differ, s.first.as_ref(), &s.diffs));
        }
    }
    let others: Vec<&Pair> = m.pairs.iter().filter(|p| p.other.is_some()).collect();
    let fails = cases.iter().filter(|c| c.2 > 0).count() + usize::from(!others.is_empty());
    let tests = cases.len() + usize::from(!others.is_empty());
    let mut out = format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites>\n<testsuite name=\"{}\" tests=\"{tests}\" failures=\"{fails}\" errors=\"0\" skipped=\"0\" time=\"0\">\n",
        x(&format!("diff {} {}", o.a, o.b)));
    let _ = writeln!(out, "  <properties><property name=\"signals_compared\" value=\"{}\"/><property name=\"only_a\" value=\"{}\"/><property name=\"only_b\" value=\"{}\"/></properties>",
        d["signals_compared"], d["only_a_count"], d["only_b_count"]);
    let line = |f: &Diff| format!("{}: {} A={} B={}", t_text(f.t), m.pairs[f.pair].a, pretty(&f.a), pretty(&f.b));
    for (name, changes, differ, first, list) in &cases {
        let _ = write!(out, "  <testcase classname=\"sva.diff\" name=\"{}\" time=\"0\">", x(name));
        if *differ > 0 {
            let _ = write!(out, "<failure type=\"differ\" message=\"{differ} of {changes} changes differ; first at {}\">",
                x(&first.map(&line).unwrap_or_default()));
            for f in list.iter() {
                let _ = writeln!(out, "{}", x(&line(f)));
            }
            if *differ > list.len() as u64 {
                let _ = writeln!(out, "… and {} more", differ - list.len() as u64);
            }
            out.push_str("</failure>");
        }
        let _ = write!(out, "<system-out>{changes} changes compared, {differ} differ</system-out>");
        out.push_str("</testcase>\n");
    }
    if !others.is_empty() {
        let _ = write!(out, "  <testcase classname=\"sva.diff\" name=\"widths\" time=\"0\"><failure type=\"other\" message=\"{} signals of another width or kind in B\">",
            others.len());
        for p in &others {
            let _ = writeln!(out, "{}", x(&format!("{}: {} in A, {} in B", p.a, p.kind.word(), p.other.as_deref().unwrap_or(""))));
        }
        out.push_str("</failure></testcase>\n");
    }
    out.push_str("</testsuite>\n</testsuites>\n");
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn buses_show_in_hex() {
        assert_eq!(pretty("11001010111111100000000000000001"), "0xcafe0001");
        assert_eq!(pretty("10101"), "0x15");
        assert_eq!(pretty("1x101"), "1x101");
        assert_eq!(pretty("1010"), "1010");
        assert_eq!(pretty("\u{0}?"), "-");
    }

    #[test]
    fn globs_match_whole_paths() {
        assert!(glob(b"tb.*.ready", b"tb.u_a.ready"));
        assert!(glob(b"tb.?x", b"tb.ax"));
        assert!(!glob(b"tb.*.ready", b"tb.u_a.ready_n"));
        assert!(glob(b"*", b""));
    }

    #[test]
    fn maps_take_the_longest_scope_and_an_exact_pair_first() {
        let r = |a: &str, b: &str, auto: bool| Rule { a: a.into(), b: b.into(), auto, used: 0 };
        let rules = [r("tb", "top", true), r("tb.if_a", "top.bif", false), r("tb.sensor_data", "top.bif.sensor_data", false)];
        assert_eq!(mapped("tb.if_a.x", &rules).unwrap().0, "top.bif.x");
        assert_eq!(mapped("tb.y", &rules).unwrap().0, "top.y");
        assert_eq!(mapped("tb.sensor_data", &rules).unwrap().0, "top.bif.sensor_data");
        assert!(mapped("other.x", &rules).is_none());
        assert!(mapped("tb.if_ab.x", &rules).unwrap().0.starts_with("top.if_ab"), "a scope is a whole name");
    }

    #[test]
    fn the_cut_is_the_length_both_segments_have() {
        assert_eq!(cut_of(Some(100), Some(0), 300, Some(150), false, None), 250);
        assert_eq!(cut_of(Some(100), Some(0), 300, Some(500), false, None), 300);
        assert_eq!(cut_of(Some(100), Some(0), 300, None, true, Some(50)), 150);
    }
}
