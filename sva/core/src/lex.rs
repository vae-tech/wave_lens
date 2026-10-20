//! Lexer: SystemVerilog text -> tokens with positions.
//!
//! It never fails. What it cannot read becomes a [`Tok::Bad`] token that carries the reason; the parser reports it only
//! if it reaches it, so module code that the parser skips (always blocks, tasks, real numbers, ...) may hold anything.
//! `` `define `` lines are read here (the body is tokenised in place, so its tokens keep their positions);
//! `` `timescale `` and the other line directives without meaning for assertions are dropped.

use serde::Serialize;

/// A place in the source: 1-based line and column (in characters), byte offsets `start..end`.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Span {
    pub line: u32,
    pub col: u32,
    pub start: u32,
    pub end: u32,
}

impl Span {
    /// From the start of `self` to the end of `b`.
    pub fn to(self, b: Span) -> Span {
        if b.end < self.start {
            return self;
        }
        Span { end: b.end, ..self }
    }
}

/// A numeric literal: `12`, `8'hFF`, `4'b10x1`, `'d5`, `8'sd3`. `unknown` has the x / z bits; `width` is the size
/// written in front of the tick (`None`: unsized); `base` is 2, 8, 10 or 16; `text` is the literal as written.
#[derive(Clone, Debug, PartialEq)]
pub struct Num {
    pub value: u64,
    pub unknown: u64,
    pub width: Option<u32>,
    pub signed: bool,
    pub base: u8,
    pub text: String,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Tok {
    /// Identifiers and keywords; escaped identifiers without their backslash, unless they hold a `.`.
    Id(String),
    /// System identifiers with their `$`: `$rose`.
    Sys(String),
    Num(Num),
    /// `'0` `'1` `'x` `'z`.
    Fill(char),
    /// A string literal, escapes decoded.
    Str(String),
    Sym(&'static str),
    /// `` `name ``: a compiler directive or a macro use (the name without the backquote).
    Directive(String),
    Define(Box<Define>),
    Bad(String),
    End,
}

/// `` `define NAME(a, b = 1) body ``: parameters with their default tokens, the body tokens.
#[derive(Clone, Debug, PartialEq)]
pub struct Define {
    pub name: String,
    pub params: Option<Vec<(String, Option<Vec<Token>>)>>,
    pub body: Vec<Token>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Token {
    pub tok: Tok,
    pub at: Span,
    /// Macro expansion depth (0: written in the file).
    pub depth: u16,
}

/// Longest first: the lexer takes the first that matches.
const SYMS: [&str; 59] = [
    "<<<", ">>>", "===", "!==", "==?", "!=?", "|->", "|=>", "#-#", "#=#", "[->", "[+]", "<->", //
    "~&", "~|", "~^", "^~", "==", "!=", "<=", ">=", "&&", "||", "<<", ">>", "**", "->", "##", "[*", "[=", "+:", "-:",
    "::", ".*", "++", "--", //
    "(", ")", "[", "]", "{", "}", ";", ":", ",", ".", "@", "#", "?", "!", "~", "&", "|", "^", "+", "-", "*", "/", "%",
];
const SYMS1: [&str; 3] = ["<", ">", "="];

/// Directives dropped together with the rest of their line.
const LINE_DIRECTIVES: [&str; 5] = ["timescale", "default_nettype", "line", "pragma", "delay_mode_path"];

struct Lexer<'a> {
    src: &'a str,
    b: &'a [u8],
    i: usize,
    end: usize,
    line: u32,
    ls: usize,
    /// The column of the last token (a byte offset and its column), so the next one counts only the characters
    /// between them: O(the line) once per line, not per token (a generated one-line file).
    col: std::cell::Cell<(usize, u32)>,
}

fn ident_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_' || c == b'$'
}

impl<'a> Lexer<'a> {
    fn span(&self, start: usize, line: u32, ls: usize) -> Span {
        let (from, c0) = match self.col.get() {
            (p, c) if p >= ls && p <= start => (p, c),
            _ => (ls, 0),
        };
        let c = c0 + self.src[from..start].chars().count() as u32;
        self.col.set((start, c));
        let col = c + 1;
        Span { line, col, start: start as u32, end: self.i as u32 }
    }
    fn at(&self, k: usize) -> u8 {
        if self.i + k < self.end {
            self.b[self.i + k]
        } else {
            0
        }
    }
    fn bump(&mut self) {
        if self.b[self.i] == b'\n' {
            self.line += 1;
            self.ls = self.i + 1;
        }
        self.i += 1;
    }
    fn skip_to_eol(&mut self) {
        while self.i < self.end && self.b[self.i] != b'\n' {
            self.i += 1;
        }
    }

