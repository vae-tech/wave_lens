//! Parser, part 3: sequences and properties, one grammar with the precedence of IEEE 1800-2017 tables 16-1 / 16-3
//! (high to low): repetition, `##`, `throughout`, `within`, `intersect`, `not` / `nexttime`, `and`, `or`, `|->` `|=>`
//! `#-#` `#=#` (right), `always` / `eventually` / `if`. Every level returns a [`Prop`]; a sequence is a `Prop::Seq`, and
//! the sequence operators check that their operands are sequences.
//!
//! A `(` at the start of an operand is ambiguous: `(a && b)` is a boolean, `(a ##1 b)` a sequence, `(a |-> b)` a
//! property. The parser reads an expression first and, when that fails, reads the parenthesis again as a property.

use crate::ast::*;
use crate::lex::{Span, Tok};
use crate::parse::{Parser, R};
use crate::SvaError;

/// Property words outside the subset, with what to say about them.
const UNSUPPORTED: &[(&str, &str)] = &[
    ("until", "until"),
    ("s_until", "s_until"),
    ("until_with", "until_with"),
    ("s_until_with", "s_until_with"),
    ("implies", "implies"),
    ("iff", "iff (property equivalence)"),
    ("accept_on", "accept_on"),
    ("reject_on", "reject_on"),
    ("sync_accept_on", "sync_accept_on"),
    ("sync_reject_on", "sync_reject_on"),
    ("case", "case in properties"),
    ("strong", "strong(...)"),
    ("weak", "weak(...)"),
    ("dist", "dist"),
    ("matches", "matches"),
];

impl<'a> Parser<'a> {
    fn unsupported(&self) -> R<()> {
        if let Tok::Id(w) = self.tok() {
            if let Some((_, what)) = UNSUPPORTED.iter().find(|u| u.0 == w) {
                return self.error(self.at(), format!("{what} is outside the subset (docs/sva/LANGUAGE.md)"));
            }
        }
        Ok(())
    }

    /// The sequence of `p`, or an error that `what` needs one.
    fn need_seq(&self, p: Prop, what: &str) -> R<Seq> {
        match p {
            Prop::Seq { seq } => Ok(seq),
            p => Err(SvaError::new(p.at(), format!("{what} needs a sequence, found a property"))),
        }
    }

    /// The lowest level: `always`, `s_always`, `eventually`, `s_eventually`, `if`, then implications.
    pub fn prop(&mut self) -> R<Prop> {
        self.deeper(1)?;
        let r = self.prop_in();
        self.up(1);
        r
    }

    fn prop_in(&mut self) -> R<Prop> {
        let from = self.i;
        self.unsupported()?;
        let w = match self.tok() {
            Tok::Id(w) => w.clone(),
            _ => String::new(),
        };
        match w.as_str() {
            "always" | "s_always" | "eventually" | "s_eventually" => {
                self.i += 1;
                let strong = w.starts_with("s_");
                let range = if self.is("[") { Some(self.prop_range()?) } else { None };
                match (&range, w.as_str()) {
                    (None, "s_always") | (None, "eventually") => return self.error(self.at(), format!("{w} needs a range: {w} [m:n] p")),
                    (Some(r), "s_always" | "eventually") if r.max.is_inf() => {
                        return self.error(self.span_from(from + 1), format!("the range of {w} must be bounded"));
                    }
                    _ => {}
                }
                let p = Box::new(self.prop()?);
                let at = self.span_from(from);
                Ok(if w.ends_with("always") { Prop::Always { strong, range, p, at } } else { Prop::Eventually { strong, range, p, at } })
            }
            "if" => {
                self.i += 1;
                self.expect("(")?;
                let cond = self.expr()?;
                self.expect(")")?;
                let then = Box::new(self.prop()?);
                let else_ = if self.eat("else") { Some(Box::new(self.prop()?)) } else { None };
                Ok(Prop::If { cond, then, else_, at: self.span_from(from) })
            }
            _ => self.implication(),
        }
    }

    /// `[m:n]` / `[m:$]` after a property operator.
    fn prop_range(&mut self) -> R<Range> {
        self.expect("[")?;
        let r = self.range_body()?;
        self.expect("]")?;
        Ok(r)
    }

