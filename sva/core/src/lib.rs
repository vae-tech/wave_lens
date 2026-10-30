//! sva-core — the SystemVerilog Assertion engine of wavelens, without I/O.
//!
//! Front end (stage 4, docs/sva/LANGUAGE.md): [`lex`](crate::lex) -> preprocessor (`` `define ``, `` `ifdef ``) ->
//! parser (items, expressions, sequences, properties) -> expansion of every assertion (instances, constants, clock,
//! element ids, signals). [`parse`] reads one file; a [`Unit`] reads several as one compilation unit (macros, packages
//! and declarations of earlier files are seen by later ones). Errors carry line:column and do not stop the file.
//!
//! Evaluator (stage 5, docs/sva/ENGINE.md): a [`Trace`] (4-state signal values at each sampling point of the clock)
//! -> one [`Outcome`] per assertion: counts, every non-vacuous attempt with its result and step trace, a per-cycle
//! lane. Everything is JSON (serde) so the CLI and the WebAssembly build share it.

mod ast;
mod consts;
mod decl;
mod engine;
mod expand;
mod explain;
mod expr;
mod lex;
mod parse;
mod pre;
mod print;
mod prop;
mod report;
mod summary;
mod value;

// the API (docs/sva/ENGINE.md *Entry points*): what the CLI, the WebAssembly module and the integration tests use; the
// rest of the tree is reachable through these types' fields
use ast::*;
pub use ast::{Assertion, Kind, Prop};
pub use explain::{explain, expressions};
pub use engine::{evaluate, evaluate_all, Attempt, Column, Options, Outcome, Results, StepInfo, Stats, Status, Trace, TraceStep, XMode};
pub use value::V;
pub use lex::Span;
pub use print::Printer;
pub use report::{describe, diagnostic};
pub use summary::{check_input as check_report_input, html as report_html, junit as report_junit, markdown as report_markdown, summarize, time_text, xml as xml_text};

use serde::{Deserialize, Serialize};
use std::fmt;

/// An error or a warning: where (1-based line and column, byte offsets `start..end` of the offending text), what.
/// Parser errors also say what was `found` and what was `expected`.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SvaError {
    pub line: usize,
    pub col: usize,
    pub start: usize,
    pub end: usize,
    pub msg: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub found: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected: Option<String>,
}

/// The file that lists the subset, named by every error of a construct outside it.
pub const LANGUAGE_MD: &str = "docs/sva/LANGUAGE.md";

impl SvaError {
    /// A construct outside the subset says where the subset is written down (one rule for every such error).
    pub fn new(at: Span, msg: impl Into<String>) -> Self {
        let mut msg = msg.into();
        if msg.contains("outside the subset") && !msg.contains(LANGUAGE_MD) {
            msg = format!("{msg} ({LANGUAGE_MD})");
        }
        SvaError { line: at.line as usize, col: at.col as usize, start: at.start as usize, end: at.end as usize, msg, found: None, expected: None }
    }
}

impl fmt::Display for SvaError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{}:{}: {}", self.line, self.col, self.msg)
    }
}

/// What a file holds: the expanded assertions, the declarations as written, the scopes, the bind statements, and the
/// errors (each ends only the item it is in) and warnings, in source order.
#[derive(Clone, Debug, Default, Serialize)]
pub struct Parsed {
    pub assertions: Vec<Assertion>,
    pub sequences: Vec<SeqDecl>,
    pub properties: Vec<PropDecl>,
    pub scopes: Vec<ScopeInfo>,
    pub binds: Vec<Bind>,
    pub errors: Vec<SvaError>,
    pub warnings: Vec<SvaError>,
}

impl Parsed {
    /// The assertions, or the errors if there are any.
    pub fn into_result(self) -> Result<Vec<Assertion>, Vec<SvaError>> {
        if self.errors.is_empty() {
            Ok(self.assertions)
        } else {
            Err(self.errors)
        }
    }
    pub fn assertion(&self, label: &str) -> Option<&Assertion> {
        self.assertions.iter().find(|a| a.label == label)
    }
}

/// Several files as one compilation unit (like `vlog a.sv b.sv`): macros, packages and declarations carry over.
#[derive(Default)]
pub struct Unit {
    st: parse::UnitState,
}

impl Unit {
    pub fn new() -> Self {
        Self::default()
    }

    /// A macro defined before the first file (`sva parse -D NAME=VALUE`).
    pub fn define(&mut self, name: &str, value: &str) {
        let mut body = lex::lex(value);
        body.pop();
        self.st.macros.insert(name.to_string(), pre::Macro { params: None, body });
    }

    /// One expression in this unit (after its files): macros applied, constants resolved, its signals
    /// (`expand::expression`).
    pub fn expression(&mut self, src: &str) -> Result<(Expr, Vec<SignalRef>), SvaError> {
        let e = parse_in(&mut self.st, src, |p| p.expr())?;
        expand::expression(&self.st, &e)
    }