    fn run(&mut self) -> Vec<Token> {
        let mut out = Vec::new();
        while self.i < self.end {
            let c = self.b[self.i];
            if c.is_ascii_whitespace() {
                self.bump();
                continue;
            }
            if c == b'\\' && (self.at(1) == b'\n' || (self.at(1) == b'\r' && self.at(2) == b'\n')) {
                self.bump();
                while self.b[self.i - 1] != b'\n' {
                    self.bump();
                }
                continue;
            }
            if c == b'/' && self.at(1) == b'/' {
                self.skip_to_eol();
                continue;
            }
            let (start, line, ls) = (self.i, self.line, self.ls);
            if c == b'/' && self.at(1) == b'*' {
                match self.src[self.i + 2..self.end].find("*/") {
                    Some(k) => {
                        let stop = self.i + 2 + k + 2;
                        while self.i < stop {
                            self.bump();
                        }
                    }
                    None => {
                        self.i += 2;
                        out.push(Token { tok: Tok::Bad("unterminated comment /* ... */".into()), at: self.span(start, line, ls), depth: 0 });
                        while self.i < self.end {
                            self.bump();
                        }
                    }
                }
                continue;
            }
            let tok = self.token(c);
            if let Some(tok) = tok {
                out.push(Token { tok, at: self.span(start, line, ls), depth: 0 });
            }
        }
        out
    }

    /// One token starting at `c` (already known not to be whitespace or a comment). `None`: nothing to emit (a line
    /// directive).
    fn token(&mut self, c: u8) -> Option<Tok> {
        if c.is_ascii_alphabetic() || c == b'_' {
            let s = self.i;
            while self.i < self.end && ident_char(self.b[self.i]) {
                self.i += 1;
            }
            return Some(Tok::Id(self.src[s..self.i].into()));
        }
        if c == b'\\' {
            let s = self.i + 1;
            self.i += 1;
            while self.i < self.end && !self.b[self.i].is_ascii_whitespace() {
                self.i += 1;
            }
            // one that would read as a hierarchical name (`\esc.x `) keeps its backslash: a dump names it so (`\bus[0] `
            // stays the select of a bit-blasted vector, as dumps have it)
            let name = &self.src[s..self.i];
            if name.is_empty() {
                return Some(Tok::Bad("empty escaped identifier (a \\ must be followed by the name)".into()));
            }
            return Some(Tok::Id(if name.contains('.') { self.src[s - 1..self.i].into() } else { name.into() }));
        }
        if c == b'$' {
            self.i += 1;
            if self.i < self.end && (self.b[self.i].is_ascii_alphabetic() || self.b[self.i] == b'_') {
                let s = self.i - 1;
                while self.i < self.end && ident_char(self.b[self.i]) {
                    self.i += 1;
                }
                return Some(Tok::Sys(self.src[s..self.i].into()));
            }
            return Some(Tok::Sym("$"));
        }
        if c == b'"' {
            return Some(self.string());
        }
        if c == b'`' {
            return self.directive();
        }
        if c.is_ascii_digit() {
            return Some(self.number());
        }
        if c == b'\'' {
            return Some(self.tick());
        }
        let rest = &self.src[self.i..self.end];
        if let Some(s) = SYMS.iter().chain(SYMS1.iter()).find(|s| rest.starts_with(**s)) {
            self.i += s.len();
            return Some(Tok::Sym(s));
        }
        let ch = rest.chars().next().unwrap();
        self.i += ch.len_utf8();
        Some(Tok::Bad(format!("unexpected character '{ch}'")))
    }