    /// `m:n` / `m:$` (inside brackets).
    fn range_body(&mut self) -> R<Range> {
        let min = self.bound(false)?;
        self.expect(":")?;
        let max_at = self.at();
        let r = Range { min, max: self.bound(true)? };
        r.check(max_at)?;
        Ok(r)
    }

    /// A constant bound: a number, `$` (when `dollar`), or an expression folded later (parameters, formal arguments).
    pub fn bound(&mut self, dollar: bool) -> R<Bound> {
        if self.is("$") {
            if !dollar {
                return self.error(self.at(), "'$' is only allowed as the end of a range");
            }
            self.i += 1;
            return Ok(Bound::INF);
        }
        let e = self.expr()?;
        Ok(match e {
            Expr::Number { value, unknown: 0, .. } => match u32::try_from(value) {
                Ok(v) => Bound::Const(v),
                Err(_) => return self.error(e.at(), "the bound is too large"),
            },
            Expr::Number { at, .. } => return self.error(at, "a bound cannot have x / z bits"),
            e => Bound::Expr(Box::new(e)),
        })
    }

    fn implication(&mut self) -> R<Prop> {
        let from = self.i;
        let lhs = self.prop_or()?;
        let op = match self.tok() {
            Tok::Sym("|->") => ImpOp::Overlap,
            Tok::Sym("|=>") => ImpOp::NonOverlap,
            Tok::Sym("#-#") => ImpOp::FollowOverlap,
            Tok::Sym("#=#") => ImpOp::FollowNonOverlap,
            _ => {
                self.unsupported()?;
                return Ok(lhs);
            }
        };
        let op_at = self.at();
        let ante = match lhs {
            Prop::Seq { seq } => seq,
            _ => {
                return Err(SvaError::new(op_at, format!("the left side of {} must be a sequence, found a property", op.sym())));
            }
        };
        self.i += 1;
        let cons = Box::new(self.prop()?);
        Ok(Prop::Implies { op, ante, cons, at: self.span_from(from) })
    }

    fn prop_or(&mut self) -> R<Prop> {
        let from = self.i;
        let mut a = self.prop_and()?;
        let mut wraps = 0;
        while self.eat("or") {
            self.deeper(1)?;
            wraps += 1;
            let b = self.prop_and()?;
            a = combine(a, b, SeqOp::Or, PropOp::Or, self.span_from(from));
        }
        self.up(wraps);
        Ok(a)
    }

    fn prop_and(&mut self) -> R<Prop> {
        let from = self.i;
        let mut a = self.prop_not()?;
        let mut wraps = 0;
        while self.eat("and") {
            self.deeper(1)?;
            wraps += 1;
            let b = self.prop_not()?;
            a = combine(a, b, SeqOp::And, PropOp::And, self.span_from(from));
        }
        self.up(wraps);
        Ok(a)
    }

    fn prop_not(&mut self) -> R<Prop> {
        let from = self.i;
        if self.eat("not") {
            self.deeper(1)?;
            let p = self.prop_not();
            self.up(1);
            return Ok(Prop::Not { p: Box::new(p?), at: self.span_from(from) });
        }
        if self.is("nexttime") || self.is("s_nexttime") {
            let strong = self.is("s_nexttime");
            self.i += 1;
            let n = if self.eat("[") {
                let b = self.bound(false)?;
                self.expect("]")?;
                b
            } else {
                Bound::Const(1)
            };
            self.deeper(1)?;
            let p = self.prop_not();
            self.up(1);
            return Ok(Prop::Nexttime { strong, n, p: Box::new(p?), at: self.span_from(from) });
        }
        self.seq_binary(0)
    }

    /// `intersect` (level 0), `within` (1): left-associative, sequences only.
    fn seq_binary(&mut self, level: u8) -> R<Prop> {
        let (word, op) = if level == 0 { ("intersect", SeqOp::Intersect) } else { ("within", SeqOp::Within) };
        let from = self.i;
        let next = |p: &mut Self| if level == 0 { p.seq_binary(1) } else { p.throughout() };
        let mut a = next(self)?;
        let mut wraps = 0;
        while self.is(word) {
            let a_seq = self.need_seq(a, word)?;
            self.i += 1;
            self.deeper(1)?;
            wraps += 1;
            let b = next(self)?;
            let b = self.need_seq(b, word)?;
            a = Prop::Seq { seq: Seq::Binary { op, a: Box::new(a_seq), b: Box::new(b), at: self.span_from(from) } };
        }
        self.up(wraps);
        Ok(a)
    }

