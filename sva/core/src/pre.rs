//! Preprocessor over tokens: `` `ifdef `` / `` `ifndef `` / `` `elsif `` / `` `else `` / `` `endif ``, `` `define `` /
//! `` `undef ``, macro uses (object-like and with arguments). Expanded tokens take the position of the macro use, so an
//! error inside an expansion points at the place the user wrote. `` `include `` is not followed (a warning).

use crate::lex::{Span, Tok, Token};
use crate::SvaError;
use std::collections::{HashMap, VecDeque};

#[derive(Clone, Debug, PartialEq)]
pub struct Macro {
    pub params: Option<Vec<(String, Option<Vec<Token>>)>>,
    pub body: Vec<Token>,
}

/// Errors and warnings of one file.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Diag {
    pub errors: Vec<SvaError>,
    pub warnings: Vec<SvaError>,
}

const MAX_DEPTH: u16 = 32;
/// Tokens all the macro uses of a file may expand to: a macro that doubles itself 24 times would make 16 M tokens and
/// gigabytes before MAX_DEPTH stops it (a page would hang); a real file stays far below.
const MAX_EXPANDED: usize = 1_000_000;

struct Cond {
    active: bool,
    taken: bool,
    seen_else: bool,
    at: Span,
}

/// The tokens after preprocessing (ending with [`Tok::End`]). `macros` carries over between the files of a unit.
pub fn preprocess(toks: Vec<Token>, macros: &mut HashMap<String, Macro>, diag: &mut Diag) -> Vec<Token> {
    let mut input: VecDeque<Token> = toks.into();
    let mut out = Vec::new();
    let mut conds: Vec<Cond> = Vec::new();
    let mut end = None;
    let mut expanded = 0usize;
    while let Some(t) = input.pop_front() {
        let active = conds.last().is_none_or(|c| c.active);
        let name = |input: &mut VecDeque<Token>, d: &str, diag: &mut Diag| -> Option<String> {
            match input.front().map(|t| &t.tok) {
                Some(Tok::Id(n)) => {
                    let n = n.clone();
                    input.pop_front();
                    Some(n)
                }
                _ => {
                    diag.errors.push(SvaError::new(t.at, format!("`{d} needs a macro name")));
                    None
                }
            }
        };
        match &t.tok {
            Tok::End => {
                end = Some(t);
                break;
            }
            Tok::Directive(d) if d == "ifdef" || d == "ifndef" => {
                let Some(n) = name(&mut input, d, diag) else { continue };
                let cond = macros.contains_key(&n) == (d == "ifdef");
                conds.push(Cond { active: active && cond, taken: cond, seen_else: false, at: t.at });
            }
            Tok::Directive(d) if d == "elsif" || d == "else" || d == "endif" => {
                let parent = conds.len() < 2 || conds[conds.len() - 2].active;
                let n = if d == "elsif" { name(&mut input, d, diag) } else { None };
                let Some(c) = conds.last_mut() else {
                    diag.errors.push(SvaError::new(t.at, format!("`{d} without `ifdef")));
                    continue;
                };
                match d.as_str() {
                    "endif" => {
                        conds.pop();
                    }
                    _ if c.seen_else => diag.errors.push(SvaError::new(t.at, format!("`{d} after `else"))),
                    "else" => {
                        c.active = parent && !c.taken;
                        c.taken = true;
                        c.seen_else = true;
                    }
                    _ => {
                        let cond = n.is_some_and(|n| macros.contains_key(&n));
                        c.active = parent && !c.taken && cond;
                        c.taken |= cond;
                    }
                }
            }
            _ if !active => {}
            Tok::Sym("``" | "`\"") => diag.errors.push(SvaError::new(t.at, "`` and `\" work only inside a macro body")),
            Tok::Define(def) => {
                macros.insert(def.name.clone(), Macro { params: def.params.clone(), body: def.body.clone() });
            }
            Tok::Directive(d) => match d.as_str() {
                "undef" => {
                    if let Some(n) = name(&mut input, d, diag) {
                        macros.remove(&n);
                    }
                }
                "undefineall" => macros.clear(),
                "include" => {
                    if matches!(input.front().map(|t| &t.tok), Some(Tok::Str(_))) {
                        input.pop_front();
                    }
                    diag.warnings.push(SvaError::new(t.at, "`include is not followed: give the included file to sva parse as well"));
                }
                "resetall" | "celldefine" | "endcelldefine" | "nounconnected_drive" | "end_keywords" => {}
                "begin_keywords" | "unconnected_drive" => {
                    input.pop_front();
                }
                _ => expand(&t, d, &mut input, macros, diag, &mut expanded),
            },
            _ => out.push(t),
        }
    }
    for c in conds {
        diag.errors.push(SvaError::new(c.at, "`ifdef without `endif"));
    }
    out.push(end.unwrap_or(Token { tok: Tok::End, at: Span::default(), depth: 0 }));
    out
}

