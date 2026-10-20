//! The evaluator (docs/sva/ENGINE.md): sampled values in, attempts with their results and step traces out.
//!
//! Every cycle starts one attempt of the assertion (none while `disable iff` holds). An attempt is a property state
//! stepped once per cycle until it passes, fails, or the trace ends (`active`, or `fail` for a strong operator).
//! Sequences run as sets of threads: a thread is a residual sequence (what is left to match from the next cycle) and
//! the path of the booleans it matched. Residual sequences are hash-consed terms, so two threads that reached the same
//! state are one thread (the first path is kept) and a thread set is bounded by the number of distinct states.
//!
//! The files: `results.rs` the inputs and outputs (`Trace`, `Options`, `Results` …), `seq.rs` the terms and one cycle of
//! a sequence, this one the property states, the paths of the steps and the driver of the attempts.
//!
//! Glossary of the short names: `Eng` the evaluator of one assertion, its fields `a` the assertion, `c` the current
//! cycle, `ar` the term arena, `cols` the sampled columns, `bools` the compiled booleans (`b`: a boolean's number),
//! `props` the compiled property nodes; `CP` a compiled property node, `PS` the state of a property instance of one
//! attempt, `CE` a compiled expression, `Tri` a 4-state truth; a term `t` (a residual sequence), a path `p` (the steps
//! matched, a linked list in `paths`), `END` a term that matched, `DONE` an `and` side that matched, `NIL` no path; `k`
//! the index of a property node in `props`.

use crate::ast::{Assertion, Bound, Expr, ImpOp, Kind, Prop, PropOp, RepOp, Seq, SeqOp, BinOp};
use crate::lex::Span;
use crate::value::{CResult, Compiler, Samples, Tri, CE, V};
use crate::{Printer, SvaError};
use std::collections::{BTreeMap, HashMap, HashSet};

mod results;
mod seq;

pub use results::*;
use seq::*;

/// The mark of the matches left out of an `ante_end` list while it is kept (never in the results).
const CUT: usize = usize::MAX;

/// A path with no steps.
const NIL: u32 = u32::MAX;
/// A boolean that is no element (an `if` condition).
const NO_ELEM: u16 = u16::MAX;
/// A path node that stands for the steps dropped from the middle of a long path.
const TRUNC: u16 = u16::MAX - 1;
/// A path longer than this keeps its first `HEAD` and last `TAIL` steps: memory per thread stays bounded.
const PATH_MAX: u32 = 96;
const HEAD: usize = 16;
const TAIL: usize = 47;

// ---------------------------------------------------------------- properties

#[derive(Clone, Debug)]
enum CP {
    /// A sequence as a property; `all`: every match counts (`cover sequence`).
    Seq { s: u32, all: bool },
    /// `|->` (delay 0), `|=>` (1); `follow`: `#-#` / `#=#`.
    Imp { ante: u32, delay: usize, cons: usize, follow: bool },
    Not(usize),
    Bin { and: bool, a: usize, b: usize },
    If { c: u16, then: usize, else_: Option<usize> },
    Next { n: u32, strong: bool, p: usize },
    Always { lo: u32, hi: u32, strong: bool, p: usize },
    Event { lo: u32, hi: u32, strong: bool, p: usize },
}

#[derive(Clone, Debug)]
struct Thread {
    t: u32,
    p: u32,
}

/// Why an instance failed: the words and the kind (`Reason`), with the boolean it is about.
#[derive(Clone, Debug)]
struct Note {
    text: String,
    kind: &'static str,
    b: Option<u16>,
}

impl Note {
    fn new(kind: &'static str, text: impl Into<String>, b: Option<u16>) -> Note {
        Note { text: text.into(), kind, b }
    }
}

#[derive(Clone, Debug)]
enum Verdict {
    Pending,
    Pass { vac: bool, end: usize, path: u32 },
    Fail { at: usize, note: Note, path: u32 },
}

#[derive(Debug)]
enum Slot {
    Run(PS),
    Done(Verdict),
}

/// The state of one property instance of one attempt.
#[derive(Debug)]
enum PS {
    Seq { k: usize, th: Vec<Thread>, dead: u32, hits: usize },
    Imp { k: usize, ante: Vec<Thread>, dead: u32, matched: bool, wait: Vec<(usize, u32)>, insts: Vec<(usize, PS)>, vac: bool, end: usize, path: u32, last: Option<(usize, Note, u32)>, ends: Vec<usize> },
    Not(Box<PS>),
    Bin { k: usize, a: Box<Slot>, b: Box<Slot> },
    If { k: usize, base: u32 },
    Next { k: usize, left: u32, base: u32 },
    /// `acc`: the steps of the instances that passed (`always`).
    Always { k: usize, off: u32, insts: Vec<PS>, base: u32, acc: u32 },
    Event { k: usize, off: u32, insts: Vec<PS>, base: u32 },
}

struct BoolDef {
    e: CE,
    elem: u16,
    show: Option<CE>,
    text: String,
}

#[derive(Clone, Copy)]
struct PathNode {
    b: u16,
    cycle: u32,
    prev: u32,
    len: u32,
}

struct Cols<'a>(Vec<&'a Column>);

impl Samples for Cols<'_> {
    fn get(&self, k: usize, c: i64) -> V {
        self.0[k].at(c)
    }
}

type Out = Vec<(u32, Vec<u16>)>;