    /// `cond throughout seq` (right-associative; `cond` a boolean).
    fn throughout(&mut self) -> R<Prop> {
        let from = self.i;
        let a = self.delay()?;
        if !self.is("throughout") {
            return Ok(a);
        }
        let at = self.at();
        let cond = match a {
            Prop::Seq { seq: s @ Seq::Bool { .. } } => s,
            p => return Err(SvaError::new(p.at().to(at), "the left side of throughout must be a boolean expression")),
        };
        self.i += 1;
        self.deeper(1)?;
        let b = self.throughout();
        self.up(1);
        let seq = self.need_seq(b?, "throughout")?;
        Ok(Prop::Seq { seq: Seq::Throughout { cond: Box::new(cond), seq: Box::new(seq), at: self.span_from(from) } })
    }

    /// `[##range] r {##range r}` where `r` is an operand with an optional repetition.
    fn delay(&mut self) -> R<Prop> {
        let from = self.i;
        let mut lhs: Option<Seq> = None;
        if !self.is("##") {
            let p = self.repetition()?;
            if !self.is("##") {
                return Ok(p);
            }
            lhs = Some(self.need_seq(p, "##")?);
        }
        let mut wraps = 0;
        while self.is("##") {
            self.i += 1;
            self.deeper(1)?;
            wraps += 1;
            let range = self.cycle_delay()?;
            let r = self.repetition()?;
            let rhs = self.need_seq(r, "##")?;
            lhs = Some(Seq::Delay { lhs: lhs.map(Box::new), range, rhs: Box::new(rhs), at: self.span_from(from) });
        }
        self.up(wraps);
        Ok(Prop::Seq { seq: lhs.unwrap() })
    }

    /// After `##`: `n`, `N`, `(expr)`, `[m:n]`, `[m:$]`, `[*]`, `[+]`.
    fn cycle_delay(&mut self) -> R<Range> {
        match self.tok().clone() {
            Tok::Num(n) => {
                self.i += 1;
                if n.unknown != 0 {
                    return self.error(self.prev(), "a delay cannot have x / z bits");
                }
                let v = u32::try_from(n.value).map_err(|_| SvaError::new(self.prev(), "the delay is too large"))?;
                Ok(Range::single(v))
            }
            Tok::Id(_) => {
                let b = Bound::Expr(Box::new(self.primary()?));
                Ok(Range { min: b.clone(), max: b })
            }
            Tok::Sym("(") => {
                self.i += 1;
                let e = self.expr()?;
                self.expect(")")?;
                let b = Bound::Expr(Box::new(e));
                Ok(Range { min: b.clone(), max: b })
            }
            Tok::Sym("[*") => {
                self.i += 1;
                self.expect("]")?;
                Ok(Range::new(0, None))
            }
            Tok::Sym("[+]") => {
                self.i += 1;
                Ok(Range::new(1, None))
            }
            Tok::Sym("[") => {
                self.i += 1;
                let r = self.range_body()?;
                self.expect("]")?;
                Ok(r)
            }
            _ => self.expected("a delay after '##': a number, [m:n], [*] or [+]"),
        }
    }

    /// An operand with an optional `[*n]` `[*m:n]` `[*]` `[+]` `[->n]` `[=n]`.
    fn repetition(&mut self) -> R<Prop> {
        let from = self.i;
        let p = self.seq_primary()?;
        let op = match self.tok() {
            Tok::Sym("[*") | Tok::Sym("[+]") => RepOp::Consec,
            Tok::Sym("[->") => RepOp::Goto,
            Tok::Sym("[=") => RepOp::NonConsec,
            _ => return Ok(p),
        };
        let rep_at = self.at();
        let seq = self.need_seq(p, "a repetition")?;
        if op != RepOp::Consec && !matches!(seq, Seq::Bool { .. }) {
            return Err(SvaError::new(rep_at, "goto [->n] and non-consecutive [=n] repetitions need a boolean, found a sequence"));
        }
        let plus = self.is("[+]");
        self.i += 1;
        let range = if plus {
            Range::new(1, None)
        } else if op == RepOp::Consec && self.eat("]") {
            Range::new(0, None)
        } else {
            let min = self.bound(false)?;
            let r = if self.eat(":") {
                let max_at = self.at();
                let r = Range { min, max: self.bound(true)? };
                r.check(max_at)?;
                r
            } else {
                Range { min: min.clone(), max: min }
            };
            self.expect("]")?;
            r
        };
        if matches!(self.tok(), Tok::Sym("[*" | "[+]" | "[->" | "[=")) {
            return self.error(self.at(), "a repetition of a repetition needs parentheses: (a[*2])[*3]");
        }
        Ok(Prop::Seq { seq: Seq::Repeat { op, range, seq: Box::new(seq), at: self.span_from(from) } })
    }

