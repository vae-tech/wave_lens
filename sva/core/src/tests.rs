//! Unit tests of the front end through the public API: syntax (precedence, printing, round trips, errors), files
//! (declarations, expansion, clocks, constants, signals, recovery), and JSON (the evaluator has its own tests: engine_tests.rs).
//! The lexer, the preprocessor and the constant evaluator have their own tests next to their code; the corpus
//! (tests/sva/*.sv) runs from tests/corpus.rs.

use super::*;
use serde_json::Value;

/// The tree as JSON without positions: two parses of different text compare equal when the structure is.
fn strip(v: Value) -> Value {
    match v {
        Value::Object(m) => Value::Object(m.into_iter().filter(|(k, _)| k != "at").map(|(k, v)| (k, strip(v))).collect()),
        Value::Array(a) => Value::Array(a.into_iter().map(strip).collect()),
        v => v,
    }
}

fn prop(src: &str) -> Prop {
    parse_prop(src).unwrap_or_else(|e| panic!("{src}: {e}"))
}
/// Printed with the fewest parentheses.
fn p(src: &str) -> String {
    prop(src).to_string()
}
/// Printed with every compound operand in parentheses.
fn full(src: &str) -> String {
    Printer::full().prop(&prop(src))
}
fn ex(src: &str) -> String {
    Printer::full().expr(&parse_expr(src).unwrap_or_else(|e| panic!("{src}: {e}")))
}
/// `line:col msg` of the error of a property expression.
fn perr(src: &str) -> String {
    match parse_prop(src) {
        Ok(p) => panic!("{src}: parsed as {p}"),
        Err(e) => format!("{}:{} {}", e.line, e.col, e.msg),
    }
}
fn eerr(src: &str) -> String {
    match parse_expr(src) {
        Ok(p) => panic!("{src}: parsed as {p}"),
        Err(e) => format!("{}:{} {}", e.line, e.col, e.msg),
    }
}
/// The errors of a file as `line:col msg`.
fn errs(src: &str) -> Vec<String> {
    parse(src).errors.iter().map(|e| format!("{}:{} {}", e.line, e.col, e.msg)).collect()
}
fn warns(src: &str) -> Vec<String> {
    parse(src).warnings.iter().map(|e| format!("{}:{} {}", e.line, e.col, e.msg)).collect()
}
/// The only assertion of a file that must parse without errors.
fn one(src: &str) -> Assertion {
    let p = parse(src);
    assert!(p.errors.is_empty(), "{src}\n{:?}", p.errors);
    assert_eq!(p.assertions.len(), 1, "{src}");
    p.assertions.into_iter().next().unwrap()
}
/// An assertion statement with a clock around `body`.
fn clocked(body: &str) -> String {
    format!("a: assert property (@(posedge clk) {body});")
}
fn labels(a: &Assertion) -> Vec<String> {
    a.elements.iter().map(|e| format!("{} {}", e.id, e.label)).collect()
}
fn sigs(a: &Assertion) -> Vec<String> {
    a.signals
        .iter()
        .map(|s| {
            let mut t = s.name.clone();
            if let Some(w) = s.width {
                t += &format!("[{w}]");
            }
            if let Some(d) = s.declared {
                t += &format!(":{d}");
            }
            t
        })
        .collect()
}

mod syntax {
    use super::*;

    #[test]
    fn expression_precedence() {
        assert_eq!(ex("a || b && c"), "a || (b && c)");
        assert_eq!(ex("a && b || c"), "(a && b) || c");
        assert_eq!(ex("a | b ^ c & d"), "a | (b ^ (c & d))");
        assert_eq!(ex("a ~^ b | c"), "(a ~^ b) | c");
        assert_eq!(ex("a == b < c"), "a == (b < c)");
        assert_eq!(ex("a != b & c"), "(a != b) & c");
        assert_eq!(ex("a < b << c"), "a < (b << c)");
        assert_eq!(ex("a << b + c"), "a << (b + c)");
        assert_eq!(ex("a + b * c"), "a + (b * c)");
        assert_eq!(ex("a * b ** c"), "a * (b ** c)");
        assert_eq!(ex("a - b - c"), "(a - b) - c");
        assert_eq!(ex("a / b % c"), "(a / b) % c");
        assert_eq!(ex("!a && ~b"), "(!a) && (~b)");
        assert_eq!(ex("-a * b"), "(-a) * b");
        assert_eq!(ex("&a | ^b"), "(&a) | (^b)");
        assert_eq!(ex("~&a && ~|b && ^~c"), "((~&a) && (~|b)) && (~^c)");
        assert_eq!(ex("a ? b : c ? d : e"), "a ? b : (c ? d : e)");
        assert_eq!(ex("a || b ? c : d"), "(a || b) ? c : d");
        assert_eq!(ex("a inside {1, [2:3]} && b"), "(a inside {1, [2:3]}) && b");
        assert_eq!(ex("a + 1 inside {2}"), "(a + 1) inside {2}");
        assert_eq!(ex("a === b && c !== d"), "(a === b) && (c !== d)");
        assert_eq!(ex("a >>> 2 >> 1 <<< 3"), "((a >>> 2) >> 1) <<< 3");
    }

    #[test]
    fn fewest_parentheses() {
        let pe = |s: &str| parse_expr(s).unwrap().to_string();
        assert_eq!(pe("(a || b) && c"), "(a || b) && c");
        assert_eq!(pe("a || (b && c)"), "a || b && c");
        assert_eq!(pe("a - (b - c)"), "a - (b - c)");
        assert_eq!(pe("(a - b) - c"), "a - b - c");
        assert_eq!(pe("((a))"), "a");
        assert_eq!(pe("-(-a)"), "-(-a)");
        assert_eq!(pe("~(&a)"), "~(&a)");
        assert_eq!(pe("!!a"), "!!a");
        assert_eq!(pe("!(a == b)"), "!(a == b)");
        assert_eq!(pe("(a ? b : c) ? d : e"), "(a ? b : c) ? d : e");
        assert_eq!(pe("(a + b)[3]"), "(a + b)[3]");
    }

    #[test]
    fn primaries() {
        let pe = |s: &str| parse_expr(s).unwrap().to_string();
        for s in [
            "a[3]", "a[7:0]", "a[i+:4]", "a[i-:4]", "mem[2][3]", "u_dut.u_fifo.count", "gen[0].u.x", "pkg::IDLE", "{a, b[1:0]}", "{4{a}}",
            "{{N{1'b0}}, a}", "$past(a, 2)", "$rose(a)", "$countones(v) == 1", "$isunknown(d)", "8'(a + b)", "8'hFF", "'0", "'1", "4'b10x1",
            "16'sd5", "'hDEAD", "x inside {[0:3], 7}", "$bits(data)", "$clog2(N)", "\\esc[0]",
        ] {
            assert_eq!(pe(s), s.trim_start_matches('\\'), "{s}");
        }
        match parse_expr("4'b10x1").unwrap() {
            Expr::Number { value, unknown, width, base, .. } => assert_eq!((value, unknown, width, base), (0b1001, 0b10, Some(4), 2)),
            e => panic!("{e:?}"),
        }
        match parse_expr("a[7:0]").unwrap() {
            Expr::Select { sel, .. } => assert_eq!(sel, SelKind::Part),
            e => panic!("{e:?}"),
        }
    }

    #[test]
    fn expression_errors() {
        assert_eq!(eerr("a +"), "1:4 expected an expression, found the end of the file");
        assert_eq!(eerr("(a"), "1:3 expected ')', found the end of the file");
        assert_eq!(eerr("a b"), "1:3 expected the end of the text, found 'b'");
        assert_eq!(eerr("$foo(a)"), "1:1 the system function $foo is outside the subset");
        assert_eq!(eerr("$past(a, 1, en)"), "1:1 the gating and clock arguments of $past are outside the subset: $past(x [, n])");
        assert_eq!(eerr("$past(a,, en)"), "1:9 $past with an empty argument is outside the subset");
        assert_eq!(eerr("$rose()"), "1:1 $rose takes 1 argument, got 0");
        assert_eq!(eerr("$stable(a, b)"), "1:1 $stable takes 1 argument, got 2");
        assert_eq!(eerr("$rose(a, @(posedge c))"), "1:10 a clock argument of $rose is outside the subset: the assertion's clock is used");
        assert!(eerr("f(a)").starts_with("1:1 calls inside an expression (f(...)) are outside the subset"));
        assert_eq!(eerr("a ==? b"), "1:3 the operator ==? is outside the subset");
        assert_eq!(eerr("a -> b"), "1:3 the operator -> is outside the subset");
        assert_eq!(eerr("a dist {1:=2}"), "1:3 dist is outside the subset");
        assert_eq!(eerr("'{a}"), "1:1 assignment patterns '{...} are outside the subset");
        assert_eq!(eerr("int'(a)"), "1:1 type casts (int'(...)) are outside the subset");
        assert_eq!(eerr("\"s\""), "1:1 strings are outside the subset (except in action block messages)");
        assert_eq!(eerr("1.5"), "1:1 real numbers are outside the subset");
        assert_eq!(eerr("++a"), "1:1 ++ is outside the subset");
        assert_eq!(eerr("a++"), "1:2 expected the end of the text, found '++'");
        assert_eq!(eerr("a + endproperty"), "1:5 expected an expression, found 'endproperty'");
        assert_eq!(eerr("0'(a)"), "1:1 a size cast needs a positive decimal width: 8'(x)");
        let e = parse_expr("a +").unwrap_err();
        assert_eq!((e.found.as_deref(), e.expected.as_deref()), (Some("the end of the file"), Some("an expression")));
    }

