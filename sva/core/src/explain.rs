//! Expressions for the page (docs/sva/ENGINE.md "Expressions and explain"): the value of any expression over a trace
//! (virtual signals, searches), and the booleans of one assertion taken apart into their sub-expressions, each valued
//! cycle by cycle over one attempt (why it matched or failed).

use crate::ast::{Assertion, BinOp, Expr, Prop, Seq, SignalRef};
use crate::engine::{value_json, Column, Trace};
use crate::value::{Compiler, Samples, V};
use crate::Unit;
use serde::Serialize;
use serde_json::{json, Value};

/// At most this many cycles are valued per node, and this many nodes per boolean (deep expressions stop there).
const MAX_CYCLES: usize = 512;
const MAX_NODES: usize = 64;
/// Values of one expression at most (a virtual signal over the whole trace).
const MAX_VALUES: usize = 4_000_000;

struct Cols<'a>(Vec<&'a Column>);

impl Samples for Cols<'_> {
    fn get(&self, k: usize, c: i64) -> V {
        self.0[k].at(c)
    }
}

/// The columns of `names` in `tr` and the compiler that reads them; `None` with the names missing from the trace.
fn columns<'t>(tr: &'t Trace, names: &[&str]) -> Result<Cols<'t>, Vec<String>> {
    let missing: Vec<String> = names.iter().filter(|n| !tr.signals.contains_key(**n)).map(|n| n.to_string()).collect();
    if !missing.is_empty() {
        return Err(missing);
    }
    Ok(Cols(names.iter().map(|n| &tr.signals[*n]).collect()))
}

/// Each expression parsed in the unit of `sources` (macros, `pkg::NAME` constants): its text as printed and its
/// signals; with a trace that has them, its width and its value at every cycle (a number, `"h…"` past 2^53, binary
/// digits with x). An expression that does not parse or compile has `errors` instead.
pub fn expressions(sources: &[String], texts: &[String], trace: Option<&Trace>) -> Vec<Value> {
    let mut unit = Unit::new();
    let mut errors = Vec::new();
    for s in sources {
        errors.extend(unit.parse(s).errors.into_iter().map(|e| e.to_string()));
    }
    texts
        .iter()
        .map(|text| match unit.expression(text) {
            Err(e) => json!({ "text": text, "errors": [e.to_string()] }),
            Ok((e, sigs)) => {
                let mut out = json!({ "text": e.to_string(), "signals": sigs });
                if let Some(tr) = trace {
                    match valued(&e, &sigs, tr) {
                        Ok((w, values)) => {
                            out["width"] = w.into();
                            out["values"] = values.into();
                        }
                        Err(m) => out["errors"] = json!([m]),
                    }
                }
                out
            }
        })
        .collect()
}

fn valued(e: &Expr, sigs: &[SignalRef], tr: &Trace) -> Result<(u32, Vec<Value>), String> {
    let names: Vec<&str> = sigs.iter().map(|s| s.name.as_str()).collect();
    let cols = columns(tr, &names).map_err(|m| format!("not in the trace: {}", m.join(", ")))?;
    let sig = |n: &str| names.iter().position(|x| *x == n).map(|k| (k, cols.0[k].width));
    let ce = Compiler { sig: &sig }.compile(e, 0).map_err(|(at, m)| format!("{}:{}: {m}", at.line, at.col))?;
    let n = tr.cycles.min(MAX_VALUES);
    Ok((ce.w, (0..n).map(|c| value_json(ce.eval(&cols, c as i64), ce.w)).collect()))
}

/// One sub-expression: its text, width, values over the cycles asked for, and its own parts (constants left out).
#[derive(Serialize)]
pub struct Node {
    pub text: String,
    pub w: u32,
    pub values: Vec<Value>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub kids: Vec<Node>,
}

/// One boolean of the assertion: the element it is (`s1`, ... as in `steps`; none for `disable iff` and an `if`
/// condition), what it is, and its tree.
#[derive(Serialize)]
pub struct Explained {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub what: &'static str,
    pub tree: Node,
}