struct Eng<'a> {
    a: &'a Assertion,
    cols: Cols<'a>,
    bools: Vec<BoolDef>,
    cache: Vec<(i64, Tri)>,
    props: Vec<CP>,
    ar: Arena,
    paths: Vec<PathNode>,
    c: usize,
    xmode: XMode,
    max_threads: usize,
    fails: Vec<u16>,
    xs: Vec<u16>,
    capped: bool,
    /// The path of the thread that met the first unknown boolean of this step.
    xpath: u32,
    /// `cover sequence`: the matches of the current step.
    hits: Vec<u32>,
    /// Compiling: the role of the booleans being compiled, the implication they belong to, implications so far; the
    /// role of every element.
    role: (&'static str, Option<u32>),
    imps: u32,
    roles: Vec<Option<(&'static str, Option<u32>)>>,
}

impl Eng<'_> {
    // ---- paths

    fn plen(&self, p: u32) -> u32 {
        if p == NIL { 0 } else { self.paths[p as usize].len }
    }

    fn push(&mut self, p: u32, b: u16, cycle: usize) -> u32 {
        let len = self.plen(p) + 1;
        self.paths.push(PathNode { b, cycle: cycle as u32, prev: p, len });
        self.paths.len() as u32 - 1
    }

    fn extend(&mut self, mut p: u32, ids: &[u16]) -> u32 {
        for &b in ids {
            if self.plen(p) >= PATH_MAX {
                p = self.shorten(p);
            }
            p = self.push(p, b, self.c);
        }
        p
    }

    /// A long path: its first `HEAD` steps, a [`TRUNC`] node, its last `TAIL` steps.
    fn shorten(&mut self, p: u32) -> u32 {
        let v = self.path(p);
        let cut = v.len() - TAIL;
        let mut q = NIL;
        for (i, &(b, cycle)) in v.iter().enumerate() {
            if i == HEAD {
                q = self.push(q, TRUNC, v[cut].1);
            }
            if i < HEAD || i >= cut {
                q = self.push(q, b, cycle);
            }
        }
        q
    }

    /// A path made of these steps (in order).
    fn chain(&mut self, steps: &[(u16, usize)]) -> u32 {
        let mut p = NIL;
        for &(b, cycle) in steps {
            if self.plen(p) >= PATH_MAX {
                p = self.shorten(p);
            }
            p = self.push(p, b, cycle);
        }
        p
    }

    /// The steps of one attempt of a group: its own steps up to the cycle it joined the group, then the leader's.
    fn member_path(&self, m: &Member, p: u32) -> Vec<(u16, usize)> {
        if m.prefix == NIL && m.since == 0 {
            return self.path(p);
        }
        let mut v = self.path(m.prefix);
        v.extend(self.path(p).into_iter().filter(|s| s.1 >= m.since));
        v
    }

    fn path(&self, mut p: u32) -> Vec<(u16, usize)> {
        let mut v = Vec::new();
        while p != NIL {
            let n = self.paths[p as usize];
            v.push((n.b, n.cycle as usize));
            p = n.prev;
        }
        v.reverse();
        v
    }

    fn merge_paths(&mut self, a: u32, b: u32) -> u32 {
        if a == NIL || a == b {
            return b;
        }
        if b == NIL {
            return a;
        }
        let mut all = self.path(a);
        for s in self.path(b) {
            if !all.contains(&s) {
                all.push(s);
            }
        }
        let elem = |b: u16| self.bools.get(b as usize).map_or(u16::MAX, |d| d.elem);
        all.sort_by_key(|s| (s.1, elem(s.0))); // by cycle, then in the order of the elements
        self.chain(&all)
    }

    /// Drop the path nodes no live attempt refers to (the arena only grows otherwise) and renumber the rest.
    fn gc(&mut self, groups: &mut [Group]) {
        let n = self.paths.len();
        let mut roots = Vec::new();
        for g in groups.iter_mut() {
            visit(&mut g.ps, &mut |p| roots.push(*p));
            roots.extend(g.members.iter().map(|m| m.prefix));
            roots.extend(g.x.map(|x| x.2));
        }
        let mut mark = vec![false; n];
        for mut p in roots {
            while p != NIL && !mark[p as usize] {
                mark[p as usize] = true;
                p = self.paths[p as usize].prev;
            }
        }
        let mut map = vec![NIL; n];
        let mut nodes = Vec::with_capacity(mark.iter().filter(|m| **m).count());
        for i in 0..n {
            if mark[i] {
                let mut nd = self.paths[i];
                if nd.prev != NIL {
                    nd.prev = map[nd.prev as usize];
                }
                map[i] = nodes.len() as u32;
                nodes.push(nd);
            }
        }
        self.paths = nodes;
        let re = &mut |p: &mut u32| {
            if *p != NIL {
                *p = map[*p as usize];
            }
        };
        for g in groups.iter_mut() {
            visit(&mut g.ps, re);
            for m in &mut g.members {
                re(&mut m.prefix);
            }
            if let Some(x) = &mut g.x {
                re(&mut x.2);
            }
        }
    }

    /// The terms (the residual sequences): only the ones the compiled properties and the pending threads use are kept
    /// (every residual ever made stayed before: 500 MB for 40 000 cycles of a wide intersect).
    fn gc_terms(&mut self, groups: &mut [Group]) {
        let mut roots = Vec::new();
        for cp in &self.props {
            match cp {
                CP::Seq { s, .. } => roots.push(*s),
                CP::Imp { ante, .. } => roots.push(*ante),
                _ => {}
            }
        }
        for g in groups.iter_mut() {
            visit_terms(&mut g.ps, &mut |t| roots.push(*t));
        }
        let map = self.ar.compact(roots.into_iter());
        let re = |t: &mut u32| {
            if (*t as usize) < map.len() {
                *t = map[*t as usize];
            }
        };
        for cp in &mut self.props {
            match cp {
                CP::Seq { s, .. } => re(s),
                CP::Imp { ante, .. } => re(ante),
                _ => {}
            }
        }
        for g in groups.iter_mut() {
            visit_terms(&mut g.ps, &mut |t| re(t));
        }
    }

    /// What decides the future of a pending instance, without its paths and with cycles relative to now: two attempts
    /// with the same signature step alike from here on (the same booleans, the same verdict at the same cycle).
    fn sig(&self, ps: &PS, s: &mut Vec<u64>) {
        let c = self.c as u64;
        match ps {
            PS::Seq { k, th, hits, .. } => {
                s.extend([0, *k as u64, (*hits > 0) as u64, th.len() as u64]);
                s.extend(th.iter().map(|t| t.t as u64));
            }
            PS::Imp { k, ante, matched, wait, insts, vac, end, last, .. } => {
                s.extend([1, *k as u64, *matched as u64, *vac as u64, c.wrapping_sub(*end as u64), ante.len() as u64]);
                s.extend(ante.iter().map(|t| t.t as u64));
                s.push(wait.len() as u64);
                s.extend(wait.iter().map(|w| (w.0 as u64).wrapping_sub(c)));
                s.push(insts.len() as u64);
                for (_, p) in insts {
                    self.sig(p, s);
                }
                match last {
                    None => s.push(0),
                    Some((at, note, _)) => s.extend([1, c.wrapping_sub(*at as u64), fnv(&note.text)]),
                }
            }
            PS::Not(i) => {
                s.push(2);
                self.sig(i, s);
            }
            PS::Bin { k, a, b } => {
                s.extend([3, *k as u64]);
                for x in [a, b] {
                    match &**x {
                        Slot::Run(p) => {
                            s.push(0);
                            self.sig(p, s);
                        }
                        Slot::Done(v) => {
                            s.push(1);
                            vsig(v, c, s);
                        }
                    }
                }
            }
            PS::If { k, .. } => s.extend([4, *k as u64]),
            PS::Next { k, left, .. } => s.extend([5, *k as u64, *left as u64]),
            PS::Always { k, off, insts, .. } | PS::Event { k, off, insts, .. } => {
                // the offset only matters up to the end of the range: [lo:$] after lo is one state
                let (lo, hi) = match self.props[*k] {
                    CP::Always { lo, hi, .. } | CP::Event { lo, hi, .. } => (lo, hi),
                    _ => unreachable!(),
                };
                let off = if hi == INF { (*off).min(lo) } else { (*off).min(hi.saturating_add(1)) };
                s.extend([if matches!(ps, PS::Always { .. }) { 6 } else { 7 }, *k as u64, off as u64, insts.len() as u64]);
                for p in insts {
                    self.sig(p, s);
                }
            }
        }
    }

    // ---- thread sets

    /// One cycle of a set of threads. Returns the paths of the matches at this cycle and the last boolean that was
    /// false for a thread of this set; `dead` gets the longest path of a thread that ended without a match.
    fn advance(&mut self, th: &mut Vec<Thread>, dead: &mut u32) -> (Vec<u32>, Option<u16>) {
        let mark = self.fails.len();
        let mut next: Vec<Thread> = Vec::with_capacity(th.len());
        let mut seen: HashSet<u32> = HashSet::new();
        let mut ends = Vec::new();
        let mut out = Vec::new();
        for x in th.iter() {
            out.clear();
            let xs = self.xs.len();
            self.step(x.t, &mut out);
            if self.xs.len() > xs && self.xpath == NIL {
                self.xpath = x.p;
            }
            if out.is_empty() && (self.plen(x.p) > self.plen(*dead) || *dead == NIL) {
                *dead = x.p;
            }
            for (n, ids) in out.drain(..) {
                let p = self.extend(x.p, &ids);
                if n == END {
                    ends.push(p);
                } else if seen.insert(n) {
                    next.push(Thread { t: n, p });
                }
            }
        }
        if next.len() > self.max_threads {
            next.truncate(self.max_threads);
            self.capped = true;
        }
        *th = next;
        (ends, self.fails[mark..].last().copied())
    }

    fn note_dead(&self, b: Option<u16>) -> Note {
        let Some(b) = b else { return Note::new("no_match", format!("no match (cycle {})", self.c), None) };
        let d = &self.bools[b as usize];
        let label = if d.elem == NO_ELEM { d.text.clone() } else { self.a.elements[d.elem as usize].label.clone() };
        if let Some(rest) = label.strip_prefix("##[") {
            if let Some((range, what)) = rest.split_once("] ") {
                return Note::new("range", format!("no {what} within [{range}]"), Some(b));
            }
        }
        Note::new("expected", format!("expected {} at cycle {}", d.text, self.c), Some(b))
    }

    // ---- property instances

    fn inst(&mut self, k: usize, base: u32) -> PS {
        match &self.props[k] {
            CP::Seq { s, .. } => PS::Seq { k, th: vec![Thread { t: *s, p: base }], dead: base, hits: 0 },
            CP::Imp { ante, .. } => PS::Imp { k, ante: vec![Thread { t: *ante, p: base }], dead: base, matched: false, wait: Vec::new(), insts: Vec::new(), vac: true, end: 0, path: NIL, last: None, ends: Vec::new() },
            CP::Not(p) => {
                let p = *p;
                PS::Not(Box::new(self.inst(p, base)))
            }
            CP::Bin { a, b, .. } => {
                let (a, b) = (*a, *b);
                PS::Bin { k, a: Box::new(Slot::Run(self.inst(a, base))), b: Box::new(Slot::Run(self.inst(b, base))) }
            }
            CP::If { .. } => PS::If { k, base },
            CP::Next { n, .. } => PS::Next { k, left: *n, base },
            CP::Always { .. } => PS::Always { k, off: 0, insts: Vec::new(), base, acc: NIL },
            CP::Event { .. } => PS::Event { k, off: 0, insts: Vec::new(), base },
        }
    }

    fn pstep(&mut self, ps: &mut PS) -> Verdict {
        let c = self.c;
        match ps {
            PS::Seq { k, th, dead, hits } => {
                let CP::Seq { all, .. } = self.props[*k] else { unreachable!() };
                let (ends, why) = self.advance(th, dead);
                if !ends.is_empty() {
                    if !all {
                        return Verdict::Pass { vac: false, end: c, path: ends[0] };
                    }
                    *hits += ends.len();
                    self.hits.extend(ends);
                }
                if th.is_empty() {
                    if *hits > 0 {
                        return Verdict::Pass { vac: false, end: c, path: NIL };
                    }
                    return Verdict::Fail { at: c, note: self.note_dead(why), path: *dead };
                }
                Verdict::Pending
            }
            PS::Imp { k, ante, dead, matched, wait, insts, vac, end, path, last, ends: ae } => {
                let CP::Imp { delay, cons, follow, .. } = self.props[*k] else { unreachable!() };
                let mut i = 0;
                while i < wait.len() {
                    if wait[i].0 == c {
                        let (_, p) = wait.remove(i);
                        let s = self.inst(cons, p);
                        insts.push((c, s));
                    } else {
                        i += 1;
                    }
                }
                if !ante.is_empty() {
                    let (ends, _) = self.advance(ante, dead);
                    for p in ends {
                        *matched = true;
                        if ae.last() != Some(&c) {
                            if ae.len() >= 64 {
                                // the first 32, a gap mark (CUT), the latest: the latency needs the latest
                                if ae[32] == CUT {
                                    ae.remove(33);
                                } else {
                                    ae[32] = CUT;
                                }
                            }
                            ae.push(c);
                        }
                        let at = c + delay;
                        if insts.iter().any(|x| x.0 == at) || wait.iter().any(|x| x.0 == at) {
                            continue; // one consequent per start cycle: the first antecedent path is shown
                        }
                        if delay == 0 {
                            let s = self.inst(cons, p);
                            insts.push((c, s));
                        } else {
                            wait.push((at, p));
                        }
                    }
                }
                let mut j = 0;
                while j < insts.len() {
                    match self.pstep(&mut insts[j].1) {
                        Verdict::Pending => j += 1,
                        Verdict::Pass { vac: v, end: e, path: p } => {
                            insts.remove(j);
                            if follow {
                                return Verdict::Pass { vac: false, end: e, path: p };
                            }
                            *vac &= v;
                            *path = self.merge_paths(*path, p); // every consequent's steps: the trace covers start..end
                            *end = (*end).max(e);
                        }
                        Verdict::Fail { at, note, path: p } => {
                            insts.remove(j);
                            if !follow {
                                return Verdict::Fail { at, note, path: p };
                            }
                            *last = Some((at, note, p));
                        }
                    }
                }
                if ante.is_empty() && wait.is_empty() && insts.is_empty() {
                    if follow {
                        let (at, note, p) = last.take().unwrap_or((c, Note::new("no_match", "the antecedent did not match", None), *dead));
                        return Verdict::Fail { at, note, path: p };
                    }
                    if !*matched {
                        return Verdict::Pass { vac: true, end: c, path: NIL };
                    }
                    return Verdict::Pass { vac: *vac, end: *end, path: *path };
                }
                Verdict::Pending
            }
            PS::Not(inner) => match self.pstep(inner) {
                Verdict::Pending => Verdict::Pending,
                Verdict::Pass { path, .. } => Verdict::Fail { at: c, note: Note::new("not_held", "the property under 'not' held", None), path },
                Verdict::Fail { at, path, .. } => Verdict::Pass { vac: false, end: at, path },
            },
            PS::Bin { k, a, b } => {
                let CP::Bin { and, .. } = self.props[*k] else { unreachable!() };
                for s in [&mut **a, &mut **b] {
                    if let Slot::Run(p) = s {
                        let v = self.pstep(p);
                        if !matches!(v, Verdict::Pending) {
                            *s = Slot::Done(v);
                        }
                    }
                }
                match (&**a, &**b) {
                    (Slot::Done(f @ Verdict::Fail { .. }), _) | (_, Slot::Done(f @ Verdict::Fail { .. })) if and => f.clone(),
                    (Slot::Done(p @ Verdict::Pass { vac: false, .. }), _) | (_, Slot::Done(p @ Verdict::Pass { vac: false, .. })) if !and => p.clone(),
                    // or: a vacuous side waits for the other, which may pass for real (the result does not depend on the order)
                    (Slot::Run(_), _) | (_, Slot::Run(_)) if !and => Verdict::Pending,
                    (Slot::Done(p @ Verdict::Pass { .. }), _) | (_, Slot::Done(p @ Verdict::Pass { .. })) if !and => p.clone(),
                    (Slot::Done(Verdict::Pass { vac: va, end: ea, path: pa }), Slot::Done(Verdict::Pass { vac: vb, end: eb, path: pb })) => {
                        let (vac, end) = (*va && *vb, (*ea).max(*eb));
                        let path = self.merge_paths(*pa, *pb);
                        Verdict::Pass { vac, end, path }
                    }
                    (Slot::Done(Verdict::Fail { .. }), Slot::Done(f @ Verdict::Fail { .. })) => f.clone(),
                    _ => Verdict::Pending,
                }
            }
            PS::If { k, base } => {
                let CP::If { c: cond, then, else_ } = self.props[*k] else { unreachable!() };
                let base = *base;
                let xs = self.xs.len();
                let branch = if self.test(cond) { Some(then) } else { else_ };
                if self.xs.len() > xs && self.xpath == NIL {
                    self.xpath = base;
                }
                match branch {
                    None => Verdict::Pass { vac: true, end: c, path: base },
                    Some(q) => {
                        *ps = self.inst(q, base);
                        self.pstep(ps)
                    }
                }
            }
            PS::Next { k, left, base } => {
                if *left > 0 {
                    *left -= 1;
                    return Verdict::Pending;
                }
                let CP::Next { p, .. } = self.props[*k] else { unreachable!() };
                *ps = self.inst(p, *base);
                self.pstep(ps)
            }
            PS::Always { k, off, insts, base, .. } | PS::Event { k, off, insts, base } => {
                let (lo, hi, p, always) = match self.props[*k] {
                    CP::Always { lo, hi, p, .. } => (lo, hi, p, true),
                    CP::Event { lo, hi, p, .. } => (lo, hi, p, false),
                    _ => unreachable!(),
                };
                if *off >= lo && *off <= hi {
                    let s = self.inst(p, *base);
                    insts.push(s);
                }
                let mut j = 0;
                let mut failed = None;
                let mut passed = NIL;
                while j < insts.len() {
                    match self.pstep(&mut insts[j]) {
                        Verdict::Pending => j += 1,
                        v @ Verdict::Pass { .. } => {
                            insts.remove(j);
                            if !always {
                                return v;
                            }
                            if let Verdict::Pass { path, .. } = v {
                                passed = self.merge_paths(passed, path);
                            }
                        }
                        v @ Verdict::Fail { .. } => {
                            insts.remove(j);
                            if always {
                                return v;
                            }
                            failed = Some(v);
                        }
                    }
                }
                *off = off.saturating_add(1);
                let (off, base) = (*off, *base);
                if let PS::Always { acc, .. } = ps {
                    *acc = self.merge_paths(*acc, passed);
                }
                if hi != INF && off > hi && matches!(ps, PS::Always { insts, .. } | PS::Event { insts, .. } if insts.is_empty()) {
                    if let PS::Always { acc, .. } = ps {
                        return Verdict::Pass { vac: false, end: c, path: if *acc == NIL { base } else { *acc } };
                    }
                    let range = if lo == hi { format!("[{lo}]") } else { format!("[{lo}:{hi}]") };
                    return match failed {
                        Some(Verdict::Fail { path, .. }) => Verdict::Fail { at: c, note: Note::new("range", format!("did not hold within {range}"), None), path },
                        _ => Verdict::Fail { at: c, note: Note::new("range", format!("did not hold within {range}"), None), path: base },
                    };
                }
                Verdict::Pending
            }
        }
    }

    /// The longest path of a pending instance: how far it got (the trace of a disabled or active attempt).
    fn progress(&self, ps: &PS) -> u32 {
        let best = |a: u32, b: u32| if self.plen(b) > self.plen(a) { b } else { a };
        let live = |th: &[Thread], dead: u32| match th.iter().fold(NIL, |m, t| best(m, t.p)) {
            NIL => dead,
            p => p,
        };
        match ps {
            PS::Seq { th, dead, .. } => live(th, *dead),
            PS::Imp { ante, dead, wait, insts, .. } => {
                let m = wait.iter().fold(live(ante, *dead), |m, w| best(m, w.1));
                insts.iter().fold(m, |m, (_, s)| best(m, self.progress(s)))
            }
            PS::Not(i) => self.progress(i),
            PS::Bin { a, b, .. } => {
                let f = |s: &Slot| match s {
                    Slot::Run(p) => self.progress(p),
                    Slot::Done(Verdict::Pass { path, .. } | Verdict::Fail { path, .. }) => *path,
                    Slot::Done(Verdict::Pending) => NIL,
                };
                best(f(a), f(b))
            }
            PS::If { base, .. } | PS::Next { base, .. } => *base,
            PS::Always { insts, base, .. } | PS::Event { insts, base, .. } => insts.iter().fold(*base, |m, s| best(m, self.progress(s))),
        }
    }

    /// An instance still pending at the end of the trace that has its result anyway: an `or` with a (vacuous) pass on
    /// one side, an `and` of two such, an implication whose consequents all have one.
    fn settled(&mut self, ps: &PS) -> Option<Verdict> {
        match ps {
            PS::Bin { k, a, b } => {
                let CP::Bin { and, .. } = self.props[*k] else { unreachable!() };
                let mut side = |s: &Slot| match s {
                    Slot::Done(v @ Verdict::Pass { .. }) => Some(v.clone()),
                    Slot::Run(p) => self.settled(p),
                    _ => None,
                };
                let (va, vb) = (side(a), side(b));
                match (va, vb) {
                    (Some(Verdict::Pass { vac: x, end: e1, path: p1 }), Some(Verdict::Pass { vac: y, end: e2, path: p2 })) if and => {
                        Some(Verdict::Pass { vac: x && y, end: e1.max(e2), path: self.merge_paths(p1, p2) })
                    }
                    (v @ Some(_), _) | (_, v @ Some(_)) if !and => v,
                    _ => None,
                }
            }
            PS::Imp { ante, wait, insts, matched, vac, end, path, .. } if ante.is_empty() && wait.is_empty() => {
                let (mut v, mut e, mut p) = (*vac, *end, *path);
                for (_, s) in insts {
                    match self.settled(s)? {
                        Verdict::Pass { vac, end, path } => {
                            v &= vac;
                            e = e.max(end);
                            p = self.merge_paths(p, path);
                        }
                        _ => return None,
                    }
                }
                Some(Verdict::Pass { vac: v || !*matched, end: e, path: p })
            }
            _ => None,
        }
    }

    /// An instance still pending at the end of the trace: `Some(why)` when a strong operator makes it fail.
    fn strong(&self, ps: &PS) -> Option<String> {
        match ps {
            PS::Seq { .. } | PS::Not(_) | PS::If { .. } => None,
            PS::Imp { insts, .. } => insts.iter().find_map(|(_, s)| self.strong(s)),
            PS::Bin { k, a, b } => {
                let CP::Bin { and, .. } = self.props[*k] else { unreachable!() };
                let f = |s: &Slot| match s {
                    Slot::Run(p) => self.strong(p),
                    Slot::Done(Verdict::Fail { note, .. }) => Some(note.text.clone()),
                    Slot::Done(_) => None,
                };
                if and { f(a).or_else(|| f(b)) } else { f(a).and(f(b)) }
            }
            PS::Next { k, .. } => match self.props[*k] {
                CP::Next { strong: true, .. } => Some("no cycle left for s_nexttime before the end of the dump".into()),
                _ => None,
            },
            PS::Always { k, insts, off, .. } => match self.props[*k] {
                CP::Always { strong: true, hi, .. } if *off <= hi => Some("the dump ends inside the range of s_always".into()),
                _ => insts.iter().find_map(|s| self.strong(s)),
            },
            PS::Event { k, .. } => match self.props[*k] {
                CP::Event { strong: true, .. } => Some("not seen before the end of the dump".into()),
                _ => None,
            },
        }
    }

    // ---- compile

    fn cbool(&mut self, e: &Expr, id: Option<&str>, cm: &Compiler) -> CResult<u16> {
        let ce = cm.compile(e, 0)?;
        let elem = id.and_then(|id| self.a.elements.iter().position(|x| x.id == id)).map_or(NO_ELEM, |k| k as u16);
        // the left side of a bus compare is shown with the step
        let show = match e {
            Expr::Binary { op: BinOp::Eq | BinOp::Ne | BinOp::CaseEq | BinOp::CaseNe | BinOp::Lt | BinOp::Le | BinOp::Gt | BinOp::Ge, a, b, .. } => {
                [a, b].into_iter().find_map(|x| cm.compile(x, 0).ok().filter(|c| c.w > 1 && c.constant().is_none()))
            }
            Expr::Inside { a, .. } => cm.compile(a, 0).ok().filter(|c| c.w > 1 && c.constant().is_none()),
            _ => None,
        };
        if self.bools.len() >= TRUNC as usize {
            return Err((e.at(), "too many booleans in one assertion".into()));
        }
        if let Some(r) = self.roles.get_mut(elem as usize) {
            r.get_or_insert(self.role);
        }
        self.bools.push(BoolDef { e: ce, elem, show, text: e.to_string() });
        self.cache.push((-1, Tri::F));
        Ok(self.bools.len() as u16 - 1)
    }

    fn range(r: &crate::ast::Range, at: Span) -> CResult<(u32, u32)> {
        let b = |x: &Bound| match x {
            Bound::Const(n) => Ok(*n),
            Bound::Inf(_) => Ok(INF),
            Bound::Expr(e) => Err((e.at(), format!("the range bound '{e}' is not a constant"))),
        };
        let (lo, hi) = (b(&r.min)?, b(&r.max)?);
        if lo == INF {
            return Err((at, "a range cannot start at $".into()));
        }
        Ok((lo, hi))
    }

    fn cseq(&mut self, s: &Seq, cm: &Compiler) -> CResult<u32> {
        Ok(match s {
            Seq::Bool { id, expr, .. } => {
                let b = self.cbool(expr, id.as_deref(), cm)?;
                self.ar.mk(Term::Bool(b))
            }
            Seq::Delay { lhs, range, rhs, at } => {
                let (lo, hi) = Self::range(range, *at)?;
                let r = self.cseq(rhs, cm)?;
                match lhs {
                    None => self.ar.del(lo, hi, r),
                    Some(l) => {
                        let l = self.cseq(l, cm)?;
                        self.ar.cat(l, lo, hi, r)
                    }
                }
            }
            Seq::Repeat { op, range, seq, at } => {
                let (lo, hi) = Self::range(range, *at)?;
                match op {
                    RepOp::Consec => {
                        let s = self.cseq(seq, cm)?;
                        self.ar.rep(s, lo, hi)
                    }
                    RepOp::Goto | RepOp::NonConsec => {
                        let Seq::Bool { id, expr, .. } = &**seq else { return Err((*at, "goto and non-consecutive repetition need a boolean".into())) };
                        let b = self.cbool(expr, id.as_deref(), cm)?;
                        if *op == RepOp::Goto { self.ar.goto(b, lo, hi) } else { self.ar.mk(Term::Non { b, lo, hi }) }
                    }
                }
            }
            Seq::Binary { op, a, b, .. } => {
                let (x, y) = (self.cseq(a, cm)?, self.cseq(b, cm)?);
                match op {
                    SeqOp::Or => self.ar.mk(Term::Or(x, y)),
                    SeqOp::And => self.ar.mk(Term::And(x, y)),
                    SeqOp::Intersect => self.ar.mk(Term::Isect(x, y)),
                    SeqOp::Within => {
                        // a within b = (1[*0:$] ##1 a ##1 1[*0:$]) intersect b
                        let any = self.ar.rep(ANY, 0, INF);
                        let tail = self.ar.cat(x, 1, 1, any);
                        let w = self.ar.cat(any, 1, 1, tail);
                        self.ar.mk(Term::Isect(w, y))
                    }
                }
            }
            Seq::Throughout { cond, seq, at } => {
                let Seq::Bool { id, expr, .. } = &**cond else { return Err((*at, "throughout needs a boolean on its left".into())) };
                let saved = self.role;
                self.role.0 = "cond";
                let b = self.cbool(expr, id.as_deref(), cm)?;
                self.role = saved;
                let s = self.cseq(seq, cm)?;
                self.ar.mk(Term::Thr { b, s })
            }
            Seq::FirstMatch { seq, .. } => {
                let s = self.cseq(seq, cm)?;
                self.ar.mk(Term::First(vec![s]))
            }
            Seq::Instance { body: Some(b), .. } => self.cseq(b, cm)?,
            Seq::Instance { name, at, .. } => return Err((*at, format!("'{name}' is not expanded"))),
        })
    }

    fn cprop(&mut self, p: &Prop, all: bool, cm: &Compiler) -> CResult<usize> {
        let cp = match p {
            Prop::Seq { seq } => CP::Seq { s: self.cseq(seq, cm)?, all },
            Prop::Implies { op, ante, cons, .. } => {
                let saved = self.role;
                self.role = ("ante", Some(self.imps));
                self.imps += 1;
                let ante = self.cseq(ante, cm)?;
                self.role.0 = "cons";
                let cons = self.cprop(cons, false, cm)?;
                self.role = saved;
                let delay = matches!(op, ImpOp::NonOverlap | ImpOp::FollowNonOverlap) as usize;
                CP::Imp { ante, delay, cons, follow: matches!(op, ImpOp::FollowOverlap | ImpOp::FollowNonOverlap) }
            }
            Prop::Not { p, .. } => CP::Not(self.cprop(p, false, cm)?),
            Prop::Binary { op, a, b, .. } => CP::Bin { and: *op == PropOp::And, a: self.cprop(a, false, cm)?, b: self.cprop(b, false, cm)? },
            Prop::If { cond, then, else_, .. } => {
                let c = self.cbool(cond, None, cm)?;
                let then = self.cprop(then, false, cm)?;
                let else_ = match else_ {
                    Some(e) => Some(self.cprop(e, false, cm)?),
                    None => None,
                };
                CP::If { c, then, else_ }
            }
            Prop::Nexttime { strong, n, p, at } => {
                let n = match n {
                    Bound::Const(n) => *n,
                    _ => return Err((*at, "nexttime needs a constant count".into())),
                };
                CP::Next { n, strong: *strong, p: self.cprop(p, false, cm)? }
            }
            Prop::Always { strong, range, p, at } => {
                let (lo, hi) = match range {
                    Some(r) => Self::range(r, *at)?,
                    None => (0, INF),
                };
                CP::Always { lo, hi, strong: *strong, p: self.cprop(p, false, cm)? }
            }
            Prop::Eventually { strong, range, p, at } => {
                let (lo, hi) = match range {
                    Some(r) => Self::range(r, *at)?,
                    None => (0, INF),
                };
                CP::Event { lo, hi, strong: *strong, p: self.cprop(p, false, cm)? }
            }
            Prop::Instance { body: Some(b), .. } => return self.cprop(b, all, cm),
            Prop::Instance { name, at, .. } => return Err((*at, format!("'{name}' is not expanded"))),
        };
        self.props.push(cp);
        Ok(self.props.len() - 1)
    }

    /// The trace of these steps, and whether some were dropped.
    fn steps(&self, v: &[(u16, usize)]) -> (Vec<TraceStep>, bool) {
        let mut cut = false;
        let mut t: Vec<TraceStep> = v
            .iter()
            .filter(|(b, _)| {
                cut |= *b == TRUNC;
                *b != TRUNC
            })
            .map(|&(b, cycle)| {
                let d = &self.bools[b as usize];
                let value = d.show.as_ref().map(|e| value_json(e.eval(&self.cols, cycle as i64), e.w));
                TraceStep { id: self.a.elements[d.elem as usize].id.clone(), cycle, value }
            })
            .collect();
        if cut && t.len() > HEAD + TAIL {
            t.drain(HEAD..t.len() - TAIL); // a path grows to PATH_MAX before it is cut again: the same length every time
        }
        (t, cut)
    }
}

