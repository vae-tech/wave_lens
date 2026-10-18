//! An assertion as the evaluator needs it: instances of sequences and properties expanded (actual arguments, already
//! expanded in the caller's context, put in place of the formals), names resolved (formal, declaration, constant,
//! signal), range bounds folded to numbers, the clock and `disable iff` found (the assertion, the property it
//! instantiates, the default of the scope), element ids and labels given, the signals collected with their widths.

use crate::ast::*;
use crate::consts;
use crate::lex::Span;
use crate::parse::{RawAssertion, UnitState};
use crate::print::Printer;
use crate::SvaError;
use std::collections::HashMap;

/// The signal list carries the signed literals it met under this prefix (taken out again in `assertion`).
const SIGNED_LIT: &str = "\u{0}signed ";

type R<T> = Result<T, SvaError>;

#[derive(Clone)]
struct Formal {
    value: Option<Prop>,
}

#[derive(Default)]
struct Shared {
    /// Instances being expanded (recursion check).
    stack: Vec<String>,
    /// Clocks of the declarations met: (clock, where the instance is, declaration name).
    clocks: Vec<(Clock, Span, String)>,
    top_clock: Option<Clock>,
    top_disable: Option<Expr>,
}

#[derive(Clone, Copy)]
enum Decl {
    Seq(usize),
    Prop(usize),
}

struct X<'u, 's> {
    u: &'u UnitState,
    scope: usize,
    env: HashMap<String, Formal>,
    sh: &'s mut Shared,
}

fn err<T>(at: Span, msg: impl Into<String>) -> R<T> {
    Err(SvaError::new(at, msg))
}

impl<'u, 's> X<'u, 's> {
    fn decl(&self, name: &str) -> Option<Decl> {
        let pick = |s: &crate::parse::Scope| s.seqs.get(name).map(|&k| Decl::Seq(k)).or_else(|| s.props.get(name).map(|&k| Decl::Prop(k)));
        if let Some((p, n)) = name.split_once("::") {
            let s = &self.u.scopes[*self.u.packages.get(p)?];
            return s.seqs.get(n).map(|&k| Decl::Seq(k)).or_else(|| s.props.get(n).map(|&k| Decl::Prop(k)));
        }
        self.u.find(self.scope, pick)
    }

    fn unknown<T>(&self, name: &str, at: Span) -> R<T> {
        if let Some(b) = self.u.find(self.scope, |s| s.broken.get(name).copied()) {
            return err(at, format!("'{name}' did not parse (line {})", b.line));
        }
        err(at, format!("no sequence or property '{name}'"))
    }

    fn prop(&mut self, p: &Prop, top: bool) -> R<Prop> {
        Ok(match p {
            Prop::Seq { seq: Seq::Bool { expr: Expr::Ident { name, at }, .. } } if self.env.contains_key(name) => match &self.env[name].value {
                Some(v) => v.clone(),
                None => return err(*at, format!("the argument '{name}' is empty")),
            },
            Prop::Seq { seq: Seq::Bool { expr: Expr::Ident { name, at }, .. } } if self.decl(name).is_some() => self.instance(name, &[], *at, top)?,
            Prop::Seq { seq: Seq::Instance { name, args, at, .. } } | Prop::Instance { name, args, at, .. } => {
                if self.decl(name).is_none() {
                    return self.unknown(name, *at);
                }
                self.instance(name, args, *at, top)?
            }
            // `p1 and p2` reads as an operator of sequences; with a property on either side it is one of properties
            Prop::Seq { seq: Seq::Binary { op: op @ (SeqOp::And | SeqOp::Or), a, b, at } } => {
                let x = self.prop(&Prop::Seq { seq: (**a).clone() }, false)?;
                let y = self.prop(&Prop::Seq { seq: (**b).clone() }, false)?;
                match (x, y) {
                    (Prop::Seq { seq: x }, Prop::Seq { seq: y }) => Prop::Seq { seq: Seq::Binary { op: *op, a: Box::new(x), b: Box::new(y), at: *at } },
                    (x, y) => Prop::Binary { op: if *op == SeqOp::And { PropOp::And } else { PropOp::Or }, a: Box::new(x), b: Box::new(y), at: *at },
                }
            }
            Prop::Seq { seq } => Prop::Seq { seq: self.seq(seq)? },
            Prop::Implies { op, ante, cons, at } => Prop::Implies { op: *op, ante: self.seq(ante)?, cons: Box::new(self.prop(cons, false)?), at: *at },
            Prop::Not { p, at } => Prop::Not { p: Box::new(self.prop(p, false)?), at: *at },
            Prop::Binary { op, a, b, at } => Prop::Binary { op: *op, a: Box::new(self.prop(a, false)?), b: Box::new(self.prop(b, false)?), at: *at },
            Prop::If { cond, then, else_, at } => Prop::If {
                cond: self.expr(cond)?,
                then: Box::new(self.prop(then, false)?),
                else_: match else_ {
                    Some(e) => Some(Box::new(self.prop(e, false)?)),
                    None => None,
                },
                at: *at,
            },
            Prop::Nexttime { strong, n, p, at } => {
                let n = self.bound(n)?;
                Prop::Nexttime { strong: *strong, n, p: Box::new(self.prop(p, false)?), at: *at }
            }
            Prop::Always { strong, range, p, at } => Prop::Always { strong: *strong, range: self.opt_range(range)?, p: Box::new(self.prop(p, false)?), at: *at },
            Prop::Eventually { strong, range, p, at } => Prop::Eventually { strong: *strong, range: self.opt_range(range)?, p: Box::new(self.prop(p, false)?), at: *at },
        })
    }