/// The booleans of `a` (its sequence elements in order, the `if` conditions, `disable iff`) taken apart, every part
/// valued at cycles `from..=to` of `tr` (at most [`MAX_CYCLES`] of them). Signals missing from the trace: an error.
pub fn explain(a: &Assertion, tr: &Trace, from: usize, to: usize) -> Result<Vec<Explained>, String> {
    let names: Vec<&str> = a.signals.iter().skip(1).map(|s| s.name.as_str()).collect(); // the clock first
    let cols = columns(tr, &names).map_err(|m| format!("not in the trace: {}", m.join(", ")))?;
    let sig = |n: &str| names.iter().position(|x| *x == n).map(|k| (k, cols.0[k].width));
    let cm = Compiler { sig: &sig };
    let to = to.min(from.saturating_add(MAX_CYCLES - 1));
    let mut bools: Vec<(Option<String>, &'static str, &Expr)> = Vec::new();
    prop_bools(&a.prop, &mut bools);
    if let Some(d) = &a.disable {
        bools.push((None, "disable iff", d));
    }
    Ok(bools
        .into_iter()
        .filter_map(|(id, what, e)| {
            let mut n = 0;
            node(e, &cm, &cols, from, to, &mut n).map(|tree| Explained { id, what, tree })
        })
        .collect())
}

fn node(e: &Expr, cm: &Compiler, s: &Cols, from: usize, to: usize, n: &mut usize) -> Option<Node> {
    if *n >= MAX_NODES {
        return None;
    }
    let ce = cm.compile(e, 0).ok()?;
    if ce.constant().is_some() {
        return None;
    }
    *n += 1;
    let values = (from..=to).map(|c| value_json(ce.eval(s, c as i64), ce.w)).collect();
    let mut parts = Vec::new();
    kids(e, &mut parts);
    let kids = if matches!(e, Expr::Ident { .. }) { Vec::new() } else { parts.into_iter().filter_map(|k| node(k, cm, s, from, to, n)).collect() };
    Some(Node { text: e.to_string(), w: ce.w, values, kids })
}

/// The parts shown under an expression: the operands (a chain of `&&` or `||` as one list), the arguments of a call.
fn kids<'e>(e: &'e Expr, out: &mut Vec<&'e Expr>) {
    let chain = |op: BinOp, x: &'e Expr, out: &mut Vec<&'e Expr>| {
        fn flat<'e>(op: BinOp, x: &'e Expr, out: &mut Vec<&'e Expr>) {
            match x {
                Expr::Binary { op: o, a, b, .. } if *o == op => {
                    flat(op, a, out);
                    flat(op, b, out);
                }
                _ => out.push(x),
            }
        }
        flat(op, x, out)
    };
    match e {
        Expr::Binary { op: op @ (BinOp::LogAnd | BinOp::LogOr), a, b, .. } => {
            chain(*op, a, out);
            chain(*op, b, out);
        }
        Expr::Binary { a, b, .. } => out.extend([&**a, &**b]),
        Expr::Unary { a, .. } | Expr::Cast { a, .. } | Expr::Inside { a, .. } => out.push(a),
        Expr::Cond { c, a, b, .. } => out.extend([&**c, &**a, &**b]),
        Expr::Select { base, index, .. } => out.extend([&**base, &**index]),
        Expr::Concat { items, .. } | Expr::Call { args: items, .. } => out.extend(items.iter()),
        Expr::Repl { items, .. } => out.extend(items.iter()),
        Expr::Ident { .. } | Expr::Const { .. } | Expr::Number { .. } | Expr::Fill { .. } => {}
    }
}

fn seq_bools<'a>(s: &'a Seq, out: &mut Vec<(Option<String>, &'static str, &'a Expr)>) {
    match s {
        Seq::Bool { id, expr, .. } => out.push((id.clone(), "step", expr)),
        Seq::Delay { lhs, rhs, .. } => {
            if let Some(l) = lhs {
                seq_bools(l, out);
            }
            seq_bools(rhs, out);
        }
        Seq::Repeat { seq, .. } | Seq::FirstMatch { seq, .. } => seq_bools(seq, out),
        Seq::Binary { a, b, .. } => {
            seq_bools(a, out);
            seq_bools(b, out);
        }
        Seq::Throughout { cond, seq, .. } => {
            seq_bools(cond, out);
            seq_bools(seq, out);
        }
        Seq::Instance { body, .. } => {
            if let Some(b) = body {
                seq_bools(b, out);
            }
        }
    }
}

