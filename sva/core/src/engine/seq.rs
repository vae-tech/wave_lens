//! Sequences: residual sequences as hash-consed terms in an arena, and one cycle of a term (`step`): a thread set
//! advances by stepping each thread's term against the booleans of the cycle (docs/sva/ENGINE.md *Sequences*).

use super::*;

// ---------------------------------------------------------------- sequence terms

pub(super) const INF: u32 = u32::MAX;
/// The term arena is collected when it has twice the terms of the last collection, at least this many (in the tests a
/// few: every test then runs through collections).
#[cfg(not(test))]
pub(super) const TERM_GC_FLOOR: usize = 1 << 16;
#[cfg(test)]
pub(super) const TERM_GC_FLOOR: usize = 8;
/// A step output: the term matched at this cycle.
pub(super) const END: u32 = u32::MAX;
/// A side of `and` that has matched.
pub(super) const DONE: u32 = u32::MAX - 1;
pub(super) const EMPTY: u32 = 0;
pub(super) const ANY: u32 = 1;

pub(super) fn dec(n: u32) -> u32 {
    if n == INF { INF } else { n - 1 }
}
pub(super) fn sat(n: u32) -> u32 {
    if n == INF { INF } else { n.saturating_sub(1) }
}

/// A sequence that starts at the cycle it is stepped at.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(super) enum Term {
    /// Matches empty only.
    Empty,
    /// Matches any one cycle (`1`).
    Any,
    Bool(u16),
    /// `l ##[lo:hi] r`.
    Cat { l: u32, lo: u32, hi: u32, r: u32 },
    /// `##[lo:hi] r`: `r` starts `lo` to `hi` cycles from now.
    Del { lo: u32, hi: u32, r: u32 },
    Rep { s: u32, lo: u32, hi: u32 },
    Goto { b: u16, lo: u32, hi: u32 },
    Non { b: u16, lo: u32, hi: u32 },
    Or(u32, u32),
    /// Either side may be [`DONE`].
    And(u32, u32),
    Isect(u32, u32),
    Thr { b: u16, s: u32 },
    /// The threads of one `first_match` (sorted).
    First(Vec<u32>),
}

pub(super) struct Arena {
    pub(super) terms: Vec<Term>,
    pub(super) nullable: Vec<bool>,
    pub(super) ids: HashMap<Term, u32>,
}

impl Arena {
    pub(super) fn new() -> Arena {
        let mut a = Arena { terms: Vec::new(), nullable: Vec::new(), ids: HashMap::new() };
        a.mk(Term::Empty);
        a.mk(Term::Any);
        a
    }
    pub(super) fn null(&self, t: u32) -> bool {
        t == DONE || self.nullable[t as usize]
    }
    pub(super) fn mk(&mut self, t: Term) -> u32 {
        if let Some(&i) = self.ids.get(&t) {
            return i;
        }
        let n = match &t {
            Term::Empty => true,
            Term::Any | Term::Bool(_) => false,
            Term::Cat { l, lo, hi, r } => self.null(*l) && self.null(*r) && *lo <= 1 && *hi >= 1,
            Term::Del { lo, r, .. } => *lo == 0 && self.null(*r),
            Term::Rep { lo, .. } | Term::Goto { lo, .. } | Term::Non { lo, .. } => *lo == 0,
            Term::Or(a, b) => self.null(*a) || self.null(*b),
            Term::And(a, b) | Term::Isect(a, b) => self.null(*a) && self.null(*b),
            Term::Thr { s, .. } => self.null(*s),
            Term::First(v) => v.iter().any(|x| self.null(*x)),
        };
        let i = self.terms.len() as u32;
        self.terms.push(t.clone());
        self.nullable.push(n);
        self.ids.insert(t, i);
        i
    }
    /// The terms a term is made of (DONE and END are no terms).
    pub(super) fn kids(t: &Term, out: &mut Vec<u32>) {
        match t {
            Term::Empty | Term::Any | Term::Bool(_) | Term::Goto { .. } | Term::Non { .. } => {}
            Term::Cat { l, r, .. } => out.extend([*l, *r]),
            Term::Del { r, .. } | Term::Rep { s: r, .. } | Term::Thr { s: r, .. } => out.push(*r),
            Term::Or(a, b) | Term::And(a, b) | Term::Isect(a, b) => out.extend([*a, *b]),
            Term::First(v) => out.extend(v.iter().copied()),
        }
    }
    /// Keep the terms reachable from `roots` (and EMPTY, ANY), in their order (a term's parts are older than it, so
    /// the order stays valid) -> the new number of every old term (NIL: dropped).
    pub(super) fn compact(&mut self, roots: impl Iterator<Item = u32>) -> Vec<u32> {
        let n = self.terms.len();
        let mut mark = vec![false; n];
        let mut stack: Vec<u32> = roots.chain([EMPTY, ANY]).collect();
        let mut kids = Vec::new();
        while let Some(t) = stack.pop() {
            if (t as usize) >= n || mark[t as usize] {
                continue;
            }
            mark[t as usize] = true;
            Arena::kids(&self.terms[t as usize], &mut kids);
            stack.append(&mut kids);
        }
        let mut map = vec![NIL; n];
        let old = std::mem::replace(self, Arena { terms: Vec::new(), nullable: Vec::new(), ids: HashMap::new() });
        let re = |t: u32, map: &[u32]| if (t as usize) < n { map[t as usize] } else { t };
        for (i, t) in old.terms.into_iter().enumerate() {
            if !mark[i] {
                continue;
            }
            let t = match t {
                Term::Cat { l, lo, hi, r } => Term::Cat { l: re(l, &map), lo, hi, r: re(r, &map) },
                Term::Del { lo, hi, r } => Term::Del { lo, hi, r: re(r, &map) },
                Term::Rep { s, lo, hi } => Term::Rep { s: re(s, &map), lo, hi },
                Term::Thr { b, s } => Term::Thr { b, s: re(s, &map) },
                Term::Or(a, b) => Term::Or(re(a, &map), re(b, &map)),
                Term::And(a, b) => Term::And(re(a, &map), re(b, &map)),
                Term::Isect(a, b) => Term::Isect(re(a, &map), re(b, &map)),
                Term::First(v) => Term::First(v.into_iter().map(|x| re(x, &map)).collect()),
                t => t,
            };
            map[i] = self.terms.len() as u32;
            self.ids.insert(t.clone(), map[i]);
            self.terms.push(t);
            self.nullable.push(old.nullable[i]);
        }
        map
    }
    pub(super) fn cat(&mut self, l: u32, lo: u32, hi: u32, r: u32) -> u32 {
        if r == EMPTY && lo <= 1 && hi >= 1 {
            return l; // `l ##1 empty` is `l`
        }
        self.mk(Term::Cat { l, lo, hi, r })
    }
    pub(super) fn del(&mut self, lo: u32, hi: u32, r: u32) -> u32 {
        if lo == 0 && hi == 0 {
            return r;
        }
        self.mk(Term::Del { lo, hi, r })
    }
    pub(super) fn rep(&mut self, s: u32, lo: u32, hi: u32) -> u32 {
        // s can match empty: any of the lo iterations can be empty, so s[*lo:hi] matches what s[*0:hi] matches (IEEE
        // 1800-2017 16.9.2; (a[*0:1])[*2] is a[*0:2])
        let lo = if self.null(s) { 0 } else { lo };
        if hi == 0 { EMPTY } else { self.mk(Term::Rep { s, lo, hi }) }
    }
    pub(super) fn goto(&mut self, b: u16, lo: u32, hi: u32) -> u32 {
        if hi == 0 { EMPTY } else { self.mk(Term::Goto { b, lo, hi }) }
    }
}