/// A macro use `t` (`` `name `` or `` `name(args) ``): its expansion goes to the front of `input`, to be scanned again.
fn expand(t: &Token, name: &str, input: &mut VecDeque<Token>, macros: &HashMap<String, Macro>, diag: &mut Diag, expanded: &mut usize) {
    // the predefined `__FILE__ (the core does not know file names: "") and `__LINE__ (the line of the use)
    let builtin = match name {
        "__FILE__" if !macros.contains_key(name) => Some(Tok::Str(String::new())),
        "__LINE__" if !macros.contains_key(name) => {
            let l = t.at.line as u64;
            Some(Tok::Num(crate::lex::Num { value: l, unknown: 0, width: None, signed: true, base: 10, text: l.to_string() }))
        }
        _ => None,
    };
    if let Some(tok) = builtin {
        input.push_front(Token { tok, at: t.at, depth: t.depth + 1 });
        return;
    }
    let Some(m) = macros.get(name) else {
        diag.errors.push(SvaError::new(t.at, format!("undefined macro `{name}")));
        return;
    };
    if t.depth >= MAX_DEPTH {
        diag.errors.push(SvaError::new(t.at, format!("macro `{name} expands into itself")));
        return;
    }
    let mut at = t.at;
    let mut args: Vec<Vec<Token>> = Vec::new();
    if let Some(params) = &m.params {
        if !matches!(input.front().map(|t| &t.tok), Some(Tok::Sym("("))) {
            diag.errors.push(SvaError::new(t.at, format!("macro `{name} needs arguments: `{name}({})", names(params))));
            return;
        }
        input.pop_front();
        let mut cur = Vec::new();
        let mut depth = 0;
        while let Some(a) = input.pop_front() {
            match a.tok {
                Tok::End => {
                    diag.errors.push(SvaError::new(t.at, format!("the arguments of `{name} are not closed")));
                    input.push_front(a);
                    return;
                }
                Tok::Sym("(" | "[" | "{") => depth += 1,
                Tok::Sym(")") if depth == 0 => {
                    at = t.at.to(a.at);
                    args.push(std::mem::take(&mut cur));
                    break;
                }
                Tok::Sym(")" | "]" | "}") => depth -= 1,
                Tok::Sym(",") if depth == 0 => {
                    args.push(std::mem::take(&mut cur));
                    continue;
                }
                _ => {}
            }
            cur.push(a);
        }
        if args.len() == 1 && args[0].is_empty() && params.is_empty() {
            args.clear();
        }
        if args.len() > params.len() {
            diag.errors.push(SvaError::new(at, format!("macro `{name} takes {} argument(s), got {}", params.len(), args.len())));
            return;
        }
        for (k, (p, default)) in params.iter().enumerate() {
            if k >= args.len() || args[k].is_empty() {
                match default {
                    Some(d) => {
                        if k >= args.len() {
                            args.push(d.clone());
                        } else {
                            args[k] = d.clone();
                        }
                    }
                    None if k < args.len() => {} // an empty argument is allowed: it expands to nothing
                    None => {
                        diag.errors.push(SvaError::new(at, format!("macro `{name}: missing argument '{p}'")));
                        return;
                    }
                }
            }
        }
    }
    let mut body = Vec::new();
    for b in &m.body {
        let arg = match (&b.tok, &m.params) {
            (Tok::Id(id), Some(ps)) => ps.iter().position(|p| &p.0 == id),
            _ => None,
        };
        match arg {
            Some(k) => body.extend(args[k].iter().cloned()),
            None => body.push(b.clone()),
        }
    }
    let body = paste(body, t.at, diag);
    *expanded = expanded.saturating_add(body.len());
    if *expanded > MAX_EXPANDED {
        if *expanded - body.len() <= MAX_EXPANDED {   // the first use over the budget: one error, the pending expansions dropped
            diag.errors.push(SvaError::new(t.at, format!("macro expansion too large: more than {MAX_EXPANDED} tokens (`{name})")));
        }
        while input.front().is_some_and(|x| x.depth > 0) {
            input.pop_front();
        }
        return;
    }
    for b in body.into_iter().rev() {
        input.push_front(Token { tok: b.tok, at, depth: t.depth + 1 });
    }
}

