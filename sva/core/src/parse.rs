//! Parser, part 1: the items of a file — scopes (module, interface, program, checker, package), `property` and
//! `sequence` declarations, assertion statements with their action blocks, constants, typedefs, imports, default
//! clocking / disable, bind, and declarations of signals (for their widths). Everything else in a module (always blocks,
//! tasks, instances, ...) is skipped. An error ends the item it is in; parsing goes on with the next one.
//!
//! Expressions are in `expr.rs`, sequences and properties in `prop.rs`, the expansion of assertions in `expand.rs`.

use crate::ast::*;
use crate::consts;
use crate::lex::{Span, Tok, Token};
use crate::pre::{Diag, Macro};
use crate::SvaError;
use std::collections::HashMap;

pub(crate) type R<T> = Result<T, SvaError>;

/// A constant: value and width (`None`: unsized), or why it has no value.
pub(crate) type ConstVal = Result<(i64, Option<u32>), String>;

#[derive(Clone, Debug, Default)]
pub(crate) struct Scope {
    pub name: String,
    pub parent: Option<usize>,
    pub consts: HashMap<String, ConstVal>,
    pub types: HashMap<String, Option<u32>>,
    pub seqs: HashMap<String, usize>,
    pub props: HashMap<String, usize>,
    /// Declarations that did not parse: a use names them instead of saying "unknown".
    pub broken: HashMap<String, Span>,
    pub nets: HashMap<String, Option<u32>>,
    /// Nets of a signed type (`int`, `byte`, `logic signed`, ...): the engine compares them as unsigned (a warning).
    pub signed: std::collections::HashSet<String>,
    pub clockings: HashMap<String, Clock>,
    pub default_clock: Option<Clock>,
    pub default_disable: Option<Expr>,
}

/// What the files of one compilation unit share: macros, scopes (0 is `$unit`), packages, declarations.
#[derive(Debug)]
pub(crate) struct UnitState {
    pub macros: HashMap<String, Macro>,
    pub scopes: Vec<Scope>,
    pub packages: HashMap<String, usize>,
    pub seqs: Vec<SeqDecl>,
    pub props: Vec<PropDecl>,
    /// The label of every assertion of the unit so far -> its module (a label is unique only in its module).
    pub labels: HashMap<String, Option<String>>,
}

impl Default for UnitState {
    fn default() -> Self {
        UnitState { macros: HashMap::new(), scopes: vec![Scope::default()], packages: HashMap::new(), seqs: Vec::new(), props: Vec::new(), labels: HashMap::new() }
    }
}

impl UnitState {
    /// The first `f(scope)` that is `Some`, from `s` out to `$unit`.
    pub fn find<'s, T>(&'s self, mut s: usize, f: impl Fn(&'s Scope) -> Option<T>) -> Option<T> {
        loop {
            if let Some(x) = f(&self.scopes[s]) {
                return Some(x);
            }
            s = self.scopes[s].parent?;
        }
    }
    /// A constant by name (`N`, `pkg::N`) as seen from scope `s`; `None`: no such constant.
    pub fn constant(&self, s: usize, name: &str) -> Option<ConstVal> {
        if let Some((p, n)) = name.split_once("::") {
            return self.packages.get(p).and_then(|&k| self.scopes[k].consts.get(n).cloned());
        }
        self.find(s, |sc| sc.consts.get(name).cloned())
    }
    pub fn eval(&self, s: usize, e: &Expr) -> Result<i64, String> {
        consts::eval(e, &|n| self.constant(s, n).map(|r| r.map(|v| v.0)))
    }
    pub fn type_width(&self, s: usize, name: &str) -> Option<Option<u32>> {
        if let Some((p, n)) = name.split_once("::") {
            return self.packages.get(p).and_then(|&k| self.scopes[k].types.get(n).copied());
        }
        self.find(s, |sc| sc.types.get(name).copied())
    }
    pub fn scope_name(&self, s: usize) -> Option<String> {
        (s != 0).then(|| self.scopes[s].name.clone())
    }
}

/// An assertion statement as written; `expand.rs` turns it into an [`Assertion`].
#[derive(Clone, Debug)]
pub(crate) struct RawAssertion {
    pub label: Option<String>,
    pub kind: Kind,
    pub cover_seq: bool,
    pub clock: Option<Clock>,
    pub disable: Option<Expr>,
    pub prop: Prop,
    pub message: Option<String>,
    pub severity: Option<String>,
    pub scope: usize,
    pub at: Span,
}

