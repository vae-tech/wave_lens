//! 4-state values and the expressions of an assertion compiled for evaluation at a cycle.
//!
//! A value is at most 64 bits: `v` holds the known bits, `x` the unknown ones (x or z: the dump's z reads as x). Widths
//! follow IEEE 1800-2017 11.6 in a reduced form: arithmetic and bitwise operators take the larger width of their
//! operands and of the context, comparisons extend both sides to the larger one, logical operators, reductions,
//! concatenation items and system-function arguments are self-determined; everything is unsigned.

use crate::ast::{BinOp, Expr, InsideItem, SelKind, UnOp};
use crate::lex::Span;

pub(crate) fn mask(w: u32) -> u64 {
    if w >= 64 {
        u64::MAX
    } else {
        (1u64 << w) - 1
    }
}

/// A sampled value: bit k is unknown when `x` has it, else it is bit k of `v` (`v` is 0 at the unknown bits).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct V {
    pub v: u64,
    pub x: u64,
}

/// The truth of a boolean: false, true, or unknown (some bit x and none known 1).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tri {
    F,
    T,
    X,
}

impl Tri {
    fn not(self) -> Tri {
        match self {
            Tri::F => Tri::T,
            Tri::T => Tri::F,
            Tri::X => Tri::X,
        }
    }
    fn v(self) -> V {
        match self {
            Tri::F => V::known(0),
            Tri::T => V::known(1),
            Tri::X => V { v: 0, x: 1 },
        }
    }
}

impl V {
    pub fn new(v: u64, x: u64) -> V {
        V { v: v & !x, x }
    }
    pub const fn known(v: u64) -> V {
        V { v, x: 0 }
    }
    pub fn unknown(w: u32) -> V {
        V { v: 0, x: mask(w) }
    }
    fn fit(self, w: u32) -> V {
        V { v: self.v & mask(w), x: self.x & mask(w) }
    }
    fn zeros(self, w: u32) -> u64 {
        !self.v & !self.x & mask(w)
    }
    pub fn truth(self) -> Tri {
        if self.v != 0 {
            Tri::T
        } else if self.x != 0 {
            Tri::X
        } else {
            Tri::F
        }
    }
    /// `0101`, `1x0x`: the low `w` bits, most significant first.
    pub fn bits(self, w: u32) -> String {
        (0..w.clamp(1, 64)).rev().map(|k| if self.x >> k & 1 == 1 { 'x' } else if self.v >> k & 1 == 1 { '1' } else { '0' }).collect()
    }
    /// A value of the trace JSON: a number, or a string of binary digits (`"10x1"`, `"x"`) or of hex digits after
    /// `h` (`"h1f"`, `"hx"`); `z` reads as `x`. `None` when the text is not a value.
    pub fn parse(s: &str) -> Option<(V, u32)> {
        let s = s.trim().replace('_', "");
        let (digits, bpd) = match s.strip_prefix(['h', 'H']) {
            Some(h) => (h.to_string(), 4),
            None => (s.clone(), 1),
        };
        if digits.is_empty() {
            return None;
        }
        let (mut v, mut x) = (0u64, 0u64);
        for c in digits.chars() {
            let (d, u) = match c.to_ascii_lowercase() {
                'x' | 'z' | 'u' | 'w' | '-' => (0, mask(bpd)),
                'h' if bpd == 1 => (1, 0), // nine-valued weak 1 / 0
                'l' if bpd == 1 => (0, 0),
                c => (c.to_digit(1 << bpd)? as u64, 0),
            };
            v = v.checked_shl(bpd).unwrap_or(0) | d;
            x = x.checked_shl(bpd).unwrap_or(0) | u;
        }
        Some((V::new(v, x), (digits.len() as u32 * bpd).min(64)))
    }
}

/// A compiled expression: its width and what it computes.
#[derive(Clone, Debug)]
pub(crate) struct CE {
    pub w: u32,
    pub op: Op,
}