/// The terms a pending instance holds (its threads), for the term arena's collection.
fn visit_terms(ps: &mut PS, f: &mut dyn FnMut(&mut u32)) {
    match ps {
        PS::Seq { th, .. } => th.iter_mut().for_each(|t| f(&mut t.t)),
        PS::Imp { ante, insts, .. } => {
            ante.iter_mut().for_each(|t| f(&mut t.t));
            insts.iter_mut().for_each(|(_, p)| visit_terms(p, f));
        }
        PS::Not(i) => visit_terms(i, f),
        PS::Bin { a, b, .. } => {
            for x in [a, b] {
                if let Slot::Run(p) = &mut **x {
                    visit_terms(p, f);
                }
            }
        }
        PS::If { .. } | PS::Next { .. } => {}
        PS::Always { insts, .. } | PS::Event { insts, .. } => insts.iter_mut().for_each(|p| visit_terms(p, f)),
    }
}

/// The paths a pending instance holds (threads, waiting consequents, decided sides), for the arena's collection.
fn visit(ps: &mut PS, f: &mut dyn FnMut(&mut u32)) {
    match ps {
        PS::Seq { th, dead, .. } => {
            th.iter_mut().for_each(|t| f(&mut t.p));
            f(dead);
        }
        PS::Imp { ante, dead, wait, insts, path, last, .. } => {
            ante.iter_mut().for_each(|t| f(&mut t.p));
            f(dead);
            wait.iter_mut().for_each(|w| f(&mut w.1));
            insts.iter_mut().for_each(|(_, p)| visit(p, f));
            f(path);
            if let Some((_, _, p)) = last {
                f(p);
            }
        }
        PS::Not(i) => visit(i, f),
        PS::Bin { a, b, .. } => {
            for x in [a, b] {
                match &mut **x {
                    Slot::Run(p) => visit(p, f),
                    Slot::Done(Verdict::Pass { path, .. } | Verdict::Fail { path, .. }) => f(path),
                    Slot::Done(Verdict::Pending) => {}
                }
            }
        }
        PS::If { base, .. } | PS::Next { base, .. } => f(base),
        PS::Always { insts, base, acc, .. } => {
            f(base);
            f(acc);
            insts.iter_mut().for_each(|p| visit(p, f));
        }
        PS::Event { insts, base, .. } => {
            f(base);
            insts.iter_mut().for_each(|p| visit(p, f));
        }
    }
}