    fn string(&mut self) -> Tok {
        self.i += 1;
        let mut s = String::new();
        while self.i < self.end {
            match self.b[self.i] {
                b'"' => {
                    self.i += 1;
                    return Tok::Str(s);
                }
                b'\n' => break,
                b'\\' if self.i + 1 < self.end => {
                    // \n \t \\ \" \ddd (octal, up to three digits); any other character stands for itself. The
                    // next character may be several bytes long: the walk goes by characters, never into one.
                    let e = self.src[self.i + 1..self.end].chars().next().unwrap_or('\\');
                    let oct: String = self.src[self.i + 1..self.end].chars().take(3).take_while(|c| ('0'..='7').contains(c)).collect();
                    if !oct.is_empty() {
                        s.push(char::from((u32::from_str_radix(&oct, 8).unwrap_or(0) & 0xff) as u8));
                        self.i += 1 + oct.len();
                        continue;
                    }
                    s.push(match e {
                        'n' => '\n',
                        't' => '\t',
                        _ => e,
                    });
                    self.i += 1 + e.len_utf8();
                }
                _ => {
                    let ch = self.src[self.i..self.end].chars().next().unwrap_or('\u{fffd}');
                    s.push(ch);
                    self.i += ch.len_utf8();
                }
            }
        }
        Tok::Bad("unterminated string".into())
    }

    fn directive(&mut self) -> Option<Tok> {
        self.i += 1;
        let s = self.i;
        while self.i < self.end && ident_char(self.b[self.i]) {
            self.i += 1;
        }
        let name = &self.src[s..self.i];
        if name.is_empty() {
            // inside a macro body: `` pastes two tokens, `" ... `" makes a string of the text between them
            let c = if self.i < self.end { self.b[self.i] } else { 0 };
            self.i = (self.i + self.src[self.i..self.end].chars().next().map_or(1, char::len_utf8)).min(self.end);
            return Some(match c {
                b'`' => Tok::Sym("``"),
                b'"' => Tok::Sym("`\""),
                _ => Tok::Bad("a lone ` (a directive or macro name must follow it)".into()),
            });
        }
        if LINE_DIRECTIVES.contains(&name) {
            self.skip_to_eol();
            return None;
        }
        if name == "define" {
            return Some(self.define());
        }
        Some(Tok::Directive(name.into()))
    }

    /// The end of a `` `define `` body that starts at `j`: the end of the line, past `\` continuations, comments and
    /// strings.
    fn define_end(&self, mut j: usize) -> usize {
        let b = self.b;
        while j < self.end {
            match b[j] {
                b'\n' => break,
                b'\\' if j + 1 < self.end && b[j + 1] == b'\n' => j += 2,
                b'\\' if j + 2 < self.end && b[j + 1] == b'\r' && b[j + 2] == b'\n' => j += 3,
                b'/' if j + 1 < self.end && b[j + 1] == b'/' => {
                    // a line comment ends the body unless it ends in a `\` itself (multi-line macros with comments)
                    while j < self.end && b[j] != b'\n' {
                        j += 1;
                    }
                    let cont = (j >= 1 && b[j - 1] == b'\\') || (j >= 2 && b[j - 1] == b'\r' && b[j - 2] == b'\\');
                    if cont && j < self.end {
                        j += 1;
                    }
                }
                b'/' if j + 1 < self.end && b[j + 1] == b'*' => {
                    j = self.src[j + 2..self.end].find("*/").map_or(self.end, |k| j + 2 + k + 2);
                }
                b'"' => {
                    j += 1;
                    while j < self.end && b[j] != b'"' && b[j] != b'\n' {
                        j += if b[j] == b'\\' { 2 } else { 1 };
                    }
                    j = (j + 1).min(self.end);
                }
                _ => j += 1,
            }
        }
        j.min(self.end)
    }

    /// Tokens of `self.src[from..to]`, positions continuing from the current line.
    fn sub(&mut self, from: usize, to: usize) -> Vec<Token> {
        while self.i < from {
            self.bump();
        }
        let mut l = Lexer { src: self.src, b: self.b, i: from, end: to, line: self.line, ls: self.ls, col: std::cell::Cell::new((0, 0)) };
        let t = l.run();
        self.i = to;
        self.line = l.line;
        self.ls = l.ls;
        t
    }