pub(crate) struct Parser<'a> {
    pub src: &'a str,
    pub t: Vec<Token>,
    pub i: usize,
    pub u: &'a mut UnitState,
    pub scope: usize,
    pub diag: Diag,
    pub raw: Vec<RawAssertion>,
    pub scopes_out: Vec<ScopeInfo>,
    pub binds: Vec<Bind>,
    /// Indices into `u.seqs` / `u.props` of the declarations of this file.
    pub seq_out: Vec<usize>,
    pub prop_out: Vec<usize>,
    /// The nesting of the item being parsed (parentheses, operators): deeper than `MAX_NEST` is an error, so that no
    /// stage (parser, expansion, evaluation, drop) can overflow the stack (the WebAssembly one is 1 MB).
    pub nest: u32,
}

pub(crate) const MAX_NEST: u32 = 500;

/// SystemVerilog keywords that cannot be signal names (IEEE 1800-2017 annex B, the ones a property can meet).
const KEYWORDS: &[&str] = &[
    "accept_on", "alias", "always", "always_comb", "always_ff", "always_latch", "and", "assert", "assign", "assume", "automatic", "before", "begin", "bind",
    "bins", "binsof", "bit", "break", "buf", "byte", "case", "casex", "casez", "cell", "chandle", "checker", "class", "clocking", "const", "constraint",
    "context", "continue", "cover", "covergroup", "coverpoint", "cross", "deassign", "default", "defparam", "disable", "dist", "do", "edge", "else", "end",
    "endcase", "endchecker", "endclass", "endclocking", "endfunction", "endgenerate", "endgroup", "endinterface", "endmodule", "endpackage",
    "endprogram", "endproperty", "endsequence", "endtask", "enum", "event", "eventually", "expect", "export", "extends", "extern", "final", "first_match",
    "for", "force", "foreach", "forever", "fork", "function", "generate", "genvar", "global", "if", "iff", "implies", "import", "inout", "input",
    "inside", "int", "integer", "interface", "intersect", "join", "join_any", "join_none", "let", "localparam", "logic", "longint", "macromodule",
    "matches", "module", "negedge", "new", "nexttime", "not", "null", "or", "output", "package", "packed", "parameter", "posedge", "priority",
    "program", "property", "pure", "rand", "randc", "real", "reg", "reject_on", "release", "repeat", "restrict", "return", "s_always",
    "s_eventually", "s_nexttime", "s_until", "s_until_with", "sequence", "shortint", "signed", "static", "string", "strong", "struct",
    "super", "supply0", "supply1", "sync_accept_on", "sync_reject_on", "task", "this", "throughout", "time", "timeprecision", "timeunit",
    "tri", "typedef", "union", "unique", "unsigned", "until", "until_with", "untyped", "uwire", "var", "virtual", "void", "wait", "wand",
    "weak", "while", "wildcard", "wire", "with", "within", "wor", "xnor", "xor",
];

pub(crate) fn is_keyword(s: &str) -> bool {
    KEYWORDS.contains(&s)
}

/// Words that start an item: recovery after an error stops in front of them.
const SYNC: &[&str] = &[
    "property", "sequence", "assert", "assume", "cover", "restrict", "module", "macromodule", "interface", "program", "checker",
    "package", "endmodule", "endinterface", "endprogram", "endchecker", "endpackage", "endproperty", "endsequence", "bind", "localparam",
    "parameter", "typedef", "import",
];

const SCOPE_ENDS: &[&str] = &["endmodule", "endinterface", "endprogram", "endchecker", "endpackage", "endproperty", "endsequence"];

/// Openers and closers of blocks inside skipped items.
const OPENERS: &[&str] = &["begin", "fork", "case", "casex", "casez", "randcase", "function", "task", "generate", "covergroup", "class", "specify", "clocking", "primitive", "table", "config"];
const CLOSERS: &[&str] = &["end", "join", "join_any", "join_none", "endcase", "endfunction", "endtask", "endgenerate", "endgroup", "endclass", "endspecify", "endclocking", "endprimitive", "endtable", "endconfig"];

const DATA_KW: &[&str] = &["logic", "reg", "bit", "int", "integer", "shortint", "longint", "byte", "time", "string", "real", "shortreal", "realtime", "chandle", "signed", "unsigned"];
const NET_KW: &[&str] = &["wire", "tri", "wand", "wor", "uwire", "tri0", "tri1", "triand", "trior", "trireg", "supply0", "supply1", "var"];

impl<'a> Parser<'a> {
    pub fn new(src: &'a str, t: Vec<Token>, u: &'a mut UnitState, diag: Diag) -> Self {
        Parser { src, t, i: 0, u, scope: 0, diag, raw: Vec::new(), scopes_out: Vec::new(), binds: Vec::new(), seq_out: Vec::new(), prop_out: Vec::new(), nest: 0 }
    }

    // ---- token helpers