fn vsig(v: &Verdict, c: u64, s: &mut Vec<u64>) {
    match v {
        Verdict::Pending => s.push(0),
        Verdict::Pass { vac, end, .. } => s.extend([1, *vac as u64, c.wrapping_sub(*end as u64)]),
        Verdict::Fail { at, note, .. } => s.extend([2, c.wrapping_sub(*at as u64), fnv(&note.text)]),
    }
}

fn fnv(s: &str) -> u64 {
    s.bytes().fold(0xcbf29ce484222325, |h, b| (h ^ b as u64).wrapping_mul(0x100000001b3))
}

/// A bus value for the results: a number when it is known (and exact in JSON), else the binary digits with x.
pub(crate) fn value_json(v: V, w: u32) -> serde_json::Value {
    if v.x == 0 && v.v < 1 << 53 {
        v.v.into()
    } else if v.x == 0 {
        format!("h{:x}", v.v).into()
    } else {
        v.bits(w).into()
    }
}

pub(crate) fn prop_text(mut p: &Prop) -> String {
    while let Prop::Instance { body: Some(b), .. } = p {
        p = b;
    }
    Printer { full: false, inline: true }.prop(p)
}

/// The steps of a trace: (boolean, cycle).
type Steps = Vec<(u16, usize)>;