    /// An instance where a property may stand: a property instance, or a sequence instance as a property.
    fn instance(&mut self, name: &str, args: &[Arg], at: Span, top: bool) -> R<Prop> {
        match self.decl(name) {
            Some(Decl::Prop(k)) => self.prop_instance(k, name, args, at, top),
            Some(Decl::Seq(k)) => Ok(Prop::Seq { seq: self.seq_instance(k, name, args, at, top)? }),
            None => self.unknown(name, at),
        }
    }

    fn seq(&mut self, s: &Seq) -> R<Seq> {
        Ok(match s {
            Seq::Bool { expr: Expr::Ident { name, at }, .. } if self.env.contains_key(name) => match &self.env[name].value {
                Some(Prop::Seq { seq }) => seq.clone(),
                Some(_) => return err(*at, format!("the argument '{name}' is a property, used here as a sequence")),
                None => return err(*at, format!("the argument '{name}' is empty")),
            },
            Seq::Bool { expr: Expr::Ident { name, at }, .. } if self.decl(name).is_some() => self.seq_by_name(name, &[], *at)?,
            Seq::Instance { name, args, at, .. } => self.seq_by_name(name, args, *at)?,
            Seq::Bool { expr, at, .. } => Seq::Bool { id: None, expr: self.expr(expr)?, at: *at },
            Seq::Delay { lhs, range, rhs, at } => Seq::Delay {
                lhs: match lhs {
                    Some(l) => Some(Box::new(self.seq(l)?)),
                    None => None,
                },
                range: self.range(range)?,
                rhs: Box::new(self.seq(rhs)?),
                at: *at,
            },
            Seq::Repeat { op, range, seq, at } => {
                let inner = self.seq(seq)?;
                if *op != RepOp::Consec && !matches!(inner, Seq::Bool { .. }) {
                    return err(*at, "goto [->n] and non-consecutive [=n] repetitions need a boolean, found a sequence");
                }
                Seq::Repeat { op: *op, range: self.range(range)?, seq: Box::new(inner), at: *at }
            }
            Seq::Binary { op, a, b, at } => Seq::Binary { op: *op, a: Box::new(self.seq(a)?), b: Box::new(self.seq(b)?), at: *at },
            Seq::Throughout { cond, seq, at } => {
                let c = self.seq(cond)?;
                if !matches!(c, Seq::Bool { .. }) {
                    return err(cond.at(), "the left side of throughout must be a boolean expression");
                }
                Seq::Throughout { cond: Box::new(c), seq: Box::new(self.seq(seq)?), at: *at }
            }
            Seq::FirstMatch { seq, at } => Seq::FirstMatch { seq: Box::new(self.seq(seq)?), at: *at },
        })
    }

    fn seq_by_name(&mut self, name: &str, args: &[Arg], at: Span) -> R<Seq> {
        match self.decl(name) {
            Some(Decl::Seq(k)) => self.seq_instance(k, name, args, at, false),
            Some(Decl::Prop(_)) => err(at, format!("the property '{name}' is used where a sequence is needed")),
            None => self.unknown(name, at),
        }
    }