/// `` a``b `` -> one token `ab` (the text of both, lexed again); `` `"a && b`" `` -> the string "a && b" (the text
/// between the quotes, a space where the source had one).
fn paste(body: Vec<Token>, at: Span, diag: &mut Diag) -> Vec<Token> {
    if !body.iter().any(|b| matches!(b.tok, Tok::Sym("``" | "`\""))) {
        return body;
    }
    let mut out: Vec<Token> = Vec::new();
    let mut it = body.into_iter().peekable();
    while let Some(b) = it.next() {
        match b.tok {
            Tok::Sym("``") => {
                let (Some(l), Some(r)) = (out.pop(), it.next()) else { continue };
                let text = tok_text(&l.tok) + &tok_text(&r.tok);
                let mut toks = crate::lex::lex(&text);
                toks.pop();
                if toks.len() != 1 {
                    diag.errors.push(SvaError::new(at, format!("pasting `{text}` does not give one token")));
                }
                out.extend(toks.into_iter().map(|x| Token { tok: x.tok, at: l.at, depth: l.depth }));
            }
            Tok::Sym("`\"") => {
                let mut text = String::new();
                let mut prev: Option<Span> = None;
                for x in it.by_ref() {
                    if x.tok == Tok::Sym("`\"") {
                        break;
                    }
                    if prev.is_some_and(|p| p.end != x.at.start) {
                        text.push(' ');
                    }
                    text += &tok_text(&x.tok);
                    prev = Some(x.at);
                }
                out.push(Token { tok: Tok::Str(text), at: b.at, depth: b.depth });
            }
            _ => out.push(b),
        }
    }
    out
}

/// A token as source text.
fn tok_text(t: &Tok) -> String {
    match t {
        Tok::Id(s) | Tok::Sys(s) => s.clone(),
        Tok::Num(n) => n.text.clone(),
        Tok::Fill(c) => format!("'{c}"),
        Tok::Str(s) => sv_quote(s),
        Tok::Sym(s) => s.to_string(),
        Tok::Directive(d) => format!("`{d}"),
        _ => String::new(),
    }
}

