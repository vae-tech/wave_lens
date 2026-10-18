//! Parser, part 2: expressions (booleans and integral values), by precedence climbing over IEEE 1800-2017 table 11-2.

use crate::ast::*;
use crate::lex::Tok;
use crate::parse::{is_keyword, Parser, R};

/// The system functions of the subset: name, least and most arguments.
pub(crate) const SYSFUNCS: &[(&str, usize, usize)] = &[
    ("$rose", 1, 1),
    ("$fell", 1, 1),
    ("$stable", 1, 1),
    ("$changed", 1, 1),
    ("$past", 1, 2),
    ("$onehot", 1, 1),
    ("$onehot0", 1, 1),
    ("$countones", 1, 1),
    ("$isunknown", 1, 1),
    ("$sampled", 1, 1),
    ("$bits", 1, 1),
    ("$clog2", 1, 1),
];

impl<'a> Parser<'a> {
    pub fn expr(&mut self) -> R<Expr> {
        self.deeper(1)?;
        let r = self.expr_in();
        self.up(1);
        r
    }

    fn expr_in(&mut self) -> R<Expr> {
        let from = self.i;
        let c = self.binary(2)?;
        if !self.eat("?") {
            return Ok(c);
        }
        let a = self.expr()?;
        self.expect(":")?;
        let b = self.expr()?;
        Ok(Expr::Cond { c: Box::new(c), a: Box::new(a), b: Box::new(b), at: self.span_from(from) })
    }

    fn binop(&self) -> Option<BinOp> {
        match self.tok() {
            Tok::Sym(s) => BinOp::from_sym(s),
            _ => None,
        }
    }

    fn binary(&mut self, min: u8) -> R<Expr> {
        let from = self.i;
        let mut a = self.unary()?;
        let mut wraps = 0;
        let r = loop {
            if let Tok::Sym(s @ ("==?" | "!=?" | "->" | "<->")) = self.tok() {
                return self.error(self.at(), format!("the operator {s} is outside the subset"));
            }
            if self.is("dist") {
                return self.error(self.at(), "dist is outside the subset");
            }
            if self.is("inside") && 8 >= min {
                self.i += 1;
                let set = self.inside_set()?;
                a = Expr::Inside { a: Box::new(a), set, at: self.span_from(from) };
                continue;
            }
            let Some(op) = self.binop() else { break Ok(a) };
            let p = op.prec();
            if p < min {
                break Ok(a);
            }
            self.i += 1;
            if let Err(e) = self.deeper(1) {
                break Err(e);
            }
            wraps += 1;
            let b = self.binary(p + 1)?;
            a = Expr::Binary { op, a: Box::new(a), b: Box::new(b), at: self.span_from(from) };
        };
        self.up(wraps);
        r
    }

    fn inside_set(&mut self) -> R<Vec<InsideItem>> {
        self.expect("{")?;
        let mut set = Vec::new();
        loop {
            if self.eat("[") {
                let lo = self.expr()?;
                self.expect(":")?;
                let hi = self.expr()?;
                self.expect("]")?;
                set.push(InsideItem::Range { lo, hi });
            } else {
                set.push(InsideItem::Value(self.expr()?));
            }
            if self.eat(",") {
                continue;
            }
            self.expect("}")?;
            return Ok(set);
        }
    }

    fn unary(&mut self) -> R<Expr> {
        let from = self.i;
        if let Tok::Sym(s) = self.tok() {
            if *s == "++" || *s == "--" {
                return self.error(self.at(), format!("{s} is outside the subset"));
            }
            if let Some(op) = UnOp::from_sym(s) {
                self.i += 1;
                self.deeper(1)?;
                let a = self.unary();
                self.up(1);
                return Ok(Expr::Unary { op, a: Box::new(a?), at: self.span_from(from) });
            }
        }
        let mut e = self.primary()?;
        let mut wraps = 0;
        while self.is("[") {
            self.i += 1;
            self.deeper(1)?;
            wraps += 1;
            let index = self.expr()?;
            let (sel, lsb) = if self.eat(":") {
                (SelKind::Part, Some(Box::new(self.expr()?)))
            } else if self.eat("+:") {
                (SelKind::Up, Some(Box::new(self.expr()?)))
            } else if self.eat("-:") {
                (SelKind::Down, Some(Box::new(self.expr()?)))
            } else {
                (SelKind::Bit, None)
            };
            self.expect("]")?;
            e = Expr::Select { base: Box::new(e), sel, index: Box::new(index), lsb, at: self.span_from(from) };
        }
        self.up(wraps);
        Ok(e)
    }