    fn seq_instance(&mut self, k: usize, name: &str, args: &[Arg], at: Span, top: bool) -> R<Seq> {
        let u = self.u;
        let d = &u.seqs[k];
        if self.sh.stack.iter().any(|n| n == name) {
            return err(at, format!("the sequence '{name}' instantiates itself: recursion is outside the subset"));
        }
        let (env, args) = self.bind(&d.name, &d.ports, args, at, d.scope_id)?;
        if let Some(c) = &d.clock {
            self.sh.clocks.push((c.clone(), at, name.to_string()));
            if top {
                self.sh.top_clock = Some(c.clone());
            }
        }
        self.sh.stack.push(name.to_string());
        let body = X { u: self.u, scope: d.scope_id, env, sh: &mut *self.sh }.seq(&d.body);
        self.sh.stack.pop();
        Ok(Seq::Instance { name: name.to_string(), args, body: Some(Box::new(body?)), at })
    }

    fn prop_instance(&mut self, k: usize, name: &str, args: &[Arg], at: Span, top: bool) -> R<Prop> {
        let u = self.u;
        let d = &u.props[k];
        if self.sh.stack.iter().any(|n| n == name) {
            return err(at, format!("the property '{name}' instantiates itself: recursion is outside the subset"));
        }
        let (env, args) = self.bind(&d.name, &d.ports, args, at, d.scope_id)?;
        if let Some(c) = &d.clock {
            self.sh.clocks.push((c.clone(), at, name.to_string()));
            if top {
                self.sh.top_clock = Some(c.clone());
            }
        }
        self.sh.stack.push(name.to_string());
        let mut x = X { u: self.u, scope: d.scope_id, env, sh: &mut *self.sh };
        let disable = match &d.disable {
            Some(_) if !top => Err(SvaError::new(at, format!("the property '{name}' has disable iff: that is allowed only when it is the whole assertion"))),
            Some(e) => x.expr(e).map(Some),
            None => Ok(None),
        };
        let body = disable.and_then(|dis| {
            let b = x.prop(&d.body, false)?;
            if dis.is_some() {
                x.sh.top_disable = dis;
            }
            Ok(b)
        });
        self.sh.stack.pop();
        Ok(Prop::Instance { name: name.to_string(), args, body: Some(Box::new(body?)), at })
    }

    /// Actual arguments to formals: positional, then named; defaults (expanded where the declaration is); checks of
    /// count and kind. Returns the environment of the body and the expanded arguments (for the tree).
    fn bind(&mut self, decl: &str, ports: &[Port], args: &[Arg], at: Span, decl_scope: usize) -> R<(HashMap<String, Formal>, Vec<Arg>)> {
        let mut vals: Vec<Option<Option<Prop>>> = vec![None; ports.len()];
        let mut out = Vec::new();
        for (k, a) in args.iter().enumerate() {
            let idx = match &a.name {
                Some(n) => match ports.iter().position(|p| &p.name == n) {
                    Some(i) => i,
                    None => return err(at, format!("'{decl}' has no argument '{n}'")),
                },
                None if k < ports.len() => k,
                None => return err(at, format!("too many arguments: '{decl}' takes {}", ports.len())),
            };
            if vals[idx].is_some() {
                return err(at, format!("the argument '{}' of '{decl}' is given twice", ports[idx].name));
            }
            if a.value.is_none() && ports[idx].default.is_some() {
                out.push(Arg { name: a.name.clone(), value: None });
                continue; // an empty argument takes the default
            }
            let v = match &a.value {
                Some(p) => Some(self.prop(p, false)?),
                None => None,
            };
            if let Some(v) = &v {
                check_kind(decl, &ports[idx], v, at)?;
            }
            vals[idx] = Some(v.clone());
            out.push(Arg { name: a.name.clone(), value: v });
        }
        let mut env = HashMap::new();
        for (p, v) in ports.iter().zip(vals) {
            let value = match v {
                Some(v) => v,
                None => match &p.default {
                    Some(d) => {
                        let mut x = X { u: self.u, scope: decl_scope, env: HashMap::new(), sh: &mut *self.sh };
                        Some(x.prop(d, false)?)
                    }
                    None => return err(at, format!("the argument '{}' of '{decl}' is missing", p.name)),
                },
            };
            env.insert(p.name.clone(), Formal { value });
        }
        Ok((env, out))
    }