pub(super) fn merge_ids(a: &[u16], b: &[u16]) -> Vec<u16> {
    let mut v = a.to_vec();
    v.extend(b.iter().filter(|x| !a.contains(x)));
    v
}


/// The steps of the sequences: the booleans of a cycle, one cycle of a term.
impl Eng<'_> {
    pub(super) fn test(&mut self, b: u16) -> bool {
        let c = self.c as i64;
        let slot = &mut self.cache[b as usize];
        let t = if slot.0 == c {
            slot.1
        } else {
            let t = self.bools[b as usize].e.eval(&self.cols, c).truth();
            *slot = (c, t);
            t
        };
        match t {
            Tri::T => true,
            Tri::F => {
                self.fails.push(b);
                false
            }
            Tri::X if self.xmode == XMode::False => {
                self.fails.push(b);
                false
            }
            Tri::X => {
                self.xs.push(b);
                false
            }
        }
    }

    pub(super) fn ids(&self, b: u16) -> Vec<u16> {
        if self.bools[b as usize].elem == NO_ELEM { Vec::new() } else { vec![b] }
    }

    
    pub(super) fn step(&mut self, t: u32, out: &mut Out) {
        let term = self.ar.terms[t as usize].clone();
        match term {
            Term::Empty => {}
            Term::Any => out.push((END, Vec::new())),
            Term::Bool(b) => {
                if self.test(b) {
                    out.push((END, self.ids(b)));
                }
            }
            Term::Del { lo, hi, r } => {
                if lo == 0 {
                    self.step(r, out);
                }
                if hi >= 1 {
                    if lo <= 1 && self.ar.null(r) {
                        out.push((END, Vec::new()));
                    }
                    if r != EMPTY {
                        let d = self.ar.del(sat(lo), dec(hi), r);
                        out.push((d, Vec::new()));
                    }
                }
            }
            Term::Cat { l, lo, hi, r } => {
                let mut tmp = Vec::new();
                self.step(l, &mut tmp);
                for (n, ids) in tmp {
                    if n == END {
                        self.then(lo, hi, r, ids, out);
                    } else {
                        let k = self.ar.cat(n, lo, hi, r);
                        out.push((k, ids));
                    }
                }
                // an empty match of `l`: `empty ##n r` is `##(n-1) r`
                if hi >= 1 && self.ar.null(l) {
                    let d = self.ar.del(lo.max(1) - 1, dec(hi), r);
                    self.step(d, out);
                }
            }
            Term::Rep { s, lo, hi } => {
                let rest = self.ar.rep(s, sat(lo), dec(hi));
                let mut tmp = Vec::new();
                self.step(s, &mut tmp);
                for (n, ids) in tmp {
                    if n == END {
                        if lo <= 1 {
                            out.push((END, ids.clone()));
                        }
                        if rest != EMPTY {
                            out.push((rest, ids));
                        }
                    } else {
                        let k = self.ar.cat(n, 1, 1, rest);
                        out.push((k, ids));
                    }
                }
            }
            Term::Goto { b, lo, hi } => {
                if self.test(b) {
                    let ids = self.ids(b);
                    if lo <= 1 {
                        out.push((END, ids.clone()));
                    }
                    let g = self.ar.goto(b, sat(lo), dec(hi));
                    if g != EMPTY {
                        out.push((g, ids));
                    }
                } else {
                    out.push((t, Vec::new()));
                }
            }
            Term::Non { b, lo, hi } => {
                if self.test(b) {
                    if hi >= 1 {
                        let ids = self.ids(b);
                        if lo <= 1 {
                            out.push((END, ids.clone()));
                        }
                        let n = self.ar.mk(Term::Non { b, lo: sat(lo), hi: dec(hi) });
                        out.push((n, ids));
                    }
                } else {
                    if lo == 0 {
                        out.push((END, Vec::new()));
                    }
                    out.push((t, Vec::new()));
                }
            }
            Term::Or(a, b) => {
                self.step(a, out);
                self.step(b, out);
            }
            Term::And(a, b) => {
                let sa = self.side(a);
                let sb = self.side(b);
                for (na, ia) in &sa {
                    for (nb, ib) in &sb {
                        let ids = merge_ids(ia, ib);
                        if *na == DONE && *nb == DONE {
                            out.push((END, ids));
                        } else {
                            let k = self.ar.mk(Term::And(*na, *nb));
                            out.push((k, ids));
                        }
                    }
                }
            }
            Term::Isect(a, b) => {
                let (mut sa, mut sb) = (Vec::new(), Vec::new());
                self.step(a, &mut sa);
                if sa.is_empty() {
                    return;
                }
                self.step(b, &mut sb);
                for (na, ia) in &sa {
                    for (nb, ib) in &sb {
                        let ids = merge_ids(ia, ib);
                        match (*na == END, *nb == END) {
                            (true, true) => out.push((END, ids)),
                            (false, false) => {
                                let k = self.ar.mk(Term::Isect(*na, *nb));
                                out.push((k, ids));
                            }
                            _ => {}
                        }
                    }
                }
            }
            Term::Thr { b, s } => {
                if !self.test(b) {
                    return;
                }
                // the condition held at this cycle: in the trace with the inner sequence's steps (its row is drawn)
                let cond = self.ids(b);
                let mut tmp = Vec::new();
                self.step(s, &mut tmp);
                for (n, ids) in tmp {
                    let k = if n == END { END } else { self.ar.mk(Term::Thr { b, s: n }) };
                    out.push((k, merge_ids(&cond, &ids)));
                }
            }
            Term::First(v) => {
                let mut tmp = Vec::new();
                for x in v {
                    self.step(x, &mut tmp);
                }
                if let Some(e) = tmp.iter().find(|o| o.0 == END) {
                    out.push((END, e.1.clone()));
                    return;
                }
                let mut set: Vec<u32> = tmp.iter().map(|o| o.0).collect();
                set.sort_unstable();
                set.dedup();
                if set.len() > self.max_threads {
                    set.truncate(self.max_threads);
                    self.capped = true;
                }
                if !set.is_empty() {
                    // the steps of every thread of the first_match: they all lead to its one match
                    let ids = tmp.iter().fold(Vec::new(), |acc, o| merge_ids(&acc, &o.1));
                    let k = self.ar.mk(Term::First(set));
                    out.push((k, ids));
                }
            }
        }
    }

    /// `l` matched at this cycle (with `ids`): `r` starts `lo` to `hi` cycles later.
    pub(super) fn then(&mut self, lo: u32, hi: u32, r: u32, ids: Vec<u16>, out: &mut Out) {
        if lo == 0 {
            let mut tmp = Vec::new();
            self.step(r, &mut tmp);
            for (n, more) in tmp {
                out.push((n, merge_ids(&ids, &more)));
            }
        }
        if hi >= 1 {
            if lo <= 1 && self.ar.null(r) {
                out.push((END, ids.clone()));
            }
            if r != EMPTY {
                let d = self.ar.del(lo.max(1) - 1, dec(hi), r);
                out.push((d, ids));
            }
        }
    }

    pub(super) fn side(&mut self, t: u32) -> Out {
        if t == DONE {
            return vec![(DONE, Vec::new())];
        }
        let mut o = Vec::new();
        self.step(t, &mut o);
        for x in &mut o {
            if x.0 == END {
                x.0 = DONE;
            }
        }
        o
    }

}
