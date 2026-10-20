//! Parser, part 3: declarations — data types and packed dimensions, parameters, imports, typedefs (enums, packed
//! structs), clocking blocks, the clock event of an assertion, bind, and the signals of a scope (their widths).

use crate::ast::*;
use crate::lex::Tok;
use crate::parse::{is_keyword, signed_type, truncate, ConstVal, Parser, NET_KW, R};

impl Parser<'_> {
    /// Unpacked dimensions after a name: skipped.
    pub(crate) fn skip_dims(&mut self) {
        while self.is("[") {
            self.i += 1;
            self.skip_until(&["]"]);
            self.i += 1;
        }
    }

    /// Up to (not taking) one of `stops` outside brackets.
    pub(crate) fn skip_until(&mut self, stops: &[&str]) {
        let mut br = 0i32;
        loop {
            match self.tok() {
                Tok::End => return,
                Tok::Sym(s) if br == 0 && stops.contains(s) => return,
                Tok::Sym("(" | "[" | "{" | "'{" | "'(") => br += 1,
                Tok::Sym(")" | "]" | "}") => br -= 1,
                _ => {}
            }
            self.i += 1;
        }
    }

    /// A data type, if one is here: its text and width (`None`: not integral or unknown). `logic [7:0]` -> 8,
    /// `int` -> 32, a typedef name -> its width, `foo bar` -> `foo` is taken as a type of unknown width.
    pub fn data_type(&mut self) -> R<Option<(String, Option<u32>)>> {
        let start = self.i;
        let w = match self.tok() {
            Tok::Id(w) => w.clone(),
            Tok::Sym("[") => {
                let w = self.packed_dims()?.unwrap_or(None);
                return Ok(Some(("logic".into(), w)));
            }
            _ => return Ok(None),
        };
        let base = |w: &str| -> Option<Option<u32>> {
            Some(match w {
                "logic" | "reg" | "bit" => Some(1),
                "int" | "integer" => Some(32),
                "shortint" => Some(16),
                "longint" | "time" => Some(64),
                "byte" => Some(8),
                "string" | "real" | "shortreal" | "realtime" | "chandle" => None,
                _ => return None,
            })
        };
        let width = if NET_KW.contains(&w.as_str()) {
            self.i += 1;
            // `wire pkg::rsp_t x`, `wire my_t x`: the net keyword, then a type name
            if let Tok::Id(x) = self.tok().clone() {
                if base(&x).is_none() && !is_keyword(&x) && (self.is_at(1, "::") || self.peek_ident(1).is_some()) {
                    let t = self.data_type()?;
                    return Ok(t.map(|(_, wd)| (self.text(start, self.i), wd)));
                }
            }
            let mut wd = Some(1);
            if let Tok::Id(x) = self.tok().clone() {
                if let Some(b) = base(&x) {
                    self.i += 1;
                    wd = b;
                }
            }
            let _ = self.eat("signed") || self.eat("unsigned");
            self.packed_dims()?.unwrap_or(wd)
        } else if let Some(b) = base(&w) {
            self.i += 1;
            let _ = self.eat("signed") || self.eat("unsigned");
            match self.packed_dims()? {
                Some(d) if b == Some(1) => d,
                Some(d) => d.zip(b).map(|(a, b)| a * b),
                None => b,
            }
        } else if w == "signed" || w == "unsigned" {
            self.i += 1;
            self.packed_dims()?.unwrap_or(Some(1))
        } else if is_keyword(&w) {
            return Ok(None);
        } else if self.is_at(1, "::") && self.peek_ident(2).is_some() && self.peek_ident(3).is_some() {
            let name = format!("{w}::{}", self.peek_ident(2).unwrap());
            self.i += 3;
            let tw = self.u.type_width(self.scope, &name).flatten();
            self.packed_dims()?.map_or(tw, |d| d.zip(tw).map(|(a, b)| a * b))
        } else if let Some(tw) = self.u.type_width(self.scope, &w) {
            if self.peek_ident(1).is_none() && !self.is_at(1, "[") {
                return Ok(None);
            }
            self.i += 1;
            self.packed_dims()?.map_or(tw, |d| d.zip(tw).map(|(a, b)| a * b))
        } else if self.peek_ident(1).is_some() {
            self.i += 1;
            None
        } else {
            return Ok(None);
        };
        Ok(Some((self.text(start, self.i), width)))
    }

    /// Packed dimensions `[7:0][3:0]`: `None` when there are none, `Some(None)` when a bound is not constant.
    pub(crate) fn packed_dims(&mut self) -> R<Option<Option<u32>>> {
        if !self.is("[") {
            return Ok(None);
        }
        let mut w = Some(1u32);
        while self.eat("[") {
            let a = self.expr()?;
            let n = if self.eat(":") {
                let b = self.expr()?;
                match (self.u.eval(self.scope, &a), self.u.eval(self.scope, &b)) {
                    (Ok(a), Ok(b)) => a.checked_sub(b).and_then(|d| d.unsigned_abs().checked_add(1)).and_then(|n| u32::try_from(n).ok()),
                    _ => None,
                }
            } else {
                self.u.eval(self.scope, &a).ok().and_then(|v| u32::try_from(v).ok())
            };
            self.expect("]")?;
            w = w.zip(n).map(|(a, b)| a.saturating_mul(b));
        }
        Ok(Some(w))
    }

    /// `[type] NAME [= expr] {, NAME [= expr]}` of a `localparam` / `parameter` (`in_body`: up to the `;`; in a
    /// `#(...)` list one item, the caller takes the commas).
    pub(crate) fn param_assignments(&mut self, in_body: bool) -> R<Vec<Param>> {
        let mut out = Vec::new();
        if self.eat("type") {
            self.skip_until(&[",", ";", ")"]);
            return Ok(out);
        }
        let ty = self.data_type()?;
        let width = ty.and_then(|t| t.1);
        loop {
            let (name, _) = self.ident()?;
            self.skip_dims();
            let val: ConstVal = if self.eat("=") {
                let e = self.expr()?;
                self.u.eval(self.scope, &e).map(|v| (truncate(v, width), width))
            } else {
                Err(format!("parameter '{name}' has no value"))
            };
            out.push(Param { name: name.clone(), value: val.as_ref().ok().map(|v| v.0) });
            self.u.scopes[self.scope].consts.insert(name, val);
            if in_body && self.eat(",") {
                continue;
            }
            return Ok(out);
        }
    }

    pub(crate) fn import(&mut self) -> R<()> {
        self.expect("import")?;
        loop {
            let (pkg, at) = self.ident()?;
            self.expect("::")?;
            let name = if self.eat("*") { None } else { Some(self.ident()?.0) };
            match self.u.packages.get(&pkg).copied() {
                Some(p) => {
                    let src = self.u.scopes[p].clone();
                    let dst = &mut self.u.scopes[self.scope];
                    let wanted = |n: &String| name.as_ref().is_none_or(|x| x == n);
                    let wild = name.is_none();
                    macro_rules! copy {
                        ($f:ident) => {
                            for (k, v) in &src.$f {
                                if wanted(k) && !(wild && dst.$f.contains_key(k)) {
                                    dst.$f.insert(k.clone(), v.clone());
                                }
                            }
                        };
                    }
                    copy!(consts);
                    copy!(types);
                    copy!(seqs);
                    copy!(props);
                    if let Some(n) = &name {
                        if ![src.consts.contains_key(n), src.types.contains_key(n), src.seqs.contains_key(n), src.props.contains_key(n)].contains(&true) {
                            return self.error(at.to(self.prev()), format!("package '{pkg}' has no '{n}'"));
                        }
                    }
                }
                None => self.warn(at, format!("package '{pkg}' is not loaded: its names are read as signals (give its file to sva parse first)")),
            }
            if self.eat(",") {
                continue;
            }
            self.expect(";")?;
            return Ok(());
        }
    }

    /// `struct packed [signed] { type a, b; type c; } NAME [dims];` -> (NAME, the sum of the members' widths).
    pub(crate) fn packed_struct(&mut self) -> R<(String, Option<u32>)> {
        self.i += 2;
        let _ = self.eat("signed") || self.eat("unsigned");
        self.expect("{")?;
        let mut width = Some(0u32);
        while !self.eat("}") {
            let t = match self.data_type()? {
                Some((_, w)) => w,
                None => return self.expected("a member type"),
            };
            loop {
                self.ident()?;
                width = width.zip(t).map(|(a, b)| a + b);
                if !self.eat(",") {
                    break;
                }
            }
            self.expect(";")?;
        }
        let (name, _) = self.ident()?;
        self.skip_dims();
        self.expect(";")?;
        Ok((name, width))
    }

    pub(crate) fn typedef(&mut self) -> R<()> {
        self.expect("typedef")?;
        if self.eat("enum") {
            let width = if self.is("{") { Some(32) } else { self.data_type()?.and_then(|t| t.1) };
            self.expect("{")?;
            let mut next = 0i64;
            loop {
                let (n, at) = self.ident()?;
                if self.is("[") {
                    return self.error(self.at(), "enum label ranges (A[3]) are outside the subset");
                }
                let v = if self.eat("=") {
                    let e = self.expr()?;
                    match self.u.eval(self.scope, &e) {
                        Ok(v) => v,
                        Err(m) => return self.error(e.at(), format!("enum label '{n}': {m}")),
                    }
                } else {
                    next
                };
                self.u.scopes[self.scope].consts.insert(n.clone(), Ok((truncate(v, width), width)));
                next = match v.checked_add(1) {
                    Some(n) => n,
                    None if self.is(",") => return self.error(at, format!("enum label '{n}': the next label's value would overflow")),
                    None => v,
                };
                if self.eat(",") {
                    continue;
                }
                self.expect("}")?;
                break;
            }
            let (name, _) = self.ident()?;
            self.expect(";")?;
            self.u.scopes[self.scope].types.insert(name, width);
            return Ok(());
        }
        if self.is("struct") && self.is_at(1, "packed") {
            // a packed struct: its width is the sum of its members' (a form it does not read: skipped as below)
            let save = self.i;
            match self.packed_struct() {
                Ok((name, width)) => {
                    self.u.scopes[self.scope].types.insert(name, width);
                    return Ok(());
                }
                Err(_) => self.i = save,
            }
        }
        if self.is("struct") || self.is("union") || self.is("class") || self.is("interface") {
            let mut last = None;
            let mut br = 0;
            loop {
                match self.tok().clone() {
                    Tok::End => return self.expected("';'"),
                    Tok::Sym("{") => br += 1,
                    Tok::Sym("}") => br -= 1,
                    Tok::Sym(";") if br == 0 => break,
                    Tok::Id(n) if br == 0 => last = Some(n),
                    _ => {}
                }
                self.i += 1;
            }
            self.i += 1;
            if let Some(n) = last {
                self.u.scopes[self.scope].types.insert(n, None);
            }
            return Ok(());
        }
        let width = match self.data_type()? {
            Some((_, w)) => w,
            None => return self.expected("a type"),
        };
        let (name, _) = self.ident()?;
        self.skip_dims();
        self.expect(";")?;
        self.u.scopes[self.scope].types.insert(name, width);
        Ok(())
    }

    /// `[default] clocking [name] @(event); ... endclocking`, `default clocking name;`.
    pub(crate) fn clocking_decl(&mut self, default: bool) -> R<()> {
        self.expect("clocking")?;
        let name = if self.peek_ident(0).is_some() { Some(self.ident()?) } else { None };
        if default && self.is(";") {
            let Some((n, at)) = name else { return self.expected("a clocking event") };
            self.i += 1;
            let Some(c) = self.u.find(self.scope, |s| s.clockings.get(&n).cloned()) else {
                return self.error(at, format!("no clocking block '{n}'"));
            };
            self.u.scopes[self.scope].default_clock = Some(c);
            return Ok(());
        }
        let c = self.clock_event()?;
        self.expect(";")?;
        while !self.is("endclocking") {
            if matches!(self.tok(), Tok::End) {
                return self.expected("'endclocking'");
            }
            self.i += 1;
        }
        self.i += 1;
        self.end_label();
        let sc = &mut self.u.scopes[self.scope];
        if let Some((n, _)) = name {
            sc.clockings.insert(n, c.clone());
        }
        if default {
            sc.default_clock = Some(c);
        }
        Ok(())
    }

    /// `@(posedge clk)`, `@(negedge clk)`, `@(edge clk)`, `@(clk)` / `@clk` (both edges), `@(cb)` / `@cb` (a clocking
    /// block).
    pub fn clock_event(&mut self) -> R<Clock> {
        self.expect("@")?;
        let paren = self.eat("(");
        if !paren && self.is("*") {
            return self.error(self.at(), "@* is not a clock");
        }
        let edge = ["posedge", "negedge", "edge"].iter().find(|e| self.is(e)).map(|e| e.to_string());
        if edge.is_some() {
            self.i += 1;
        }
        let (signal, _) = match self.hier_name() {
            Ok(x) => x,
            Err(_) => return self.expected("a clock signal"),
        };
        if paren {
            if self.is("iff") {
                return self.error(self.at(), "@(... iff ...) clock gating is outside the subset");
            }
            if self.is("or") || self.is(",") {
                return self.error(self.at(), "clock events with several signals are outside the subset");
            }
            self.expect(")")?;
        }
        if edge.is_none() {
            if let Some(c) = self.u.find(self.scope, |s| s.clockings.get(&signal).cloned()) {
                return Ok(c);
            }
        }
        Ok(Clock { edge: edge.unwrap_or_else(|| "edge".into()), signal })
    }

    pub(crate) fn bind(&mut self) -> R<()> {
        let at = self.at();
        self.expect("bind")?;
        let (target, _) = self.hier_name()?;
        let mut instances = Vec::new();
        if self.eat(":") {
            loop {
                instances.push(self.hier_name()?.0);
                if !self.eat(",") {
                    break;
                }
            }
        }
        let (module, _) = self.ident()?;
        if self.eat("#") {
            self.expect("(")?;
            self.skip_until(&[")"]);
            self.expect(")")?;
        }
        let (instance, _) = self.ident()?;
        self.skip_dims();
        self.expect("(")?;
        let mut ports = Vec::new();
        if !self.eat(")") {
            loop {
                if self.eat(".*") {
                    ports.push(BindPort { name: Some("*".into()), expr: String::new() });
                } else if self.eat(".") {
                    let (n, _) = self.ident()?;
                    let expr = if self.eat("(") {
                        let s = self.i;
                        self.skip_until(&[")"]);
                        let e = self.text(s, self.i);
                        self.expect(")")?;
                        e
                    } else {
                        n.clone()
                    };
                    ports.push(BindPort { name: Some(n), expr });
                } else {
                    let s = self.i;
                    self.skip_until(&[",", ")"]);
                    ports.push(BindPort { name: None, expr: self.text(s, self.i) });
                }
                if self.eat(",") {
                    continue;
                }
                self.expect(")")?;
                break;
            }
        }
        self.skip_until(&[";"]);
        self.expect(";")?;
        self.binds.push(Bind { target, instances, module, instance, ports, at: at.to(self.prev()) });
        Ok(())
    }

    /// `[input|output|inout] type name [dims] [= init] {, ...};` — the widths of signals. `false` (nothing taken) when
    /// the item is something else.
    pub(crate) fn decl_item(&mut self) -> bool {
        let save = self.i;
        let dir = ["input", "output", "inout"].iter().any(|d| self.eat(d));
        let dt = match self.data_type() {
            Ok(d) => d,
            Err(_) => {
                self.i = save;
                return false;
            }
        };
        if dt.is_none() && !dir {
            self.i = save;
            return false;
        }
        let signed = dt.as_ref().is_some_and(|d| signed_type(&d.0));
        let width = dt.map_or(Some(1), |d| d.1);
        let mut names = Vec::new();
        loop {
            let Some(n) = self.peek_ident(0).map(String::from) else {
                self.i = save;
                return false;
            };
            self.i += 1;
            self.skip_dims();
            if self.eat("=") {
                self.skip_until(&[",", ";"]);
            }
            names.push(n);
            if self.eat(",") {
                continue;
            }
            if self.eat(";") {
                break;
            }
            self.i = save;
            return false;
        }
        for n in names {
            if signed {
                self.u.scopes[self.scope].signed.insert(n.clone());
            }
            self.u.scopes[self.scope].nets.insert(n, width);
        }
        true
    }
}