    pub fn parse(&mut self, src: &str) -> Parsed {
        let mut diag = pre::Diag::default();
        let toks = pre::preprocess(lex::lex(src), &mut self.st.macros, &mut diag);
        let mut p = parse::Parser::new(src, toks, &mut self.st, diag);
        p.file();
        let parse::Parser { raw, mut diag, scopes_out, binds, seq_out, prop_out, .. } = p;
        let mut out = Parsed { scopes: scopes_out, binds, ..Default::default() };
        for r in &raw {
            match expand::assertion(&self.st, r) {
                Ok(mut a) => {
                    // a label is unique in its module: the same label in another module of the unit (`a_hold` in two
                    // checkers) is `module.label`; the first one keeps the plain label
                    match self.st.labels.get(&a.label) {
                        Some(m) if *m != a.scope => {
                            if let Some(m) = &a.scope {
                                a.label = format!("{m}.{}", a.label);
                            }
                        }
                        Some(_) => {}
                        None => {
                            self.st.labels.insert(a.label.clone(), a.scope.clone());
                        }
                    }
                    if let Some(f) = a.flags.iter().find(|f| f.starts_with("compared as unsigned")) {
                        diag.warnings.push(SvaError::new(r.at, format!("{}: {f}", a.label)));
                    }
                    out.assertions.push(a)
                }
                Err(mut e) => {
                    // an error inside a declaration: say which assertion led there
                    if e.start < r.at.start as usize || e.end > r.at.end as usize {
                        let label = r.label.clone().unwrap_or_else(|| format!("{}_{}", r.kind.word(), r.at.line));
                        e.msg += &format!(" (in assertion '{label}', line {})", r.at.line);
                    }
                    diag.errors.push(e);
                }
            }
        }
        out.sequences = seq_out.iter().map(|&k| self.st.seqs[k].clone()).collect();
        out.properties = prop_out.iter().map(|&k| self.st.props[k].clone()).collect();
        diag.errors.sort_by_key(|e| (e.line, e.col));
        diag.warnings.sort_by_key(|e| (e.line, e.col));
        out.errors = diag.errors;
        out.warnings = diag.warnings;
        out
    }
}

/// Parse one file.
pub fn parse(src: &str) -> Parsed {
    Unit::new().parse(src)
}

fn parse_one<T>(src: &str, f: impl FnOnce(&mut parse::Parser) -> Result<T, SvaError>) -> Result<T, SvaError> {
    parse_in(&mut parse::UnitState::default(), src, f)
}

fn parse_in<T>(st: &mut parse::UnitState, src: &str, f: impl FnOnce(&mut parse::Parser) -> Result<T, SvaError>) -> Result<T, SvaError> {
    let mut diag = pre::Diag::default();
    let toks = pre::preprocess(lex::lex(src), &mut st.macros, &mut diag);
    if let Some(e) = diag.errors.into_iter().next() {
        return Err(e);
    }
    let mut p = parse::Parser::new(src, toks, st, pre::Diag::default());
    let x = f(&mut p)?;
    if !matches!(p.tok(), lex::Tok::End) {
        return p.expected("the end of the text");
    }
    Ok(x)
}

/// One expression as written (no expansion): for tests and for the page's input fields.
pub fn parse_expr(src: &str) -> Result<Expr, SvaError> {
    parse_one(src, |p| p.expr())
}

/// One property expression as written (no expansion, no clock).
pub fn parse_prop(src: &str) -> Result<Prop, SvaError> {
    parse_one(src, |p| p.prop())
}

/// Parse `source` and evaluate its assertions (all, or the ones named in `only`) over `trace`.
pub fn run(source: &str, trace: &Trace, opt: &Options, only: &[String]) -> Result<Results, Vec<SvaError>> {
    run_unit(&[source.to_string()], trace, opt, only)
}

/// The same for several files read as one compilation unit (a package in the first, the checks in the next). The
/// assertions of the last unit are kept, so evaluating it again (the page: one request per binding or clock) does not
/// parse it again.
pub fn run_unit(sources: &[String], trace: &Trace, opt: &Options, only: &[String]) -> Result<Results, Vec<SvaError>> {
    evaluate_all(&unit_assertions(sources)?, trace, opt, only)
}

/// The assertions of the files read as one unit, from the cache when the files are the last ones read (compared whole:
/// a hash alone could give the assertions of other files on a collision).
fn unit_assertions(sources: &[String]) -> Result<std::rc::Rc<Vec<Assertion>>, Vec<SvaError>> {
    let cached = LAST_UNIT.with(|c| c.borrow().as_ref().filter(|(k, _)| k.as_slice() == sources).map(|(_, a)| a.clone()));
    let asserts = match cached {
        Some(a) => a,
        None => {
            let mut unit = Unit::new();
            let mut asserts = Vec::new();
            for s in sources {
                asserts.extend(unit.parse(s).into_result()?);
            }
            let a = std::rc::Rc::new(asserts);
            LAST_UNIT.with(|c| *c.borrow_mut() = Some((sources.to_vec(), a.clone())));
            a
        }
    };
    Ok(asserts)
}

/// The sources of the last unit read and its assertions.
type UnitCache = Option<(Vec<String>, std::rc::Rc<Vec<Assertion>>)>;