    fn expr(&mut self, e: &Expr) -> R<Expr> {
        let b = |x: &mut Self, e: &Expr| -> R<Box<Expr>> { Ok(Box::new(x.expr(e)?)) };
        Ok(match e {
            Expr::Ident { name, at } => {
                if let Some(f) = self.env.get(name) {
                    return match &f.value {
                        Some(Prop::Seq { seq: Seq::Bool { expr, .. } }) => Ok(expr.clone()),
                        Some(_) => err(*at, format!("the argument '{name}' is a sequence or a property, used here in an expression")),
                        None => err(*at, format!("the argument '{name}' is empty")),
                    };
                }
                if let Some(c) = self.u.constant(self.scope, name) {
                    return match c {
                        Ok((value, width)) => Ok(Expr::Const { name: name.clone(), value, width, at: *at }),
                        Err(m) => err(*at, format!("the constant '{name}' has no value: {m}")),
                    };
                }
                if let Some((p, n)) = name.split_once("::") {
                    return match self.u.packages.get(p) {
                        Some(_) => err(*at, format!("package '{p}' has no constant '{n}'")),
                        None => err(*at, format!("unknown package '{p}': give its file to sva parse first")),
                    };
                }
                if self.decl(name).is_some() {
                    return err(*at, format!("the sequence or property '{name}' is used inside an expression"));
                }
                if self.u.find(self.scope, |s| s.broken.get(name)).is_some() {
                    return self.unknown(name, *at);
                }
                if let Some((s, m)) = name.rsplit_once('.') {
                    if (m == "triggered" || m == "matched") && self.decl(s).is_some() {
                        return err(*at, format!(".{m} is outside the subset"));
                    }
                }
                e.clone()
            }
            Expr::Const { .. } | Expr::Number { .. } | Expr::Fill { .. } => e.clone(),
            Expr::Unary { op, a, at } => Expr::Unary { op: *op, a: b(self, a)?, at: *at },
            Expr::Binary { op, a, b: y, at } => Expr::Binary { op: *op, a: b(self, a)?, b: b(self, y)?, at: *at },
            Expr::Cond { c, a, b: y, at } => Expr::Cond { c: b(self, c)?, a: b(self, a)?, b: b(self, y)?, at: *at },
            Expr::Select { base, sel, index, lsb, at } => Expr::Select {
                base: b(self, base)?,
                sel: *sel,
                index: b(self, index)?,
                lsb: match lsb {
                    Some(l) => Some(b(self, l)?),
                    None => None,
                },
                at: *at,
            },
            Expr::Concat { items, at } => Expr::Concat { items: items.iter().map(|i| self.expr(i)).collect::<R<_>>()?, at: *at },
            Expr::Repl { count, items, at } => {
                let count = b(self, count)?;
                if let Err(m) = consts::eval(&count, &|_| None) {
                    return err(count.at(), format!("a replication count must be a constant: {m}"));
                }
                Expr::Repl { count, items: items.iter().map(|i| self.expr(i)).collect::<R<_>>()?, at: *at }
            }
            Expr::Inside { a, set, at } => Expr::Inside {
                a: b(self, a)?,
                set: set
                    .iter()
                    .map(|i| {
                        Ok(match i {
                            InsideItem::Value(v) => InsideItem::Value(self.expr(v)?),
                            InsideItem::Range { lo, hi } => InsideItem::Range { lo: self.expr(lo)?, hi: self.expr(hi)? },
                        })
                    })
                    .collect::<R<_>>()?,
                at: *at,
            },
            Expr::Call { func, args, at } => {
                let args: Vec<Expr> = args.iter().map(|a| self.expr(a)).collect::<R<_>>()?;
                if func == "$past" && args.len() == 2 {
                    match consts::eval(&args[1], &|_| None) {
                        Ok(n) if n >= 1 => {}
                        Ok(n) => return err(args[1].at(), format!("the depth of $past must be at least 1, got {n}")),
                        Err(m) => return err(args[1].at(), format!("the depth of $past must be a constant: {m}")),
                    }
                }
                Expr::Call { func: func.clone(), args, at: *at }
            }
            Expr::Cast { width, a, at } => Expr::Cast { width: *width, a: b(self, a)?, at: *at },
        })
    }

