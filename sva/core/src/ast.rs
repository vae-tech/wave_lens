//! The syntax tree (docs/sva/LANGUAGE.md, JSON: docs/sva/ast.schema.json).
//!
//! Three layers: [`Expr`] (booleans and integral values, sampled at one clock tick), [`Seq`] (sequences: what can match
//! over a span of ticks) and [`Prop`] (properties: what holds or fails for an attempt). A sequence is a property
//! ([`Prop::Seq`]); a boolean is a sequence of one tick ([`Seq::Bool`]). Every node carries its source span (`at`).
//!
//! Declarations keep the tree as written. An [`Assertion`] holds the expanded tree: sequence and property instances get
//! their bodies (with the actual arguments substituted), constants their values, range bounds are folded to numbers,
//! and every boolean that can match at a tick (a sequence element) gets an id `s1`, `s2`, ... unique in the assertion.

use crate::lex::Span;
use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum UnOp {
    #[serde(rename = "!")]
    Not,
    #[serde(rename = "~")]
    BitNot,
    #[serde(rename = "&")]
    RedAnd,
    #[serde(rename = "|")]
    RedOr,
    #[serde(rename = "^")]
    RedXor,
    #[serde(rename = "~&")]
    RedNand,
    #[serde(rename = "~|")]
    RedNor,
    #[serde(rename = "~^")]
    RedXnor,
    #[serde(rename = "-")]
    Neg,
    #[serde(rename = "+")]
    Plus,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum BinOp {
    #[serde(rename = "**")]
    Pow,
    #[serde(rename = "*")]
    Mul,
    #[serde(rename = "/")]
    Div,
    #[serde(rename = "%")]
    Mod,
    #[serde(rename = "+")]
    Add,
    #[serde(rename = "-")]
    Sub,
    #[serde(rename = "<<")]
    Shl,
    #[serde(rename = ">>")]
    Shr,
    #[serde(rename = "<<<")]
    AShl,
    #[serde(rename = ">>>")]
    AShr,
    #[serde(rename = "<")]
    Lt,
    #[serde(rename = "<=")]
    Le,
    #[serde(rename = ">")]
    Gt,
    #[serde(rename = ">=")]
    Ge,
    #[serde(rename = "==")]
    Eq,
    #[serde(rename = "!=")]
    Ne,
    #[serde(rename = "===")]
    CaseEq,
    #[serde(rename = "!==")]
    CaseNe,
    #[serde(rename = "&")]
    BitAnd,
    #[serde(rename = "^")]
    BitXor,
    #[serde(rename = "~^")]
    BitXnor,
    #[serde(rename = "|")]
    BitOr,
    #[serde(rename = "&&")]
    LogAnd,
    #[serde(rename = "||")]
    LogOr,
}

impl UnOp {
    pub fn sym(self) -> &'static str {
        use UnOp::*;
        match self {
            Not => "!",
            BitNot => "~",
            RedAnd => "&",
            RedOr => "|",
            RedXor => "^",
            RedNand => "~&",
            RedNor => "~|",
            RedXnor => "~^",
            Neg => "-",
            Plus => "+",
        }
    }
    pub fn from_sym(s: &str) -> Option<UnOp> {
        use UnOp::*;
        Some(match s {
            "!" => Not,
            "~" => BitNot,
            "&" => RedAnd,
            "|" => RedOr,
            "^" => RedXor,
            "~&" => RedNand,
            "~|" => RedNor,
            "~^" | "^~" => RedXnor,
            "-" => Neg,
            "+" => Plus,
            _ => return None,
        })
    }
}