/// A string as SystemVerilog writes it: quotes, \\ \" \n \t, other control characters as \ooo (Rust's {:?} would
/// write \u{1} or escape non-ASCII, which SystemVerilog does not read).
fn sv_quote(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\{:03o}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn names(params: &[(String, Option<Vec<Token>>)]) -> String {
    params.iter().map(|p| p.0.as_str()).collect::<Vec<_>>().join(", ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lex::lex;

    fn run(src: &str) -> (Vec<Token>, Diag) {
        let mut m = HashMap::new();
        let mut d = Diag::default();
        let t = preprocess(lex(src), &mut m, &mut d);
        (t, d)
    }
    /// The tokens as text (identifiers, numbers, symbols), errors as `line:col msg`.
    fn text(src: &str) -> String {
        let (t, d) = run(src);
        let mut s: Vec<String> = t
            .iter()
            .filter_map(|t| match &t.tok {
                Tok::Id(s) | Tok::Sys(s) => Some(s.clone()),
                Tok::Num(n) => Some(n.text.clone()),
                Tok::Sym(s) => Some(s.to_string()),
                Tok::Str(s) => Some(format!("{s:?}")),
                _ => None,
            })
            .collect();
        s.extend(d.errors.iter().map(|e| format!("!{}:{} {}", e.line, e.col, e.msg)));
        s.extend(d.warnings.iter().map(|e| format!("?{}:{} {}", e.line, e.col, e.msg)));
        s.join(" ")
    }

    #[test]
    fn object_like_macros() {
        assert_eq!(text("`define N 3\na ##`N b"), "a ## 3 b");
        assert_eq!(text("`define A `B + 1\n`define B 2\nx = `A;"), "x = 2 + 1 ;"); // expanded at the use
        assert_eq!(text("`define E\na `E b"), "a b");
        assert_eq!(text("a\n  `__LINE__ `__FILE__"), "a 2 \"\"");
        // token pasting and stringification (OpenTitan's prim_assert macros)
        assert_eq!(text("`define K(n) n``KnownEnable: x\n`K(Paddr_A)"), "Paddr_AKnownEnable : x");
        assert_eq!(text("`define P(a, b) a``_``b\n`P(u, v) `P(3, 4)"), "u_v 3_4");
        assert_eq!(text("`define S(x) `\"x`\"\n`S(a&&b) `S(f(c) || d)"), "\"a&&b\" \"f(c) || d\"");
        assert_eq!(text("a `` b"), "a b !1:3 `` and `\" work only inside a macro body");
        assert_eq!(text("`define T(x) $error(\"%s\", `\"x`\")\n`T(ack)"), "$error ( \"%s\" , \"ack\" )");
        assert_eq!(text("`define L `__LINE__\n\nx = `L;"), "x = 3 ;"); // the line of the outermost use
        assert_eq!(text("`define N 1\n`undef N\n`N"), "!3:1 undefined macro `N");
    }

    #[test]
    fn macros_with_arguments() {
        assert_eq!(text("`define D(a, b) a ##1 b\n`D(req, (ack || x))"), "req ## 1 ( ack || x )");
        assert_eq!(text("`define D(a, b = 2) a + b\n`D(1) `D(1, 3) `D(1, )"), "1 + 2 1 + 3 1 + 2");
        assert_eq!(text("`define F() 7\n`F()"), "7");
        assert_eq!(text("`define D(a) [a]\n`D(f(1, 2))"), "[ f ( 1 , 2 ) ]");
        assert_eq!(text("`define D(a) a\n`D"), "!2:1 macro `D needs arguments: `D(a)");
        assert_eq!(text("`define D(a) a\n`D(1, 2)"), "!2:1 macro `D takes 1 argument(s), got 2");
        assert_eq!(text("`define D(a, b) a\n`D(1)"), "!2:1 macro `D: missing argument 'b'");
        assert_eq!(text("`define D(a) a\n`D(1"), "!2:1 the arguments of `D are not closed");
    }

    #[test]
    fn expansion_keeps_the_use_position() {
        let (t, _) = run("`define C (a &&\\\n b)\nx\n  `C y");
        let at: Vec<_> = t.iter().map(|t| (t.at.line, t.at.col, t.depth)).collect();
        assert_eq!(at, [(3, 1, 0), (4, 3, 1), (4, 3, 1), (4, 3, 1), (4, 3, 1), (4, 3, 1), (4, 6, 0), (4, 7, 0)]);
        let (t, _) = run("`define M(a) a\n`M(q)");
        assert_eq!((t[0].at.col, t[0].at.end), (1, 20)); // the whole use, up to the closing parenthesis
    }

    #[test]
    fn recursion_is_an_error() {
        let e = text("`define R `R\n`R");
        assert!(e.ends_with("!2:1 macro `R expands into itself"), "{e}");
    }

    #[test]
    fn conditionals() {
        assert_eq!(text("`define X\n`ifdef X a `else b `endif"), "a");
        assert_eq!(text("`ifdef X a `else b `endif"), "b");
        assert_eq!(text("`ifndef X a `else b `endif"), "a");
        assert_eq!(text("`define Y\n`ifdef X a `elsif Y b `else c `endif"), "b");
        assert_eq!(text("`define X\n`define Y\n`ifdef X a `elsif Y b `else c `endif"), "a");
        assert_eq!(text("`ifdef X a `elsif Y b `else c `endif"), "c");
        // nesting: an inner true branch inside an outer false one stays off
        assert_eq!(text("`define I\n`ifdef O `ifdef I a `else b `endif c `else d `endif"), "d");
        assert_eq!(text("`define O\n`ifdef O `ifdef I a `else b `endif c `endif"), "b c");
    }

    #[test]
    fn inactive_code_is_not_read() {
        // undefined macros, defines and bad tokens in a false branch do nothing
        assert_eq!(text("`ifdef X\n`define N 1\n`UNDEF 1.5\n`endif\n`ifdef N n `endif ok"), "ok");
    }

    #[test]
    fn conditional_errors() {
        assert_eq!(text("a `endif"), "a !1:3 `endif without `ifdef");
        assert_eq!(text("`ifdef X\na"), "!1:1 `ifdef without `endif");
        assert_eq!(text("`ifdef X `else `else `endif"), "!1:16 `else after `else");
        assert_eq!(text("`ifdef\n"), "!1:1 `ifdef needs a macro name");
    }

    #[test]
    fn other_directives() {
        assert_eq!(text("`include \"x.svh\"\na"), "a ?1:1 `include is not followed: give the included file to sva parse as well");
        assert_eq!(text("`resetall `celldefine a `endcelldefine"), "a");
        assert_eq!(text("`timescale 1ns/1ps\na"), "a");
    }

    #[test]
    fn macros_carry_over_between_files() {
        let mut m = HashMap::new();
        let mut d = Diag::default();
        preprocess(lex("`define W 8"), &mut m, &mut d);
        let t = preprocess(lex("`W"), &mut m, &mut d);
        assert_eq!(t[0].tok, Tok::Num(crate::lex::Num { value: 8, unknown: 0, width: None, signed: true, base: 10, text: "8".into() }));
        assert!(d.errors.is_empty());
    }
    #[test]
    fn expansion_budget() {
        // 24 levels of a macro that doubles: 16 M tokens without a budget (gigabytes, a hung page); one error instead
        let mut src = String::from("`define L0 a\n");
        for i in 1..=24 {
            src += &format!("`define L{i} `L{} + `L{}\n", i - 1, i - 1);
        }
        src += "`L24 z";
        let t0 = std::time::Instant::now();
        let (t, d) = run(&src);
        assert!(t0.elapsed().as_secs_f64() < 5.0, "{:?}", t0.elapsed());
        assert_eq!(d.errors.len(), 1, "{:?}", d.errors);
        assert!(d.errors[0].msg.starts_with("macro expansion too large: more than 1000000 tokens"), "{}", d.errors[0].msg);
        assert!(matches!(&t[t.len() - 2].tok, Tok::Id(z) if z == "z"));   // the file goes on after the use
    }
    #[test]
    fn strings_quoted_as_systemverilog() {
        assert_eq!(sv_quote("a\"b\\c\nd\u{1}é"), r#""a\"b\\c\nd\001é""#);
    }
}