struct Rec {
    start: usize,
    end: usize,
    result: Status,
    steps: Vec<(u16, usize)>,
    failed_at: Option<usize>,
    note: Option<Note>,
    ante: Vec<usize>,
}

/// One attempt of a group: where its own steps end (`prefix`, up to cycle `since` - 1); from `since` on it shares the
/// steps of the group's first attempt. `ante`: the antecedent matches of its own (before `since`).
struct Member {
    start: usize,
    prefix: u32,
    since: usize,
    ante: Vec<usize>,
}

/// Pending attempts in the same state: stepped once for all of them. `x`: the first unknown boolean it read (the
/// boolean, the cycle, the path that read it); `capped`: the thread limit dropped some of its threads.
struct Group {
    ps: PS,
    members: Vec<Member>,
    x: Option<(u16, usize, u32)>,
    capped: bool,
}

/// Evaluate one assertion over the trace. Signals the trace does not have are listed in `missing` (nothing else is
/// done); a construct the evaluator cannot run is an error at its position.
pub fn evaluate(a: &Assertion, tr: &Trace, opt: &Options) -> Result<Outcome, SvaError> {
    let mut out = Outcome {
        name: a.label.clone(),
        kind: a.kind,
        file: None,
        line: a.line,
        text: a.text.clone(),
        scope: None,
        signals: BTreeMap::new(),
        clock: None,
        cycles: None,
        steps: Vec::new(),
        stats: Stats::default(),
        attempts: Vec::new(),
        lane: None,
        missing: Vec::new(),
        notes: Vec::new(),
    };
    let names: Vec<&str> = a.signals.iter().skip(1).map(|s| s.name.as_str()).collect(); // the clock first
    out.missing = names.iter().filter(|n| !tr.signals.contains_key(**n)).map(|n| n.to_string()).collect();
    if !out.missing.is_empty() {
        return Ok(out);
    }
    let cols = Cols(names.iter().map(|n| &tr.signals[*n]).collect());
    for (n, c) in names.iter().zip(&cols.0) {
        if let Some(w) = tr.warnings.get(*n) {
            out.notes.push(w.clone());
        }
        if c.len() < tr.cycles.min(opt.to.unwrap_or(usize::MAX)) && !out.notes.iter().any(|x| x.starts_with(&format!("{n}: "))) {
            out.notes.push(format!("{n}: {} values for {} cycles; the later cycles read its initial value ({})", c.len(), tr.cycles, if c.two_state { "0" } else { "x" }));
        }
    }
    let sig = |n: &str| names.iter().position(|x| *x == n).map(|k| (k, cols.0[k].width));
    let cm = Compiler { sig: &sig };
    let mut e = Eng {
        a,
        cols: Cols(cols.0.clone()),
        bools: Vec::new(),
        cache: Vec::new(),
        props: Vec::new(),
        ar: Arena::new(),
        paths: Vec::new(),
        c: 0,
        xmode: opt.x,
        max_threads: opt.max_threads.max(1),
        fails: Vec::new(),
        xs: Vec::new(),
        capped: false,
        xpath: NIL,
        hits: Vec::new(),
        role: ("seq", None),
        imps: 0,
        roles: vec![None; a.elements.len()],
    };
    let err = |(at, msg): (Span, String)| SvaError::new(at, format!("{}: {msg}", a.label));
    let cover_seq = a.flags.iter().any(|f| f.starts_with("cover sequence"));
    let root = e.cprop(&a.prop, cover_seq, &cm).map_err(err)?;
    out.steps = a.elements.iter().zip(&e.roles).map(|(x, r)| {
        let (role, group) = r.unwrap_or(("seq", None));
        StepInfo { id: x.id.clone(), label: x.label.clone(), role, group }
    }).collect();
    let disable = match &a.disable {
        Some(d) => Some(cm.compile(d, 0).map_err(err)?),
        None => None,
    };
    let cover = a.kind == Kind::Cover;
    let end = opt.to.unwrap_or(tr.cycles).min(tr.cycles);
    let mut groups: Vec<Group> = Vec::new();
    let mut recs: Vec<Rec> = Vec::new();
    let mut cover_hits: Vec<(usize, usize, Steps)> = Vec::new();
    let mut matches = 0usize;
    let mut gc_at = 1usize << 16;
    let mut term_gc_at = TERM_GC_FLOOR;
    let xnote = |e: &Eng, b: u16, at: usize| Note::new("unknown", format!("{} is unknown (x) at cycle {at}", e.bools[b as usize].text), Some(b));
    let xpass = |e: &Eng, b: u16, at: usize| {
        Note::new("unknown", format!("{} is unknown (x) at cycle {at}, read as false: the attempt passed with it", e.bools[b as usize].text), Some(b))
    };
    let capped_note = |e: &Eng| Note::new("capped", format!("thread limit {} reached: some matches were not followed, the result is not known", e.max_threads), None);
    // the antecedent matches of one attempt of a group: its own, then the group's from `since` on
    let ante = |m: &Member, ps: &PS| {
        let mut v = m.ante.clone();
        if let PS::Imp { ends, .. } = ps {
            v.extend(ends.iter().filter(|c| **c >= m.since));
        }
        v
    };
    // a decided group: one record per attempt. x reads as false; a non-vacuous pass stands, any other result of an
    // attempt that read an unknown fails naming it (option x: "false" keeps the IEEE result)
    let rec = |e: &Eng, g: &Group, v: &Verdict, c: usize, recs: &mut Vec<Rec>| {
        for m in &g.members {
            let r = |result, end, p, failed_at, note| Rec { start: m.start, end, result, steps: e.member_path(m, p), failed_at, note, ante: ante(m, &g.ps) };
            recs.push(match (v, g.x) {
                _ if g.capped => {
                    let p = match v {
                        Verdict::Pass { path, .. } | Verdict::Fail { path, .. } => *path,
                        Verdict::Pending => NIL,
                    };
                    r(Status::Capped, c, p, None, Some(capped_note(e)))
                }
                // a pass that read an unknown (an x that chose the else branch of an if, an operand of an or …): it
                // stands, with a note naming the unknown, so a pass decided by an x is not silent
                (Verdict::Pass { vac: false, end, path }, x) => r(Status::Pass, *end, *path, None, x.map(|(b, at, _)| xpass(e, b, at))),
                (_, Some((b, at, p))) => r(Status::Fail, c, p, Some(at), Some(xnote(e, b, at))),
                (Verdict::Pass { end, .. }, None) => r(Status::Vacuous, *end, NIL, None, None),
                (Verdict::Fail { at, note, path }, None) => r(Status::Fail, *at, *path, Some(*at), Some(note.clone())),
                (Verdict::Pending, None) => unreachable!(),
            });
        }
    };
    for c in 0..end {
        e.c = c;
        if let Some(d) = &disable {
            if d.eval(&e.cols, c as i64).truth() == Tri::T {
                for g in groups.drain(..) {
                    let p = e.progress(&g.ps);
                    for m in &g.members {
                        recs.push(Rec { start: m.start, end: c, result: Status::Disabled, steps: e.member_path(m, p), failed_at: None, note: None, ante: ante(m, &g.ps) });
                    }
                }
                continue;
            }
        }
        if c >= opt.from {
            groups.push(Group { ps: e.inst(root, NIL), members: vec![Member { start: c, prefix: NIL, since: 0, ante: Vec::new() }], x: None, capped: false });
            out.stats.attempts += 1;
        }
        let keep_hits = cover_hits.len() < opt.cover_traces;
        let mut i = 0;
        while i < groups.len() {
            e.xs.clear();
            e.fails.clear();
            e.capped = false;
            e.xpath = NIL;
            let v = e.pstep(&mut groups[i].ps);
            if e.capped {
                groups[i].capped = true;
            }
            if let (XMode::Fail, None, Some(&b)) = (e.xmode, groups[i].x, e.xs.first()) {
                let p = if e.bools[b as usize].elem == NO_ELEM { e.xpath } else { e.extend(e.xpath, &[b]) };
                groups[i].x = Some((b, c, p));
            }
            let g = &groups[i];
            for p in std::mem::take(&mut e.hits) {
                matches += g.members.len();
                if keep_hits {
                    for m in &g.members {
                        cover_hits.push((m.start, c, e.member_path(m, p)));
                    }
                }
            }
            if e.capped && out.notes.len() < 10 {
                out.notes.push(format!("thread limit {} reached at cycle {c} (attempt {}): some matches were not followed", e.max_threads, g.members[0].start));
            }
            if let Verdict::Pending = v {
                i += 1;
                continue;
            }
            rec(&e, &groups[i], &v, c, &mut recs);
            groups.remove(i);
        }
        // attempts in the same state go on as one: their steps from here are the same
        if opt.merge && groups.len() > 1 {
            let mut seen: HashMap<Vec<u64>, usize> = HashMap::new();
            let mut kept: Vec<Group> = Vec::with_capacity(groups.len());
            for g in std::mem::take(&mut groups) {
                let mut sg = vec![g.capped as u64];
                match g.x {
                    Some((b, at, _)) => sg.extend([1, b as u64, (c - at) as u64]),
                    None => sg.push(0),
                }
                e.sig(&g.ps, &mut sg);
                match seen.get(&sg) {
                    Some(&j) => {
                        let p = e.progress(&g.ps);
                        for m in &g.members {
                            let v = e.member_path(m, p);
                            let prefix = e.chain(&v);
                            kept[j].members.push(Member { start: m.start, prefix, since: c + 1, ante: ante(m, &g.ps) });
                        }
                    }
                    None => {
                        seen.insert(sg, kept.len());
                        kept.push(g);
                    }
                }
            }
            groups = kept;
        }
        if e.paths.len() > gc_at {
            e.gc(&mut groups);
            gc_at = (2 * e.paths.len()).max(1 << 16);
        }
        if e.ar.terms.len() > term_gc_at {
            e.gc_terms(&mut groups);
            term_gc_at = (2 * e.ar.terms.len()).max(TERM_GC_FLOOR);
        }
    }
    let last = end.saturating_sub(1);
    for g in std::mem::take(&mut groups).iter() {
        let p = e.progress(&g.ps);
        let strong = e.strong(&g.ps);
        if strong.is_none() {
            if let Some(v) = e.settled(&g.ps) {
                rec(&e, g, &v, last, &mut recs);
                continue;
            }
        }
        let x = g.x.map(|(b, at, _)| xnote(&e, b, at));
        let p = g.x.map_or(p, |x| x.2); // with an unknown: the steps up to it
        for m in &g.members {
            let r = |result, failed_at, note| Rec { start: m.start, end: last, result, steps: e.member_path(m, p), failed_at, note, ante: ante(m, &g.ps) };
            recs.push(match &strong {
                _ if g.capped => r(Status::Capped, None, Some(capped_note(&e))),
                Some(note) => {
                    let text = match &x {
                        Some(x) => format!("{note}; {}", x.text),
                        None => note.clone(),
                    };
                    r(Status::Fail, Some(last), Some(Note::new("strong_end", text, None)))
                }
                None => r(Status::Active, None, x.clone()),
            });
        }
    }
    recs.sort_by_key(|r| (r.start, r.end));
    let st = &mut out.stats;
    for r in &recs {
        match r.result {
            Status::Pass => st.pass += 1,
            Status::Fail => st.fail += 1,
            Status::Vacuous => st.vacuous += 1,
            Status::Active => st.active += 1,
            Status::Disabled => st.disabled += 1,
            Status::Capped => st.capped += 1,
        }
    }
    if cover {
        st.matches = Some(if cover_seq { matches } else { st.pass });
    }
    let mut lane = vec![b'.'; if opt.lane { end } else { 0 }];
    let rank = |ch: u8| b".SPCDF".iter().position(|&x| x == ch).unwrap_or(0);
    let mut mark = |k: usize, ch: u8| {
        if let Some(x) = lane.get_mut(k) {
            if rank(ch) > rank(*x) {
                *x = ch;
            }
        }
    };
    for r in &recs {
        if r.result == Status::Vacuous || (cover && r.result == Status::Fail) {
            continue;
        }
        mark(r.start, b'S');
        match r.result {
            Status::Pass => mark(r.end, b'P'),
            Status::Fail => mark(r.end, b'F'),
            Status::Disabled => mark(r.end, b'D'),
            Status::Capped => mark(r.end, b'C'),
            _ => {}
        }
    }
    if opt.lane {
        out.lane = Some(String::from_utf8(lane).unwrap());
    }
    let attempt = |r: &Rec| {
        let (trace, truncated) = e.steps(&r.steps);
        let reason = r.note.as_ref().map(|n| Reason {
            kind: n.kind,
            step: n.b.map(|b| e.bools[b as usize].elem).filter(|el| *el != NO_ELEM).map(|el| a.elements[el as usize].id.clone()),
            cycle: r.failed_at.unwrap_or(r.end),
        });
        let note = r.note.as_ref().map(|n| n.text.clone());
        Attempt { start: r.start, end: r.end, result: r.result, trace, truncated, failed_at: r.failed_at, note, reason,
            ante_end: r.ante.iter().copied().filter(|c| *c != CUT).collect(), ante_truncated: r.ante.contains(&CUT) }
    };
    out.attempts = if cover_seq {
        cover_hits.sort_by_key(|h| (h.1, h.0));
        cover_hits
            .iter()
            .take(opt.cover_traces)
            .map(|(start, end, p)| {
                let (trace, truncated) = e.steps(p);
                Attempt { start: *start, end: *end, result: Status::Pass, trace, truncated, failed_at: None, note: None, reason: None, ante_end: Vec::new(), ante_truncated: false }
            })
            .collect()
    } else if cover {
        recs.iter().filter(|r| r.result == Status::Pass).take(opt.cover_traces).map(attempt).collect()
    } else {
        recs.iter().filter(|r| opt.vacuous || r.result != Status::Vacuous).map(attempt).collect()
    };
    Ok(out)
}