    fn bound(&mut self, b: &Bound) -> R<Bound> {
        let Bound::Expr(e) = b else { return Ok(b.clone()) };
        let x = self.expr(e)?;
        match consts::eval(&x, &|_| None) {
            Ok(v) if v < 0 => err(e.at(), format!("a delay or repetition count must not be negative, got {v}")),
            Ok(v) => match u32::try_from(v) {
                Ok(v) => Ok(Bound::Const(v)),
                Err(_) => err(e.at(), "the bound is too large"),
            },
            Err(m) => err(e.at(), format!("a delay or repetition count must be a constant: {m}")),
        }
    }

    fn range(&mut self, r: &Range) -> R<Range> {
        let (min, max) = (self.bound(&r.min)?, self.bound(&r.max)?);
        if let (Bound::Const(m), Bound::Const(n)) = (&min, &max) {
            if n < m {
                let at = match (&r.max, &r.min) {
                    (Bound::Expr(e), _) | (_, Bound::Expr(e)) => e.at(),
                    _ => Span::default(),
                };
                return err(at, format!("the range ends before it starts ({m}:{n})"));
            }
        }
        Ok(Range { min, max })
    }

    fn opt_range(&mut self, r: &Option<Range>) -> R<Option<Range>> {
        match r {
            Some(r) => Ok(Some(self.range(r)?)),
            None => Ok(None),
        }
    }
}

/// A sequence formal takes a sequence; a typed formal (`logic`, `int`, ...) an expression.
fn check_kind(decl: &str, p: &Port, v: &Prop, at: Span) -> R<()> {
    match p.ty.as_str() {
        "untyped" | "property" => Ok(()),
        "sequence" if v.as_seq().is_some() => Ok(()),
        "sequence" => err(at, format!("the argument '{}' of '{decl}' must be a sequence", p.name)),
        _ if matches!(v, Prop::Seq { seq: Seq::Bool { .. } }) => Ok(()),
        t => err(at, format!("the argument '{}' of '{decl}' ({t}) must be an expression", p.name)),
    }
}

/// The expanded assertion of a statement.
pub(crate) fn assertion(u: &UnitState, raw: &RawAssertion) -> R<Assertion> {
    let mut sh = Shared::default();
    let mut x = X { u, scope: raw.scope, env: HashMap::new(), sh: &mut sh };
    let mut prop = x.prop(&raw.prop, true)?;
    let disable = match &raw.disable {
        Some(d) => Some(x.expr(d)?),
        None => None,
    };
    let default_disable = match u.find(raw.scope, |s| s.default_disable.clone()) {
        Some(d) => Some(x.expr(&d)?),
        None => None,
    };
    let mut clock = raw.clock.clone().or(sh.top_clock.clone());
    for (c, at, name) in &sh.clocks {
        match &clock {
            Some(k) if k != c => return err(*at, format!("multi-clock: '{name}' is clocked by {c}, the assertion by {k}")),
            Some(_) => {}
            None => clock = Some(c.clone()),
        }
    }
    let Some(clock) = clock.or_else(|| u.find(raw.scope, |s| s.default_clock.clone())) else {
        return err(raw.at, "the assertion has no clock: write @(posedge clk) or declare a default clocking");
    };
    if let (Some(d), Some(_)) = (&disable, &sh.top_disable) {
        return err(d.at(), "disable iff is given twice: in the assertion and in the property");
    }
    let disable = disable.or(sh.top_disable.take()).or(default_disable);
    let property = match &prop {
        Prop::Instance { name, .. } | Prop::Seq { seq: Seq::Instance { name, .. } } => Some(name.clone()),
        _ => None,
    };
    let mut elements = Vec::new();
    ids_prop(&mut prop, &mut elements);
    let mut sigs: Vec<(String, Option<u32>)> = Vec::new();
    add_sig(&mut sigs, &clock.signal, None);
    if let Some(d) = &disable {
        sig_expr(d, &mut sigs);
    }
    sig_prop(&prop, &mut sigs);
    let lits: Vec<String> = sigs.iter().filter_map(|(n, _)| n.strip_prefix(SIGNED_LIT).map(String::from)).collect();
    sigs.retain(|(n, _)| !n.starts_with(SIGNED_LIT));
    let signed: Vec<String> = sigs.iter().filter(|(n, _)| u.find(raw.scope, |s| s.signed.contains(n).then_some(())).is_some()).map(|(n, _)| n.clone()).chain(lits).collect();
    let signals = sigs.into_iter().map(|(name, width)| SignalRef { declared: u.find(raw.scope, |s| s.nets.get(&name).copied()).flatten(), name, width }).collect();
    let line = raw.at.line as usize;
    let mut flags = Vec::new();
    if raw.kind == Kind::Assume {
        flags.push("assume: checked like an assertion".to_string());
    }
    if raw.cover_seq {
        flags.push("cover sequence: every match counts".to_string());
    }
    if !signed.is_empty() {
        flags.push(format!("compared as unsigned (no signed arithmetic in the engine): {}", signed.join(", ")));
    }
    let text = crate::engine::prop_text(&prop);
    Ok(Assertion {
        label: raw.label.clone().unwrap_or_else(|| format!("{}_{line}", raw.kind.word())),
        kind: raw.kind,
        scope: u.scope_name(raw.scope),
        property,
        clock,
        disable,
        prop,
        text,
        elements,
        signals,
        message: raw.message.clone(),
        severity: raw.severity.clone(),
        flags,
        line,
        at: raw.at,
    })
}

