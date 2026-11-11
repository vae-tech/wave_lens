//! The engine against a brute-force reference matcher over random sequences and random traces (bughunt 2026-11-10:
//! the checker's matcher found B-01 and confirmed B-02, B-04, B-07). The reference computes, for a start cycle, every
//! end cycle of a match straight from the definitions of docs/sva/ENGINE.md (*Empty matches*: `empty ##n s` is
//! `##(n-1) s`, `s ##n empty` is `s ##(n-1) 1`, `##0` with an empty side does not match, `and` / `intersect` / `within`
//! need both operands to match a cycle); an end of `start - 1` is an empty match. Checked:
//! - `cover sequence (S)`: the listed (start, end) pairs and the count are the reference's, each match once;
//! - `a |-> S`, `a |=> S`: an attempt passes, at the first match, exactly when the reference has a match;
//! - attempts in the same state merged (the default) give what the attempts stepped one by one give.

use std::collections::BTreeSet;
use sva_core::{evaluate, parse, Column, Options, Outcome, Status, Trace};

const INF: u32 = u32::MAX;
const SIGS: [&str; 3] = ["a", "b", "c"];

#[derive(Clone, Debug)]
enum S {
    /// A signal, maybe negated.
    B(usize, bool),
    /// `1` (the left side of a leading delay; not generated).
    T,
    Cat(Box<S>, u32, u32, Box<S>),
    /// `##[lo:hi] r`, lo >= 1 (a leading `##0` is left out: the engine reads it as `r`).
    Del(u32, u32, Box<S>),
    Rep(Box<S>, u32, u32),
    Goto(usize, u32, u32),
    Non(usize, u32, u32),
    Or(Box<S>, Box<S>),
    And(Box<S>, Box<S>),
    Isect(Box<S>, Box<S>),
    Within(Box<S>, Box<S>),
    Thr(usize, bool, Box<S>),
    First(Box<S>),
}

fn range(lo: u32, hi: u32) -> String {
    match hi {
        INF => format!("{lo}:$"),
        _ if hi == lo => format!("{lo}"),
        _ => format!("{lo}:{hi}"),
    }
}

fn delay(lo: u32, hi: u32) -> String {
    if lo == hi { format!("##{lo}") } else { format!("##[{}]", range(lo, hi)) }
}

fn lit(k: usize, neg: bool) -> String {
    format!("{}{}", if neg { "!" } else { "" }, SIGS[k])
}

impl S {
    fn text(&self) -> String {
        let p = |s: &S| match s {
            S::B(..) | S::T | S::Goto(..) | S::Non(..) => s.text(),
            _ => format!("({})", s.text()),
        };
        match self {
            S::B(k, n) => lit(*k, *n),
            S::T => "1".into(),
            S::Cat(l, lo, hi, r) => format!("{} {} {}", p(l), delay(*lo, *hi), p(r)),
            S::Del(lo, hi, r) => format!("{} {}", delay(*lo, *hi), p(r)),
            S::Rep(s, lo, hi) => match **s {
                S::B(..) | S::T => format!("{}[*{}]", s.text(), range(*lo, *hi)),
                _ => format!("({})[*{}]", s.text(), range(*lo, *hi)),
            },
            S::Goto(k, lo, hi) => format!("{}[->{}]", SIGS[*k], range(*lo, *hi)),
            S::Non(k, lo, hi) => format!("{}[={}]", SIGS[*k], range(*lo, *hi)),
            S::Or(a, b) => format!("{} or {}", p(a), p(b)),
            S::And(a, b) => format!("{} and {}", p(a), p(b)),
            S::Isect(a, b) => format!("{} intersect {}", p(a), p(b)),
            S::Within(a, b) => format!("{} within {}", p(a), p(b)),
            S::Thr(k, n, s) => format!("{} throughout {}", lit(*k, *n), p(s)),
            S::First(s) => format!("first_match({})", s.text()),
        }
    }
}

struct Tr {
    n: i64,
    v: Vec<Vec<bool>>,
}

impl Tr {
    fn at(&self, k: usize, neg: bool, t: i64) -> bool {
        t >= 0 && t < self.n && self.v[k][t as usize] != neg
    }
    /// The cycles from `i` on where signal k is 1.
    fn hits(&self, k: usize, i: i64) -> Vec<i64> {
        (i.max(0)..self.n).filter(|t| self.at(k, false, *t)).collect()
    }
}