/// Evaluate every assertion of `asserts` (or the ones named in `only`) over one trace.
pub fn evaluate_all(asserts: &[Assertion], tr: &Trace, opt: &Options, only: &[String]) -> Result<Results, Vec<SvaError>> {
    // the cycles of the window (as the CLI's): a time after `to` is not one of them
    let shown = tr.times[..opt.to.unwrap_or(tr.times.len()).min(tr.times.len())].to_vec();
    let mut res = Results { clock: String::new(), unit: tr.unit.clone().unwrap_or_else(|| "ps".into()), cycles: shown, assertions: Vec::new() };
    let mut errors = Vec::new();
    let mut bad = |m: String| errors.push(SvaError::new(Span::default(), m));
    for name in only {
        if !asserts.iter().any(|a| &a.label == name) {
            bad(format!("no assertion '{name}'"));
        }
    }
    if opt.max_threads == 0 {
        bad("options.max_threads: at least 1".into());
    }
    if opt.to.is_some_and(|t| t < opt.from) {
        bad(format!("options.to ({}) is before options.from ({}): nothing to check", opt.to.unwrap_or(0), opt.from));
    }
    let chosen: Vec<&Assertion> = asserts.iter().filter(|a| only.is_empty() || only.contains(&a.label)).collect();
    // one trace is sampled at the edges of one clock: assertions on another clock need a request of their own
    if let Some(a0) = chosen.first() {
        let other: Vec<&str> = chosen.iter().filter(|a| a.clock.signal != a0.clock.signal || a.clock.edge != a0.clock.edge).map(|a| a.label.as_str()).collect();
        if !other.is_empty() {
            bad(format!("one request, one clock: {} on @({} {}), {} on another (one request per clock)", a0.label, a0.clock.edge, a0.clock.signal, other.join(", ")));
        }
    }
    if !errors.is_empty() {
        return Err(errors);
    }
    for a in chosen {
        if res.clock.is_empty() {
            res.clock = a.clock.signal.clone();
        }
        match evaluate(a, tr, opt) {
            Ok(o) => res.assertions.push(o),
            Err(e) => errors.push(e),
        }
    }
    if errors.is_empty() { Ok(res) } else { Err(errors) }
}

#[cfg(test)]
#[path = "engine_tests.rs"]
mod tests;