    /// The current token; past the end, the last one (end of input), so that no path can index beyond it.
    pub fn tok(&self) -> &Tok {
        &self.t[self.i.min(self.t.len() - 1)].tok
    }
    pub fn tok_at(&self, k: usize) -> &Tok {
        &self.t[(self.i + k).min(self.t.len() - 1)].tok
    }
    pub fn at(&self) -> Span {
        self.t[self.i.min(self.t.len() - 1)].at
    }
    /// The span of the last token taken.
    pub fn prev(&self) -> Span {
        self.t[self.i.saturating_sub(1).min(self.t.len() - 1)].at
    }
    /// From the token at `from` to the last token taken.
    pub fn span_from(&self, from: usize) -> Span {
        self.t[from.min(self.t.len() - 1)].at.to(self.prev())
    }
    pub fn is(&self, s: &str) -> bool {
        tok_is(self.tok(), s)
    }
    pub fn is_at(&self, k: usize, s: &str) -> bool {
        tok_is(self.tok_at(k), s)
    }
    pub fn eat(&mut self, s: &str) -> bool {
        let y = self.is(s);
        if y {
            self.i += 1;
        }
        y
    }
    pub fn expect(&mut self, s: &str) -> R<Span> {
        if self.is(s) {
            self.i += 1;
            Ok(self.prev())
        } else {
            self.expected(&format!("'{s}'"))
        }
    }
    pub fn found(&self) -> String {
        describe(self.tok())
    }
    /// `expected <what>, found <the current token>`; a token the lexer could not read gives its own message.
    pub fn expected<T>(&self, what: &str) -> R<T> {
        let t = &self.t[self.i.min(self.t.len() - 1)];
        if let Tok::Bad(m) = &t.tok {
            return Err(SvaError::new(t.at, m.clone()));
        }
        let found = self.found();
        let mut e = SvaError::new(t.at, format!("expected {what}, found {found}"));
        e.found = Some(found);
        e.expected = Some(what.to_string());
        Err(e)
    }
    pub fn error<T>(&self, at: Span, msg: impl Into<String>) -> R<T> {
        Err(SvaError::new(at, msg))
    }
    /// `n` levels deeper (a nested operand, or `n` more operators of a chain); the caller gives them back with `up`.
    pub fn deeper(&mut self, n: u32) -> R<()> {
        self.nest += n;
        if self.nest > MAX_NEST {
            return self.error(self.at(), format!("nested too deeply: more than {MAX_NEST} levels of operators and parentheses"));
        }
        Ok(())
    }
    pub fn up(&mut self, n: u32) {
        self.nest = self.nest.saturating_sub(n);
    }
    /// A name that is not a keyword.
    pub fn ident(&mut self) -> R<(String, Span)> {
        match self.tok().clone() {
            Tok::Id(s) if !is_keyword(&s) => {
                self.i += 1;
                Ok((s, self.prev()))
            }
            _ => self.expected("a name"),
        }
    }
    pub fn peek_ident(&self, k: usize) -> Option<&str> {
        match self.tok_at(k) {
            Tok::Id(s) if !is_keyword(s) => Some(s),
            _ => None,
        }
    }
    /// `a`, `a.b.c`.
    pub fn hier_name(&mut self) -> R<(String, Span)> {
        let (mut n, at) = self.ident()?;
        while self.is(".") && self.peek_ident(1).is_some() {
            self.i += 1;
            n = format!("{n}.{}", self.ident()?.0);
        }
        Ok((n, at.to(self.prev())))
    }
    /// The source text of tokens `from..to`, whitespace collapsed.
    pub fn text(&self, from: usize, to: usize) -> String {
        if from >= to {
            return String::new();
        }
        let (a, b) = (self.t[from].at.start as usize, self.t[to - 1].at.end as usize);
        if self.t[from].depth > 0 || b < a {
            // from a macro: rebuild from the tokens
            return self.t[from..to].iter().map(|t| describe(&t.tok).trim_matches('\'').to_string()).collect::<Vec<_>>().join(" ");
        }
        self.src[a..b].split_whitespace().collect::<Vec<_>>().join(" ")
    }
    fn warn(&mut self, at: Span, msg: impl Into<String>) {
        self.diag.warnings.push(SvaError::new(at, msg));
    }

    // ---- items

    pub fn file(&mut self) {
        self.items(None);
    }

