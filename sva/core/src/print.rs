//! The tree back to SystemVerilog text, with the fewest parentheses that keep its structure: printing and parsing
//! again gives the same tree (the round-trip tests rely on it). Element labels and `sva parse` use this text.
//! [`Printer::full`] parenthesises every compound node (tests of precedence); [`Printer::inline`] prints the bodies of
//! instances instead of their names.

use crate::ast::*;
use std::fmt;

#[derive(Clone, Copy, Debug, Default)]
pub struct Printer {
    pub full: bool,
    pub inline: bool,
}

const ATOM: u8 = 20;

fn expr_prec(e: &Expr) -> u8 {
    match e {
        Expr::Binary { op, .. } => op.prec(),
        Expr::Inside { .. } => 8,
        Expr::Cond { .. } => 1,
        Expr::Unary { .. } => 13,
        _ => ATOM,
    }
}

/// Sequence and property operators on one scale (IEEE 1800-2017 tables 16-1 and 16-3), higher binds tighter.
fn seq_prec(s: &Seq) -> u8 {
    match s {
        Seq::Repeat { .. } => 12,
        Seq::Delay { .. } => 11,
        Seq::Throughout { .. } => 10,
        Seq::Binary { op: SeqOp::Within, .. } => 9,
        Seq::Binary { op: SeqOp::Intersect, .. } => 8,
        Seq::Binary { op: SeqOp::And, .. } => 6,
        Seq::Binary { op: SeqOp::Or, .. } => 5,
        Seq::Bool { .. } | Seq::FirstMatch { .. } | Seq::Instance { .. } => ATOM,
    }
}

fn prop_prec(p: &Prop) -> u8 {
    match p {
        Prop::Seq { seq } => seq_prec(seq),
        Prop::Not { .. } | Prop::Nexttime { .. } => 7,
        Prop::Binary { op: PropOp::And, .. } => 6,
        Prop::Binary { op: PropOp::Or, .. } => 5,
        Prop::Implies { .. } => 2,
        Prop::If { .. } | Prop::Always { .. } | Prop::Eventually { .. } => 1,
        Prop::Instance { .. } => ATOM,
    }
}

fn paren(s: String, yes: bool) -> String {
    if yes {
        format!("({s})")
    } else {
        s
    }
}

impl Printer {
    pub fn full() -> Printer {
        Printer { full: true, inline: false }
    }

    fn wrap(&self, s: String, prec: u8, need: bool) -> String {
        paren(s, need || (self.full && prec < ATOM))
    }

    pub fn expr(&self, e: &Expr) -> String {
        let sub = |x: &Expr, need: bool| self.wrap(self.expr(x), expr_prec(x), need);
        match e {
            Expr::Ident { name, .. } | Expr::Const { name, .. } if name.starts_with('\\') => format!("{name} "),   // an escaped identifier ends at a space
            Expr::Ident { name, .. } | Expr::Const { name, .. } => name.clone(),
            Expr::Number { text, .. } => text.clone(),
            Expr::Fill { bit, .. } => format!("'{bit}"),
            Expr::Unary { op, a, .. } => {
                // `~&a` would read as a reduction; `- -a` must keep its space: nested unary operators get parentheses
                let nested = matches!(**a, Expr::Unary { .. }) && *op != UnOp::Not;
                format!("{}{}", op.sym(), sub(a, expr_prec(a) < 13 || nested))
            }
            Expr::Binary { op, a, b, .. } => {
                let p = op.prec();
                format!("{} {} {}", sub(a, expr_prec(a) < p), op.sym(), sub(b, expr_prec(b) <= p))
            }
            Expr::Cond { c, a, b, .. } => {
                format!("{} ? {} : {}", sub(c, expr_prec(c) <= 1), sub(a, expr_prec(a) <= 1), sub(b, false))
            }
            Expr::Select { base, sel, index, lsb, .. } => {
                let b = sub(base, expr_prec(base) < ATOM);
                let (i, l) = (self.expr(index), lsb.as_ref().map(|l| self.expr(l)).unwrap_or_default());
                match sel {
                    SelKind::Bit => format!("{b}[{i}]"),
                    SelKind::Part => format!("{b}[{i}:{l}]"),
                    SelKind::Up => format!("{b}[{i}+:{l}]"),
                    SelKind::Down => format!("{b}[{i}-:{l}]"),
                }
            }
            Expr::Concat { items, .. } => format!("{{{}}}", self.list(items)),
            Expr::Repl { count, items, .. } => format!("{{{}{{{}}}}}", sub(count, expr_prec(count) < ATOM), self.list(items)),
            Expr::Inside { a, set, .. } => {
                let items: Vec<String> = set
                    .iter()
                    .map(|i| match i {
                        InsideItem::Value(v) => self.expr(v),
                        InsideItem::Range { lo, hi } => format!("[{}:{}]", self.expr(lo), self.expr(hi)),
                    })
                    .collect();
                format!("{} inside {{{}}}", sub(a, expr_prec(a) < 8), items.join(", "))
            }
            Expr::Call { func, args, .. } => format!("{func}({})", self.list(args)),
            Expr::Cast { width, a, .. } => format!("{width}'({})", self.expr(a)),
        }
    }