    fn define(&mut self) -> Tok {
        while self.i < self.end && (self.b[self.i] == b' ' || self.b[self.i] == b'\t') {
            self.i += 1;
        }
        let s = self.i;
        while self.i < self.end && ident_char(self.b[self.i]) {
            self.i += 1;
        }
        let name = self.src[s..self.i].to_string();
        if name.is_empty() || name.as_bytes()[0].is_ascii_digit() {
            self.skip_to_eol();
            return Tok::Bad("`define needs a macro name".into());
        }
        let mut params = None;
        if self.at(0) == b'(' {
            let mut ps = Vec::new();
            self.i += 1;
            loop {
                while self.i < self.end && (self.b[self.i] == b' ' || self.b[self.i] == b'\t') {
                    self.i += 1;
                }
                let s = self.i;
                while self.i < self.end && ident_char(self.b[self.i]) {
                    self.i += 1;
                }
                let p = self.src[s..self.i].to_string();
                while self.i < self.end && (self.b[self.i] == b' ' || self.b[self.i] == b'\t') {
                    self.i += 1;
                }
                let mut default = None;
                if self.at(0) == b'=' {
                    let from = self.i + 1;
                    let mut j = from;
                    let mut depth = 0;
                    while j < self.end && self.b[j] != b'\n' && !(depth == 0 && (self.b[j] == b',' || self.b[j] == b')')) {
                        match self.b[j] {
                            b'(' | b'[' | b'{' => depth += 1,
                            b')' | b']' | b'}' => depth -= 1,
                            _ => {}
                        }
                        j += 1;
                    }
                    default = Some(self.sub(from, j));
                }
                if p.is_empty() && !(ps.is_empty() && self.at(0) == b')') {
                    self.skip_to_eol();
                    return Tok::Bad(format!("`define {name}: expected a parameter name"));
                }
                if !p.is_empty() {
                    ps.push((p, default));
                }
                match self.at(0) {
                    b',' => self.i += 1,
                    b')' => {
                        self.i += 1;
                        break;
                    }
                    _ => {
                        self.skip_to_eol();
                        return Tok::Bad(format!("`define {name}: expected ',' or ')' in the parameter list"));
                    }
                }
            }
            params = Some(ps);
        }
        let to = self.define_end(self.i);
        let body = self.sub(self.i, to);
        Tok::Define(Box::new(Define { name, params, body }))
    }

    fn number(&mut self) -> Tok {
        let s = self.i;
        while self.i < self.end && (self.b[self.i].is_ascii_digit() || self.b[self.i] == b'_') {
            self.i += 1;
        }
        let dec = self.src[s..self.i].replace('_', "");
        // a real number or a time literal: only in code the parser skips
        if self.at(0) == b'.' && self.at(1).is_ascii_digit() {
            self.i += 1;
            while self.i < self.end && (self.b[self.i].is_ascii_alphanumeric() || self.b[self.i] == b'_') {
                self.i += 1;
            }
            return Tok::Bad("real numbers are outside the subset".into());
        }
        // a size in front of a based literal: `8'hFF`, `8 'h FF`
        let mut j = self.i;
        while j < self.end && (self.b[j] == b' ' || self.b[j] == b'\t') {
            j += 1;
        }
        if j < self.end && self.b[j] == b'\'' {
            let k = j + 1 + (j + 1 < self.end && (self.b[j + 1] | 0x20) == b's') as usize;
            if k < self.end && matches!(self.b[k] | 0x20, b'b' | b'o' | b'd' | b'h') {
                let width = match dec.parse::<u32>() {
                    Ok(0) => return self.bad_literal("a literal cannot have size 0"),
                    Ok(w) => w,
                    Err(_) => return self.bad_literal("literal size too large"),
                };
                self.i = j + 1;
                return self.based(s, Some(width));
            }
        }
        match dec.parse::<u64>() {
            Ok(value) => Tok::Num(Num { value, unknown: 0, width: None, signed: true, base: 10, text: self.src[s..self.i].into() }),
            Err(_) => Tok::Bad("number wider than 64 bits".into()),
        }
    }

    fn bad_literal(&mut self, msg: &str) -> Tok {
        while self.i < self.end && (self.b[self.i].is_ascii_alphanumeric() || b"_'?".contains(&self.b[self.i])) {
            self.i += 1;
        }
        Tok::Bad(msg.into())
    }