#[derive(Clone, Debug)]
pub(crate) enum Op {
    Sig(usize),
    Lit(V),
    Un(UnOp, Box<CE>),
    Bin(BinOp, Box<CE>, Box<CE>),
    Cond(Box<CE>, Box<CE>, Box<CE>),
    /// `base[lsb +: w]` with `lsb` computed (bit select: w = 1).
    Sel(Box<CE>, Box<CE>),
    /// `base[lsb +: w]` with `lsb = index - (w - 1)`.
    SelDown(Box<CE>, Box<CE>),
    Concat(Vec<CE>),
    Inside(Box<CE>, Vec<(CE, Option<CE>)>),
    Past(Box<CE>, u32),
    Rose(Box<CE>),
    Fell(Box<CE>),
    Stable(Box<CE>),
    Changed(Box<CE>),
    OneHot(Box<CE>),
    OneHot0(Box<CE>),
    CountOnes(Box<CE>),
    IsUnknown(Box<CE>),
    Clog2(Box<CE>),
    /// The operand at its own width, then cut to (or extended to) the node's width.
    Resize(Box<CE>),
}

/// Columns of sampled values, one per signal of the assertion; cycles before 0 read the initial value.
pub(crate) trait Samples {
    fn get(&self, sig: usize, cycle: i64) -> V;
}

impl CE {
    fn lit(v: V, w: u32) -> CE {
        CE { w, op: Op::Lit(v.fit(w)) }
    }

    /// The value when the expression reads no signal (a select bound, a replication count).
    pub fn constant(&self) -> Option<u64> {
        struct None_;
        impl Samples for None_ {
            fn get(&self, _: usize, _: i64) -> V {
                V::unknown(64)
            }
        }
        match self.reads_signals() {
            false => match self.eval(&None_, 0) {
                V { v, x: 0 } => Some(v),
                _ => None,
            },
            true => None,
        }
    }

    fn reads_signals(&self) -> bool {
        let any = |v: &[&CE]| v.iter().any(|e| e.reads_signals());
        match &self.op {
            Op::Sig(_) => true,
            Op::Lit(_) => false,
            Op::Un(_, a) | Op::Past(a, _) | Op::Rose(a) | Op::Fell(a) | Op::Stable(a) | Op::Changed(a) | Op::OneHot(a) | Op::OneHot0(a) | Op::CountOnes(a) | Op::IsUnknown(a) | Op::Clog2(a) | Op::Resize(a) => a.reads_signals(),
            Op::Bin(_, a, b) | Op::Sel(a, b) | Op::SelDown(a, b) => any(&[a, b]),
            Op::Cond(c, a, b) => any(&[c, a, b]),
            Op::Concat(v) => v.iter().any(|e| e.reads_signals()),
            Op::Inside(a, set) => a.reads_signals() || set.iter().any(|(l, h)| l.reads_signals() || h.as_ref().is_some_and(|h| h.reads_signals())),
        }
    }