// ---- element ids and labels

fn ids_prop(p: &mut Prop, out: &mut Vec<Element>) {
    match p {
        Prop::Seq { seq } => ids_seq(seq, "", out),
        Prop::Implies { ante, cons, .. } => {
            ids_seq(ante, "", out);
            ids_prop(cons, out);
        }
        Prop::Not { p, .. } | Prop::Nexttime { p, .. } | Prop::Always { p, .. } | Prop::Eventually { p, .. } => ids_prop(p, out),
        Prop::Binary { a, b, .. } => {
            ids_prop(a, out);
            ids_prop(b, out);
        }
        Prop::If { then, else_, .. } => {
            ids_prop(then, out);
            if let Some(e) = else_ {
                ids_prop(e, out);
            }
        }
        Prop::Instance { body, .. } => {
            if let Some(b) = body {
                ids_prop(b, out);
            }
        }
    }
}

fn give_id(s: &mut Seq, label: String, out: &mut Vec<Element>) {
    if let Seq::Bool { id, at, .. } = s {
        let n = format!("s{}", out.len() + 1);
        *id = Some(n.clone());
        out.push(Element { id: n, label, at: *at });
    }
}

/// `pre` (a delay written in front, `##[1:3] `) goes into the label of the boolean it leads to.
fn ids_seq(s: &mut Seq, pre: &str, out: &mut Vec<Element>) {
    let pr = Printer::default();
    match s {
        Seq::Bool { expr, .. } => {
            let label = format!("{pre}{}", pr.expr(expr));
            give_id(s, label, out);
        }
        Seq::Delay { lhs, range, rhs, .. } => {
            let d = pr.delay(range);
            let pre_rhs = match lhs {
                Some(l) => {
                    ids_seq(l, pre, out);
                    format!("{d} ")
                }
                None => format!("{pre}{d} "),
            };
            match &**rhs {
                Seq::Bool { .. } | Seq::Repeat { .. } => ids_seq(rhs, &pre_rhs, out),
                _ => ids_seq(rhs, "", out),
            }
        }
        Seq::Repeat { .. } => {
            let label = format!("{pre}{}", pr.seq(s));
            let Seq::Repeat { seq, .. } = s else { unreachable!() };
            if matches!(**seq, Seq::Bool { .. }) {
                give_id(seq, label, out);
            } else {
                ids_seq(seq, "", out);
            }
        }
        Seq::Binary { a, b, .. } => {
            ids_seq(a, "", out);
            ids_seq(b, "", out);
        }
        Seq::Throughout { cond, seq, .. } => {
            ids_seq(cond, "", out);
            ids_seq(seq, "", out);
        }
        Seq::FirstMatch { seq, .. } => ids_seq(seq, "", out),
        Seq::Instance { body, .. } => {
            if let Some(b) = body {
                ids_seq(b, pre, out);
            }
        }
    }
}

// ---- signals