    /// Items up to `end` (taken) or the end of the file.
    fn items(&mut self, end: Option<(&'static str, Span, &str)>) {
        loop {
            match self.tok().clone() {
                Tok::End => {
                    if let Some((e, at, what)) = end {
                        self.diag.errors.push(SvaError::new(at, format!("'{e}' missing: {what} is not closed")));
                    }
                    return;
                }
                Tok::Id(w) if end.is_some_and(|e| e.0 == w) => {
                    self.i += 1;
                    return;
                }
                Tok::Id(w) if SCOPE_ENDS.contains(&w.as_str()) => {
                    let e = match end {
                        Some((e, ..)) => SvaError::new(self.at(), format!("expected '{e}', found '{w}'")),
                        None => SvaError::new(self.at(), format!("'{w}' without its opening")),
                    };
                    self.diag.errors.push(e);
                    self.i += 1;
                    continue;
                }
                _ => {}
            }
            let start = self.i;
            self.nest = 0;
            if let Err(e) = self.item() {
                self.diag.errors.push(e);
                self.recover(start);
            }
        }
    }

    /// Skip after an error: to the next `;` outside brackets (taken) or in front of a word that starts an item.
    fn recover(&mut self, start: usize) {
        if self.i == start && !matches!(self.tok(), Tok::End) {
            self.i += 1;
        }
        let mut br = 0i32;
        loop {
            match self.tok() {
                Tok::End => return,
                Tok::Sym("(" | "[" | "{") => br += 1,
                Tok::Sym(")" | "]" | "}") => br = (br - 1).max(0),
                Tok::Sym(";") if br == 0 => {
                    self.i += 1;
                    return;
                }
                Tok::Id(w) if br == 0 && (SYNC.contains(&w.as_str()) || self.label_here()) => return,
                _ => {}
            }
            self.i += 1;
        }
    }

    /// `name :` in front of an assertion statement.
    fn label_here(&self) -> bool {
        self.peek_ident(0).is_some() && self.is_at(1, ":") && ["assert", "assume", "cover", "restrict"].iter().any(|k| self.is_at(2, k))
    }

    fn item(&mut self) -> R<()> {
        let w = match self.tok() {
            Tok::Id(w) => w.clone(),
            Tok::Sym(";") => {
                self.i += 1;
                return Ok(());
            }
            Tok::Bad(m) if self.scope == 0 => return self.error(self.at(), m.clone()),
            _ if self.scope == 0 => return self.expected("a declaration or an assertion"),
            _ => {
                self.skip_item();
                return Ok(());
            }
        };
        match w.as_str() {
            "property" => self.prop_decl(),
            "sequence" => self.seq_decl(),
            "module" | "macromodule" | "interface" | "program" | "checker" | "package" if !self.is_at(1, "class") => self.scope_decl(),
            "bind" => self.bind(),
            "localparam" | "parameter" => {
                self.i += 1;
                self.param_assignments(true)?;
                self.expect(";")?;
                Ok(())
            }
            "import" if !matches!(self.tok_at(1), Tok::Str(_)) => self.import(),
            "typedef" => self.typedef(),
            "default" if self.is_at(1, "clocking") => {
                self.i += 1;
                self.clocking_decl(true)
            }
            "default" if self.is_at(1, "disable") => {
                self.i += 2;
                self.expect("iff")?;
                let e = self.expr()?;
                self.expect(";")?;
                self.u.scopes[self.scope].default_disable = Some(e);
                Ok(())
            }
            "clocking" => self.clocking_decl(false),
            "assert" | "assume" | "cover" | "restrict" | "expect" => self.assertion(None),
            _ if self.label_here() => {
                let (l, at) = self.ident()?;
                self.i += 1;
                self.assertion(Some((l, at)))
            }
            _ => {
                if self.decl_item() {
                    return Ok(());
                }
                if self.scope == 0 && !is_keyword(&w) {
                    // reported here and skipped to its `;`: recovery would stop at a `property` inside it
                    let e = self.expected::<()>("a declaration or an assertion").unwrap_err();
                    self.diag.errors.push(e);
                    self.skip_until(&[";"]);
                    self.i += 1;
                    return Ok(());
                }
                self.skip_item();
                Ok(())
            }
        }
    }

    /// Skip an item this parser does not read (always blocks, assign, instances, tasks, ...). A concurrent assertion
    /// found inside is an error: it would be lost silently otherwise.
    fn skip_item(&mut self) {
        let mut depth = 0i32;
        let mut br = 0i32;
        let mut proto = matches!(self.tok(), Tok::Id(w) if w == "extern" || w == "pure" || w == "import");
        let mut reported = false;
        let first = self.i;
        loop {
            match self.tok().clone() {
                Tok::End => return,
                Tok::Sym("(" | "[" | "{" | "'{" | "'(") => br += 1,
                Tok::Sym(")" | "]" | "}") => br = (br - 1).max(0),
                Tok::Sym(";") if br == 0 && depth == 0 => {
                    self.i += 1;
                    return;
                }
                Tok::Id(w) => {
                    let after_wait = self.i > 0 && matches!(&self.t[self.i - 1].tok, Tok::Id(p) if p == "wait" || p == "disable");
                    if OPENERS.contains(&w.as_str()) && !(w == "fork" && after_wait) && !(proto && (w == "function" || w == "task")) {
                        depth += 1;
                    } else if CLOSERS.contains(&w.as_str()) {
                        depth -= 1;
                        if depth <= 0 {
                            self.i += 1;
                            if self.is(":") && self.peek_ident(1).is_some() {
                                self.i += 2;
                            }
                            return;
                        }
                    } else if ["assert", "assume", "cover"].contains(&w.as_str()) && (self.is_at(1, "property") || self.is_at(1, "sequence")) {
                        if !reported {
                            let msg = format!("{w} property inside a procedural block or generate is outside the subset: write it at module level");
                            self.diag.errors.push(SvaError::new(self.at(), msg));
                            reported = true;
                        }
                    } else if depth == 0 && br == 0 && (SYNC.contains(&w.as_str()) && w != "import") && self.i > first {
                        return;
                    }
                    if w == "import" && matches!(self.tok_at(1), Tok::Str(_)) {
                        proto = true;
                    }
                }
                _ => {}
            }
            self.i += 1;
        }
    }

    // ---- scopes

    fn scope_decl(&mut self) -> R<()> {
        let at = self.at();
        let Tok::Id(kw) = self.tok().clone() else { unreachable!() };
        self.i += 1;
        let (kind, end): (&'static str, &'static str) = match kw.as_str() {
            "interface" => ("interface", "endinterface"),
            "program" => ("program", "endprogram"),
            "checker" => ("checker", "endchecker"),
            "package" => ("package", "endpackage"),
            _ => ("module", "endmodule"),
        };
        let _ = self.eat("automatic") || self.eat("static");
        let (name, _) = self.ident()?;
        let id = self.u.scopes.len();
        self.u.scopes.push(Scope { name: name.clone(), parent: Some(self.scope), ..Default::default() });
        if kind == "package" {
            self.u.packages.insert(name.clone(), id);
        }
        let outer = self.scope;
        self.scope = id;
        let mut info = ScopeInfo { kind: kind.into(), name: name.clone(), ports: Vec::new(), params: Vec::new(), at };
        let start = self.i;
        if let Err(e) = self.scope_header(&mut info) {
            self.diag.errors.push(e);
            self.recover(start);
        }
        let what = format!("{kind} '{name}'");
        self.items(Some((end, at, &what)));
        if self.is(":") && self.peek_ident(1).is_some() {
            self.i += 2;
        }
        self.scope = outer;
        self.scopes_out.push(info);
        Ok(())
    }

    /// `import p::*;` lines, `#(parameters)`, `(ports)`, `;`.
    fn scope_header(&mut self, info: &mut ScopeInfo) -> R<()> {
        while self.is("import") {
            self.import()?;
        }
        if self.eat("#") {
            self.expect("(")?;
            if !self.eat(")") {
                loop {
                    let _ = self.eat("parameter") || self.eat("localparam");
                    info.params.extend(self.param_assignments(false)?);
                    if self.eat(",") {
                        continue;
                    }
                    self.expect(")")?;
                    break;
                }
            }
        }
        while self.is("import") {
            self.import()?;
        }
        if self.is("(") {
            info.ports = self.port_list(info.kind == "checker")?;
        }
        self.expect(";")?;
        Ok(())
    }

    /// ANSI ports `(input logic [7:0] a, b, output x)`, non-ANSI `(a, b)` (widths from the declarations inside),
    /// checker ports `(logic a, sequence s)`, interface ports `(bus_if.slave bus)`. A checker port with a constant
    /// default (`int max_wait = 4`) is also a constant of that value: it bounds ranges like a parameter.
    fn port_list(&mut self, checker: bool) -> R<Vec<Net>> {
        self.expect("(")?;
        let mut out = Vec::new();
        if self.eat(")") {
            return Ok(out);
        }
        let mut width: Option<u32> = None;
        let mut signed = false;
        loop {
            let dir = ["input", "output", "inout", "ref"].iter().any(|d| self.eat(d));
            let _ = self.eat("var");
            if ["sequence", "property", "untyped", "event"].iter().any(|d| self.eat(d)) {
                (width, signed) = (None, false);
            } else if self.peek_ident(0).is_some() && self.is_at(1, ".") && self.peek_ident(2).is_some() && self.peek_ident(3).is_some() {
                self.i += 3; // interface port with a modport
                (width, signed) = (None, false);
            } else if let Some((t, w)) = self.data_type()? {
                (width, signed) = (w, signed_type(&t));
            } else if dir {
                (width, signed) = (Some(1), false);
            }
            let (name, _) = self.ident()?;
            self.skip_dims();
            if self.eat("=") {
                let s = self.i;
                self.skip_until(&[",", ")"]);
                if checker {
                    let e = self.i;
                    self.i = s;
                    if let Ok(x) = self.expr() {
                        if self.i == e {
                            if let Ok(v) = self.u.eval(self.scope, &x) {
                                self.u.scopes[self.scope].consts.insert(name.clone(), Ok((v, width)));
                            }
                        }
                    }
                    self.i = e;
                }
            }
            self.u.scopes[self.scope].nets.insert(name.clone(), width);
            if signed {
                self.u.scopes[self.scope].signed.insert(name.clone());
            }
            out.push(Net { name, width });
            if self.eat(",") {
                continue;
            }
            self.expect(")")?;
            return Ok(out);
        }
    }

    /// Unpacked dimensions after a name: skipped.
    fn skip_dims(&mut self) {
        while self.is("[") {
            self.i += 1;
            self.skip_until(&["]"]);
            self.i += 1;
        }
    }

    /// Up to (not taking) one of `stops` outside brackets.
    fn skip_until(&mut self, stops: &[&str]) {
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
    fn packed_dims(&mut self) -> R<Option<Option<u32>>> {
        if !self.is("[") {
            return Ok(None);
        }
        let mut w = Some(1u32);
        while self.eat("[") {
            let a = self.expr()?;
            let n = if self.eat(":") {
                let b = self.expr()?;
                match (self.u.eval(self.scope, &a), self.u.eval(self.scope, &b)) {
                    (Ok(a), Ok(b)) => u32::try_from((a - b).unsigned_abs() + 1).ok(),
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
    fn param_assignments(&mut self, in_body: bool) -> R<Vec<Param>> {
        let mut out = Vec::new();
        if self.eat("type") {
            self.skip_until(&[",", ";", ")"]);
            return Ok(out);
        }
        let ty = self.data_type()?;
        let width = ty.and_then(|t| t.1);
        loop {
            let (name, at) = self.ident()?;
            self.skip_dims();
            let val: ConstVal = if self.eat("=") {
                let e = self.expr()?;
                self.u.eval(self.scope, &e).map(|v| (truncate(v, width), width))
            } else {
                Err(format!("parameter '{name}' has no value"))
            };
            let _ = at;
            out.push(Param { name: name.clone(), value: val.as_ref().ok().map(|v| v.0) });
            self.u.scopes[self.scope].consts.insert(name, val);
            if in_body && self.eat(",") {
                continue;
            }
            return Ok(out);
        }
    }

    fn import(&mut self) -> R<()> {
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
    fn packed_struct(&mut self) -> R<(String, Option<u32>)> {
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

    fn typedef(&mut self) -> R<()> {
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
                let _ = at;
                self.u.scopes[self.scope].consts.insert(n, Ok((truncate(v, width), width)));
                next = v + 1;
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
    fn clocking_decl(&mut self, default: bool) -> R<()> {
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
        if self.is(":") && self.peek_ident(1).is_some() {
            self.i += 2;
        }
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
        let (signal, at) = match self.hier_name() {
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
        let _ = at;
        if edge.is_none() {
            if let Some(c) = self.u.find(self.scope, |s| s.clockings.get(&signal).cloned()) {
                return Ok(c);
            }
        }
        Ok(Clock { edge: edge.unwrap_or_else(|| "edge".into()), signal })
    }

    fn bind(&mut self) -> R<()> {
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
    fn decl_item(&mut self) -> bool {
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

    // ---- declarations

    /// Local variables (`int x;` after the header) are outside the subset.
    fn no_local_vars(&self) -> R<()> {
        if matches!(self.tok(), Tok::Id(w) if DATA_KW.contains(&w.as_str()) && self.peek_ident(1).is_some()) {
            return self.error(self.at(), "local variables in sequences and properties are outside the subset");
        }
        Ok(())
    }

    fn prop_decl(&mut self) -> R<()> {
        let at = self.at();
        self.expect("property")?;
        let (name, _) = self.ident()?;
        let r = self.ports_and_body(true);
        match r {
            Ok((ports, clock, disable, body)) => {
                let k = self.u.props.len();
                let scope = self.u.scope_name(self.scope);
                self.u.props.push(PropDecl { name: name.clone(), scope, ports, clock, disable, body, at, scope_id: self.scope });
                self.u.scopes[self.scope].props.insert(name, k);
                self.prop_out.push(k);
            }
            Err(e) => {
                self.diag.errors.push(e);
                self.u.scopes[self.scope].broken.insert(name, at);
                self.skip_to_end("endproperty");
            }
        }
        if self.is(":") && self.peek_ident(1).is_some() {
            self.i += 2;
        }
        Ok(())
    }

    fn seq_decl(&mut self) -> R<()> {
        let at = self.at();
        self.expect("sequence")?;
        let (name, _) = self.ident()?;
        match self.ports_and_body(false) {
            Ok((ports, clock, _, body)) => {
                let Prop::Seq { seq } = body else { unreachable!() };
                let k = self.u.seqs.len();
                let scope = self.u.scope_name(self.scope);
                self.u.seqs.push(SeqDecl { name: name.clone(), scope, ports, clock, body: seq, at, scope_id: self.scope });
                self.u.scopes[self.scope].seqs.insert(name, k);
                self.seq_out.push(k);
            }
            Err(e) => {
                self.diag.errors.push(e);
                self.u.scopes[self.scope].broken.insert(name, at);
                self.skip_to_end("endsequence");
            }
        }
        if self.is(":") && self.peek_ident(1).is_some() {
            self.i += 2;
        }
        Ok(())
    }

    #[allow(clippy::type_complexity)]
    fn ports_and_body(&mut self, property: bool) -> R<(Vec<Port>, Option<Clock>, Option<Expr>, Prop)> {
        let ports = if self.is("(") { self.formal_ports()? } else { Vec::new() };
        self.expect(";")?;
        self.no_local_vars()?;
        let (clock, disable, body) = self.prop_spec()?;
        if !property {
            if let Some(d) = &disable {
                return self.error(d.at(), "disable iff belongs to a property, not to a sequence");
            }
            if body.as_seq().is_none() {
                return self.error(body.at(), "a sequence declaration needs a sequence, found a property");
            }
        }
        let _ = self.eat(";");
        self.expect(if property { "endproperty" } else { "endsequence" })?;
        Ok((ports, clock, disable, body))
    }

    /// After an error in a declaration: past its end word (or in front of the next item if it is missing).
    fn skip_to_end(&mut self, end: &str) {
        loop {
            match self.tok() {
                Tok::End => return,
                Tok::Id(w) if w == end => {
                    self.i += 1;
                    return;
                }
                Tok::Id(w) if SYNC.contains(&w.as_str()) && !["assert", "assume", "cover"].contains(&w.as_str()) => return,
                _ => self.i += 1,
            }
        }
    }

    /// `(a, b = 1, sequence s, logic [7:0] d, int n)`; a formal without a type takes the type of the one before it.
    fn formal_ports(&mut self) -> R<Vec<Port>> {
        self.expect("(")?;
        let mut out = Vec::new();
        if self.eat(")") {
            return Ok(out);
        }
        let mut ty = "untyped".to_string();
        loop {
            let at = self.at();
            if self.is("local") || self.is("input") || self.is("output") || self.is("inout") {
                return self.error(at, "local and directional formal arguments are outside the subset");
            }
            if self.is("event") {
                return self.error(at, "event formal arguments are outside the subset");
            }
            if let Some(t) = ["untyped", "sequence", "property"].iter().find(|t| self.is(t)) {
                ty = t.to_string();
                self.i += 1;
            } else if let Some((t, _)) = self.data_type()? {
                ty = t;
            }
            let (name, nat) = self.ident()?;
            if self.is("[") {
                return self.error(self.at(), "unpacked dimensions of formal arguments are outside the subset");
            }
            let default = if self.eat("=") { Some(self.prop()?) } else { None };
            out.push(Port { name, ty: ty.clone(), default, at: nat });
            if self.eat(",") {
                continue;
            }
            self.expect(")")?;
            return Ok(out);
        }
    }

    // ---- assertions

    fn assertion(&mut self, label: Option<(String, Span)>) -> R<()> {
        let at = label.as_ref().map_or(self.at(), |l| l.1);
        let label = label.map(|l| l.0);
        let kw_at = self.at();
        let Tok::Id(kw) = self.tok().clone() else { unreachable!() };
        self.i += 1;
        let kind = match kw.as_str() {
            "assert" => Kind::Assert,
            "assume" => Kind::Assume,
            "cover" => Kind::Cover,
            "restrict" => {
                self.skip_item();
                self.warn(at, "restrict property is skipped: it only constrains formal tools");
                return Ok(());
            }
            _ => return self.error(kw_at, "expect statements are outside the subset"),
        };
        let mut cover_seq = false;
        if self.eat("property") {
        } else if kind == Kind::Cover && self.eat("sequence") {
            cover_seq = true;
        } else if self.is("(") || self.is("#") || self.is("final") {
            return self.error(kw_at, format!("immediate assertions ({kw} (expr)) are outside the subset: use {kw} property (...)"));
        } else {
            return self.expected("'property'");
        }
        self.expect("(")?;
        let (clock, disable, prop) = self.prop_spec()?;
        self.expect(")")?;
        if cover_seq && prop.as_seq().is_none() {
            return self.error(prop.at(), "cover sequence needs a sequence, found a property");
        }
        let at = at.to(self.prev());
        let (severity, message) = self.action_block(kind == Kind::Cover)?;
        self.raw.push(RawAssertion { label, kind, cover_seq, clock, disable, prop, message, severity, scope: self.scope, at });
        Ok(())
    }

    /// `;` | statement | `[statement] else statement`: the severity and text of the first message task (of the fail
    /// branch; of the pass branch for cover).
    fn action_block(&mut self, cover: bool) -> R<(Option<String>, Option<String>)> {
        if self.eat(";") {
            return Ok((None, None));
        }
        // a missing `;` must not swallow the next item into an action block
        if self.label_here() || matches!(self.tok(), Tok::Id(w) if SYNC.contains(&w.as_str()) || SCOPE_ENDS.contains(&w.as_str())) || matches!(self.tok(), Tok::End) {
            return self.expected("';' or an action block");
        }
        let mut msg = (None, None);
        if !self.is("else") {
            let m = self.statement()?;
            if cover {
                msg = m;
            }
        }
        if self.eat("else") {
            let m = self.statement()?;
            if !cover {
                msg = m;
            }
        }
        Ok(msg)
    }

    fn statement(&mut self) -> R<(Option<String>, Option<String>)> {
        let start = self.i;
        if self.eat(";") {
            return Ok((None, None));
        }
        if self.is("begin") {
            let mut depth = 0;
            loop {
                match self.tok() {
                    Tok::End => return self.expected("'end'"),
                    Tok::Id(w) if w == "begin" || w == "fork" => depth += 1,
                    Tok::Id(w) if w == "end" || w.starts_with("join") => {
                        depth -= 1;
                        if depth == 0 {
                            self.i += 1;
                            break;
                        }
                    }
                    _ => {}
                }
                self.i += 1;
            }
            if self.is(":") && self.peek_ident(1).is_some() {
                self.i += 2;
            }
        } else {
            self.skip_until(&[";"]);
            self.expect(";")?;
        }
        let mut k = start;
        while k < self.i {
            if let Tok::Sys(s) = &self.t[k].tok {
                let sev = match s.as_str() {
                    "$error" => "error",
                    "$fatal" => "fatal",
                    "$warning" => "warning",
                    "$info" | "$display" | "$write" => "info",
                    _ => {
                        k += 1;
                        continue;
                    }
                };
                let mut msg = None;
                if matches!(self.t[k + 1].tok, Tok::Sym("(")) {
                    let mut j = k + 2;
                    while j < self.i && !matches!(self.t[j].tok, Tok::Sym(")")) {
                        if let Tok::Str(s) = &self.t[j].tok {
                            msg = Some(s.clone());
                            break;
                        }
                        j += 1;
                    }
                }
                return Ok((Some(sev.into()), msg));
            }
            k += 1;
        }
        Ok((None, None))
    }

    /// `[@(clock)] [disable iff (expr)] property_expr`.
    pub fn prop_spec(&mut self) -> R<(Option<Clock>, Option<Expr>, Prop)> {
        let clock = if self.is("@") { Some(self.clock_event()?) } else { None };
        let mut disable = None;
        if self.eat("disable") {
            self.expect("iff")?;
            self.expect("(")?;
            disable = Some(self.expr()?);
            self.expect(")")?;
            if self.is("@") {
                return self.error(self.at(), "the clock goes before disable iff: @(posedge clk) disable iff (...) ...");
            }
        }
        let p = self.prop()?;
        Ok((clock, disable, p))
    }
}

fn tok_is(t: &Tok, s: &str) -> bool {
    match t {
        Tok::Sym(x) => *x == s,
        Tok::Id(x) => x == s,
        _ => false,
    }
}

/// A token for messages: `'name'`, `'8'hFF'`, `the end of the file`.
pub(crate) fn describe(t: &Tok) -> String {
    match t {
        Tok::Id(s) | Tok::Sys(s) => format!("'{s}'"),
        Tok::Num(n) => format!("'{}'", n.text),
        Tok::Fill(c) => format!("''{c}'"),
        Tok::Str(_) => "a string".into(),
        Tok::Sym(s) => format!("'{s}'"),
        Tok::Directive(d) => format!("'`{d}'"),
        Tok::Define(_) => "'`define'".into(),
        Tok::Bad(m) => m.clone(),
        Tok::End => "the end of the file".into(),
    }
}

/// A value that does not fit its declared width keeps its low bits (`logic [1:0] X = 5` is 1); negative values of
/// signed types stay as they are.
fn truncate(v: i64, width: Option<u32>) -> i64 {
    match width {
        Some(w) if w < 63 && v > 0 && v >> w != 0 => v & ((1i64 << w) - 1),
        _ => v,
    }
}

/// A data type written as `int`, `byte`, `logic signed [7:0]`, ...: signed unless it says `unsigned`.
fn signed_type(t: &str) -> bool {
    let w: Vec<&str> = t.split(|c: char| !c.is_ascii_alphanumeric() && c != '_').filter(|x| !x.is_empty()).collect();
    !w.contains(&"unsigned") && (w.contains(&"signed") || w.first().is_some_and(|f| ["int", "integer", "shortint", "byte", "longint"].contains(f)))
}