    pub fn eval(&self, s: &dyn Samples, c: i64) -> V {
        let w = self.w;
        let m = mask(w);
        let ev = |e: &CE| e.eval(s, c);
        match &self.op {
            Op::Sig(k) => s.get(*k, c).fit(w),
            Op::Lit(v) => *v,
            Op::Un(op, a) => {
                let x = ev(a);
                match op {
                    UnOp::Not => x.truth().not().v(),
                    UnOp::BitNot => V { v: !x.v & !x.x & m, x: x.x & m },
                    UnOp::Neg if x.x != 0 => V::unknown(w),
                    UnOp::Neg => V::known(x.v.wrapping_neg() & m),
                    UnOp::Plus => x.fit(w),
                    UnOp::RedAnd | UnOp::RedNand => {
                        let t = if x.zeros(a.w) != 0 { Tri::F } else if x.x != 0 { Tri::X } else { Tri::T };
                        if *op == UnOp::RedNand { t.not().v() } else { t.v() }
                    }
                    UnOp::RedOr | UnOp::RedNor => {
                        let t = x.truth();
                        if *op == UnOp::RedNor { t.not().v() } else { t.v() }
                    }
                    UnOp::RedXor | UnOp::RedXnor => {
                        if x.x != 0 {
                            Tri::X.v()
                        } else {
                            V::known((x.v.count_ones() as u64 & 1) ^ (*op == UnOp::RedXnor) as u64)
                        }
                    }
                }
            }
            Op::Bin(op, a, b) => bin(*op, ev(a), ev(b), a.w.max(b.w), w),
            Op::Cond(k, a, b) => match ev(k).truth() {
                Tri::T => ev(a),
                Tri::F => ev(b),
                Tri::X => {
                    let (a, b) = (ev(a), ev(b));
                    let same = !(a.v ^ b.v) & !a.x & !b.x & m;
                    V { v: a.v & same, x: m & !same }
                }
            },
            Op::Sel(base, lsb) | Op::SelDown(base, lsb) => {
                let l = ev(lsb);
                if l.x != 0 {
                    return V::unknown(w);
                }
                let lo = if matches!(self.op, Op::SelDown(..)) { l.v as i64 - (w as i64 - 1) } else { l.v as i64 };
                let b = ev(base);
                // bits outside the base read x
                let (mut v, mut x) = (0, 0);
                for k in 0..w as i64 {
                    let i = lo + k;
                    if i < 0 || i >= base.w as i64 {
                        x |= 1 << k;
                    } else {
                        v |= (b.v >> i & 1) << k;
                        x |= (b.x >> i & 1) << k;
                    }
                }
                V { v, x }
            }
            Op::Concat(items) => {
                let (mut v, mut x) = (0u64, 0u64);
                for e in items {
                    let y = ev(e);
                    v = v.checked_shl(e.w).unwrap_or(0) | y.v;
                    x = x.checked_shl(e.w).unwrap_or(0) | y.x;
                }
                V { v: v & m, x: x & m }
            }
            Op::Inside(a, set) => {
                let y = ev(a);
                let mut t = Tri::F;
                for (lo, hi) in set {
                    let ww = a.w.max(lo.w).max(hi.as_ref().map_or(0, |h| h.w));
                    let r = match hi {
                        None => wild_eq(y, ev(lo)),
                        Some(hi) => and3(bin(BinOp::Ge, y, ev(lo), ww, 1).truth(), bin(BinOp::Le, y, ev(hi), ww, 1).truth()),
                    };
                    t = or3(t, r);
                    if t == Tri::T {
                        break;
                    }
                }
                t.v()
            }
            Op::Past(a, n) => a.eval(s, c - *n as i64).fit(w),
            Op::Rose(a) | Op::Fell(a) => {
                let (now, then) = (ev(a), a.eval(s, c - 1));
                let bit = |v: V| if v.x & 1 == 1 { 2 } else { v.v & 1 };
                let want = matches!(self.op, Op::Rose(_)) as u64;
                V::known((bit(now) == want && bit(then) != want) as u64)
            }
            Op::Stable(a) | Op::Changed(a) => {
                let same = ev(a) == a.eval(s, c - 1);
                V::known((same == matches!(self.op, Op::Stable(_))) as u64)
            }
            Op::OneHot(a) => V::known((ev(a).v.count_ones() == 1) as u64),
            Op::OneHot0(a) => V::known((ev(a).v.count_ones() <= 1) as u64),
            Op::CountOnes(a) => V::known(ev(a).v.count_ones() as u64),
            Op::IsUnknown(a) => V::known((ev(a).x != 0) as u64),
            Op::Clog2(a) => {
                let y = ev(a);
                if y.x != 0 {
                    V::unknown(w)
                } else {
                    V::known(if y.v <= 1 { 0 } else { 64 - (y.v - 1).leading_zeros() as u64 })
                }
            }
            Op::Resize(a) => ev(a).fit(w),
        }
    }
}