    /// `first_match(...)`, `name(args)`, a boolean, or `( property )`.
    fn seq_primary(&mut self) -> R<Prop> {
        let from = self.i;
        self.unsupported()?;
        if self.is("first_match") {
            self.i += 1;
            self.expect("(")?;
            let p = self.prop()?;
            let seq = self.need_seq(p, "first_match")?;
            if self.is(",") {
                return self.error(self.at(), "sequence match items (local variables) are outside the subset");
            }
            self.expect(")")?;
            return Ok(Prop::Seq { seq: Seq::FirstMatch { seq: Box::new(seq), at: self.span_from(from) } });
        }
        let scoped = self.peek_ident(0).is_some() && self.is_at(1, "::") && self.peek_ident(2).is_some() && self.is_at(3, "(");
        if scoped || (self.peek_ident(0).is_some() && self.is_at(1, "(")) {
            let (mut name, _) = self.ident()?;
            if scoped {
                self.i += 1;
                name = format!("{name}::{}", self.ident()?.0);
            }
            let args = self.args()?;
            return Ok(Prop::Seq { seq: Seq::Instance { name, args, body: None, at: self.span_from(from) } });
        }
        if self.is("@") {
            return self.error(self.at(), "a clock inside a property (multi-clock) is outside the subset");
        }
        match self.expr() {
            Ok(e) => Ok(Prop::from_expr(e)),
            Err(e1) => {
                if !self.t[from].tok.eq(&Tok::Sym("(")) {
                    return Err(e1);
                }
                let far1 = self.i;
                self.i = from + 1;
                let inner = self.prop().and_then(|p| {
                    if self.is(",") {
                        return self.error(self.at(), "sequence match items (local variables) are outside the subset");
                    }
                    self.expect(")")?;
                    Ok(p)
                });
                match inner {
                    Ok(p) => Ok(p),
                    Err(_) if far1 > self.i => {
                        self.i = far1;
                        Err(e1)
                    }
                    Err(e2) => Err(e2),
                }
            }
        }
    }

    /// `(a, .b(x), , c)` — each a property (an expression or a sequence is one too).
    fn args(&mut self) -> R<Vec<Arg>> {
        self.expect("(")?;
        let mut out = Vec::new();
        if self.eat(")") {
            return Ok(out);
        }
        loop {
            if self.eat(".") {
                let (name, _) = self.ident()?;
                self.expect("(")?;
                let value = if self.is(")") { None } else { Some(self.prop()?) };
                self.expect(")")?;
                out.push(Arg { name: Some(name), value });
            } else if self.is(",") || self.is(")") {
                out.push(Arg { name: None, value: None });
            } else {
                if out.iter().any(|a| a.name.is_some()) {
                    return self.error(self.at(), "a positional argument after a named one");
                }
                out.push(Arg { name: None, value: Some(self.prop()?) });
            }
            if self.eat(",") {
                continue;
            }
            self.expect(")")?;
            return Ok(out);
        }
    }
}

/// `a and b` / `a or b`: a sequence when both sides are, a property otherwise.
fn combine(a: Prop, b: Prop, sop: SeqOp, pop: PropOp, at: Span) -> Prop {
    match (a, b) {
        (Prop::Seq { seq: a }, Prop::Seq { seq: b }) => Prop::Seq { seq: Seq::Binary { op: sop, a: Box::new(a), b: Box::new(b), at } },
        (a, b) => Prop::Binary { op: pop, a: Box::new(a), b: Box::new(b), at },
    }
}