/// Every end of a match of `s` started at `i` (`i - 1`: empty), ends after the trace left out.
fn ends(s: &S, i: i64, tr: &Tr) -> BTreeSet<i64> {
    let n = tr.n;
    let mut out = BTreeSet::new();
    match s {
        S::B(k, neg) => {
            if tr.at(*k, *neg, i) {
                out.insert(i);
            }
        }
        S::Cat(l, lo, hi, r) => {
            for j in ends(l, i, tr) {
                let hi = if *hi == INF { n as u32 + 1 } else { *hi };
                for k in *lo..=hi {
                    let (k, st) = (k as i64, j + k as i64);
                    if (k == 0 && j == i - 1) || st > n {
                        continue;
                    }
                    for e in ends(r, st, tr) {
                        if !(k == 0 && e == st - 1) {
                            out.insert(e);
                        }
                    }
                }
            }
        }
        S::T => {
            if i < n {
                out.insert(i);
            }
        }
        // `##[m:n] r` is `1 ##[m:n] r`
        S::Del(lo, hi, r) => return ends(&S::Cat(Box::new(S::T), *lo, *hi, r.clone()), i, tr),
        S::Rep(x, lo, hi) => {
            let mut cur = BTreeSet::from([i - 1]);
            let top = if *hi == INF { n as u32 + 2 } else { *hi };
            for c in 0..=top {
                if c >= *lo {
                    out.extend(cur.iter().copied());
                }
                let mut next = BTreeSet::new();
                for j in &cur {
                    if *j < n {
                        next.extend(ends(x, j + 1, tr));
                    }
                }
                cur = next;
            }
        }
        S::Goto(k, lo, hi) => {
            let h = tr.hits(*k, i);
            if *lo == 0 {
                out.insert(i - 1);
            }
            for (c, t) in h.iter().enumerate() {
                let c = c as u32 + 1;
                if c >= *lo && c <= *hi {
                    out.insert(*t);
                }
            }
        }
        S::Non(k, lo, hi) => {
            let h = tr.hits(*k, i);
            for c in *lo..=(*hi).min(h.len() as u32) {
                let from = if c == 0 { i - 1 } else { h[c as usize - 1] };
                let to = h.get(c as usize).copied().unwrap_or(n); // exclusive
                out.extend(from..to);
            }
        }
        S::Or(a, b) => {
            out = ends(a, i, tr);
            out.extend(ends(b, i, tr));
        }
        S::And(a, b) => {
            let (ea, eb) = (ends(a, i, tr), ends(b, i, tr));
            for x in ea.iter().filter(|x| **x >= i) {
                for y in eb.iter().filter(|y| **y >= i) {
                    out.insert(*x.max(y));
                }
            }
        }
        S::Isect(a, b) => out = ends(a, i, tr).intersection(&ends(b, i, tr)).copied().filter(|e| *e >= i).collect(),
        S::Within(x, y) => {
            for j in ends(y, i, tr).into_iter().filter(|j| *j >= i) {
                if (i..=j).any(|p| ends(x, p, tr).iter().any(|q| *q >= p && *q <= j)) {
                    out.insert(j);
                }
            }
        }
        S::Thr(k, neg, x) => {
            for e in ends(x, i, tr) {
                if (i..=e).all(|t| tr.at(*k, *neg, t)) {
                    out.insert(e);
                }
            }
        }
        S::First(x) => {
            if let Some(e) = ends(x, i, tr).into_iter().next() {
                out.insert(e);
            }
        }
    }
    out.retain(|e| *e < n);
    out
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
    fn range(&mut self, max_lo: u32) -> (u32, u32) {
        let lo = self.below(max_lo as u64 + 1) as u32;
        if self.below(6) == 0 { (lo, INF) } else { (lo, lo + self.below(3) as u32) }
    }
    fn sig(&mut self) -> usize {
        self.below(SIGS.len() as u64) as usize
    }
    fn seq(&mut self, depth: u32) -> S {
        let leaf = depth == 0 || self.below(4) == 0;
        if leaf {
            return match self.below(6) {
                0 => {
                    let (lo, hi) = self.range(2);
                    S::Goto(self.sig(), lo, hi.max(1).max(lo))
                }
                1 => {
                    let (lo, hi) = self.range(2);
                    S::Non(self.sig(), lo, hi)
                }
                2 => {
                    let (lo, hi) = self.range(2);
                    S::Rep(Box::new(S::B(self.sig(), false)), lo, hi)
                }
                _ => S::B(self.sig(), self.below(4) == 0),
            };
        }
        let sub = |r: &mut Rng| Box::new(r.seq(depth - 1));
        match self.below(11) {
            0..=2 => {
                let (lo, hi) = self.range(2);
                S::Cat(sub(self), lo, hi, sub(self))
            }
            3 => {
                let (lo, hi) = self.range(2);
                S::Del(lo.max(1), hi.max(lo.max(1)), sub(self))
            }
            4 => {
                let (lo, hi) = self.range(2);
                S::Rep(sub(self), lo, hi)
            }
            5 => S::Or(sub(self), sub(self)),
            6 => S::And(sub(self), sub(self)),
            7 => S::Isect(sub(self), sub(self)),
            8 => S::Within(sub(self), sub(self)),
            9 => S::Thr(self.sig(), self.below(3) == 0, sub(self)),
            _ => S::First(sub(self)),
        }
    }
}

fn trace(tr: &Tr) -> Trace {
    let mut t = Trace::default();
    for (k, name) in SIGS.iter().enumerate() {
        t.add(name, Column::known(1, &tr.v[k].iter().map(|b| *b as u64).collect::<Vec<_>>()));
    }
    t.add("s", Column::known(1, &vec![1; tr.n as usize]));
    t
}