    /// After the tick: `[s]b|o|d|h digits`. `s` is where the literal (its size, if any) starts.
    fn based(&mut self, s: usize, width: Option<u32>) -> Tok {
        let signed = (self.at(0) | 0x20) == b's';
        if signed {
            self.i += 1;
        }
        let base = match self.at(0) | 0x20 {
            b'b' => 2u8,
            b'o' => 8,
            b'd' => 10,
            _ => 16,
        };
        self.i += 1;
        while self.i < self.end && (self.b[self.i] == b' ' || self.b[self.i] == b'\t') {
            self.i += 1;
        }
        let ds = self.i;
        while self.i < self.end && (self.b[self.i].is_ascii_alphanumeric() || self.b[self.i] == b'_' || self.b[self.i] == b'?') {
            self.i += 1;
        }
        let text: String = self.src[s..self.i].chars().filter(|c| !c.is_whitespace()).collect();
        let digits: Vec<u8> = self.b[ds..self.i].iter().copied().filter(|&c| c != b'_').collect();
        if digits.is_empty() {
            return Tok::Bad(format!("expected digits after '{}", base_char(base)));
        }
        let xz = |c: u8| matches!(c | 0x20, b'x' | b'z') || c == b'?';
        let (mut value, mut unknown): (u128, u128) = (0, 0);
        if base == 10 {
            if digits.len() == 1 && xz(digits[0]) {
                unknown = u64::MAX as u128;
            } else {
                for &d in &digits {
                    if !d.is_ascii_digit() {
                        return Tok::Bad(format!("'{}' is not a decimal digit", d as char));
                    }
                    value = match value.checked_mul(10).and_then(|v| v.checked_add((d - b'0') as u128)) {
                        Some(v) => v,
                        None => return Tok::Bad("literal wider than 64 bits".into()),
                    };
                }
            }
        } else {
            let mut bits = 0u32;   // the significant bits so far: the shifts below stay inside u128
            let bpd = match base {
                2 => 1,
                8 => 3,
                _ => 4,
            };
            for &d in &digits {
                let (v, u) = if xz(d) {
                    (0, (1u128 << bpd) - 1)
                } else {
                    match (d as char).to_digit(base as u32) {
                        Some(v) => (v as u128, 0),
                        None => return Tok::Bad(format!("'{}' is not a digit in base {base}", d as char)),
                    }
                };
                if bits > 0 || v != 0 || u != 0 {
                    bits += bpd;
                }
                if bits > 128 {
                    return Tok::Bad("literal wider than 64 bits".into());
                }
                value = (value << bpd) | v;
                unknown = (unknown << bpd) | u;
            }
            // a leading x / z fills the rest of the size
            if let (Some(w), true) = (width, xz(digits[0])) {
                let have = digits.len() as u32 * bpd;
                if w > have {
                    unknown |= mask128(w) & !mask128(have);
                }
            }
        }
        if let Some(w) = width {
            value &= mask128(w);
            unknown &= mask128(w);
        }
        if value >> 64 != 0 || unknown >> 64 != 0 {
            return Tok::Bad("literal wider than 64 bits".into());
        }
        Tok::Num(Num { value: value as u64, unknown: unknown as u64, width, signed, base, text })
    }