fn add_sig(out: &mut Vec<(String, Option<u32>)>, name: &str, width: Option<u32>) {
    match out.iter_mut().find(|s| s.0 == name) {
        Some(s) => s.1 = s.1.max(width),
        None => out.push((name.to_string(), width)),
    }
}

fn const_of(e: &Expr) -> Option<u32> {
    match e {
        Expr::Number { value, unknown: 0, .. } => u32::try_from(*value).ok(),
        Expr::Const { value, .. } => u32::try_from(*value).ok(),
        _ => consts::eval(e, &|_| None).ok().and_then(|v| u32::try_from(v).ok()),
    }
}

fn sig_expr(e: &Expr, out: &mut Vec<(String, Option<u32>)>) {
    match e {
        Expr::Ident { name, .. } => add_sig(out, name, None),
        Expr::Select { base, sel, index, lsb, .. } => {
            if let Expr::Ident { name, .. } = &**base {
                let (i, l) = (const_of(index), lsb.as_ref().and_then(|l| const_of(l)));
                let w = match sel {
                    SelKind::Bit | SelKind::Down => i.map(|i| i + 1),
                    SelKind::Part => i.zip(l).map(|(a, b)| a.max(b) + 1),
                    SelKind::Up => i.zip(l).map(|(a, b)| a + b),
                };
                add_sig(out, name, w);
            } else {
                sig_expr(base, out);
            }
            sig_expr(index, out);
            if let Some(l) = lsb {
                sig_expr(l, out);
            }
        }
        Expr::Number { signed: true, width, base, text, .. } if width.is_some() || *base != 10 => add_sig(out, &format!("{SIGNED_LIT}{text}"), None),
        Expr::Const { .. } | Expr::Number { .. } | Expr::Fill { .. } => {}
        Expr::Unary { a, .. } | Expr::Cast { a, .. } => sig_expr(a, out),
        Expr::Binary { a, b, .. } => {
            sig_expr(a, out);
            sig_expr(b, out);
        }
        Expr::Cond { c, a, b, .. } => {
            sig_expr(c, out);
            sig_expr(a, out);
            sig_expr(b, out);
        }
        Expr::Concat { items, .. } | Expr::Call { args: items, .. } => items.iter().for_each(|i| sig_expr(i, out)),
        Expr::Repl { count, items, .. } => {
            sig_expr(count, out);
            items.iter().for_each(|i| sig_expr(i, out));
        }
        Expr::Inside { a, set, .. } => {
            sig_expr(a, out);
            for i in set {
                match i {
                    InsideItem::Value(v) => sig_expr(v, out),
                    InsideItem::Range { lo, hi } => {
                        sig_expr(lo, out);
                        sig_expr(hi, out);
                    }
                }
            }
        }
    }
}

fn sig_seq(s: &Seq, out: &mut Vec<(String, Option<u32>)>) {
    match s {
        Seq::Bool { expr, .. } => sig_expr(expr, out),
        Seq::Delay { lhs, rhs, .. } => {
            if let Some(l) = lhs {
                sig_seq(l, out);
            }
            sig_seq(rhs, out);
        }
        Seq::Repeat { seq, .. } | Seq::FirstMatch { seq, .. } => sig_seq(seq, out),
        Seq::Binary { a, b, .. } | Seq::Throughout { cond: a, seq: b, .. } => {
            sig_seq(a, out);
            sig_seq(b, out);
        }
        Seq::Instance { body, .. } => {
            if let Some(b) = body {
                sig_seq(b, out);
            }
        }
    }
}

fn sig_prop(p: &Prop, out: &mut Vec<(String, Option<u32>)>) {
    match p {
        Prop::Seq { seq } => sig_seq(seq, out),
        Prop::Implies { ante, cons, .. } => {
            sig_seq(ante, out);
            sig_prop(cons, out);
        }
        Prop::Not { p, .. } | Prop::Nexttime { p, .. } | Prop::Always { p, .. } | Prop::Eventually { p, .. } => sig_prop(p, out),
        Prop::Binary { a, b, .. } => {
            sig_prop(a, out);
            sig_prop(b, out);
        }
        Prop::If { cond, then, else_, .. } => {
            sig_expr(cond, out);
            sig_prop(then, out);
            if let Some(e) = else_ {
                sig_prop(e, out);
            }
        }
        Prop::Instance { body, .. } => {
            if let Some(b) = body {
                sig_prop(b, out);
            }
        }
    }
}