    #[test]
    fn delays() {
        assert_eq!(p("a ##1 b"), "a ##1 b");
        assert_eq!(p("a ##0 b"), "a ##0 b");
        assert_eq!(p("a ##[1:3] b"), "a ##[1:3] b");
        assert_eq!(p("a ##[2:$] b"), "a ##[2:$] b");
        assert_eq!(p("a ##[*] b"), "a ##[0:$] b");
        assert_eq!(p("a ##[+] b"), "a ##[1:$] b");
        assert_eq!(p("##2 a"), "##2 a");
        assert_eq!(p("a ##N b"), "a ##N b");
        assert_eq!(p("a ##(N+1) b"), "a ##(N + 1) b");
        assert_eq!(p("a ##[1:N] b"), "a ##[1:N] b");
        assert_eq!(full("a ##1 b ##2 c"), "(a ##1 b) ##2 c");
        assert_eq!(full("##1 a ##1 b"), "(##1 a) ##1 b");
        assert_eq!(full("a ##1 (b ##1 c)"), "a ##1 (b ##1 c)");
        let Prop::Seq { seq: Seq::Delay { range, lhs, .. } } = prop("a ##[1:3] b") else { panic!() };
        assert_eq!((range, lhs.is_some()), (Range::new(1, Some(3)), true));
        let Prop::Seq { seq: Seq::Delay { range, .. } } = prop("a ##[+] b") else { panic!() };
        assert_eq!(range, Range::new(1, None));
    }

    #[test]
    fn repetitions() {
        assert_eq!(p("a[*3]"), "a[*3]");
        assert_eq!(p("a [*1:3]"), "a[*1:3]");
        assert_eq!(p("a[*2:$]"), "a[*2:$]");
        assert_eq!(p("a[*]"), "a[*0:$]");
        assert_eq!(p("a[+]"), "a[*1:$]");
        assert_eq!(p("a[->2]"), "a[->2]");
        assert_eq!(p("a[->1:3]"), "a[->1:3]");
        assert_eq!(p("a[=1:$]"), "a[=1:$]");
        assert_eq!(p("a[*N]"), "a[*N]");
        assert_eq!(p("(a ##1 b)[*2]"), "(a ##1 b)[*2]");
        assert_eq!(p("(a && b)[*2]"), "(a && b)[*2]");
        assert_eq!(p("a && b[*2]"), "(a && b)[*2]"); // the repetition takes the whole boolean
        assert_eq!(full("a ##1 b[*2] ##1 c"), "(a ##1 (b[*2])) ##1 c");
        let Prop::Seq { seq: Seq::Repeat { op, range, .. } } = prop("a[->2]") else { panic!() };
        assert_eq!((op, range), (RepOp::Goto, Range::single(2)));
    }

    #[test]
    fn sequence_operators() {
        assert_eq!(full("a and b or c"), "(a and b) or c");
        assert_eq!(full("a or b and c"), "a or (b and c)");
        assert_eq!(full("a intersect b and c"), "(a intersect b) and c");
        assert_eq!(full("a within b intersect c"), "(a within b) intersect c");
        assert_eq!(full("a within b within c"), "(a within b) within c");
        assert_eq!(full("a throughout b ##1 c"), "a throughout (b ##1 c)");
        assert_eq!(full("a ##1 b within c"), "(a ##1 b) within c");
        assert_eq!(full("en throughout a ##1 b within c"), "(en throughout (a ##1 b)) within c");
        assert_eq!(full("x throughout y throughout s"), "x throughout (y throughout s)");
        assert_eq!(p("first_match(a ##[1:3] b)"), "first_match(a ##[1:3] b)");
        assert_eq!(p("first_match(a ##[1:3] b) ##1 c"), "first_match(a ##[1:3] b) ##1 c");
        assert!(matches!(prop("a and b"), Prop::Seq { seq: Seq::Binary { op: SeqOp::And, .. } }));
        assert!(matches!(prop("(a ##1 b) or c"), Prop::Seq { seq: Seq::Binary { op: SeqOp::Or, .. } }));
    }

    #[test]
    fn property_operators() {
        assert_eq!(full("a |-> b |-> c"), "a |-> (b |-> c)");
        assert_eq!(full("a and b |-> c"), "(a and b) |-> c");
        assert_eq!(full("a |-> b and c"), "a |-> (b and c)");
        assert_eq!(full("a ##1 b |=> c ##1 d"), "(a ##1 b) |=> (c ##1 d)");
        assert_eq!(full("not a and b"), "(not a) and b");
        assert_eq!(full("not a ##1 b"), "not (a ##1 b)");
        assert_eq!(full("not not a"), "not (not a)");
        assert_eq!(full("nexttime a or b"), "(nexttime a) or b");
        assert_eq!(p("nexttime [2] a"), "nexttime [2] a");
        assert_eq!(p("s_nexttime a"), "s_nexttime a");
        assert_eq!(full("always a |-> b"), "always (a |-> b)");
        assert_eq!(full("a |-> always b"), "a |-> (always b)");
        assert_eq!(p("always [2:5] a"), "always [2:5] a");
        assert_eq!(p("s_always [0:3] a"), "s_always [0:3] a");
        assert_eq!(p("eventually [1:4] a"), "eventually [1:4] a");
        assert_eq!(p("s_eventually a"), "s_eventually a");
        assert_eq!(p("s_eventually [1:$] a"), "s_eventually [1:$] a");
        assert_eq!(full("if (c) a |-> b else d"), "if (c) (a |-> b) else d");
        assert_eq!(full("if (c) a"), "if (c) a");
        assert_eq!(p("a #-# b"), "a #-# b");
        assert_eq!(p("a #=# b ##1 c"), "a #=# b ##1 c");
        assert_eq!(p("(a |-> b) and (c |=> d)"), "(a |-> b) and (c |=> d)");
        assert!(matches!(prop("a and (b |-> c)"), Prop::Binary { op: PropOp::And, .. }));
        assert!(matches!(prop("(a |-> b) or c"), Prop::Binary { op: PropOp::Or, .. }));
        // the dangling else goes with the nearest if
        let Prop::If { then, else_, .. } = prop("if (a) if (b) p else q") else { panic!() };
        assert!(else_.is_none());
        assert!(matches!(*then, Prop::If { else_: Some(_), .. }));
    }

    #[test]
    fn parentheses_are_read_as_what_they_hold() {
        assert!(matches!(prop("(a || b) ##1 c"), Prop::Seq { seq: Seq::Delay { lhs: Some(l), .. } } if matches!(*l, Seq::Bool { .. })));
        assert!(matches!(prop("(a ##1 b) |-> c"), Prop::Implies { .. }));
        assert!(matches!(prop("((a)) ##1 b"), Prop::Seq { seq: Seq::Delay { .. } }));
        assert!(matches!(prop("(a |-> b)"), Prop::Implies { .. }));
        assert_eq!(p("((a ##1 b) or c) |=> d"), "(a ##1 b) or c |=> d");
        assert_eq!(p("(a ##1 b)[*2] ##1 c"), "(a ##1 b)[*2] ##1 c");
        assert_eq!(p("((a ##1 (b)))"), "a ##1 b");
    }

    #[test]
    fn instances() {
        let Prop::Seq { seq: Seq::Instance { name, args, body, .. } } = prop("s(a, b ##1 c)") else { panic!() };
        assert_eq!((name.as_str(), args.len(), body.is_none()), ("s", 2, true));
        assert!(matches!(args[1].value, Some(Prop::Seq { seq: Seq::Delay { .. } })));
        assert_eq!(p("p(.a(x), .b())"), "p(.a(x), .b())");
        assert_eq!(p("s(a, , c)"), "s(a, , c)");
        assert_eq!(p("p()"), "p");
        assert_eq!(p("s(a) ##1 t(b) |-> q(c |-> d)"), "s(a) ##1 t(b) |-> q(c |-> d)");
    }

    #[test]
    fn round_trips() {
        for s in [
            "req |-> ##[1:3] ack",
            "a ##1 b ##2 c",
            "a ##1 (b ##2 c)",
            "##[0:$] a ##1 b",
            "a[*2:5] ##1 b[->1] ##1 c[=2]",
            "(a ##1 b)[*1:$] intersect c[*5]",
            "en throughout (a ##[1:4] b)",
            "(a ##1 b) within (c ##[2:6] d)",
            "first_match(a ##[1:$] b) |=> c",
            "a and b or c and d",
            "(a or b) and (c or d)",
            "not (a ##1 b)",
            "not a and not b",
            "(a |-> b) and (c |-> d)",
            "a |-> b |-> c",
            "(a |-> b) or c",
            "always (a |-> s_eventually b)",
            "if (m) a |-> b else c |=> d",
            "if (a) (if (b) c) else d",
            "nexttime [3] (a |-> b)",
            "s_always [1:4] a and b",
            "eventually [0:2] (a or b)",
            "a #-# b ##1 c",
            "$rose(a) && !b ##1 $fell(c) || d",
            "a ? b : c ##1 d",
            "x inside {[0:3], 9} |-> y[7:4] == 4'hF",
            "s1(a, .b(c ##1 d)) or p1(e)",
            "{a, b} == 2'b01 ##[1:N] (c && $past(d, 2))",
            "(a ##[*] b)[*0:1] ##0 c",
            "a ##(N + 1) b",
            "(a[*2])[*3]",
        ] {
            let a = prop(s);
            let text = a.to_string();
            let b = prop(&text);
            assert_eq!(b.to_string(), text, "{s}");
            assert_eq!(strip(serde_json::to_value(&a).unwrap()), strip(serde_json::to_value(&b).unwrap()), "{s} -> {text}");
            let f = Printer::full().prop(&a); // the fully parenthesised text reads back the same
            assert_eq!(strip(serde_json::to_value(prop(&f)).unwrap()), strip(serde_json::to_value(&a).unwrap()), "{s} -> {f}");
        }
    }