    pub(crate) fn primary(&mut self) -> R<Expr> {
        let from = self.i;
        let at = self.at();
        match self.tok().clone() {
            Tok::Num(n) => {
                self.i += 1;
                if self.eat("'(") {
                    let Ok(width) = u32::try_from(n.value) else { return self.error(at, "cast width too large") };
                    if width == 0 || n.base != 10 || n.width.is_some() {
                        return self.error(at, "a size cast needs a positive decimal width: 8'(x)");
                    }
                    let a = self.expr()?;
                    self.expect(")")?;
                    return Ok(Expr::Cast { width, a: Box::new(a), at: self.span_from(from) });
                }
                Ok(Expr::Number { value: n.value, unknown: n.unknown, width: n.width, signed: n.signed, base: n.base, text: n.text, at })
            }
            Tok::Fill(bit) => {
                self.i += 1;
                Ok(Expr::Fill { bit, at })
            }
            Tok::Str(_) => self.error(at, "strings are outside the subset (except in action block messages)"),
            Tok::Sys(name) => self.sysfunc(name),
            Tok::Sym("(") => {
                self.i += 1;
                let e = self.expr()?;
                self.expect(")")?;
                Ok(e)
            }
            Tok::Sym("{") => {
                self.i += 1;
                let first = self.expr()?;
                if self.eat("{") {
                    let mut items = vec![self.expr()?];
                    while self.eat(",") {
                        items.push(self.expr()?);
                    }
                    self.expect("}")?;
                    self.expect("}")?;
                    return Ok(Expr::Repl { count: Box::new(first), items, at: self.span_from(from) });
                }
                let mut items = vec![first];
                while self.eat(",") {
                    items.push(self.expr()?);
                }
                self.expect("}")?;
                Ok(Expr::Concat { items, at: self.span_from(from) })
            }
            Tok::Sym("'{") => self.error(at, "assignment patterns '{...} are outside the subset"),
            Tok::Sym("'(") => self.error(at, "type casts are outside the subset (size casts 8'(x) are in)"),
            Tok::Sym("$") => self.error(at, "'$' is only allowed as the end of a range"),
            Tok::Sym("@") => self.error(at, "a clock inside a property (multi-clock) is outside the subset"),
            Tok::Id(s) if is_keyword(&s) => {
                if s == "type" || DATA_TYPES.contains(&s.as_str()) {
                    return self.error(at, format!("type casts ({s}'(...)) are outside the subset"));
                }
                self.expected("an expression")
            }
            Tok::Id(s) => {
                self.i += 1;
                let mut name = s;
                if self.is("::") {
                    self.i += 1;
                    name = format!("{name}::{}", self.ident()?.0);
                }
                // a hierarchical name: `a.b`, with constant indices in the middle `gen[0].u.x`
                loop {
                    if self.is(".") && self.peek_ident(1).is_some() {
                        self.i += 1;
                        name = format!("{name}.{}", self.ident()?.0);
                    } else if self.is("[") && matches!(self.tok_at(1), Tok::Num(_)) && self.is_at(2, "]") && self.is_at(3, ".") && self.peek_ident(4).is_some() {
                        let Tok::Num(n) = self.tok_at(1).clone() else { unreachable!() };
                        self.i += 4;
                        name = format!("{name}[{}].{}", n.text, self.ident()?.0);
                    } else {
                        break;
                    }
                }
                if self.is("(") {
                    return self.error(at, format!("calls inside an expression ({name}(...)) are outside the subset: only sequence and property instances, outside booleans"));
                }
                if self.is("'(") {
                    // a size cast by a constant (`p_PTR_W'(x)`, a parameter of the module): its value is the width
                    let id = Expr::Ident { name: name.clone(), at: self.span_from(from) };
                    return match self.u.eval(self.scope, &id).ok().and_then(|v| u32::try_from(v).ok()).filter(|w| *w > 0) {
                        Some(width) => {
                            self.i += 1;
                            let a = self.expr()?;
                            self.expect(")")?;
                            Ok(Expr::Cast { width, a: Box::new(a), at: self.span_from(from) })
                        }
                        None => self.error(at, format!("type casts are outside the subset (size casts 8'(x) and N'(x) with a constant N are in; {name} is no constant width)")),
                    };
                }
                Ok(Expr::Ident { name, at: self.span_from(from) })
            }
            _ => self.expected("an expression"),
        }
    }

    fn sysfunc(&mut self, name: String) -> R<Expr> {
        let from = self.i;
        let at = self.at();
        let Some(&(_, min, max)) = SYSFUNCS.iter().find(|f| f.0 == name) else {
            return self.error(at, format!("the system function {name} is outside the subset"));
        };
        self.i += 1;
        self.expect("(")?;
        let mut args = Vec::new();
        if !self.is(")") {
            loop {
                if self.is("@") {
                    return self.error(self.at(), format!("a clock argument of {name} is outside the subset: the assertion's clock is used"));
                }
                if self.is(",") && name == "$past" {
                    return self.error(self.at(), "$past with an empty argument is outside the subset");
                }
                args.push(self.expr()?);
                if !self.eat(",") {
                    break;
                }
            }
        }
        self.expect(")")?;
        let at = at.to(self.prev());
        if name == "$past" && args.len() > 2 {
            return self.error(at, "the gating and clock arguments of $past are outside the subset: $past(x [, n])");
        }
        if args.len() < min || args.len() > max {
            let n = if min == max { format!("{min} argument") } else { format!("{min} to {max} arguments") };
            return self.error(at, format!("{name} takes {n}, got {}", args.len()));
        }
        Ok(Expr::Call { func: name, args, at: self.span_from(from) })
    }
}

const DATA_TYPES: &[&str] = &["logic", "bit", "reg", "int", "integer", "byte", "shortint", "longint", "signed", "unsigned", "string"];