fn run(src: &str, t: &Trace, merge: bool) -> Outcome {
    let p = parse(src);
    assert!(p.errors.is_empty(), "{src}: {:?}", p.errors);
    let opt = Options { cover_traces: 100_000, merge, ..Options::default() };
    evaluate(&p.assertions[0], t, &opt).unwrap()
}

fn shape(o: &Outcome) -> Vec<(usize, usize, Status)> {
    o.attempts.iter().map(|a| (a.start, a.end, a.result)).collect()
}

#[test]
fn the_engine_agrees_with_the_reference_matcher() {
    let mut rng = Rng(0x9e37_79b9_7f4a_7c15);
    let (mut checked, mut capped) = (0, 0);
    let mut bad: Vec<String> = Vec::new();
    for _ in 0..1500 {
        let s = rng.seq(3);
        let text = s.text();
        for _ in 0..3 {
            let n = 10 + rng.below(8) as i64;
            let density = 20 + rng.below(60);
            let v: Vec<Vec<bool>> = SIGS.iter().map(|_| (0..n).map(|_| rng.below(100) < density).collect()).collect();
            let tr = Tr { n, v };
            let t = trace(&tr);
            let bits = SIGS.iter().enumerate().map(|(k, s)| {
                format!("{s}={}", tr.v[k].iter().map(|b| if *b { '1' } else { '0' }).collect::<String>())
            }).collect::<Vec<_>>().join(" ");
            // cover sequence: every (start, end), each once
            let src = format!("c: cover sequence (@(posedge clk) {text});");
            let o = run(&src, &t, true);
            if !o.notes.is_empty() {
                capped += 1;
                continue;
            }
            let mut got: Vec<(usize, usize)> = o.attempts.iter().map(|a| (a.start, a.end)).collect();
            got.sort();
            let want: Vec<(usize, usize)> =
                (0..n).flat_map(|i| ends(&s, i, &tr).into_iter().filter(move |e| *e >= i).map(move |e| (i as usize, e as usize))).collect();
            let mut set = got.clone();
            set.dedup();
            if set != want {
                bad.push(format!("set: cover sequence ({text}) over {bits}: got {set:?}, want {want:?}"));
            } else if got != want || o.stats.matches != Some(want.len()) {
                bad.push(format!("count: cover sequence ({text}) over {bits}: {} listed, {:?} counted, want {}", got.len(), o.stats.matches, want.len()));
            }
            let one = run(&src, &t, false);
            if shape(&one) != shape(&o) || one.stats != o.stats {
                bad.push(format!("merge: cover sequence ({text}) over {bits}: merged and one by one differ"));
            }
            // implications with the sequence as the consequent: a pass exactly at the reference's first match
            for (op, d) in [("|->", 0), ("|=>", 1)] {
                let src = format!("t: assert property (@(posedge clk) a {op} {});", if matches!(s, S::B(..)) { text.clone() } else { format!("({text})") });
                let o = run(&src, &t, true);
                if !o.notes.is_empty() {
                    capped += 1;
                    continue;
                }
                for at in &o.attempts {
                    let j = at.start as i64 + d;
                    let first = if j < n { ends(&s, j, &tr).into_iter().find(|e| *e >= j) } else { None };
                    let ok = match (at.result, first) {
                        (Status::Pass, Some(e)) => e as usize == at.end,
                        (Status::Fail | Status::Active, None) => true,
                        _ => false,
                    };
                    if !ok {
                        bad.push(format!("verdict: a {op} ({text}) over {bits}: attempt {} {:?} at {}, the reference's first match {first:?}", at.start, at.result, at.end));
                    }
                }
                let listed: BTreeSet<usize> = o.attempts.iter().map(|a| a.start).collect();
                let want: BTreeSet<usize> = (0..n as usize).filter(|i| tr.v[0][*i]).collect();
                if listed != want {
                    bad.push(format!("verdict: a {op} ({text}) over {bits}: attempts {listed:?}, want {want:?}"));
                }
                let one = run(&src, &t, false);
                if shape(&one) != shape(&o) || one.stats != o.stats || one.lane != o.lane {
                    bad.push(format!("merge: a {op} ({text}) over {bits}: merged and one by one differ"));
                }
                checked += 1;
            }
        }
    }
    let mut kinds: Vec<&str> = bad.iter().map(|b| b.split(':').next().unwrap()).collect();
    kinds.sort();
    kinds.dedup();
    let firsts: Vec<String> = kinds.iter().flat_map(|k| bad.iter().filter(move |b| b.starts_with(&format!("{k}:"))).take(3).cloned()).collect();
    assert!(bad.is_empty(), "{} disagreements ({kinds:?}), the first of each kind:\n{}", bad.len(), firsts.join("\n"));
    assert!(checked > 6000 && capped < checked / 20, "checked {checked}, capped {capped}");
}