    #[test]
    fn positions_of_nodes() {
        let a = prop("a ##[1:3]  bb");
        let Prop::Seq { seq: Seq::Delay { rhs, at, .. } } = a else { panic!() };
        assert_eq!((at.col, at.start, at.end), (1, 0, 13));
        assert_eq!((rhs.at().col, rhs.at().start, rhs.at().end), (12, 11, 13));
    }

    #[test]
    fn sequence_errors() {
        assert_eq!(perr("a ##[3:1] b"), "1:8 the range ends before it starts (3:1)");
        assert_eq!(perr("a[*3:1]"), "1:6 the range ends before it starts (3:1)");
        assert_eq!(perr("a ##[1] b"), "1:7 expected ':', found ']'");
        assert_eq!(perr("a ##[$:3] b"), "1:6 '$' is only allowed as the end of a range");
        assert_eq!(perr("a ##"), "1:5 expected a delay after '##': a number, [m:n], [*] or [+], found the end of the file");
        assert_eq!(perr("a ##1"), "1:6 expected an expression, found the end of the file");
        assert_eq!(perr("a ##1 b throughout c"), "1:1 the left side of throughout must be a boolean expression");
        assert_eq!(perr("(a ##1 b)[->2]"), "1:10 goto [->n] and non-consecutive [=n] repetitions need a boolean, found a sequence");
        assert_eq!(perr("(a ##1 b)[=2]"), "1:10 goto [->n] and non-consecutive [=n] repetitions need a boolean, found a sequence");
        assert_eq!(perr("a[*2][*3]"), "1:6 a repetition of a repetition needs parentheses: (a[*2])[*3]");
        assert_eq!(perr("(not a) ##1 b"), "1:2 ## needs a sequence, found a property");
        assert_eq!(perr("a intersect (b |-> c)"), "1:14 intersect needs a sequence, found a property");
        assert_eq!(perr("(a |-> b) within c"), "1:2 within needs a sequence, found a property");
        assert_eq!(perr("first_match(a |-> b)"), "1:13 first_match needs a sequence, found a property");
        assert_eq!(perr("(a, v = b)"), "1:3 sequence match items (local variables) are outside the subset");
        assert_eq!(perr("a ##1 @(posedge c) b"), "1:7 a clock inside a property (multi-clock) is outside the subset");
        assert_eq!(perr("(a ##1 )"), "1:8 expected an expression, found ')'");
        assert_eq!(perr("a ##4'bx b"), "1:5 a delay cannot have x / z bits");
        assert_eq!(perr("s(.a(x), y)"), "1:10 a positional argument after a named one");
    }