    fn list(&self, items: &[Expr]) -> String {
        items.iter().map(|x| self.expr(x)).collect::<Vec<_>>().join(", ")
    }

    pub fn bound(&self, b: &Bound) -> String {
        match b {
            Bound::Const(n) => n.to_string(),
            Bound::Inf(_) => "$".into(),
            Bound::Expr(e) => self.expr(e),
        }
    }

    /// `[m:n]`, `[m:$]`, or `[n]` when `single` allows it (repetitions, `nexttime`).
    fn range(&self, r: &Range, single: bool) -> String {
        if single && r.min == r.max {
            return self.bound(&r.min);
        }
        format!("{}:{}", self.bound(&r.min), self.bound(&r.max))
    }

    /// `##n`, `##(N + 1)`, `##[m:n]`.
    pub fn delay(&self, r: &Range) -> String {
        if r.min == r.max {
            return match &r.min {
                Bound::Expr(e) if expr_prec(e) < ATOM => format!("##({})", self.expr(e)),
                b => format!("##{}", self.bound(b)),
            };
        }
        format!("##[{}]", self.range(r, false))
    }

    pub fn repeat(&self, op: RepOp, r: &Range) -> String {
        let o = match op {
            RepOp::Consec => "*",
            RepOp::Goto => "->",
            RepOp::NonConsec => "=",
        };
        format!("[{o}{}]", self.range(r, true))
    }

    pub fn seq(&self, s: &Seq) -> String {
        let sub = |x: &Seq, need: bool| self.wrap(self.seq(x), seq_prec(x), need);
        match s {
            Seq::Bool { expr, .. } => self.expr(expr),
            Seq::Delay { lhs, range, rhs, .. } => {
                let r = format!("{} {}", self.delay(range), sub(rhs, seq_prec(rhs) <= 11));
                match lhs {
                    Some(l) => format!("{} {r}", sub(l, seq_prec(l) < 11)),
                    None => r,
                }
            }
            Seq::Repeat { op, range, seq, .. } => {
                // a compound boolean keeps its parentheses: `(a && b)[*2]` (the parser reads it the same without)
                let need = match &**seq {
                    Seq::Bool { expr, .. } => expr_prec(expr) < ATOM,
                    x => seq_prec(x) < ATOM,
                };
                format!("{}{}", sub(seq, need), self.repeat(*op, range))
            }
            Seq::Binary { op, a, b, .. } => {
                let p = seq_prec(s);
                let w = match op {
                    SeqOp::And => "and",
                    SeqOp::Or => "or",
                    SeqOp::Intersect => "intersect",
                    SeqOp::Within => "within",
                };
                // a chain of ## as an operand gets parentheses for the reader: `(a ##1 b) and (c ##2 d)`
                let chain = |x: &Seq| matches!(x, Seq::Delay { .. } | Seq::Throughout { .. });
                format!("{} {w} {}", sub(a, seq_prec(a) < p || chain(a)), sub(b, seq_prec(b) <= p || chain(b)))
            }
            Seq::Throughout { cond, seq, .. } => format!("{} throughout {}", sub(cond, false), sub(seq, seq_prec(seq) < 10)),
            Seq::FirstMatch { seq, .. } => format!("first_match({})", self.seq(seq)),
            Seq::Instance { name, args, body, .. } => match body {
                Some(b) if self.inline => format!("({})", self.seq(b)),
                _ => self.instance(name, args),
            },
        }
    }