fn and3(a: Tri, b: Tri) -> Tri {
    match (a, b) {
        (Tri::F, _) | (_, Tri::F) => Tri::F,
        (Tri::T, Tri::T) => Tri::T,
        _ => Tri::X,
    }
}

fn or3(a: Tri, b: Tri) -> Tri {
    match (a, b) {
        (Tri::T, _) | (_, Tri::T) => Tri::T,
        (Tri::F, Tri::F) => Tri::F,
        _ => Tri::X,
    }
}

/// `==?` (what `inside` uses, IEEE 1800-2017 11.4.13): unknown bits of the set item `b` match anything.
fn wild_eq(a: V, b: V) -> Tri {
    let care = !b.x;
    cmp_eq(V::new(a.v & care, a.x & care), V::new(b.v & care, 0))
}

fn cmp_eq(a: V, b: V) -> Tri {
    if (a.v ^ b.v) & !a.x & !b.x != 0 {
        Tri::F
    } else if a.x | b.x != 0 {
        Tri::X
    } else {
        Tri::T
    }
}

/// `a op b`: `ow` is the width of the operands, `w` the width of the result.
fn bin(op: BinOp, a: V, b: V, ow: u32, w: u32) -> V {
    use BinOp::*;
    let m = mask(w);
    let any_x = a.x | b.x != 0;
    match op {
        LogAnd => and3(a.truth(), b.truth()).v(),
        LogOr => or3(a.truth(), b.truth()).v(),
        Eq => cmp_eq(a, b).v(),
        Ne => cmp_eq(a, b).not().v(),
        CaseEq => V::known((a == b) as u64),
        CaseNe => V::known((a != b) as u64),
        Lt | Le | Gt | Ge if any_x => Tri::X.v(),
        Lt => V::known((a.v < b.v) as u64),
        Le => V::known((a.v <= b.v) as u64),
        Gt => V::known((a.v > b.v) as u64),
        Ge => V::known((a.v >= b.v) as u64),
        BitAnd => {
            let ones = a.v & b.v;
            let zeros = a.zeros(ow) | b.zeros(ow);
            V { v: ones & m, x: m & !(ones | zeros) }
        }
        BitOr => {
            let ones = a.v | b.v;
            let zeros = a.zeros(ow) & b.zeros(ow);
            V { v: ones & m, x: m & !(ones | zeros) }
        }
        BitXor | BitXnor => {
            let x = (a.x | b.x) & m;
            let v = if op == BitXor { a.v ^ b.v } else { !(a.v ^ b.v) };
            V { v: v & !x & m, x }
        }
        Shl | Shr | AShl | AShr => {
            if b.x != 0 {
                return V::unknown(w);
            }
            let n = b.v.min(64) as u32;
            if matches!(op, Shl | AShl) {
                V { v: a.v.checked_shl(n).unwrap_or(0) & m, x: a.x.checked_shl(n).unwrap_or(0) & m }
            } else {
                V { v: a.v.checked_shr(n).unwrap_or(0), x: a.x.checked_shr(n).unwrap_or(0) }
            }
        }
        _ if any_x => V::unknown(w),
        Add => V::known(a.v.wrapping_add(b.v) & m),
        Sub => V::known(a.v.wrapping_sub(b.v) & m),
        Mul => V::known(a.v.wrapping_mul(b.v) & m),
        Div => a.v.checked_div(b.v).map_or(V::unknown(w), |v| V::known(v & m)),
        Mod => a.v.checked_rem(b.v).map_or(V::unknown(w), |v| V::known(v & m)),
        Pow => V::known(a.v.wrapping_pow(b.v.min(u32::MAX as u64) as u32) & m),
    }
}