thread_local! {
    static LAST_UNIT: std::cell::RefCell<UnitCache> = const { std::cell::RefCell::new(None) };
}

/// A key that is there (null too) is `Some`: `{"report": null}` is a report request with a bad input, not a parse.
fn present<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<serde_json::Value>, D::Error> {
    serde_json::Value::deserialize(d).map(Some)
}

/// A key the engine does not know (a typo of the page or of a script) is an error, not a request run with defaults.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    files: Vec<String>,
    #[serde(default)]
    trace: Option<Trace>,
    #[serde(default)]
    options: Options,
    #[serde(default)]
    assert: Vec<String>,
    /// `{"meta", "results": [...]}`: the report of results documents (summary.rs); present even when null
    #[serde(default, deserialize_with = "present")]
    report: Option<serde_json::Value>,
    /// with `report`: `"md"`, `"junit"` or `"html"` adds that text
    #[serde(default)]
    format: Option<String>,
    /// expressions of the page (virtual signals, searches) in the unit of `files`; with `trace` their values too
    #[serde(default)]
    exprs: Vec<String>,
    /// with `files` and `trace`: the booleans of one assertion and their parts, valued over cycles `from..=to`
    #[serde(default)]
    explain: Option<ExplainReq>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ExplainReq {
    assert: String,
    from: usize,
    to: usize,
}

/// JSON in, JSON out (the WebAssembly entry point). `{"source": "..."}` -> the [`Parsed`] file; `{"files": ["...",
/// ...]}` (the texts of several files, one compilation unit) -> `{"files": [Parsed, ...]}`; with `"trace": {...}`,
/// `"options"?: {...}` and `"assert"?: ["name", ...]` either gives the [`Results`] of its assertions or
/// `{"errors": [{"line", "col", "msg", ...}]}`. `{"report": {"meta", "results": [...]}, "format"?: "md" | "junit" |
/// "html"}` -> `{"summary": {...}, "text"?: "..."}` (the report of stage 8). `{"files"?, "exprs": ["a && b", ...],
/// "trace"?}` -> `{"exprs": [{"text", "signals": [...], "width"?, "values"?: [...] } | {"text", "errors"}]}` (the page's
/// virtual signals and searches, [`expressions`]); `{"files", "trace", "explain": {"assert", "from", "to"}}` -> `{"explain":
/// [...]}` ([`explain`]).
pub fn run_json(request: &str) -> String {
    let out = match serde_json::from_str::<Request>(request) {
        Err(e) => serde_json::json!({ "errors": [{ "line": e.line(), "col": e.column(), "msg": format!("request: {e}") }] }),
        Ok(Request { report: Some(r), format, .. }) => match check_report_input(&r) {
            Err(e) => serde_json::json!({ "errors": [{ "line": 0, "col": 0, "msg": format!("report: {e}") }] }),
            Ok(()) => {
                let sum = summarize(&r);
                let text = match format.as_deref() {
                    Some("md") => Ok(Some(report_markdown(&sum))),
                    Some("junit") => Ok(Some(report_junit(&sum))),
                    Some("html") => Ok(Some(report_html(&sum))),
                    None => Ok(None),
                    Some(f) => Err(f),
                };
                match text {
                    Ok(text) => serde_json::json!({ "summary": sum, "text": text }),
                    Err(f) => serde_json::json!({ "errors": [{ "line": 0, "col": 0, "msg": format!("report: no format '{f}' (md, junit, html)") }] }),
                }
            }
        },
        Ok(Request { files, exprs, trace, .. }) if !exprs.is_empty() => serde_json::json!({ "exprs": expressions(&files, &exprs, trace.as_ref()) }),
        Ok(Request { files, trace: Some(t), explain: Some(x), .. }) => match unit_assertions(&files) {
            Err(errors) => serde_json::json!({ "errors": errors }),
            Ok(asserts) => match asserts.iter().find(|a| a.label == x.assert) {
                None => serde_json::json!({ "errors": [{ "line": 0, "col": 0, "msg": format!("explain: no assertion '{}'", x.assert) }] }),
                Some(a) => match explain(a, &t, x.from, x.to) {
                    Ok(v) => serde_json::json!({ "explain": v }),
                    Err(m) => serde_json::json!({ "errors": [{ "line": 0, "col": 0, "msg": format!("explain: {m}") }] }),
                },
            },
        },
        Ok(Request { source, files, trace, options, assert, .. }) => {
            let one = files.is_empty();
            let sources = if one { vec![source.unwrap_or_default()] } else { files };
            match trace {
                None if one => serde_json::to_value(parse(&sources[0])).unwrap(),
                None => {
                    let mut unit = Unit::new();
                    let parsed: Vec<Parsed> = sources.iter().map(|s| unit.parse(s)).collect();
                    serde_json::json!({ "files": parsed })
                }
                Some(t) => match run_unit(&sources, &t, &options, &assert) {
                    Ok(res) => serde_json::to_value(res).unwrap(),
                    Err(errors) => serde_json::json!({ "errors": errors }),
                },
            }
        }
    };
    out.to_string()
}

#[cfg(test)]
mod tests;