    fn tick(&mut self) -> Tok {
        let s = self.i;
        self.i += 1;
        let c = self.at(0);
        let after = self.at(1);
        if matches!(c | 0x20, b'0' | b'1' | b'x' | b'z') && !ident_char(after) && (c.is_ascii_digit() || c.is_ascii_alphabetic()) {
            self.i += 1;
            return Tok::Fill((c | 0x20) as char);
        }
        let k = (c | 0x20 == b's') as usize;
        if matches!(self.at(k) | 0x20, b'b' | b'o' | b'd' | b'h') {
            return self.based(s, None);
        }
        match c {
            b'(' => {
                self.i += 1;
                Tok::Sym("'(")
            }
            b'{' => {
                self.i += 1;
                Tok::Sym("'{")
            }
            _ => Tok::Sym("'"),
        }
    }
}

fn base_char(base: u8) -> char {
    match base {
        2 => 'b',
        8 => 'o',
        10 => 'd',
        _ => 'h',
    }
}

fn mask128(w: u32) -> u128 {
    if w >= 128 {
        u128::MAX
    } else {
        (1u128 << w) - 1
    }
}

/// Tokens of `src`, ending with [`Tok::End`].
pub fn lex(src: &str) -> Vec<Token> {
    let mut l = Lexer { src, b: src.as_bytes(), i: 0, end: src.len(), line: 1, ls: 0, col: std::cell::Cell::new((0, 0)) };
    let mut out = l.run();
    let at = l.span(src.len(), l.line, l.ls);
    out.push(Token { tok: Tok::End, at, depth: 0 });
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn toks(src: &str) -> Vec<Tok> {
        lex(src).into_iter().map(|t| t.tok).filter(|t| *t != Tok::End).collect()
    }
    fn num(src: &str) -> Num {
        match &toks(src)[..] {
            [Tok::Num(n)] => n.clone(),
            t => panic!("{src}: {t:?}"),
        }
    }
    fn bad(src: &str) -> String {
        match toks(src).into_iter().find_map(|t| if let Tok::Bad(m) = t { Some(m) } else { None }) {
            Some(m) => m,
            None => panic!("{src}: no Bad token"),
        }
    }
    fn id(s: &str) -> Tok {
        Tok::Id(s.into())
    }

    #[test]
    fn identifiers_keywords_system_names() {
        assert_eq!(toks("a_1 b$c _x"), [id("a_1"), id("b$c"), id("_x")]);
        assert_eq!(toks("$rose($past)"), [Tok::Sys("$rose".into()), Tok::Sym("("), Tok::Sys("$past".into()), Tok::Sym(")")]);
        assert_eq!(toks("##[1:$]")[4], Tok::Sym("$"));
        assert_eq!(toks("\\bus[0] x"), [id("bus[0]"), id("x")]);
    }

    #[test]
    fn decimal_and_based_numbers() {
        let n = num("1_000");
        assert_eq!((n.value, n.width, n.base, n.text.as_str()), (1000, None, 10, "1_000"));
        let n = num("8'hFF");
        assert_eq!((n.value, n.width, n.base, n.signed), (255, Some(8), 16, false));
        assert_eq!(num("4'b1010").value, 10);
        assert_eq!(num("6'o17").value, 15);
        assert_eq!(num("10'd1023").value, 1023);
        assert_eq!(num("'hDEAD_BEEF").value, 0xDEAD_BEEF);
        assert_eq!(num("'hDEAD_BEEF").width, None);
        assert!(num("8'sd5").signed);
        assert_eq!(num("8 'h 1F").value, 0x1F);
        assert_eq!(num("8 'h 1F").text, "8'h1F");
        assert_eq!(num("64'hFFFF_FFFF_FFFF_FFFF").value, u64::MAX);
        assert_eq!(num("4'hFF").value, 0xF); // truncated to the size
    }

    #[test]
    fn unknown_digits() {
        let n = num("4'b10x1");
        assert_eq!((n.value, n.unknown), (0b1001, 0b0010));
        let n = num("8'hx");
        assert_eq!(n.unknown, 0xFF); // a leading x fills the size
        let n = num("4'b?0z1");
        assert_eq!(n.unknown, 0b1010);
        assert_eq!(num("8'dx").unknown, 0xFF);
    }

    #[test]
    fn fills_and_ticks() {
        assert_eq!(toks("'0 '1 'x 'Z"), [Tok::Fill('0'), Tok::Fill('1'), Tok::Fill('x'), Tok::Fill('z')]);
        assert_eq!(toks("2'(a)")[..2], [Tok::Num(Num { value: 2, unknown: 0, width: None, signed: true, base: 10, text: "2".into() }), Tok::Sym("'(")]);
        assert_eq!(toks("'{a}")[0], Tok::Sym("'{"));
    }

    #[test]
    fn bad_literals() {
        assert_eq!(bad("1.5"), "real numbers are outside the subset");
        assert_eq!(bad("99999999999999999999"), "number wider than 64 bits");
        assert_eq!(bad("72'hFF_FFFF_FFFF_FFFF_FFFF"), "literal wider than 64 bits");
        assert_eq!(bad("0'h1"), "a literal cannot have size 0");
        assert_eq!(bad("4'b102"), "'2' is not a digit in base 2");
        assert_eq!(bad("8'h"), "expected digits after 'h");
        assert_eq!(bad("\"abc"), "unterminated string");
        assert_eq!(bad("/* x"), "unterminated comment /* ... */");
        assert_eq!(bad("a ` b"), "a lone ` (a directive or macro name must follow it)");
        assert_eq!(toks("a``b `\"c`\""), [id("a"), Tok::Sym("``"), id("b"), Tok::Sym("`\""), id("c"), Tok::Sym("`\"")]);
        assert_eq!(bad("a § b"), "unexpected character '§'");
    }

    #[test]
    fn longest_symbols_first() {
        let s = |src: &str| toks(src).into_iter().map(|t| if let Tok::Sym(s) = t { s } else { "?" }).collect::<Vec<_>>();
        assert_eq!(s("|-> |=> || |"), ["|->", "|=>", "||", "|"]);
        assert_eq!(s("#-# #=# ## #"), ["#-#", "#=#", "##", "#"]);
        assert_eq!(s("[* [= [-> [+] ["), ["[*", "[=", "[->", "[+]", "["]);
        assert_eq!(s("=== !== == != <= >= < > ="), ["===", "!==", "==", "!=", "<=", ">=", "<", ">", "="]);
        assert_eq!(s("<<< >>> << >> **"), ["<<<", ">>>", "<<", ">>", "**"]);
        assert_eq!(s("~& ~| ~^ ^~ ~ & ^"), ["~&", "~|", "~^", "^~", "~", "&", "^"]);
        assert_eq!(s("+: -: :: :"), ["+:", "-:", "::", ":"]);
        assert_eq!(s("a[*3]").len(), 4);
    }

    #[test]
    fn strings_and_comments() {
        assert_eq!(toks(r#""a \"b\"\n""#), [Tok::Str("a \"b\"\n".into())]);
        assert_eq!(toks("a // b c\n d /* e\n f */ g"), [id("a"), id("d"), id("g")]);
    }

    #[test]
    fn positions() {
        let t = lex("ab  cd\n\t x /* \n */ y\n\"é\" z");
        let p: Vec<_> = t.iter().map(|t| (t.at.line, t.at.col, t.at.start, t.at.end)).collect();
        assert_eq!(p, [(1, 1, 0, 2), (1, 5, 4, 6), (2, 3, 9, 10), (3, 5, 19, 20), (4, 1, 21, 25), (4, 5, 26, 27), (4, 6, 27, 27)]);
        assert_eq!(Span { line: 1, col: 1, start: 0, end: 2 }.to(Span { line: 1, col: 5, start: 4, end: 6 }).end, 6);
    }

    #[test]
    fn line_directives_are_dropped() {
        assert_eq!(toks("`timescale 1ns/1ps\na `default_nettype none\nb"), [id("a"), id("b")]);
        assert_eq!(toks("`ifdef X a `endif"), [Tok::Directive("ifdef".into()), id("X"), id("a"), Tok::Directive("endif".into())]);
    }

    #[test]
    fn defines() {
        let t = lex("`define D 3 + \\\n  4 // c\nx");
        let Tok::Define(d) = &t[0].tok else { panic!("{:?}", t[0]) };
        assert_eq!(d.name, "D");
        assert_eq!(d.params, None);
        let body: Vec<_> = d.body.iter().map(|t| (t.tok.clone(), t.at.line, t.at.col)).collect();
        let n = |v: u64| Tok::Num(Num { value: v, unknown: 0, width: None, signed: true, base: 10, text: v.to_string() });
        assert_eq!(body, [(n(3), 1, 11), (Tok::Sym("+"), 1, 13), (n(4), 2, 3)]);
        assert_eq!((t[1].tok.clone(), t[1].at.line), (id("x"), 3));

        let t = lex("`define M(a, b = 1) a ## b\n");
        let Tok::Define(d) = &t[0].tok else { panic!() };
        let ps = d.params.as_ref().unwrap();
        assert_eq!(ps.len(), 2);
        assert_eq!((ps[0].0.as_str(), ps[0].1.is_none()), ("a", true));
        assert_eq!(ps[1].1.as_ref().unwrap()[0].tok, n(1));
        assert_eq!(d.body.len(), 3);
        // a comment line ending in a backslash keeps the macro going (OpenTitan's prim_assert macros)
        let t = lex("`define C(k) \\\n  // a comment \\\n  k + \\\n  1\nz");
        let Tok::Define(d) = &t[0].tok else { panic!("{:?}", t[0]) };
        assert_eq!(d.body.iter().map(|t| t.tok.clone()).collect::<Vec<_>>(), [id("k"), Tok::Sym("+"), n(1)]);
        assert_eq!((t[1].tok.clone(), t[1].at.line), (id("z"), 5));
        // a space before the parenthesis: an object-like macro whose body starts with '('
        let t = lex("`define P (x)\n");
        let Tok::Define(d) = &t[0].tok else { panic!() };
        assert_eq!((d.params.is_none(), d.body.len()), (true, 3));
        assert_eq!(bad("`define 3x"), "`define needs a macro name");
    }
    #[test]
    fn non_ascii_never_splits_a_character() {
        // after a backslash in a string, after a backquote, inside an escaped name, in a macro body and in `"…`": a
        // token or an error, never a byte index inside a character (a panic: E1, E2 of the first review)
        assert_eq!(toks("\"x\\é\""), [Tok::Str("xé".into())]);
        assert_eq!(bad("`é"), "a lone ` (a directive or macro name must follow it)");
        assert_eq!(toks("\\aé.b c"), [id("\\aé.b"), id("c")]);
        let t = lex("`define M \"é\\é\" `é\nM");
        assert!(matches!(t[0].tok, Tok::Define(_)), "{:?}", t[0]);
        assert_eq!(toks("`\"é`\""), [Tok::Sym("`\""), Tok::Bad("unexpected character 'é'".into()), Tok::Sym("`\"")]);
        assert_eq!(toks("é"), [Tok::Bad("unexpected character 'é'".into())]);
    }

    #[test]
    fn string_escapes() {
        assert_eq!(toks(r#""\101\"\\\t""#), [Tok::Str("A\"\\\t".into())]);
        assert_eq!(toks(r#""\0x""#), [Tok::Str("\0x".into())]);
    }

    #[test]
    fn empty_escaped_identifier() {
        assert_eq!(bad("\\ x"), "empty escaped identifier (a \\ must be followed by the name)");
    }

    #[test]
    fn columns_on_a_long_line() {
        // counted from the previous token, not from the start of the line for each one (a generated one-line file)
        let src = "a ".repeat(5000) + "é b";
        let t = lex(&src);
        let last = &t[t.len() - 2];
        assert_eq!((last.tok.clone(), last.at.line, last.at.col), (id("b"), 1, 10003));
    }

    #[test]
    fn crlf_lines() {
        let t = lex("a\r\nb");
        assert_eq!((t[1].tok.clone(), t[1].at.line, t[1].at.col), (id("b"), 2, 1));
    }

    #[test]
    fn fuzz_utf8_never_panics() {
        // random strings of 1-64 bytes of keywords, operators, backslashes, quotes, backquotes and multi-byte
        // characters: the lexer, the preprocessor and the parser give tokens and errors with positions, never a panic
        let parts = ["assert", "property", "`define", "`", "\\", "\"", "é", "ж", "€", "𝄞", " ", "\n", "(", ")", "##", "[*", "'", "8'h", "x", "//", "/*", "*/", "$rose", "`\"", "``", "\r\n", ";", "module", "endmodule"];
        let mut seed: u64 = 0x9e37_79b9_7f4a_7c15;
        let mut next = || {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            seed
        };
        for _ in 0..20_000 {
            let mut src = String::new();
            let n = 1 + next() % 16;
            for _ in 0..n {
                src.push_str(parts[(next() % parts.len() as u64) as usize]);
                if src.len() > 64 {
                    break;
                }
            }
            let t = lex(&src);
            for tk in &t {
                assert!(src.is_char_boundary(tk.at.start as usize) && src.is_char_boundary(tk.at.end as usize), "{src:?}: {tk:?}");
            }
            let _ = crate::parse(&src);
        }
    }
}