impl BinOp {
    pub fn sym(self) -> &'static str {
        use BinOp::*;
        match self {
            Pow => "**",
            Mul => "*",
            Div => "/",
            Mod => "%",
            Add => "+",
            Sub => "-",
            Shl => "<<",
            Shr => ">>",
            AShl => "<<<",
            AShr => ">>>",
            Lt => "<",
            Le => "<=",
            Gt => ">",
            Ge => ">=",
            Eq => "==",
            Ne => "!=",
            CaseEq => "===",
            CaseNe => "!==",
            BitAnd => "&",
            BitXor => "^",
            BitXnor => "~^",
            BitOr => "|",
            LogAnd => "&&",
            LogOr => "||",
        }
    }
    /// Binding power (IEEE 1800-2017 table 11-2): higher binds tighter; all of these are left-associative.
    pub fn prec(self) -> u8 {
        use BinOp::*;
        match self {
            Pow => 12,
            Mul | Div | Mod => 11,
            Add | Sub => 10,
            Shl | Shr | AShl | AShr => 9,
            Lt | Le | Gt | Ge => 8,
            Eq | Ne | CaseEq | CaseNe => 7,
            BitAnd => 6,
            BitXor | BitXnor => 5,
            BitOr => 4,
            LogAnd => 3,
            LogOr => 2,
        }
    }
    pub fn from_sym(s: &str) -> Option<BinOp> {
        use BinOp::*;
        Some(match s {
            "**" => Pow,
            "*" => Mul,
            "/" => Div,
            "%" => Mod,
            "+" => Add,
            "-" => Sub,
            "<<" => Shl,
            ">>" => Shr,
            "<<<" => AShl,
            ">>>" => AShr,
            "<" => Lt,
            "<=" => Le,
            ">" => Gt,
            ">=" => Ge,
            "==" => Eq,
            "!=" => Ne,
            "===" => CaseEq,
            "!==" => CaseNe,
            "&" => BitAnd,
            "^" => BitXor,
            "~^" | "^~" => BitXnor,
            "|" => BitOr,
            "&&" => LogAnd,
            "||" => LogOr,
            _ => return None,
        })
    }
}