fn prop_bools<'a>(p: &'a Prop, out: &mut Vec<(Option<String>, &'static str, &'a Expr)>) {
    match p {
        Prop::Seq { seq } => seq_bools(seq, out),
        Prop::Implies { ante, cons, .. } => {
            seq_bools(ante, out);
            prop_bools(cons, out);
        }
        Prop::Not { p, .. } | Prop::Nexttime { p, .. } | Prop::Always { p, .. } | Prop::Eventually { p, .. } => prop_bools(p, out),
        Prop::Binary { a, b, .. } => {
            prop_bools(a, out);
            prop_bools(b, out);
        }
        Prop::If { cond, then, else_, .. } => {
            out.push((None, "if", cond));
            prop_bools(then, out);
            if let Some(e) = else_ {
                prop_bools(e, out);
            }
        }
        Prop::Instance { body, .. } => {
            if let Some(b) = body {
                prop_bools(b, out);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn trace(sigs: &[(&str, &[u64])]) -> Trace {
        let mut t = Trace::default();
        for (n, v) in sigs {
            t.add(n, Column::known(1, v));
        }
        t
    }

    #[test]
    fn an_expression_is_valued_at_every_cycle() {
        let t = trace(&[("a", &[0, 1, 1, 0]), ("b", &[1, 1, 0, 0])]);
        let out = expressions(&[], &["a && !b".into(), "$rose(a)".into(), "a +".into()], Some(&t));
        assert_eq!(out[0]["values"], json!([0, 0, 1, 0]));
        assert_eq!(out[0]["signals"], json!([{ "name": "a" }, { "name": "b" }]));
        assert_eq!(out[1]["values"], json!([0, 1, 0, 0]));
        assert!(out[2]["errors"][0].as_str().unwrap().contains("1:4"));
    }

    #[test]
    fn package_constants_and_missing_signals() {
        let pkg = "package p; localparam int IDLE = 2; endpackage".to_string();
        let mut t = Trace::default();
        t.add("st", Column::known(2, &[2, 1]));
        let out = expressions(&[pkg], &["st == p::IDLE".into(), "st && nope".into()], Some(&t));
        assert_eq!(out[0]["values"], json!([1, 0]));
        assert_eq!(out[1]["errors"], json!(["not in the trace: nope"]));
        let info = expressions(&[], &["x[3:0] == 4'h5".into()], None);
        assert_eq!(info[0]["signals"], json!([{ "name": "x", "width": 4 }]));
        assert!(info[0].get("values").is_none());
    }

    #[test]
    fn explain_takes_the_booleans_apart() {
        let src = "module m; a_p: assert property (@(posedge clk) a && b |-> ##1 (c || !d)); endmodule";
        let a = crate::parse(src).assertions.remove(0);
        let t = trace(&[("a", &[1, 0, 0]), ("b", &[1, 1, 0]), ("c", &[0, 0, 0]), ("d", &[0, 1, 1])]);
        let x = explain(&a, &t, 0, 1).unwrap();
        assert_eq!(x.iter().map(|b| (b.id.clone().unwrap(), b.tree.text.clone())).collect::<Vec<_>>(), [("s1".into(), "a && b".into()), ("s2".into(), "c || !d".into())]);
        assert_eq!(x[0].tree.values, [json!(1), json!(0)]);
        assert_eq!(x[0].tree.kids.iter().map(|k| k.text.as_str()).collect::<Vec<_>>(), ["a", "b"]);
        let not_d = &x[1].tree.kids[1];
        assert_eq!((not_d.text.as_str(), &not_d.values, not_d.kids[0].text.as_str()), ("!d", &vec![json!(1), json!(0)], "d"));
        assert_eq!(explain(&a, &trace(&[("a", &[1])]), 0, 0).err().unwrap(), "not in the trace: b, c, d");
        // a window starting far past the trace: no overflow (debug) and no wrap (release), an empty answer
        let _ = explain(&a, &t, usize::MAX, usize::MAX);
    }

    #[test]
    fn explain_through_json() {
        let src = "module m; a_p: assert property (@(posedge clk) a |-> b); endmodule";
        let req = json!({ "files": [src], "trace": { "signals": { "a": [1, 0], "b": [0, 1] } }, "explain": { "assert": "a_p", "from": 0, "to": 1 } });
        let out: Value = serde_json::from_str(&crate::run_json(&req.to_string())).unwrap();
        assert_eq!(out["explain"][0]["tree"]["values"], json!([1, 0]));
        let req = json!({ "exprs": ["a || b"], "trace": { "signals": { "a": [1, 0], "b": [0, 0] } } });
        let out: Value = serde_json::from_str(&crate::run_json(&req.to_string())).unwrap();
        assert_eq!(out["exprs"][0]["values"], json!([1, 0]));
    }
}