/// Compiles the expressions of one assertion: `sig` gives the column and width of a signal name.
pub(crate) struct Compiler<'a> {
    pub sig: &'a dyn Fn(&str) -> Option<(usize, u32)>,
}

pub(crate) type CResult<T> = Result<T, (Span, String)>;

fn lit_width(value: u64, width: Option<u32>) -> u32 {
    width.unwrap_or_else(|| (64 - value.leading_zeros()).max(32)).clamp(1, 64)
}

fn is_ctx(op: BinOp) -> bool {
    use BinOp::*;
    matches!(op, Add | Sub | Mul | Div | Mod | BitAnd | BitOr | BitXor | BitXnor)
}

impl Compiler<'_> {
    /// The self-determined width of `e`.
    pub fn width(&self, e: &Expr) -> CResult<u32> {
        let w = |x: &Expr| self.width(x);
        Ok(match e {
            Expr::Ident { name, at } => match (self.sig)(name) {
                Some((_, w)) => w,
                None => return Err((*at, format!("no signal '{name}'"))),
            },
            Expr::Const { value, width, .. } => lit_width(*value as u64 & mask(width.unwrap_or(64)), *width),
            Expr::Number { value, width, .. } => lit_width(*value, *width),
            Expr::Fill { .. } => 1,
            Expr::Unary { op: UnOp::BitNot | UnOp::Neg | UnOp::Plus, a, .. } => w(a)?,
            Expr::Unary { .. } => 1,
            Expr::Binary { op, a, b, .. } => match op {
                _ if is_ctx(*op) => w(a)?.max(w(b)?),
                BinOp::Pow | BinOp::Shl | BinOp::Shr | BinOp::AShl | BinOp::AShr => w(a)?,
                _ => 1,
            },
            Expr::Cond { a, b, .. } => w(a)?.max(w(b)?),
            Expr::Select { sel, index, lsb, at, .. } => match (sel, lsb) {
                (SelKind::Bit, _) | (_, None) => 1,
                (SelKind::Part, Some(l)) => {
                    let (m, l) = (self.konst(index)?, self.konst(l)?);
                    (m.abs_diff(l) + 1).min(64) as u32
                }
                (_, Some(n)) => match self.konst(n)? {
                    n @ 1..=64 => n as u32,
                    n => return Err((*at, format!("a select of {n} bits (1 to 64 are evaluated)"))),
                },
            },
            Expr::Concat { items, .. } => items.iter().map(w).sum::<CResult<u32>>()?.min(64),
            Expr::Repl { count, items, .. } => (self.konst(count)? as u32).saturating_mul(items.iter().map(w).sum::<CResult<u32>>()?).min(64),
            Expr::Inside { .. } => 1,
            Expr::Call { func, args, .. } => match func.as_str() {
                "$past" | "$sampled" => w(&args[0])?,
                "$countones" | "$bits" | "$clog2" => 32,
                _ => 1,
            },
            Expr::Cast { width, .. } => (*width).clamp(1, 64),
        })
    }

    fn konst(&self, e: &Expr) -> CResult<u64> {
        let c = self.compile(e, 1)?;
        c.constant().ok_or_else(|| (e.at(), format!("'{e}' must be a constant here")))
    }

    /// `e` evaluated at width `max(its own, ctx)` where the operator takes the context.
    pub fn compile(&self, e: &Expr, ctx: u32) -> CResult<CE> {
        let own = self.width(e)?;
        let w = own.max(ctx).min(64);
        let bx = |x: CE| Box::new(x);
        Ok(match e {
            Expr::Ident { name, .. } => {
                let (k, sw) = (self.sig)(name).unwrap();
                let s = CE { w: sw, op: Op::Sig(k) };
                if w == sw { s } else { CE { w, op: Op::Resize(bx(s)) } }
            }
            Expr::Const { value, .. } => CE::lit(V::known(*value as u64), w),
            Expr::Number { value, unknown, .. } => CE::lit(V::new(*value, *unknown), w),
            Expr::Fill { bit, .. } => {
                let w = ctx.max(1);
                CE::lit(match bit {
                    '0' => V::known(0),
                    '1' => V::known(mask(w)),
                    _ => V::unknown(w),
                }, w)
            }
            Expr::Unary { op, a, .. } => match op {
                UnOp::BitNot | UnOp::Neg | UnOp::Plus => CE { w, op: Op::Un(*op, bx(self.compile(a, w)?)) },
                _ => CE { w: 1, op: Op::Un(*op, bx(self.compile(a, 0)?)) },
            },
            Expr::Binary { op, a, b, .. } => {
                use BinOp::*;
                match op {
                    _ if is_ctx(*op) => CE { w, op: Op::Bin(*op, bx(self.compile(a, w)?), bx(self.compile(b, w)?)) },
                    Pow | Shl | Shr | AShl | AShr => CE { w, op: Op::Bin(*op, bx(self.compile(a, w)?), bx(self.compile(b, 0)?)) },
                    LogAnd | LogOr => CE { w: 1, op: Op::Bin(*op, bx(self.compile(a, 0)?), bx(self.compile(b, 0)?)) },
                    _ => {
                        let ow = self.width(a)?.max(self.width(b)?);
                        CE { w: 1, op: Op::Bin(*op, bx(self.compile(a, ow)?), bx(self.compile(b, ow)?)) }
                    }
                }
            }
            Expr::Cond { c, a, b, .. } => CE { w, op: Op::Cond(bx(self.compile(c, 0)?), bx(self.compile(a, w)?), bx(self.compile(b, w)?)) },
            Expr::Select { base, sel, index, lsb, .. } => {
                let b = self.compile(base, 0)?;
                let i = self.compile(index, 0)?;
                let s = match (sel, lsb) {
                    (SelKind::Part, Some(l)) => {
                        let lo = self.konst(index)?.min(self.konst(l)?);
                        CE { w: own, op: Op::Sel(bx(b), bx(CE::lit(V::known(lo), 32))) }
                    }
                    (SelKind::Down, Some(_)) => CE { w: own, op: Op::SelDown(bx(b), bx(i)) },
                    _ => CE { w: own, op: Op::Sel(bx(b), bx(i)) },
                };
                if w == own { s } else { CE { w, op: Op::Resize(bx(s)) } }
            }
            Expr::Concat { items, .. } => {
                let items = items.iter().map(|x| self.compile(x, 0)).collect::<CResult<Vec<_>>>()?;
                let c = CE { w: own, op: Op::Concat(items) };
                if w == own { c } else { CE { w, op: Op::Resize(bx(c)) } }
            }
            Expr::Repl { count, items, .. } => {
                let n = self.konst(count)?;
                let items = items.iter().map(|x| self.compile(x, 0)).collect::<CResult<Vec<_>>>()?;
                let all: Vec<CE> = (0..n.min(64)).flat_map(|_| items.iter().cloned()).collect();
                let c = CE { w: own, op: Op::Concat(all) };
                if w == own { c } else { CE { w, op: Op::Resize(bx(c)) } }
            }
            Expr::Inside { a, set, .. } => {
                let aw = self.width(a)?;
                let mut out = Vec::new();
                let mut iw = aw;
                for it in set {
                    match it {
                        InsideItem::Value(v) => iw = iw.max(self.width(v)?),
                        InsideItem::Range { lo, hi } => iw = iw.max(self.width(lo)?).max(self.width(hi)?),
                    }
                }
                for it in set {
                    out.push(match it {
                        InsideItem::Value(v) => (self.compile(v, iw)?, None),
                        InsideItem::Range { lo, hi } => (self.compile(lo, iw)?, Some(self.compile(hi, iw)?)),
                    });
                }
                CE { w: 1, op: Op::Inside(bx(self.compile(a, iw)?), out) }
            }
            Expr::Call { func, args, at } => {
                let a0 = || self.compile(&args[0], 0).map(bx);
                let op = match func.as_str() {
                    "$past" => {
                        let n = match args.get(1) {
                            Some(n) => self.konst(n)?,
                            None => 1,
                        };
                        if n == 0 || n > 1 << 20 {
                            return Err((*at, format!("$past of {n} cycles (1 to {} are evaluated)", 1 << 20)));
                        }
                        Op::Past(bx(self.compile(&args[0], w)?), n as u32)
                    }
                    "$sampled" => return self.compile(&args[0], w),
                    "$rose" => Op::Rose(a0()?),
                    "$fell" => Op::Fell(a0()?),
                    "$stable" => Op::Stable(a0()?),
                    "$changed" => Op::Changed(a0()?),
                    "$onehot" => Op::OneHot(a0()?),
                    "$onehot0" => Op::OneHot0(a0()?),
                    "$countones" => Op::CountOnes(a0()?),
                    "$isunknown" => Op::IsUnknown(a0()?),
                    "$clog2" => Op::Clog2(a0()?),
                    "$bits" => return Ok(CE::lit(V::known(self.width(&args[0])? as u64), w)),
                    f => return Err((*at, format!("{f} is not evaluated"))),
                };
                CE { w, op }
            }
            Expr::Cast { a, .. } => {
                let inner = self.compile(a, own.max(self.width(a)?))?;
                let c = CE { w: own, op: Op::Resize(bx(inner)) };
                if w == own { c } else { CE { w, op: Op::Resize(bx(c)) } }
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Cols(Vec<(u32, Vec<V>)>);
    impl Samples for Cols {
        fn get(&self, k: usize, c: i64) -> V {
            if c < 0 { V::unknown(self.0[k].0) } else { self.0[k].1[c as usize] }
        }
    }

    /// `src` over signals a (8 bits), b (8 bits), c (1 bit) with one value each (at cycle 1; cycle 0 holds `prev`).
    fn ev(src: &str, a: V, b: V, c: V) -> V {
        let names = ["a", "b", "c"];
        let widths = [8, 8, 1];
        let sig = |n: &str| names.iter().position(|x| *x == n).map(|k| (k, widths[k]));
        let cols = Cols(vec![(8, vec![V::known(0), a]), (8, vec![V::known(0), b]), (1, vec![V::known(0), c])]);
        let e = crate::parse_expr(src).unwrap();
        Compiler { sig: &sig }.compile(&e, 0).unwrap().eval(&cols, 1)
    }
    const X: V = V { v: 0, x: 0xFF };
    fn k(v: u64) -> V {
        V::known(v)
    }

    #[test]
    fn widths_follow_the_context() {
        // 8-bit operands: the carry is lost in an 8-bit compare, kept against a 9-bit literal
        assert_eq!(ev("a + b == 8'd0", k(0x80), k(0x80), k(0)), k(1));
        assert_eq!(ev("a + b == 9'h100", k(0x80), k(0x80), k(0)), k(1));
        assert_eq!(ev("~a == 8'hFE", k(1), k(0), k(0)), k(1));
        assert_eq!(ev("~c", k(0), k(0), k(1)), k(0));
        assert_eq!(ev("{a, b} == 16'h1234", k(0x12), k(0x34), k(0)), k(1));
        assert_eq!(ev("{2{a[3:0]}} == 8'h55", k(0x15), k(0), k(0)), k(1));
        assert_eq!(ev("a[7:4]", k(0xA5), k(0), k(0)), k(0xA));
        assert_eq!(ev("a[b +: 2]", k(0b1100), k(2), k(0)), k(3));
        assert_eq!(ev("a[b -: 2]", k(0b1100), k(3), k(0)), k(3));
        assert_eq!(ev("a[b]", k(0xFF), k(9), k(0)), V { v: 0, x: 1 }); // outside the vector
        assert_eq!(ev("4'(a)", k(0xAB), k(0), k(0)), k(0xB));
        assert_eq!(ev("$bits(a) + $clog2(b)", k(0), k(9), k(0)), k(12));
        assert_eq!(ev("a inside {1, [5:7]}", k(6), k(0), k(0)), k(1));
        assert_eq!(ev("a inside {1, [5:7]}", k(4), k(0), k(0)), k(0));
    }

    #[test]
    fn unknown_bits() {
        let half = V { v: 0, x: 0x0F }; // 0000xxxx
        assert_eq!(ev("a == 8'hF0", half, k(0), k(0)), k(0), "known bits differ: false, not x");
        assert_eq!(ev("a == 8'h00", half, k(0), k(0)).truth(), Tri::X);
        assert_eq!(ev("a === 8'h00", half, k(0), k(0)), k(0));
        assert_eq!(ev("a === b", half, half, k(0)), k(1));
        assert_eq!(ev("a & 8'hF0", half, k(0), k(0)), k(0), "x & 0 is 0");
        assert_eq!(ev("a | 8'h0F", half, k(0), k(0)), k(0x0F), "x | 1 is 1");
        assert_eq!(ev("a + 1", half, k(0), k(0)).x, mask(32));
        assert_eq!(ev("c && a", k(0), k(0), k(0)), k(0), "0 && x is 0");
        assert_eq!(ev("c || a", X, k(0), k(1)), k(1), "1 || x is 1");
        assert_eq!(ev("!a", X, k(0), k(0)).truth(), Tri::X);
        assert_eq!(ev("$isunknown(a)", half, k(0), k(0)), k(1));
        assert_eq!(ev("$countones(a)", V { v: 0b1010_0000, x: 0b0101 }, k(0), k(0)), k(2));
        assert_eq!(ev("c ? a : b", k(3), k(1), V { v: 0, x: 1 }), V { v: 1, x: 2 }, "an unknown condition merges the bits");
        assert_eq!(ev("&a", V { v: 0xF0, x: 0x0F }, k(0), k(0)).truth(), Tri::X);
        assert_eq!(ev("&a", V { v: 0x70, x: 0x0F }, k(0), k(0)), k(0));
        assert_eq!(ev("^a", k(0b0111), k(0), k(0)), k(1));
    }

    #[test]
    fn sampled_value_functions_see_the_previous_cycle() {
        // cycle 0: a = b = c = 0
        assert_eq!(ev("$rose(c)", k(0), k(0), k(1)), k(1));
        assert_eq!(ev("$fell(c)", k(0), k(0), k(1)), k(0));
        assert_eq!(ev("$stable(a)", k(0), k(0), k(0)), k(1));
        assert_eq!(ev("$changed(a)", k(5), k(0), k(0)), k(1));
        assert_eq!(ev("$past(a) == 0 && a == 5", k(5), k(0), k(0)), k(1));
        assert_eq!(ev("$past(a, 2)", k(5), k(0), k(0)), X, "before the dump: the initial value x");
        assert_eq!(ev("$rose(a[0])", k(1), k(0), k(0)), k(1));
    }

    #[test]
    fn trace_values_parse() {
        assert_eq!(V::parse("1"), Some((k(1), 1)));
        assert_eq!(V::parse("10x1"), Some((V { v: 0b1001, x: 0b0010 }, 4)));
        assert_eq!(V::parse("z"), Some((V { v: 0, x: 1 }, 1)));
        assert_eq!(V::parse("h1F"), Some((k(0x1F), 8)));
        assert_eq!(V::parse("hx0"), Some((V { v: 0, x: 0xF0 }, 8)));
        assert_eq!(V::parse("2"), None);
        assert_eq!(V::parse(""), None);
    }
}