    #[test]
    fn property_errors() {
        assert_eq!(perr("(a |-> b) |-> c"), "1:11 the left side of |-> must be a sequence, found a property");
        assert_eq!(perr("not a |=> b"), "1:7 the left side of |=> must be a sequence, found a property");
        assert_eq!(perr("a |->"), "1:6 expected an expression, found the end of the file");
        assert_eq!(perr("a until b"), "1:3 until is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("a s_until_with b"), "1:3 s_until_with is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("a implies b"), "1:3 implies is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("a iff b"), "1:3 iff (property equivalence) is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("accept_on (r) a"), "1:1 accept_on is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("a |-> strong(b ##1 c)"), "1:7 strong(...) is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("case (x) 1: a; endcase"), "1:1 case in properties is outside the subset (docs/sva/LANGUAGE.md)");
        assert_eq!(perr("s_always a"), "1:10 s_always needs a range: s_always [m:n] p");
        assert_eq!(perr("eventually a"), "1:12 eventually needs a range: eventually [m:n] p");
        assert_eq!(perr("s_always [1:$] a"), "1:10 the range of s_always must be bounded");
        assert_eq!(perr("always [3:2] a"), "1:11 the range ends before it starts (3:2)");
        assert_eq!(perr("if a b"), "1:4 expected '(', found 'a'");
        assert_eq!(perr("nexttime [$] a"), "1:11 '$' is only allowed as the end of a range");
    }
}

mod files {
    use super::*;

    const SPIKE: &str = "property p_req_ack; @(posedge clk) disable iff (!rst_n) req |-> ##[1:3] ack; endproperty\n\
                         a_req_ack: assert property (p_req_ack);";

    #[test]
    fn the_spike_property() {
        let a = one(SPIKE);
        assert_eq!((a.label.as_str(), a.kind, a.property.as_deref(), a.line), ("a_req_ack", Kind::Assert, Some("p_req_ack"), 2));
        assert_eq!(a.clock, Clock { edge: "posedge".into(), signal: "clk".into() });
        assert_eq!(a.disable.as_ref().map(|d| d.to_string()).as_deref(), Some("!rst_n"));
        assert_eq!(labels(&a), ["s1 req", "s2 ##[1:3] ack"]);
        assert_eq!(sigs(&a), ["clk", "rst_n", "req", "ack"]);
        assert_eq!(a.prop.to_string(), "p_req_ack");
        assert_eq!(Printer { full: false, inline: true }.prop(&a.prop), "(req |-> ##[1:3] ack)");
        assert_eq!(a.element("s2").unwrap().at.line, 1);
    }

    #[test]
    fn labels_messages_kinds() {
        let p = parse(
            "assert property (@(posedge c) a) else $error(\"m1 %0d\", x);\n\
             assert property (@(posedge c) a) else $fatal(1, \"m2\");\n\
             assert property (@(posedge c) a) else begin $warning(\"m3\"); n++; end\n\
             cover property (@(posedge c) a) $display(\"hit\");\n\
             assert property (@(posedge c) a) $info(\"ok\"); else $error(\"bad\");\n\
             assume property (@(posedge c) a);\n\
             l7: cover sequence (@(posedge c) a ##1 b);\n\
             assert property (@(posedge c) a) else $error;\n\
             assert property (@(posedge c) a) else ;",
        );
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        let m: Vec<_> = p.assertions.iter().map(|a| (a.label.as_str(), a.kind, a.severity.as_deref(), a.message.as_deref())).collect();
        assert_eq!(
            m,
            [
                ("assert_1", Kind::Assert, Some("error"), Some("m1 %0d")),
                ("assert_2", Kind::Assert, Some("fatal"), Some("m2")),
                ("assert_3", Kind::Assert, Some("warning"), Some("m3")),
                ("cover_4", Kind::Cover, Some("info"), Some("hit")),
                ("assert_5", Kind::Assert, Some("error"), Some("bad")),
                ("assume_6", Kind::Assume, None, None),
                ("l7", Kind::Cover, None, None),
                ("assert_8", Kind::Assert, Some("error"), None),
                ("assert_9", Kind::Assert, None, None),
            ]
        );
        assert_eq!(p.assertions[5].flags, ["assume: checked like an assertion"]);
        assert_eq!(p.assertions[6].flags, ["cover sequence: every match counts"]);
    }

    #[test]
    fn statements_outside_the_subset() {
        assert_eq!(errs("assert (a);"), ["1:1 immediate assertions (assert (expr)) are outside the subset: use assert property (...)"]);
        assert_eq!(errs("assert final (a);"), ["1:1 immediate assertions (assert (expr)) are outside the subset: use assert property (...)"]);
        assert_eq!(errs("expect (@(posedge c) a);"), ["1:1 expect statements are outside the subset"]);
        assert_eq!(errs("cover sequence (@(posedge c) a |-> b);"), ["1:30 cover sequence needs a sequence, found a property"]);
        assert_eq!(warns("restrict property (@(posedge c) a);"), ["1:1 restrict property is skipped: it only constrains formal tools"]);
        assert!(parse("restrict property (@(posedge c) a);").assertions.is_empty());
        assert_eq!(errs("module m; always @(posedge c) begin assert property (a); end endmodule"), ["1:37 assert property inside a procedural block or generate is outside the subset: write it at module level"]);
        assert_eq!(errs("assrt property (@(posedge c) a);"), ["1:1 expected a declaration or an assertion, found 'assrt'"]);
    }

    #[test]
    fn clocks() {
        assert_eq!(one(&clocked("a")).clock.to_string(), "@(posedge clk)");
        assert_eq!(one("a: assert property (@(negedge ck) a);").clock.edge, "negedge");
        assert_eq!(one("a: assert property (@(edge ck) a);").clock.edge, "edge");
        assert_eq!(one("a: assert property (@(ck) a);").clock, Clock { edge: "edge".into(), signal: "ck".into() });
        assert_eq!(one("a: assert property (@(posedge u.ck) a);").clock.signal, "u.ck");
        // from the declaration, from a sequence, from a default clocking (anonymous, named, by reference)
        assert_eq!(one("property p; @(posedge k) a; endproperty a: assert property (p);").clock.signal, "k");
        assert_eq!(one("sequence s; @(negedge k) a ##1 b; endsequence a: assert property (s);").clock.edge, "negedge");
        assert_eq!(one("module m; default clocking @(posedge k); endclocking a: assert property (x); endmodule").clock.signal, "k");
        assert_eq!(one("module m; default clocking cb @(posedge k); input x; endclocking a: assert property (x); endmodule").clock.signal, "k");
        assert_eq!(one("module m; clocking cb @(negedge k); endclocking default clocking cb; a: assert property (x); endmodule").clock.edge, "negedge");
        assert_eq!(one("module m; clocking cb @(negedge k); endclocking a: assert property (@cb x); endmodule").clock.edge, "negedge");
        assert_eq!(one("module m; clocking cb @(posedge k); endclocking a: assert property (@(cb) x); endmodule").clock.signal, "k");
        // the default of an outer scope reaches an inner one; the assertion's own clock wins
        assert_eq!(one("default clocking @(posedge k); endclocking module m; a: assert property (@(posedge j) x); endmodule").clock.signal, "j");
    }

    #[test]
    fn clock_errors() {
        assert_eq!(errs("a: assert property (x);"), ["1:1 the assertion has no clock: write @(posedge clk) or declare a default clocking"]);
        assert_eq!(errs("property p; @(posedge k) x; endproperty a: assert property (@(posedge j) p);"), ["1:74 multi-clock: 'p' is clocked by @(posedge k), the assertion by @(posedge j)"]);
        assert_eq!(errs(&clocked("a").replace("posedge clk", "posedge clk iff en")), ["1:35 @(... iff ...) clock gating is outside the subset"]);
        assert_eq!(errs(&clocked("a").replace("posedge clk", "posedge clk or negedge r")), ["1:35 clock events with several signals are outside the subset"]);
        assert_eq!(errs("a: assert property (disable iff (r) @(posedge c) a);"), ["1:37 the clock goes before disable iff: @(posedge clk) disable iff (...) ..."]);
        assert_eq!(errs("a: assert property (@(posedge) a);"), ["1:30 expected a clock signal, found ')'"]);
        assert_eq!(errs("module m; default clocking cb; endmodule"), ["1:28 no clocking block 'cb'"]);
    }

    #[test]
    fn disable_iff() {
        assert_eq!(one(&clocked("disable iff (r) a")).disable.unwrap().to_string(), "r");
        let a = one("module m; default disable iff (!rst_n); a: assert property (@(posedge c) x); endmodule");
        assert_eq!(a.disable.unwrap().to_string(), "!rst_n");
        let a = one("module m; default disable iff (!rst_n); a: assert property (@(posedge c) disable iff (kill) x); endmodule");
        assert_eq!(a.disable.unwrap().to_string(), "kill");
        let a = one("property p(r); @(posedge c) disable iff (r) x; endproperty a: assert property (p(rst));");
        assert_eq!(a.disable.unwrap().to_string(), "rst");
        assert_eq!(errs("property p; @(posedge c) disable iff (r) x; endproperty a: assert property (disable iff (k) p);"), ["1:90 disable iff is given twice: in the assertion and in the property"]);
        assert_eq!(errs("property p; disable iff (r) x; endproperty a: assert property (@(posedge c) p and y);"), ["1:77 the property 'p' has disable iff: that is allowed only when it is the whole assertion"]);
        assert_eq!(errs("sequence s; disable iff (r) x; endsequence"), ["1:26 disable iff belongs to a property, not to a sequence"]);
    }

    #[test]
    fn instances_and_arguments() {
        let decls = "sequence s_hs(v, r); v ##[0:$] r; endsequence\n\
                     property p_two(a, b = 1'b1, int n = 2); a |-> ##n b; endproperty\n";
        let a = one(&format!("{decls}{}", clocked("p_two(x, y, 3)")));
        assert_eq!(labels(&a), ["s1 x", "s2 ##3 y"]);
        let a = one(&format!("{decls}{}", clocked("p_two(.b(y), .a(x))")));
        assert_eq!(labels(&a), ["s1 x", "s2 ##2 y"]);
        let a = one(&format!("{decls}{}", clocked("p_two(x)")));
        assert_eq!(labels(&a), ["s1 x", "s2 ##2 1'b1"]);
        let a = one(&format!("{decls}{}", clocked("s_hs(req, ack) |=> s_hs(ack, done)")));
        assert_eq!(labels(&a), ["s1 req", "s2 ##[0:$] ack", "s3 ack", "s4 ##[0:$] done"]);
        assert_eq!(a.prop.to_string(), "s_hs(req, ack) |=> s_hs(ack, done)");
        // a sequence and a property as actual arguments
        let a = one(&format!("sequence s(x); x; endsequence property q(p, sequence t); t |-> p; endproperty {}", clocked("q(c |-> d, s(e) ##1 f)")));
        assert_eq!(Printer { full: false, inline: true }.prop(&a.prop), "((e) ##1 f |-> c |-> d)");
        assert_eq!(labels(&a), ["s1 e", "s2 ##1 f", "s3 c", "s4 d"]);
        // a formal without a type takes the type of the previous one
        let p = parse("property p(int a, b); x; endproperty");
        assert_eq!(p.properties[0].ports.iter().map(|p| p.ty.as_str()).collect::<Vec<_>>(), ["int", "int"]);
        // a declaration may come after its use
        assert_eq!(labels(&one(&format!("{}\nsequence later; q ##1 r; endsequence", clocked("later")))), ["s1 q", "s2 ##1 r"]);
        // a sequence instance with a repetition and inside a delay
        let a = one(&format!("sequence s; a ##1 b; endsequence {}", clocked("x ##1 s[*2] ##1 y")));
        assert_eq!(labels(&a), ["s1 x", "s2 a", "s3 ##1 b", "s4 ##1 y"]);
    }

    #[test]
    fn argument_errors() {
        let d = "property p(a, b); a |-> b; endproperty\nsequence s(sequence x, logic y); x ##1 y; endsequence\n";
        let e = |body: &str| errs(&format!("{d}{}", clocked(body)));
        assert_eq!(e("p(x)"), ["3:36 the argument 'b' of 'p' is missing"]);
        assert_eq!(e("p(x, y, z)"), ["3:36 too many arguments: 'p' takes 2"]);
        assert_eq!(e("p(.a(x), .c(y))"), ["3:36 'p' has no argument 'c'"]);
        assert_eq!(e("p(x, .a(y))"), ["3:36 the argument 'a' of 'p' is given twice"]);
        assert_eq!(e("s(x |-> y, z)"), ["3:36 the argument 'x' of 's' must be a sequence"]);
        assert_eq!(e("s(x, y ##1 z)"), ["3:36 the argument 'y' of 's' (logic) must be an expression"]);
        assert_eq!(e("q(x)"), ["3:36 no sequence or property 'q'"]);
        assert_eq!(e("s(p(a, b), c)"), ["3:36 the argument 'x' of 's' must be a sequence"]);
        assert_eq!(e("s(x, y) ##1 s(p, z)"), ["3:50 the argument 'a' of 'p' is missing"]);
        assert_eq!(e("x ##1 p(a, b)"), ["3:42 the property 'p' is used where a sequence is needed"]);
        assert_eq!(e("x && s"), ["3:41 the sequence or property 's' is used inside an expression"]);
        assert_eq!(e("s.triggered"), ["3:36 .triggered is outside the subset"]);
        assert_eq!(e("p(, y)"), ["1:19 the argument 'a' is empty (in assertion 'a', line 3)"]);
        assert_eq!(errs(&format!("property r; r; endproperty {}", clocked("r"))), ["1:13 the property 'r' instantiates itself: recursion is outside the subset (in assertion 'a', line 1)"]);
        assert_eq!(errs(&format!("sequence t; a ##1 t; endsequence {}", clocked("t"))), ["1:19 the sequence 't' instantiates itself: recursion is outside the subset (in assertion 'a', line 1)"]);
        assert_eq!(errs(&format!("property u(x); x |-> b; endproperty {}", clocked("u(a ##1 b |-> c)"))), ["1:16 the argument 'x' is a property, used here as a sequence (in assertion 'a', line 1)"]);
        assert_eq!(errs(&format!("property u(x); x && b; endproperty {}", clocked("u(a ##1 b)"))), ["1:16 the argument 'x' is a sequence or a property, used here in an expression (in assertion 'a', line 1)"]);
    }

    #[test]
    fn broken_declarations_are_named() {
        let p = parse("property p; @(posedge c) a |-> ; endproperty\na: assert property (p);\nproperty q; @(posedge c) x; endproperty\nb: assert property (q);");
        let e: Vec<_> = p.errors.iter().map(|e| format!("{}:{} {}", e.line, e.col, e.msg)).collect();
        assert_eq!(e, ["1:32 expected an expression, found ';'", "2:21 'p' did not parse (line 1)"]);
        assert_eq!(p.assertions.len(), 1);
        assert_eq!(p.assertions[0].label, "b");
    }

    #[test]
    fn constants() {
        let a = one(&format!("localparam int N = 3, M = N * 2;\nparameter W = $clog2(16);\n{}", clocked("a ##N b ##[1:M] c[*W] ##(N - 1) d")));
        assert_eq!(labels(&a), ["s1 a", "s2 ##3 b", "s3 ##[1:6] c[*4]", "s4 ##2 d"]);
        let a = one(&format!("localparam logic [1:0] MID = 2'(5);\nlocalparam X = 4'hA;\n{}", clocked("v == MID && w == X")));
        let Prop::Seq { seq: Seq::Bool { expr: Expr::Binary { a: x, .. }, .. } } = &a.prop else { panic!() };
        let Expr::Binary { b: mid, .. } = &**x else { panic!() };
        assert!(matches!(**mid, Expr::Const { value: 1, width: Some(2), .. }), "{mid:?}");
        assert_eq!(sigs(&a), ["clk", "v", "w"]); // constants are not signals
        // module header parameters, size casts, a truncated value
        let a = one(&format!("module m #(parameter int BIT = 4, W = 8) (input logic clk); localparam logic [1:0] LAST = 2'(BIT - 1); {} endmodule", clocked("##LAST x ##W y")));
        assert_eq!(labels(&a), ["s1 ##3 x", "s2 ##8 y"]);
        let p = parse("module m #(parameter int BIT = 4, W = 8) (); endmodule");
        assert_eq!(p.scopes[0].params, [Param { name: "BIT".into(), value: Some(4) }, Param { name: "W".into(), value: Some(8) }]);
    }

    #[test]
    fn enums_and_packages() {
        let pkg = "package p; localparam int W = 8; typedef enum logic [2:0] {IDLE, RUN = 4, DONE} st_t; sequence s_p; go ##1 run; endsequence endpackage\n";
        let a = one(&format!("{pkg}module m import p::*; (input st_t st); {} endmodule", clocked("st == IDLE ##1 st == DONE ##1 s_p")));
        let consts: Vec<String> = a.prop.to_string().split(' ').map(String::from).collect();
        assert!(consts.contains(&"DONE".to_string()));
        assert_eq!(sigs(&a), ["clk", "st:3", "go", "run"]);
        let Prop::Seq { seq: Seq::Delay { lhs: Some(l), .. } } = &a.prop else { panic!() };
        let Seq::Delay { rhs, .. } = &**l else { panic!() };
        assert!(matches!(rhs.as_bool(), Some(Expr::Binary { b, .. }) if matches!(**b, Expr::Const { value: 5, .. })));
        // pkg::NAME without an import, a named import
        assert_eq!(labels(&one(&format!("{pkg}{}", clocked("x ##p::W y")))), ["s1 x", "s2 ##8 y"]);
        assert_eq!(labels(&one(&format!("{pkg}module m; import p::W; {} endmodule", clocked("x ##W y")))), ["s1 x", "s2 ##8 y"]);
        assert_eq!(errs(&format!("{pkg}module m; import p::NOPE; endmodule")), ["2:18 package 'p' has no 'NOPE'"]);
        assert_eq!(errs(&format!("{pkg}{}", clocked("x == p::NOPE"))), ["2:41 package 'p' has no constant 'NOPE'"]);
        assert_eq!(errs(&clocked("x == q::A")), ["1:41 unknown package 'q': give its file to sva parse first"]);
        assert_eq!(warns("module m; import q::*; endmodule"), ["1:18 package 'q' is not loaded: its names are read as signals (give its file to sva parse first)"]);
        assert_eq!(errs("typedef enum {A, B[2]} t;"), ["1:19 enum label ranges (A[3]) are outside the subset"]);
    }

    #[test]
    fn constant_errors() {
        assert_eq!(errs(&format!("localparam N = q + 1;\n{}", clocked("##N x"))), ["2:38 the constant 'N' has no value: 'q' is not a constant"]);
        assert_eq!(errs(&clocked("a ##n b")), ["1:40 a delay or repetition count must be a constant: 'n' is not a constant"]);
        assert_eq!(errs(&format!("localparam N = 1;\n{}", clocked("a ##[N:N-2] b"))), ["2:43 a delay or repetition count must not be negative, got -1"]);
        assert_eq!(errs(&format!("localparam N = 3;\n{}", clocked("a ##[N:2] b"))), ["2:41 the range ends before it starts (3:2)"]);
        assert_eq!(errs(&clocked("$past(a, 0)")), ["1:45 the depth of $past must be at least 1, got 0"]);
        assert_eq!(errs(&clocked("$past(a, b)")), ["1:45 the depth of $past must be a constant: 'b' is not a constant"]);
        assert_eq!(errs(&clocked("{n{a}} == 0")), ["1:37 a replication count must be a constant: 'n' is not a constant"]);
    }

    #[test]
    fn signals_and_widths() {
        let a = one(&clocked("disable iff (!r) a[3] && a[1:0] == 2 ##1 b[4+:4] ##1 c[7-:2] != d[i] ##1 u.v.w && m[2][1]"));
        assert_eq!(sigs(&a), ["clk", "r", "a[4]", "b[8]", "c[8]", "d", "i", "u.v.w", "m[3]"]);
        let a = one("module m(input logic clk, input logic [7:0] data, input bit [3:0][1:0] pk, output st); wire [15:0] w16; logic x, y; int n;\n\
                     a: assert property (@(posedge clk) data[3] && pk == 0 ##1 w16 > n ##1 x || y || st || ext);\nendmodule");
        assert_eq!(sigs(&a), ["clk:1", "data[4]:8", "pk:8", "w16:16", "n:32", "x:1", "y:1", "st:1", "ext"]);
        // non-ANSI ports: widths from the declarations inside
        let a = one("module m(clk, d); input clk; input [3:0] d; a: assert property (@(posedge clk) d == 0); endmodule");
        assert_eq!(sigs(&a), ["clk:1", "d:4"]);
        assert_eq!(parse("module m(clk, d); input clk; input [3:0] d; endmodule").scopes[0].ports, [Net { name: "clk".into(), width: None }, Net { name: "d".into(), width: None }]);
        // sampled value functions and inside sets read signals too
        let a = one(&clocked("$rose(a) ##1 $past(b[2], 2) ##1 c inside {d, [e:f]}"));
        assert_eq!(sigs(&a), ["clk", "a", "b[3]", "c", "d", "e", "f"]);
    }

    #[test]
    fn element_ids_are_per_assertion() {
        let p = parse(&format!("sequence s(x); x ##1 y; endsequence\n{}\nb: assert property (@(posedge clk) s(p) and s(q) and (en throughout z[->2]));", clocked("a |-> b")));
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        assert_eq!(labels(&p.assertions[0]), ["s1 a", "s2 b"]);
        assert_eq!(labels(&p.assertions[1]), ["s1 p", "s2 ##1 y", "s3 q", "s4 ##1 y", "s5 en", "s6 z[->2]"]);
        let a = one(&clocked("a ##1 (b ##1 c) ##[1:2] (d && e)[*2] ##1 (f or g) ##1 first_match(h)"));
        assert_eq!(labels(&a), ["s1 a", "s2 b", "s3 ##1 c", "s4 ##[1:2] (d && e)[*2]", "s5 f", "s6 g", "s7 h"]);
        let a = one(&clocked("if (m) a |-> b else not c"));
        assert_eq!(labels(&a), ["s1 a", "s2 b", "s3 c"]);
        let ids: Vec<_> = a.elements.iter().map(|e| e.id.clone()).collect();
        let mut seen = std::collections::HashSet::new();
        assert!(ids.iter().all(|i| seen.insert(i.clone())));
    }

    #[test]
    fn scopes_and_bind() {
        let p = parse(
            "interface bus_if(input logic clk); logic v, r; a1: assert property (@(posedge clk) v |-> r); endinterface\n\
             checker ck(logic clk, sequence s); a2: assert property (@(posedge clk) s); endchecker\n\
             program pg; a3: assert property (@(posedge k) x); endprogram\n\
             module dut(input logic clk, bus_if.slave bus); a4: assert property (@(posedge clk) y); endmodule : dut\n\
             bind dut: u1, u2 dut_sva #(.N(2)) u_sva (.clk(clk), .req(bus.v), .*);\n\
             bind top.u_dut checker_m chk (clk, x[0]);",
        );
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        let s: Vec<_> = p.assertions.iter().map(|a| (a.label.as_str(), a.scope.as_deref())).collect();
        assert_eq!(s, [("a1", Some("bus_if")), ("a2", Some("ck")), ("a3", Some("pg")), ("a4", Some("dut"))]);
        let k: Vec<_> = p.scopes.iter().map(|s| (s.kind.as_str(), s.name.as_str(), s.ports.len())).collect();
        assert_eq!(k, [("interface", "bus_if", 1), ("checker", "ck", 2), ("program", "pg", 0), ("module", "dut", 2)]);
        assert_eq!(p.binds.len(), 2);
        let b = &p.binds[0];
        assert_eq!((b.target.as_str(), b.instances.clone(), b.module.as_str(), b.instance.as_str()), ("dut", vec!["u1".to_string(), "u2".into()], "dut_sva", "u_sva"));
        assert_eq!(b.ports, [BindPort { name: Some("clk".into()), expr: "clk".into() }, BindPort { name: Some("req".into()), expr: "bus.v".into() }, BindPort { name: Some("*".into()), expr: "".into() }]);
        assert_eq!(p.binds[1].target, "top.u_dut");
        assert_eq!(p.binds[1].ports[1], BindPort { name: None, expr: "x[0]".into() });
    }

    #[test]
    fn module_code_is_skipped() {
        let src = "module m import q::*; #(parameter N = 2) (input logic clk, rst_n, output logic [1:0] st);\n\
                   typedef struct packed { logic a; logic [3:0] b; } s_t;\n\
                   s_t sv; real r = 1.5; string s = \"x\";\n\
                   always_ff @(posedge clk or negedge rst_n)\n  if (!rst_n) begin st <= 0; end else begin\n    case (st) 0: st <= 1; default: st <= 0; endcase\n  end\n\
                   assign w = {4{1'b1}};\n\
                   function automatic int f(input int x); return x + 1; endfunction\n\
                   task t; @(posedge clk); wait fork; endtask\n\
                   sub u_sub (.*);\n\
                   generate for (genvar i = 0; i < N; i++) begin : g end endgenerate\n\
                   initial begin #10; $display(\"%0t\", $time); end\n\
                   a: assert property (@(posedge clk) disable iff (!rst_n) st != 3);\n\
                   endmodule";
        let p = parse(src);
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        assert_eq!(p.assertions.len(), 1);
        assert_eq!(sigs(&p.assertions[0]), ["clk:1", "rst_n:1", "st:2"]);
    }

    #[test]
    fn recovery() {
        let src = "property p1; @(posedge c) a ##[3:1] b; endproperty\n\
                   property p2; @(posedge c) a |-> b; endproperty\n\
                   a1: assert property (@(posedge c) a |-> ) else $error(\"x\");\n\
                   a2: assert property (p2);\n\
                   endproperty\n\
                   a3: assert property (@(posedge c) a ##1 b);";
        let p = parse(src);
        let e: Vec<_> = p.errors.iter().map(|e| format!("{}:{} {}", e.line, e.col, e.msg)).collect();
        assert_eq!(e, ["1:34 the range ends before it starts (3:1)", "3:41 expected an expression, found ')'", "5:1 'endproperty' without its opening"]);
        assert_eq!(p.assertions.iter().map(|a| a.label.as_str()).collect::<Vec<_>>(), ["a2", "a3"]);
        assert_eq!(p.properties.len(), 1);
        assert_eq!(errs("module m; a: assert property (@(posedge c) x);"), ["1:1 'endmodule' missing: module 'm' is not closed"]);
        assert_eq!(errs("module m; endchecker"), ["1:1 'endmodule' missing: module 'm' is not closed", "1:11 expected 'endmodule', found 'endchecker'"]);
        assert_eq!(errs("property p; @(posedge c) x;\nsequence s; y; endsequence"), ["2:1 expected 'endproperty', found 'sequence'"]);
        assert_eq!(parse("property p; @(posedge c) x;\nsequence s; y; endsequence").sequences.len(), 1);
    }

    #[test]
    fn local_variables_and_formals_outside_the_subset() {
        assert_eq!(errs("property p; int x; @(posedge c) a; endproperty"), ["1:13 local variables in sequences and properties are outside the subset"]);
        assert_eq!(errs("sequence s(local input int x); a; endsequence"), ["1:12 local and directional formal arguments are outside the subset"]);
        assert_eq!(errs("property p(event e); a; endproperty"), ["1:12 event formal arguments are outside the subset"]);
        assert_eq!(errs("property p(a[2]); a; endproperty"), ["1:13 unpacked dimensions of formal arguments are outside the subset"]);
        assert_eq!(errs("sequence s; a |-> b; endsequence"), ["1:13 a sequence declaration needs a sequence, found a property"]);
    }

    #[test]
    fn macros_and_conditionals_in_files() {
        let src = "`define CLK @(posedge clk)\n`define WIN(n) ##[1:n]\n`ifdef FORMAL\nf: assume property (`CLK x);\n`else\nn: assert property (`CLK req `WIN(4) ack);\n`endif";
        let a = one(src);
        assert_eq!((a.label.as_str(), labels(&a)), ("n", vec!["s1 req".to_string(), "s2 ##[1:4] ack".into()]));
        let mut u = Unit::new();
        u.define("FORMAL", "");
        let p = u.parse(src);
        assert_eq!(p.assertions[0].label, "f");
        // an error inside an expansion points at the macro use
        assert_eq!(errs("`define BAD ##[3:1]\na: assert property (@(posedge c) x `BAD y);"), ["2:36 the range ends before it starts (3:1)"]);
        assert_eq!(errs("a: assert property (@(posedge c) x `NOPE y);"), ["1:36 undefined macro `NOPE", "1:42 expected ')', found 'y'"]);
    }

    #[test]
    fn a_unit_of_files() {
        let mut u = Unit::new();
        let p1 = u.parse("`define D 2\npackage pk; typedef enum {A, B} e_t; sequence s; go ##1 run; endsequence endpackage");
        assert!(p1.errors.is_empty() && p1.assertions.is_empty());
        let p2 = u.parse("module m import pk::*; (input e_t st, input logic clk); a: assert property (@(posedge clk) s ##`D st == B); endmodule");
        assert!(p2.errors.is_empty(), "{:?}", p2.errors);
        assert_eq!(labels(&p2.assertions[0]), ["s1 go", "s2 ##1 run", "s3 ##2 st == B"]);
        assert_eq!(sigs(&p2.assertions[0]), ["clk:1", "go", "run", "st:32"]);
        // the declarations of the first file are not output again by the second
        assert!(p2.sequences.is_empty());
    }

    #[test]
    fn describe_text() {
        let src = format!("module m(input logic clk, req, ack, rst_n);\n{SPIKE}\nendmodule\nfoo bar baz;");
        let p = parse(&src);
        let t = describe(&p, &src, "x.sv", false);
        assert_eq!(
            t,
            "x.sv:5:1: error: expected a declaration or an assertion, found 'foo'\n    5 | foo bar baz;\n      | ^^^\n\
             module m ports clk:1 req:1 ack:1 rst_n:1\n\
             property p_req_ack @(posedge clk) disable iff (!rst_n): req |-> ##[1:3] ack\n\
             assert a_req_ack in m, line 3\n  clock     @(posedge clk) disable iff (!rst_n)\n  property  p_req_ack\n  expr      p_req_ack\n\
             \x20 s1        req\n  s2        ##[1:3] ack\n  signals   clk:1 rst_n:1 req:1 ack:1\n"
        );
    }
}

mod json {
    use super::*;

    #[test]
    fn parse_only_request() {
        let out: Value = serde_json::from_str(&run_json(r#"{"source": "a: assert property (@(posedge c) x |=> y);"}"#)).unwrap();
        let a = &out["assertions"][0];
        assert_eq!(a["label"], "a");
        assert_eq!(a["kind"], "assert");
        assert_eq!(a["prop"]["kind"], "implies");
        assert_eq!(a["prop"]["op"], "|=>");
        assert_eq!(a["prop"]["ante"]["id"], "s1");
        assert_eq!(a["elements"][1]["label"], "y");
        assert_eq!(a["signals"][0]["name"], "c");
        assert_eq!(a["text"], "x |=> y");
        assert_eq!(out["errors"], Value::Array(vec![]));
    }

    #[test]
    fn text_is_the_property_with_instances_expanded() {
        let a = one("property p(x, y); x |-> ##[1:2] y; endproperty\na: assert property (@(posedge c) p(req, ack));");
        assert_eq!(a.text, "req |-> ##[1:2] ack");
        assert_eq!(crate::text(&a), a.text);
    }

    #[test]
    fn the_last_unit_is_kept_for_the_next_evaluation() {
        // the same files again: not parsed again (the page evaluates one request per binding or clock)
        let req = |src: &str, sig: &str| serde_json::json!({ "files": [src], "trace": { "signals": { "x": [sig, sig] } } }).to_string();
        let a = "a: assert property (@(posedge c) x);";
        let t = std::time::Instant::now();
        let one: Value = serde_json::from_str(&run_json(&req(a, "1"))).unwrap();
        let two: Value = serde_json::from_str(&run_json(&req(a, "0"))).unwrap();
        assert_eq!((one["assertions"][0]["stats"]["pass"].as_u64(), two["assertions"][0]["stats"]["fail"].as_u64()), (Some(2), Some(2)));
        // other files: parsed (the cache does not answer for them)
        let other: Value = serde_json::from_str(&run_json(&req("b: assert property (@(posedge c) !x);", "1"))).unwrap();
        assert_eq!((other["assertions"][0]["name"].as_str(), other["assertions"][0]["stats"]["fail"].as_u64()), (Some("b"), Some(2)));
        assert!(t.elapsed().as_secs_f64() < 1.0);
    }

    #[test]
    fn files_request_is_one_unit() {
        let pkg = "package p; typedef enum logic [1:0] {IDLE, RUN} st_t; endpackage";
        let chk = "module m import p::*; (input logic c, input st_t s); a: assert property (@(posedge c) s == IDLE |=> s == RUN); endmodule";
        let req = serde_json::json!({ "files": [pkg, chk] }).to_string();
        let out: Value = serde_json::from_str(&run_json(&req)).unwrap();
        assert_eq!(out["files"].as_array().unwrap().len(), 2);
        assert_eq!(out["files"][1]["errors"], Value::Array(vec![]));
        assert_eq!(out["files"][1]["assertions"][0]["text"], "s == IDLE |=> s == RUN");
        assert_eq!(out["files"][1]["assertions"][0]["signals"].as_array().unwrap().len(), 2);
        // alone, the second file does not know the package: a warning, and IDLE, RUN read as signals
        let out: Value = serde_json::from_str(&run_json(&serde_json::json!({ "files": [chk] }).to_string())).unwrap();
        assert!(out["files"][0]["warnings"][0]["msg"].as_str().unwrap().contains("package 'p' is not loaded"));
        assert_eq!(out["files"][0]["assertions"][0]["signals"].as_array().unwrap().len(), 4);
        // evaluated as a unit
        let req = serde_json::json!({ "files": [pkg, chk], "trace": { "signals": { "s": ["0", "1", "0", "0"] } }, "assert": ["a"] }).to_string();
        let out: Value = serde_json::from_str(&run_json(&req)).unwrap();
        let st = &out["assertions"][0]["stats"];
        assert_eq!((st["pass"].as_u64(), st["fail"].as_u64()), (Some(1), Some(1)), "{out}");
    }

    #[test]
    fn errors_say_found_and_expected() {
        let out: Value = serde_json::from_str(&run_json(r#"{"source": "a: assert property (@(posedge c) x |=> );"}"#)).unwrap();
        let e = &out["errors"][0];
        assert_eq!((e["line"].as_u64(), e["col"].as_u64()), (Some(1), Some(40)));
        assert_eq!(e["found"], "')'");
        assert_eq!(e["expected"], "an expression");
        assert_eq!((e["start"].as_u64(), e["end"].as_u64()), (Some(39), Some(40)));
        let out: Value = serde_json::from_str(&run_json("{bad")).unwrap();
        assert!(out["errors"][0]["msg"].as_str().unwrap().starts_with("request: "));
    }

    #[test]
    fn node_shapes() {
        let a = one(&clocked("$rose(a) ##[1:$] b[*2] |-> s_eventually [1:3] c inside {1, [2:3]}"));
        let v = serde_json::to_value(&a).unwrap();
        let p = &v["prop"];
        assert_eq!(p["ante"]["kind"], "delay");
        assert_eq!(p["ante"]["range"], serde_json::json!({"min": 1, "max": "$"}));
        assert_eq!(p["ante"]["lhs"]["expr"]["kind"], "call");
        assert_eq!(p["ante"]["lhs"]["expr"]["func"], "$rose");
        assert_eq!(p["ante"]["rhs"]["op"], "[*]");
        assert_eq!(p["cons"]["kind"], "eventually");
        assert_eq!(p["cons"]["strong"], true);
        assert_eq!(p["cons"]["p"]["seq"]["expr"]["set"][1], serde_json::json!({"lo": {"kind": "number", "value": 2, "signed": true, "base": 10, "text": "2", "at": p["cons"]["p"]["seq"]["expr"]["set"][1]["lo"]["at"].clone()}, "hi": p["cons"]["p"]["seq"]["expr"]["set"][1]["hi"].clone()}));
        assert_eq!(v["at"]["line"], 1);
    }
}

mod nesting {
    use super::*;

    fn chain(n: usize) -> String {
        format!("a: assert property (@(posedge clk) {});", vec!["a"; n].join(" ##0 "))
    }

    #[test]
    fn too_deep_is_an_error_not_a_crash() {
        std::thread::Builder::new().stack_size(16 << 20).spawn(too_deep).unwrap().join().unwrap();
    }

    fn too_deep() {
        for src in [chain(3000), format!("a: assert property (@(posedge clk) {}a{});", "(".repeat(3000), ")".repeat(3000)),
                    format!("a: assert property (@(posedge clk) {}a);", "not ".repeat(3000)), format!("a: assert property (@(posedge clk) {});", vec!["a"; 3000].join(" && "))] {
            let p = parse(&src);
            assert!(p.errors.iter().any(|e| e.msg.starts_with("nested too deeply")), "{:?}", p.errors);
        }
    }

    #[test]
    fn deep_but_allowed_evaluates() {
        // the limit parses, expands and evaluates (debug frames are large: 16 MB here; the release WebAssembly build
        // evaluates 499 levels of every form with its 1 MB stack, docs/sva/ENGINE.md)
        std::thread::Builder::new().stack_size(16 << 20).spawn(|| {
            let p = parse(&chain(499));
            assert!(p.errors.is_empty(), "{:?}", p.errors);
            let mut t = Trace::default();
            t.add("a", Column::known(1, &[1, 1, 0]));
            let o = evaluate(&p.assertions[0], &t, &Options::default()).unwrap();
            assert_eq!((o.stats.pass, o.stats.fail), (2, 1));
        }).unwrap().join().unwrap();
    }
}

// ---------------------------------------------------------------- report (summary.rs)

fn report_doc() -> serde_json::Value {
    serde_json::json!({ "clock": "clk", "unit": "ps", "cycles": [10, 20, 30, 40, 50, 60, 70, 80],
        "assertions": [
          { "name": "a", "kind": "assert", "scope": "tb", "line": 3, "text": "req |-> ##[1:3] ack",
            "steps": [{ "id": "s1", "label": "req", "role": "ante", "group": 0 }, { "id": "s2", "label": "##[1:3] ack", "role": "cons", "group": 0 }],
            "stats": { "attempts": 8, "pass": 2, "fail": 2, "vacuous": 3, "disabled": 0, "active": 0, "capped": 1 },
            "attempts": [
              { "start": 0, "end": 1, "result": "pass", "trace": [["s1", 0], ["s2", 1]], "ante_end": [0] },
              { "start": 1, "end": 4, "result": "fail", "trace": [["s1", 1]], "failed_at": 4, "note": "no ack within [1:3]", "reason": { "kind": "range", "step": "s2", "cycle": 4 }, "ante_end": [1] },
              { "start": 2, "end": 5, "result": "pass", "trace": [["s1", 2], ["s2", 5]], "ante_end": [2] },
              { "start": 3, "end": 3, "result": "capped", "trace": [], "reason": { "kind": "capped", "cycle": 3 } },
              { "start": 6, "end": 6, "result": "fail", "trace": [["s1", 6]], "failed_at": 6, "note": "ack is unknown (x) at cycle 6", "reason": { "kind": "unknown", "step": "s2", "cycle": 6 }, "ante_end": [6] } ] },
          { "name": "c", "kind": "cover", "scope": "tb", "line": 4, "text": "req", "steps": [], "stats": { "attempts": 8, "pass": 0, "fail": 8, "vacuous": 0, "disabled": 0, "active": 0, "capped": 0, "matches": 0 }, "attempts": [] },
          { "name": "m", "kind": "assert", "scope": "tb", "line": 5, "text": "x", "steps": [], "stats": { "attempts": 0, "pass": 0, "fail": 0, "vacuous": 0, "disabled": 0, "active": 0, "capped": 0 }, "attempts": [], "missing": ["x"] } ] })
}

#[test]
fn report_numbers_per_assertion() {
    let r = crate::summarize(&serde_json::json!({ "meta": { "title": "T" }, "results": [report_doc()] }));
    let a = &r["assertions"][0];
    assert_eq!(a["latency"], serde_json::json!({ "min": 1, "avg": 2.0, "max": 3, "n": 2, "text": "1 / 2.0 / 3" }), "pass attempts: ante_end -> the last consequent step");
    assert_eq!((a["first_fail"]["start"].as_u64(), a["first_fail"]["failed_at"].as_u64(), a["first_fail"]["time"].as_str(), a["first_fail"]["kind"].as_str()), (Some(1), Some(4), Some("20 ps"), Some("range")));
    assert_eq!((a["last_fail"]["start"].as_u64(), a["last_fail"]["kind"].as_str()), (Some(6), Some("unknown")));
    assert_eq!(a["longest"]["cycles"], 3);
    assert_eq!(r["assertions"][1]["covered"], 0);
    let t = &r["totals"];
    assert_eq!((t["assertions"].as_u64(), t["evaluated"].as_u64(), t["with_failures"].as_u64(), t["fail"].as_u64(), t["capped"].as_u64(), t["covered"].as_u64()), (Some(3), Some(2), Some(1), Some(2), Some(1), Some(0)));
    assert_eq!(r["failures"].as_array().unwrap().iter().map(|f| f["start"].as_u64().unwrap()).collect::<Vec<_>>(), vec![1, 6], "by time; the capped one is no failure");
}

#[test]
fn report_texts() {
    let r = crate::summarize(&serde_json::json!({ "meta": { "title": "T", "dump": "x.fst" }, "results": [report_doc()] }));
    let md = crate::report_markdown(&r);
    assert!(md.starts_with("# T\n\n- dump: x.fst\n"), "{md}");
    assert!(md.contains("2 fail, 3 vacuous, 0 disabled, 0 active, 1 capped (no verdict); 0 of 1 covers hit"), "{md}");
    assert!(md.contains("| `m` (not evaluated: no x) |"), "{md}");
    assert!(md.contains("| 2 | `a` | tb | 70 ps (cycle 6) | 70 ps (cycle 6) | unknown | ack is unknown (x) at cycle 6 |"), "{md}");
    assert!(md.contains("| `c` | tb | cover: 0 hit | 8 | 0 | — |"), "a cover's misses are no failures: {md}");
    let x = crate::report_junit(&r);
    assert!(x.contains("tests=\"3\" failures=\"1\" errors=\"0\" skipped=\"2\""), "{x}");
    assert!(x.contains("<property name=\"capped\" value=\"1\"/>") && x.contains("<skipped message=\"cover never hit\"/>") && x.contains("<skipped message=\"not evaluated: no x\"/>"), "{x}");
    let h = crate::report_html(&r);
    assert!(h.contains("<tr class=\"bad\"><td><code title=\"req |-&gt; ##[1:3] ack\">a</code>"), "{h}");
    // through the page's entry point
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(&serde_json::json!({ "report": { "results": [report_doc()] }, "format": "md" }).to_string())).unwrap();
    assert_eq!(out["summary"]["totals"]["fail"], 2);
    assert!(out["text"].as_str().unwrap().contains("## Failures (2)"));
}

/// Short inputs never panic: every sequence of one to three tokens over keywords, names and punctuation parses to an
/// error with a position (or to nothing).
#[test]
fn short_inputs_do_not_panic() {
    let toks = ["a", "b", "module", "endmodule", "property", "assert", "(", ")", "{", "}", ";", "@", "##1", "|->", "`define", "`ifdef", "\\esc ", "'h1", "\"s", "/*"];
    let mut n = 0;
    for x in toks {
        for y in [""].iter().chain(toks.iter()) {
            for z in [""].iter().chain(toks.iter()) {
                let src = format!("{x} {y} {z}");
                let r = std::panic::catch_unwind(|| parse(&src));
                let p = r.unwrap_or_else(|_| panic!("panicked on {src:?}"));
                assert!(p.errors.iter().all(|e| e.line >= 1), "{src:?}");
                n += 1;
            }
        }
    }
    assert_eq!(n, 20 * 21 * 21);
    for src in ["a", "a b", "garbage", "x {{{"] {
        let p = parse(src);
        assert!(!p.errors.is_empty() && p.errors[0].line == 1, "{src}: {:?}", p.errors);
    }
}

#[test]
fn report_time_text_is_exact() {
    use crate::time_text as t;
    assert_eq!([t(400, "ps"), t(15_000, "ps"), t(3_005_000, "ps"), t(1_000_400, "ps"), t(81_716_400, "ps"), t(2_000_000_000, "ps"), t(1_500_000_000_000, "ps"), t(7, "cycles")],
        ["400 ps", "15 ns", "3.005 us", "1.0004 us", "81.7164 us", "2 ms", "1.5 s", "cycle 7"]);
}

/// One assertion over its own cycles (1 ns each), with the attempts given.
fn one_doc(name: &str, text: &str, attempts: serde_json::Value, stats: serde_json::Value) -> serde_json::Value {
    serde_json::json!({ "unit": "ps", "cycles": (0..400u64).map(|k| k * 1000).collect::<Vec<_>>(), "assertions": [{ "name": name, "kind": "assert", "scope": "tb", "text": text,
        "steps": [{ "id": "s1", "label": "a", "role": "ante", "group": 0 }, { "id": "s2", "label": "b", "role": "cons", "group": 0 }], "stats": stats, "attempts": attempts }] })
}

#[test]
fn report_hardening() {
    // the latency takes the latest antecedent match: the engine keeps the first 32 and the last 32 of a long one
    let mut t = Trace::default();
    t.add("a", Column::known(1, &(0..120).map(|k| (k < 100) as u64).collect::<Vec<_>>()));
    t.add("b", Column::known(1, &[1; 120]));
    let p = parse("module m; a1: assert property (@(posedge clk) a[*1:200] |-> ##1 b); endmodule");
    let o = evaluate(&p.assertions[0], &t, &Options::default()).unwrap();
    let doc = serde_json::json!({ "unit": "cycles", "cycles": (0..120u64).collect::<Vec<_>>(), "assertions": [serde_json::to_value(&o).unwrap()] });
    let r = crate::summarize(&serde_json::json!({ "results": [doc] }));
    assert_eq!(r["assertions"][0]["latency"]["text"], "1 / 1.0 / 1", "{}", r["assertions"][0]["latency"]);
    assert!(o.attempts.iter().all(|a| a.ante_end.len() <= 64) && o.attempts[0].ante_end.contains(&99), "{:?}", o.attempts[0].ante_end);
    assert!(o.attempts[0].ante_truncated && !o.attempts[90].ante_truncated, "the first attempt's list was cut, a late one's not");
    assert_eq!(&o.attempts[0].ante_end[30..34], &[30, 31, 68, 69], "the first 32, then the latest 32");

    // the same assertion from two files: rows and failures apart (JUnit lists each one's own), a source column
    let f1 = one_doc("x", "a |-> b", serde_json::json!([{ "start": 1, "end": 1, "result": "fail", "failed_at": 1, "note": "one" }]), serde_json::json!({ "attempts": 1, "fail": 1 }));
    let f2 = one_doc("x", "a |-> b", serde_json::json!([{ "start": 2, "end": 2, "result": "fail", "failed_at": 2, "note": "two" }, { "start": 3, "end": 3, "result": "fail", "failed_at": 3, "note": "three" }]), serde_json::json!({ "attempts": 2, "fail": 2 }));
    let r = crate::summarize(&serde_json::json!({ "results": [f1, f2], "sources": ["r1.json", "r2.json"] }));
    let x = crate::report_junit(&r);
    let cases: Vec<&str> = x.split("<testcase").skip(1).collect();
    assert!(cases[0].contains("[r1.json]") && cases[0].contains(": one") && !cases[0].contains("two"), "{x}");
    assert!(cases[1].contains("[r2.json]") && cases[1].contains(": two") && cases[1].contains(": three") && !cases[1].contains(": one"), "{x}");
    assert!(crate::report_markdown(&r).contains("| Assertion | Scope | Source | Kind |"));

    // capped only: an error of its test case, the notes in the texts
    let c = serde_json::json!({ "unit": "ps", "cycles": [0, 1000], "assertions": [{ "name": "cap", "kind": "assert", "scope": "tb", "notes": ["thread limit 256 reached at cycle 1 (attempt 0)"],
        "stats": { "attempts": 1, "pass": 0, "fail": 0, "capped": 1 }, "attempts": [{ "start": 0, "end": 1, "result": "capped" }] }] });
    let r = crate::summarize(&serde_json::json!({ "results": [c] }));
    let x = crate::report_junit(&r);
    assert!(x.contains("errors=\"1\"") && x.contains("<error type=\"capped\" message=\"1 attempts without verdict (thread limit)\"/>") && x.contains("note: thread limit 256"), "{x}");
    assert!(crate::report_markdown(&r).contains("## Notes\n\n- `cap` tb: thread limit 256 reached"), "{}", crate::report_markdown(&r));
    assert!(crate::report_html(&r).contains("<ul class=\"notes\">"));
    assert_eq!(r["totals"]["not_proven"], 1);
    assert_eq!(r["assertions"][0]["longest"], serde_json::Value::Null, "a capped attempt has no length of its own");

    // first failure = the first found: by failed_at, not by start
    let f = one_doc("late", "a |-> ##5 b and ##1 c", serde_json::json!([{ "start": 0, "end": 5, "result": "fail", "failed_at": 5 }, { "start": 2, "end": 3, "result": "fail", "failed_at": 3 }]), serde_json::json!({ "attempts": 2, "fail": 2 }));
    let r = crate::summarize(&serde_json::json!({ "results": [f] }));
    assert_eq!((r["assertions"][0]["first_fail"]["failed_at"].as_u64(), r["assertions"][0]["last_fail"]["failed_at"].as_u64()), (Some(3), Some(5)));
    assert_eq!(r["failures"][0]["failed_at"], 3);

    // at most max_failures per assertion in the texts, all of them in the JSON
    let many: Vec<serde_json::Value> = (0..30).map(|k| serde_json::json!({ "start": k, "end": k, "result": "fail", "failed_at": k })).collect();
    let f = one_doc("many", "a", serde_json::json!(many), serde_json::json!({ "attempts": 30, "fail": 30 }));
    let r = crate::summarize(&serde_json::json!({ "results": [f], "max_failures": 5 }));
    let md = crate::report_markdown(&r);
    assert!(r["failures"].as_array().unwrap().len() == 30 && md.contains("## Failures (30)") && md.contains("| 5 | `many`") && !md.contains("| 6 | `many`") && md.contains("… and 25 more failures of `many`"), "{md}");
    assert!(crate::report_junit(&r).contains("… and 25 more"));

    // escaping: a backtick in a name, HTML in a note, control characters in XML
    let f = one_doc("x`y", "a", serde_json::json!([{ "start": 0, "end": 0, "result": "fail", "failed_at": 0, "note": "<img src=x> & |" }]), serde_json::json!({ "attempts": 1, "fail": 1 }));
    let r = crate::summarize(&serde_json::json!({ "meta": { "title": "T\u{1}x" }, "results": [f] }));
    let md = crate::report_markdown(&r);
    assert!(md.contains("``x`y``") && md.contains("&lt;img src=x> &amp; \\|"), "{md}");
    let x = crate::report_junit(&r);
    assert!(x.contains("name=\"Tx\"") && x.contains("time=\"0\""), "{x}");

    // the input is checked: anything else is an error, not an empty report
    for bad in [serde_json::json!({}), serde_json::json!([]), serde_json::json!(42), serde_json::json!({ "results": 5 }),
        serde_json::json!({ "results": [{ "assertions": [{ "name": "a", "stats": { "fail": "2" } }] }] }), serde_json::json!({ "results": [], "totals": {} })] {
        assert!(crate::check_report_input(&bad).is_err(), "{bad}");
    }
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(r#"{"report": null}"#)).unwrap();
    assert!(out["errors"][0]["msg"].as_str().unwrap().starts_with("report: "), "{out}");
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(&serde_json::json!({ "report": { "results": [] }, "format": "pdf" }).to_string())).unwrap();
    assert!(out["errors"][0]["msg"].as_str().unwrap().contains("no format 'pdf'"), "{out}");
    // an end before its start does not underflow
    let f = one_doc("odd", "a", serde_json::json!([{ "start": 5, "end": 2, "result": "pass" }]), serde_json::json!({ "attempts": 1, "pass": 1 }));
    assert_eq!(crate::summarize(&serde_json::json!({ "results": [f] }))["assertions"][0]["longest"]["cycles"], 0);
}

/// An escaped identifier that would read as a hierarchical name keeps its backslash (a dump names it so)
/// and prints with the space that ends it; a plain one loses the backslash.
#[test]
fn escaped_identifiers() {
    let p = parse("module m(input clk);\n  a1: assert property (@(posedge clk) \\plain  |-> \\esc.x );\nendmodule\n");
    assert!(p.errors.is_empty(), "{:?}", p.errors);
    let names: Vec<&str> = p.assertions[0].signals.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, ["clk", "plain", "\\esc.x"]);
    let text = Printer::full().prop(&p.assertions[0].prop);
    assert!(text.contains("\\esc.x "), "{text}");
    assert_eq!(Printer::full().prop(&parse_prop(&text).unwrap()), text, "prints and parses back");
}

/// From the CoaXPress checkers (examples/test_video): a size cast by a parameter, a port typed by a package type.
#[test]
fn cast_by_parameter_and_package_typed_port() {
    let src = "package p;\n  typedef struct packed { logic [7:0] code; logic [15:0] n; } rsp_t;\n  localparam int unsigned MAX = 100;\nendpackage\n\
        module chk #(parameter int p_W = 13, parameter int p_D = 4096) (input wire logic clk, input wire logic [p_W-1:0] fill, input wire p::rsp_t rsp, input wire logic [6:0] run);\n\
          a_fill: assert property (@(posedge clk) fill <= p_W'(p_D));\n\
          a_run: assert property (@(posedge clk) run <= 7'(p::MAX - 1));\n\
          a_rsp: assert property (@(posedge clk) $stable(rsp));\nendmodule\n";
    let p = parse(src);
    assert!(p.errors.is_empty(), "{:?}", p.errors);
    assert_eq!(p.assertions.len(), 3);
    assert_eq!(Printer::full().prop(&p.assertions[0].prop), "fill <= 13'(p_D)");
    let d = crate::describe(&p, src, "x.sv", false);
    assert!(d.contains("rsp:24"), "the port's width from the packed struct: {d}");
    let e = parse("module m #(parameter int w = 0) (input logic clk, input logic [3:0] a);\n  x: assert property (@(posedge clk) w'(a) == 0);\nendmodule\n");
    assert!(e.errors.iter().any(|x| x.msg.contains("no constant width")), "{:?}", e.errors);
}

/// A label is unique in its module: the same label in another module of the unit is `module.label` (the first keeps
/// the plain one), across files of one unit too.
#[test]
fn labels_qualified_by_module_when_repeated() {
    let mut u = Unit::new();
    let a = u.parse("module m1(input clk, a); a_hold: assert property (@(posedge clk) a); endmodule\n");
    let b = u.parse("module m2(input clk, b); a_hold: assert property (@(posedge clk) b); x: assert property (@(posedge clk) b); endmodule\n");
    assert_eq!(a.assertions[0].label, "a_hold");
    assert_eq!(b.assertions.iter().map(|x| x.label.as_str()).collect::<Vec<_>>(), ["m2.a_hold", "x"]);
    assert!(a.errors.is_empty() && b.errors.is_empty());
}