    fn instance(&self, name: &str, args: &[Arg]) -> String {
        if args.is_empty() {
            return name.to_string();
        }
        let a: Vec<String> = args
            .iter()
            .map(|a| {
                let v = a.value.as_ref().map(|v| self.prop(v)).unwrap_or_default();
                match &a.name {
                    Some(n) => format!(".{n}({v})"),
                    None => v,
                }
            })
            .collect();
        format!("{name}({})", a.join(", "))
    }

    pub fn prop(&self, p: &Prop) -> String {
        let sub = |x: &Prop, need: bool| self.wrap(self.prop(x), prop_prec(x), need);
        match p {
            Prop::Seq { seq } => self.seq(seq),
            Prop::Implies { op, ante, cons, .. } => {
                format!("{} {} {}", self.wrap(self.seq(ante), seq_prec(ante), seq_prec(ante) <= 2), op.sym(), sub(cons, false))
            }
            Prop::Not { p: x, .. } => format!("not {}", sub(x, prop_prec(x) < 7)),
            Prop::Binary { op, a, b, .. } => {
                let q = prop_prec(p);
                let w = if *op == PropOp::And { "and" } else { "or" };
                format!("{} {w} {}", sub(a, prop_prec(a) < q), sub(b, prop_prec(b) <= q))
            }
            Prop::If { cond, then, else_, .. } => {
                let dangling = else_.is_some() && matches!(**then, Prop::If { else_: None, .. });
                let mut s = format!("if ({}) {}", self.expr(cond), sub(then, dangling));
                if let Some(e) = else_ {
                    s += &format!(" else {}", sub(e, false));
                }
                s
            }
            Prop::Nexttime { strong, n, p: x, .. } => {
                let w = if *strong { "s_nexttime" } else { "nexttime" };
                let n = if *n == Bound::Const(1) { String::new() } else { format!(" [{}]", self.bound(n)) };
                format!("{w}{n} {}", sub(x, prop_prec(x) < 7))
            }
            Prop::Always { strong, range, p: x, .. } | Prop::Eventually { strong, range, p: x, .. } => {
                let w = match (matches!(p, Prop::Always { .. }), strong) {
                    (true, false) => "always",
                    (true, true) => "s_always",
                    (false, false) => "eventually",
                    (false, true) => "s_eventually",
                };
                let r = range.as_ref().map_or(String::new(), |r| format!(" [{}]", self.range(r, false)));
                format!("{w}{r} {}", sub(x, false))
            }
            Prop::Instance { name, args, body, .. } => match body {
                Some(b) if self.inline => format!("({})", self.prop(b)),
                _ => self.instance(name, args),
            },
        }
    }
}

impl fmt::Display for Expr {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str(&Printer::default().expr(self))
    }
}

impl fmt::Display for Seq {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str(&Printer::default().seq(self))
    }
}

impl fmt::Display for Prop {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str(&Printer::default().prop(self))
    }
}

impl fmt::Display for Clock {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "@({} {})", self.edge, self.signal)
    }
}