/// `a[i]`, `a[m:l]`, `a[b+:w]`, `a[b-:w]`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SelKind {
    Bit,
    Part,
    Up,
    Down,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum InsideItem {
    Value(Expr),
    Range { lo: Expr, hi: Expr },
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Expr {
    /// A signal (or, before expansion, any name): `req`, `u_dut.state`, `pkg::IDLE`.
    Ident { name: String, at: Span },
    /// A named constant after expansion: a `localparam` / `parameter`, an enum label, a constant argument.
    Const { name: String, value: i64, #[serde(skip_serializing_if = "Option::is_none")] width: Option<u32>, at: Span },
    Number { value: u64, #[serde(skip_serializing_if = "is_zero")] unknown: u64, #[serde(skip_serializing_if = "Option::is_none")] width: Option<u32>, signed: bool, base: u8, text: String, at: Span },
    /// `'0` `'1` `'x` `'z`.
    Fill { bit: char, at: Span },
    Unary { op: UnOp, a: Box<Expr>, at: Span },
    Binary { op: BinOp, a: Box<Expr>, b: Box<Expr>, at: Span },
    Cond { c: Box<Expr>, a: Box<Expr>, b: Box<Expr>, at: Span },
    /// `base[index]` (`lsb` absent), `base[msb:lsb]`, `base[index+:lsb]`, `base[index-:lsb]`.
    Select { base: Box<Expr>, sel: SelKind, index: Box<Expr>, #[serde(skip_serializing_if = "Option::is_none")] lsb: Option<Box<Expr>>, at: Span },
    Concat { items: Vec<Expr>, at: Span },
    /// `{count{items}}`.
    Repl { count: Box<Expr>, items: Vec<Expr>, at: Span },
    Inside { a: Box<Expr>, set: Vec<InsideItem>, at: Span },
    /// A system function: `$rose(a)`, `$past(a, 2)`.
    Call { func: String, args: Vec<Expr>, at: Span },
    /// `width'(a)`.
    Cast { width: u32, a: Box<Expr>, at: Span },
}

fn is_zero(v: &u64) -> bool {
    *v == 0
}

/// A range bound: a number, `$` (open end), or (in declarations, before folding) a constant expression.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum Bound {
    Const(u32),
    Inf(Dollar),
    Expr(Box<Expr>),
}

/// Serialises as `"$"`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Dollar;

impl Serialize for Dollar {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str("$")
    }
}

impl Bound {
    pub const INF: Bound = Bound::Inf(Dollar);
    pub fn value(&self) -> Option<u32> {
        match self {
            Bound::Const(n) => Some(*n),
            _ => None,
        }
    }
    pub fn is_inf(&self) -> bool {
        matches!(self, Bound::Inf(_))
    }
}

/// `##n` is `min == max == n`; `##[m:$]` has `max` [`Bound::INF`]. The same for repetitions and property ranges.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Range {
    pub min: Bound,
    pub max: Bound,
}

impl Range {
    pub fn single(n: u32) -> Range {
        Range { min: Bound::Const(n), max: Bound::Const(n) }
    }
    pub fn new(min: u32, max: Option<u32>) -> Range {
        Range { min: Bound::Const(min), max: max.map_or(Bound::INF, Bound::Const) }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum RepOp {
    /// consecutive `[*n]`
    #[serde(rename = "[*]")]
    Consec,
    /// goto `[->n]`
    #[serde(rename = "[->]")]
    Goto,
    /// non-consecutive `[=n]`
    #[serde(rename = "[=]")]
    NonConsec,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SeqOp {
    And,
    Or,
    Intersect,
    Within,
}

/// An actual argument of an instance: positional (`name` absent) or named `.name(value)`; `value` absent for `()`.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Arg {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub value: Option<Prop>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Seq {
    /// A boolean: matches at one tick where it is true. `id` is set in an assertion (the sequence element).
    Bool { #[serde(skip_serializing_if = "Option::is_none")] id: Option<String>, expr: Expr, at: Span },
    /// `lhs ##range rhs`; a leading `##range rhs` has no `lhs`.
    Delay { #[serde(skip_serializing_if = "Option::is_none")] lhs: Option<Box<Seq>>, range: Range, rhs: Box<Seq>, at: Span },
    Repeat { op: RepOp, range: Range, seq: Box<Seq>, at: Span },
    Binary { op: SeqOp, a: Box<Seq>, b: Box<Seq>, at: Span },
    /// `cond throughout seq`; `cond` is a [`Seq::Bool`].
    Throughout { cond: Box<Seq>, seq: Box<Seq>, at: Span },
    FirstMatch { seq: Box<Seq>, at: Span },
    /// `name(args)`; `body` is the expanded declaration (in an assertion only).
    Instance { name: String, args: Vec<Arg>, #[serde(skip_serializing_if = "Option::is_none")] body: Option<Box<Seq>>, at: Span },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum ImpOp {
    /// overlapped implication
    #[serde(rename = "|->")]
    Overlap,
    /// non-overlapped implication
    #[serde(rename = "|=>")]
    NonOverlap,
    /// overlapped followed-by
    #[serde(rename = "#-#")]
    FollowOverlap,
    /// non-overlapped followed-by
    #[serde(rename = "#=#")]
    FollowNonOverlap,
}

impl ImpOp {
    pub fn sym(self) -> &'static str {
        match self {
            ImpOp::Overlap => "|->",
            ImpOp::NonOverlap => "|=>",
            ImpOp::FollowOverlap => "#-#",
            ImpOp::FollowNonOverlap => "#=#",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PropOp {
    And,
    Or,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Prop {
    Seq { seq: Seq },
    Implies { op: ImpOp, ante: Seq, cons: Box<Prop>, at: Span },
    Not { p: Box<Prop>, at: Span },
    Binary { op: PropOp, a: Box<Prop>, b: Box<Prop>, at: Span },
    If { cond: Expr, then: Box<Prop>, #[serde(rename = "else", skip_serializing_if = "Option::is_none")] else_: Option<Box<Prop>>, at: Span },
    /// `nexttime [n] p` (`n` is 1 when not written), `s_nexttime`.
    Nexttime { strong: bool, n: Bound, p: Box<Prop>, at: Span },
    /// `always p`, `always [m:n] p`, `s_always [m:n] p`.
    Always { strong: bool, #[serde(skip_serializing_if = "Option::is_none")] range: Option<Range>, p: Box<Prop>, at: Span },
    /// `s_eventually p`, `s_eventually [m:n] p`, `eventually [m:n] p`.
    Eventually { strong: bool, #[serde(skip_serializing_if = "Option::is_none")] range: Option<Range>, p: Box<Prop>, at: Span },
    /// A property instance (in an assertion only: the parser writes every `name(args)` as a [`Seq::Instance`]).
    Instance { name: String, args: Vec<Arg>, #[serde(skip_serializing_if = "Option::is_none")] body: Option<Box<Prop>>, at: Span },
}

impl Expr {
    pub fn at(&self) -> Span {
        use Expr::*;
        match self {
            Ident { at, .. } | Const { at, .. } | Number { at, .. } | Fill { at, .. } | Unary { at, .. } | Binary { at, .. } | Cond { at, .. } | Select { at, .. } | Concat { at, .. } | Repl { at, .. } | Inside { at, .. } | Call { at, .. } | Cast { at, .. } => *at,
        }
    }
}

impl Seq {
    pub fn at(&self) -> Span {
        use Seq::*;
        match self {
            Bool { at, .. } | Delay { at, .. } | Repeat { at, .. } | Binary { at, .. } | Throughout { at, .. } | FirstMatch { at, .. } | Instance { at, .. } => *at,
        }
    }
    /// The boolean of a [`Seq::Bool`].
    pub fn as_bool(&self) -> Option<&Expr> {
        match self {
            Seq::Bool { expr, .. } => Some(expr),
            _ => None,
        }
    }
}

impl Prop {
    pub fn at(&self) -> Span {
        use Prop::*;
        match self {
            Seq { seq } => seq.at(),
            Implies { at, .. } | Not { at, .. } | Binary { at, .. } | If { at, .. } | Nexttime { at, .. } | Always { at, .. } | Eventually { at, .. } | Instance { at, .. } => *at,
        }
    }
    pub fn as_seq(&self) -> Option<&Seq> {
        match self {
            Prop::Seq { seq } => Some(seq),
            _ => None,
        }
    }
    pub fn from_expr(e: Expr) -> Prop {
        let at = e.at();
        Prop::Seq { seq: Seq::Bool { id: None, expr: e, at } }
    }
}

/// `@(posedge clk)`: `edge` is `posedge`, `negedge` or `edge` (`@(clk)` is `edge`: both edges).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Clock {
    pub edge: String,
    pub signal: String,
}

/// A formal argument of a sequence or property: `ty` is `untyped`, `sequence`, `property` or a data type (`logic`,
/// `int`, ...: the actual must then be an expression).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Port {
    pub name: String,
    pub ty: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default: Option<Prop>,
    pub at: Span,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SeqDecl {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scope: Option<String>,
    pub ports: Vec<Port>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub clock: Option<Clock>,
    pub body: Seq,
    pub at: Span,
    #[serde(skip)]
    pub scope_id: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct PropDecl {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scope: Option<String>,
    pub ports: Vec<Port>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub clock: Option<Clock>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disable: Option<Expr>,
    pub body: Prop,
    pub at: Span,
    #[serde(skip)]
    pub scope_id: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Assert,
    Assume,
    Cover,
}

impl Kind {
    pub fn word(self) -> &'static str {
        match self {
            Kind::Assert => "assert",
            Kind::Assume => "assume",
            Kind::Cover => "cover",
        }
    }
}

/// A sequence element of an assertion: the viewer draws it as a step.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Element {
    pub id: String,
    pub label: String,
    pub at: Span,
}

/// A signal an assertion reads: `width` is the least width its selects imply (`a[7:0]` -> 8; absent: no select with
/// constant bounds), `declared` the width from a declaration in the assertion's scope (ports, nets, variables).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SignalRef {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub width: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub declared: Option<u32>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Assertion {
    /// The statement label, or `assert_<line>` (`assume_`, `cover_`) when there is none.
    pub label: String,
    pub kind: Kind,
    /// The module, checker, interface or program the assertion is written in.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scope: Option<String>,
    /// The property (or sequence) name when the assertion is one instance: `assert property (p_req_ack);`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub property: Option<String>,
    pub clock: Clock,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disable: Option<Expr>,
    pub prop: Prop,
    /// The property on one line as the report and the page show it (instances replaced by their bodies).
    pub text: String,
    pub elements: Vec<Element>,
    /// Every signal the assertion reads, the clock first.
    pub signals: Vec<SignalRef>,
    /// The text of the first `$error` / `$fatal` / `$warning` / `$info` / `$display` of the action block.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub severity: Option<String>,
    /// Notes for the report: `assume`, `cover sequence`.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub flags: Vec<String>,
    pub line: usize,
    pub at: Span,
}

impl Assertion {
    pub fn element(&self, id: &str) -> Option<&Element> {
        self.elements.iter().find(|e| e.id == id)
    }
}

/// A name with its width (a port or a parameter of a scope).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Net {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub width: Option<u32>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Param {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<i64>,
}

/// A module, interface, program, checker or package of the file.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct ScopeInfo {
    pub kind: String,
    pub name: String,
    pub ports: Vec<Net>,
    pub params: Vec<Param>,
    pub at: Span,
}

/// `bind target[: inst, ...] module [#(...)] instance (.port(expr), ...);` — the connection text as written.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Bind {
    pub target: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub instances: Vec<String>,
    pub module: String,
    pub instance: String,
    pub ports: Vec<BindPort>,
    pub at: Span,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct BindPort {
    /// The port name (`.name(...)`), absent for a positional connection; `.*` is the name `*`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub expr: String,
}
