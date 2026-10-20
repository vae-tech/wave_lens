//! The evaluator over hand-made traces: one test per construct, each with the expected attempts.
//!
//! A trace is written as `name=0110x` (a 1-bit signal, one character per cycle: 0 1 x z) or `name=3,4,x,5` (one value
//! per cycle, `b1x0` for binary digits; `name:W=` gives the width, else the widest value sets it); a leading `@` makes the signal 2-state. The
//! expected attempts are `start-end` and a letter: P pass, F fail, A active, D disabled, V vacuous (listed only with
//! `vacuous: true`). The property runs as `t: assert property (@(posedge clk) <prop>);` unless it is a whole source.

use super::*;
use crate::parse;

fn trace(sigs: &str) -> Trace {
    let mut t = Trace::default();
    for s in sigs.split_whitespace() {
        let (name, spec) = s.split_once('=').unwrap();
        let (name, two) = match name.strip_prefix('@') {
            Some(n) => (n, true),
            None => (name, false),
        };
        let (name, width) = match name.split_once(':') {
            Some((n, w)) => (n, Some(w.parse::<u32>().unwrap())),
            None => (name, None),
        };
        let vals: Vec<(V, u32)> = if spec.contains(',') || width.is_some() {
            spec.split(',').map(|v| match (v, v.strip_prefix('b')) {
                ("x", _) => (V::unknown(64), 1),
                (_, Some(bits)) => V::parse(bits).unwrap(),
                _ => {
                    let n: u64 = v.parse().unwrap();
                    (V::known(n), (64 - n.leading_zeros()).max(1))
                }
            }).collect()
        } else {
            spec.chars().map(|c| V::parse(&c.to_string()).unwrap()).collect()
        };
        let w = width.unwrap_or_else(|| vals.iter().map(|v| v.1).max().unwrap_or(1));
        let m = crate::value::mask(w);
        let mut col = Column::new(w, &vals.iter().map(|(v, _)| V::new(v.v & m, v.x & m)).collect::<Vec<_>>());
        col.two_state = two;
        t.add(name, col);
    }
    t
}

fn source(prop: &str) -> String {
    if prop.contains("assert") || prop.contains("cover") {
        prop.to_string()
    } else {
        format!("t: assert property (@(posedge clk) {prop});")
    }
}

fn outcome(prop: &str, sigs: &str, opt: &Options) -> Outcome {
    let p = parse(&source(prop));
    assert!(p.errors.is_empty(), "{prop}: {:?}", p.errors);
    evaluate(&p.assertions[0], &trace(sigs), opt).unwrap()
}

fn summary(o: &Outcome) -> String {
    let letter = |s: Status| match s {
        Status::Pass => 'P',
        Status::Fail => 'F',
        Status::Vacuous => 'V',
        Status::Active => 'A',
        Status::Disabled => 'D',
        Status::Capped => 'C',
    };
    o.attempts.iter().map(|a| format!("{}-{}{}", a.start, a.end, letter(a.result))).collect::<Vec<_>>().join(" ")
}

fn check(prop: &str, sigs: &str, want: &str) {
    let o = outcome(prop, sigs, &Options::default());
    assert_eq!(summary(&o), want, "{prop} over {sigs}");
}

/// The trace of the first listed attempt: `s1@0 s2@3`, a bus value as `s2@3=5`.
fn steps(o: &Outcome) -> String {
    o.attempts[0].trace.iter().map(|s| match &s.value {
        Some(v) => format!("{}@{}={v}", s.id, s.cycle),
        None => format!("{}@{}", s.id, s.cycle),
    }).collect::<Vec<_>>().join(" ")
}

macro_rules! cases {
    ($($name:ident: $prop:expr, $sigs:expr => $want:expr;)*) => {
        $(#[test] fn $name() { check($prop, $sigs, $want); })*
    };
}

cases! {
    // ---- booleans and delays (a sequence as a property: pass at its first match)
    boolean_each_cycle: "a", "a=0110" => "0-0F 1-1P 2-2P 3-3F";
    fixed_delay: "a ##2 b", "a=1100 b=0010" => "0-2P 1-3F 2-2F 3-3F";
    fusion: "a |-> b ##0 c", "a=10 b=11 c=10" => "0-0P";
    leading_delay: "a |-> ##2 b", "a=1000 b=0010" => "0-2P";
    // ---- implication: vacuous attempts are not listed
    overlap: "a |-> b", "a=101 b=100" => "0-0P 2-2F";
    non_overlap: "a |=> b", "a=1100 b=0101" => "0-1P 1-2F";
    range_in_consequent: "a |-> ##[1:3] b", "a=1001000 b=0000100" => "0-3F 3-4P";
    sequence_antecedent: "a ##1 b |-> c", "a=1100 b=0110 c=0010" => "0-1F 1-2P";
    every_antecedent_match_needs_its_consequent: "a ##[0:2] b |-> c", "a=1000 b=1110 c=1010" => "0-1F";
    passes_after_the_last_antecedent_match: "a ##[0:2] b |-> c", "a=1000 b=1110 c=1110" => "0-2P";
    consequent_left_open_at_the_end: "a |=> ##[0:5] b", "a=0010 b=0000" => "2-3A";
    consequent_open_range_matches: "a |-> ##[1:$] b", "a=1000 b=0001" => "0-3P";
    consequent_open_range_waits: "a |-> ##[1:$] b", "a=1000 b=0000" => "0-3A";
    weak_sequence_cut_by_the_end: "a |-> b ##3 c", "a=100 b=100 c=000" => "0-2A";
    nested_implication: "a |=> (b |-> ##1 c)", "a=1000 b=0100 c=0000" => "0-2F";
    nested_implication_vacuous_inside: "a |=> (b |-> c)", "a=1000 b=0000 c=0000" => "";
    // ---- repetition
    consecutive: "a |-> b[*3]", "a=1000 b=1110" => "0-2P";
    consecutive_breaks: "a |-> b[*3]", "a=1000 b=1100" => "0-2F";
    consecutive_range: "a |-> b[*1:3] ##1 c", "a=10000 b=11100 c=00010" => "0-3P";
    zero_repetition_is_empty: "s |-> a ##1 b[*0] ##1 c", "s=1000 a=1000 b=0000 c=0100" => "0-1P";
    optional_repetition: "s |-> a ##1 b[*0:1] ##1 c", "s=1000 a=1000 b=0100 c=0010" => "0-2P";
    open_repetition_active: "a |-> b[*2:$] ##1 c", "a=1000 b=1111 c=0000" => "0-3A";
    goto: "a |-> b[->2] ##1 c", "a=100000 b=010100 c=000010" => "0-4P";
    goto_waits: "a |-> b[->1]", "a=1000 b=0000" => "0-3A";
    goto_range: "a |-> b[->1:2] ##1 c", "a=10000 b=01010 c=00001" => "0-4P";
    non_consecutive_ends_later: "a |-> b[=2] ##1 c", "a=100000 b=010100 c=000001" => "0-5P";
    non_consecutive_third_hit: "a |-> b[=2] ##1 c", "a=100000 b=010110 c=000001" => "0-4F";
    // ---- sequence operators
    seq_and_ends_at_the_later: "a |-> (b ##1 c) and (d ##2 e)", "a=1000 b=1000 c=0100 d=1000 e=0010" => "0-2P";
    seq_and_one_side_fails: "a |-> (b ##1 c) and (d ##2 e)", "a=1000 b=1000 c=0100 d=1000 e=0000" => "0-2F";
    seq_or: "a |-> (b ##1 c) or (d ##2 e)", "a=1000 b=1000 c=0000 d=1000 e=0010" => "0-2P";
    intersect_same_length: "a |-> b[*1:5] intersect (c ##2 d)", "a=1000 b=1110 c=1000 d=0010" => "0-2P";
    intersect_no_common_end: "a |-> b[*1:5] intersect (c ##2 d)", "a=1000 b=1100 c=1000 d=0010" => "0-2F";
    within: "a |-> (b ##1 c) within (d ##3 e)", "a=10000 b=01000 c=00100 d=10000 e=00010" => "0-3P";
    within_outside: "a |-> (b ##1 c) within (d ##3 e)", "a=10000 b=00010 c=00001 d=10000 e=00010" => "0-3F";
    throughout: "a |-> b throughout (c ##2 d)", "a=1000 b=1110 c=1000 d=0010" => "0-2P";
    throughout_breaks: "a |-> b throughout (c ##2 d)", "a=1000 b=1010 c=1000 d=0010" => "0-1F";
    first_match_antecedent: "first_match(a ##[1:3] b) |-> c", "a=10000 b=01110 c=01000" => "0-1P";
    without_first_match_every_match: "a ##[1:3] b |-> c", "a=10000 b=01110 c=01000" => "0-2F";
    // ---- property operators
    not_inverts: "not (a ##1 b)", "a=110 b=010" => "0-1F 1-2P 2-2P";
    not_of_a_vacuous_implication_fails: "not (a |-> b)", "a=0 b=0" => "0-0F";
    property_and: "(a |-> b) and (a |-> ##1 c)", "a=1000 b=1000 c=0100" => "0-1P";
    property_and_one_vacuous: "(a |-> b) and (c |-> d)", "a=10 b=10 c=00 d=00" => "0-0P";
    property_or: "(a |-> b) or (a |-> ##1 c)", "a=1000 b=0000 c=0100" => "0-1P";
    property_or_both_fail: "(a |-> b) or (a |-> ##1 c)", "a=1000 b=0000 c=0000" => "0-1F";
    if_else: "a |-> if (m) b else c", "a=1100 m=1000 b=1000 c=0000" => "0-0P 1-1F";
    if_without_else_is_vacuous: "if (m) b", "m=0 b=0" => "";
    nexttime: "a |-> nexttime b", "a=100 b=010" => "0-1P";
    nexttime_n: "a |-> nexttime [2] b", "a=100 b=001" => "0-2P";
    nexttime_past_the_end: "a |-> nexttime [3] b", "a=100 b=000" => "0-2A";
    s_nexttime_past_the_end: "a |-> s_nexttime [3] b", "a=100 b=000" => "0-2F";
    always_range: "a |-> always [1:2] b", "a=1000 b=0110" => "0-2P";
    always_range_fails: "a |-> always [1:2] b", "a=1000 b=0100" => "0-2F";
    always_unbounded_stays_active: "a |-> always b", "a=1000 b=1111" => "0-3A";
    s_eventually: "a |-> s_eventually b", "a=1000 b=0001" => "0-3P";
    s_eventually_not_seen: "a |-> s_eventually b", "a=1000 b=0000" => "0-3F";
    eventually_range: "a |-> eventually [1:2] b", "a=1000 b=0010" => "0-2P";
    eventually_range_missed: "a |-> eventually [1:2] b", "a=1000 b=0001" => "0-2F";
    followed_by: "a #-# b", "a=10 b=10" => "0-0P 1-1F";
    followed_by_next: "a #=# b", "a=100 b=010" => "0-1P 1-1F 2-2F";
    // ---- disable iff: alive attempts end as disabled, none starts while it holds
    disable_iff: "disable iff (rst) a |-> ##[1:2] b", "rst=000100 a=110000 b=000000" => "0-2F 1-3D";
    disable_x_does_not_disable: "disable iff (rst) a |=> b", "rst=0x0 a=100 b=010" => "0-1P";
    // ---- sampled-value functions
    rose: "$rose(a) |=> b", "a=0110 b=0010" => "1-2P";
    rose_from_the_initial_x: "$rose(a) |-> b", "a=1100 b=1000" => "0-0P";
    rose_of_a_2_state_signal: "$rose(a) |-> b", "@a=1100 b=0000" => "0-0F";
    fell: "$fell(a) |-> b", "a=1100 b=0010" => "2-2P";
    stable: "a |=> $stable(d)", "a=1100 d=1,1,2,2" => "0-1P 1-2F";
    changed: "a |=> $changed(d)", "a=1100 d=1,1,2,2" => "0-1F 1-2P";
    past: "a |-> d == $past(d) + 1", "a=0111 d=1,2,3,5" => "1-1P 2-2P 3-3F";
    past_before_the_dump_is_x: "a |-> $past(b) == 0", "a=11 b=00" => "0-0F 1-1P";
    past_of_a_2_state_signal: "a |-> $past(b) == 0", "a=11 @b=00" => "0-0P 1-1P";
    onehot: "$onehot(d)", "d=1,3,4,0" => "0-0P 1-1F 2-2P 3-3F";
    isunknown: "a |-> !$isunknown(d)", "a=11 d=x,1" => "0-0F 1-1P";
    case_equality_sees_x: "a |-> b === 1'bx", "a=11 b=x0" => "0-0P 1-1F";
    // ---- 4-state values: an unknown boolean fails the attempt (x: "fail", the default)
    unknown_consequent: "a |-> b", "a=11 b=x1" => "0-0F 1-1P";
    unknown_antecedent: "a |-> b", "a=x1 b=01" => "0-0F 1-1P";
    known_despite_x: "a |-> b || c", "a=1 b=x c=1" => "0-0P";
    fill_literal: "a |-> d == '1", "a=1 d:4=15" => "0-0P";
    // ---- named sequences and properties
    instances: "sequence s(x, y); x ##1 y; endsequence\nproperty p(q); s(q, b) |-> c; endproperty\nt: assert property (@(posedge clk) p(a));", "a=1000 b=0100 c=0100" => "0-1P";
}

// the examples of docs/sva/LANGUAGE.md ("Constructs, one example each")
cases! {
    lang_delay: "req |-> ##2 ack", "req=1000 ack=0010" => "0-2P";
    lang_fusion: "req ##0 gnt", "req=10 gnt=11" => "0-0P 1-1F";
    lang_star_delay: "start |-> ##[*] done", "start=100 done=100" => "0-0P";
    lang_plus_delay: "start |-> ##[+] done", "start=100 done=101" => "0-2P";
    lang_leading_delay: "##1 req ##1 gnt", "req=0100 gnt=0010" => "0-2P 1-2F 2-3F 3-3A";
    lang_repetition: "a |=> b[*3] ##1 c", "a=10000 b=01110 c=00001" => "0-4P";
    lang_goto: "req |-> gnt[->1]", "req=1000 gnt=0010" => "0-2P";
    lang_sequence_repetition: "s |-> (a ##1 b)[*2]", "s=1000 a=1010 b=0101" => "0-3P";
    lang_intersect: "s |-> (a ##[1:5] b) intersect (c[*3])", "s=100 a=100 b=001 c=111" => "0-2P";
    lang_throughout: "s |-> en throughout (busy[*1:$] ##1 stop)", "s=1000 en=1111 busy=1100 stop=0010" => "0-2P";
    lang_first_match: "first_match(start ##[1:4] busy) |=> stop", "start=100000 busy=011000 stop=001000" => "0-2P";
    lang_followed_by: "req ##1 gnt #-# ack", "req=1000 gnt=0100 ack=0100" => "0-1P 1-1F 2-2F 3-3F";
    lang_followed_by_next: "req #=# ##[0:2] ack", "req=1000 ack=0001" => "0-3P 1-1F 2-2F 3-3F";
    lang_not: "not (req ##1 err)", "req=10 err=00" => "0-1P 1-1P";
    lang_if_else: "start |-> if (mode) ##1 a else ##2 b", "start=1100 mode=1000 a=0100 b=0001" => "0-1P 1-3P";
    lang_s_nexttime: "req |-> s_nexttime [2] ack", "req=100 ack=001" => "0-2P";
    lang_always_after_reset: "$fell(rst_n) |-> always !start", "rst_n=1100 start=0000" => "2-3A";
    lang_always_range: "always [1:3] !done", "done=0000" => "0-3P 1-3A 2-3A 3-3A";
    lang_s_always_range: "s_always [0:2] x", "x=111" => "0-2P 1-2F 2-2F";
    lang_eventually_range: "eventually [1:8] done", "done=0100" => "0-1P 1-3A 2-3A 3-3A";
    lang_case_equality: "be === 4'b1x0z", "be:4=b1x0x,b1000" => "0-0P 1-1F";
    lang_inside: "st inside {0, [2:3]}", "st:2=0,1,2,3" => "0-0P 1-1F 2-2P 3-3P";
    lang_past_n: "data == $past(data, 2)", "data=1,2,1,2" => "0-0F 1-1F 2-2P 3-3P";
    lang_onehot0: "$onehot0(grant)", "grant=0,1,3" => "0-0P 1-1P 2-2F";
    lang_concat: "{v, w, x} == 3'b101", "v=1 w=0 x=1" => "0-0P";
    lang_conditional: "(v ? data : addr) != 0", "v=10 data=5,0 addr=0,0" => "0-0P 1-1F";
    lang_reductions: "&be || |data || ^addr", "be:4=15,7 data:8=0,0 addr:8=0,0" => "0-0P 1-1F";
    lang_power: "2 ** st == 8", "st=3,2" => "0-0P 1-1F";
    lang_indexed_select: "be[0+:2] == 2'b11", "be:4=3,6" => "0-0P 1-1F";
}

#[test]
fn spike_trace() {
    // the toy trace of sva/spike/spike.html (checked in the page by tests/smoke.py)
    let o = outcome("property p_req_ack; @(posedge clk) disable iff (!rst_n) req |-> ##[1:3] ack; endproperty\na_req_ack: assert property (p_req_ack);",
        "rst_n=011111111011 req=010010001001 ack=000100000000", &Options::default());
    assert_eq!(summary(&o), "1-3P 4-7F 8-9D 11-11A");
    assert_eq!(o.stats, Stats { attempts: 10, pass: 1, fail: 1, vacuous: 6, disabled: 1, active: 1, capped: 0, matches: None });
    assert_eq!(o.lane.as_deref(), Some(".S.PS..FSD.S"));
    assert_eq!(o.attempts.iter().map(|a| a.trace.len()).collect::<Vec<_>>(), [2, 1, 1, 1], "disabled and active attempts show how far they got");
    let o = outcome("a |-> b ##1 c ##5 d", "a=1000 b=1000 c=0100 d=0000", &Options::default());
    assert_eq!((summary(&o), steps(&o)), ("0-3A".into(), "s1@0 s2@0 s3@1".into()));
}

#[test]
fn fail_notes_and_traces() {
    let o = outcome("a |-> ##[1:3] b", "a=1001000 b=0000100", &Options::default());
    let f = o.first_fail().unwrap();
    assert_eq!((f.failed_at, f.note.as_deref()), (Some(3), Some("no b within [1:3]")));
    assert_eq!(steps(&o), "s1@0", "the failed attempt shows the antecedent");
    assert_eq!(o.attempts[1].trace.iter().map(|s| (s.id.as_str(), s.cycle)).collect::<Vec<_>>(), [("s1", 3), ("s2", 4)]);
    let o = outcome("a |=> b", "a=10 b=00", &Options::default());
    assert_eq!(summary(&o), "0-1F");
    assert_eq!(o.attempts[0].note.as_deref(), Some("expected b at cycle 1"));
    let o = outcome("a |-> b[->2] ##1 c", "a=100000 b=010100 c=000010", &Options::default());
    assert_eq!(steps(&o), "s1@0 s2@1 s2@3 s3@4", "every hit of a goto is a step");
    let o = outcome("a |-> s_eventually b", "a=1000 b=0000", &Options::default());
    assert_eq!(o.attempts[0].note.as_deref(), Some("not seen before the end of the dump"));
    let o = outcome("a |-> s_nexttime [3] b", "a=100 b=000", &Options::default());
    assert!(o.attempts[0].note.as_deref().unwrap().contains("s_nexttime"));
}

#[test]
fn bus_compares_show_the_value() {
    let o = outcome("a |-> d == 8'h5 ##1 d != 0", "a=10 d=5,7", &Options::default());
    assert_eq!(steps(&o), "s1@0 s2@0=5 s3@1=7");
    let o = outcome("a |-> st inside {1, 2}", "a=1 st:2=3", &Options::default());
    assert_eq!(steps(&o), "s1@0", "a failed compare is not a step");
    assert_eq!(o.attempts[0].note.as_deref(), Some("expected st inside {1, 2} at cycle 0"));
}

#[test]
fn unknown_values_fail_with_a_note_or_read_as_false() {
    let o = outcome("a |-> b", "a=11 b=x1", &Options::default());
    assert_eq!(o.attempts[0].note.as_deref(), Some("b is unknown (x) at cycle 0"));
    assert_eq!(steps(&o), "s1@0 s2@0", "the unknown boolean is the last step shown");
    let f = Options { x: XMode::False, ..Default::default() };
    assert_eq!(summary(&outcome("a |-> b", "a=11 b=x1", &f)), "0-0F 1-1P");
    assert_eq!(outcome("a |-> b", "a=11 b=x1", &f).attempts[0].note.as_deref(), Some("expected b at cycle 0"));
    assert_eq!(summary(&outcome("a |-> b", "a=x1 b=01", &f)), "1-1P", "an unknown antecedent is false: vacuous");
    let o = outcome("a |-> if (m) b", "a=1 m=x b=1", &Options::default());
    assert_eq!(o.attempts[0].note.as_deref(), Some("m is unknown (x) at cycle 0"));
    assert_eq!(steps(&o), "s1@0", "an if condition is no step");
}

#[test]
fn counts_lane_and_options() {
    let o = outcome("a |-> ##[1:3] b", "a=1001000 b=0000100", &Options::default());
    assert_eq!(o.stats, Stats { attempts: 7, pass: 1, fail: 1, vacuous: 5, disabled: 0, active: 0, capped: 0, matches: None });
    assert_eq!(o.lane.as_deref(), Some("S..FP.."), "start, then the fail outranks the start of the next attempt");
    assert_eq!(o.steps.iter().map(|s| format!("{} {}", s.id, s.label)).collect::<Vec<_>>(), ["s1 a", "s2 ##[1:3] b"]);
    assert_eq!(o.text, "a |-> ##[1:3] b");
    let v = Options { vacuous: true, lane: false, ..Default::default() };
    let o = outcome("a |-> b", "a=01 b=11", &v);
    assert_eq!(summary(&o), "0-0V 1-1P");
    assert_eq!(o.lane, None);
    let w = Options { from: 2, to: Some(5), ..Default::default() };
    let o = outcome("a |-> ##[1:3] b", "a=1001000 b=0000100", &w);
    assert_eq!(summary(&o), "3-4P");
    assert_eq!((o.stats.attempts, o.lane.as_deref()), (3, Some("...SP")));
    let o = outcome("disable iff (rst) a |-> ##[1:2] b", "rst=000100 a=110000 b=000000", &Options::default());
    assert_eq!(o.stats, Stats { attempts: 5, pass: 0, fail: 1, vacuous: 3, disabled: 1, active: 0, capped: 0, matches: None });
    assert_eq!(o.lane.as_deref(), Some("SSFD.."));
}

#[test]
fn thread_limit_is_reported() {
    let cap = Options { max_threads: 1, ..Default::default() };
    let o = outcome("a |-> (b ##1 c) or (b ##2 d)", "a=100 b=100 c=000 d=001", &cap);
    assert_eq!(summary(&o), "0-1C", "the second thread was dropped: no verdict, not a false fail");
    assert_eq!(o.notes, ["thread limit 1 reached at cycle 0 (attempt 0): some matches were not followed"]);
    assert_eq!((o.stats.capped, o.stats.fail, o.lane.as_deref()), (1, 0, Some("SC.")));
    assert!(o.attempts[0].note.as_deref().unwrap().contains("the result is not known"));
    let two = Options { max_threads: 2, ..Default::default() };
    assert_eq!(summary(&outcome("a |-> (b ##1 c) or (b ##2 d)", "a=100 b=100 c=000 d=001", &two)), "0-2P", "two threads are enough");
    // a capped attempt still pending at the end of the dump has no verdict either
    assert_eq!(summary(&outcome("a |-> (b ##1 c) or (b ##[2:$] d)", "a=100 b=100 c=000 d=000", &cap)), "0-1C");
    let o = outcome("a |-> (b ##1 c) or (b ##2 d)", "a=100 b=100 c=000 d=001", &Options::default());
    assert_eq!((summary(&o), o.notes.len()), ("0-2P".into(), 0));
}

#[test]
fn covers_count_matches() {
    let o = outcome("c: cover property (@(posedge clk) a ##1 b);", "a=1010 b=0101", &Options::default());
    assert_eq!(summary(&o), "0-1P 2-3P", "only matches are listed");
    assert_eq!((o.stats.pass, o.stats.fail, o.stats.matches), (2, 2, Some(2)));
    assert_eq!(o.lane.as_deref(), Some("SPSP"));
    let o = outcome("c: cover sequence (@(posedge clk) a ##[1:2] b);", "a=1000 b=0110", &Options::default());
    assert_eq!(summary(&o), "0-1P 0-2P", "every match of a cover sequence");
    assert_eq!((o.stats.pass, o.stats.matches), (1, Some(2)));
    let few = Options { cover_traces: 1, ..Default::default() };
    let o = outcome("c: cover sequence (@(posedge clk) a ##[1:2] b);", "a=1000 b=0110", &few);
    assert_eq!((summary(&o), o.stats.matches), ("0-1P".into(), Some(2)));
    let o = outcome("c: cover property (@(posedge clk) a |-> b);", "a=0110 b=0100", &Options::default());
    assert_eq!((summary(&o), o.stats.pass, o.stats.vacuous), ("1-1P".into(), 1, 2), "a vacuous pass does not cover");
}

#[test]
fn missing_signals_are_listed() {
    let o = outcome("a |-> nope", "a=1", &Options::default());
    assert_eq!(o.missing, ["nope"]);
    assert_eq!((o.stats.attempts, o.attempts.len()), (0, 0));
}

#[test]
fn trace_json_and_results_json() {
    let req = r#"{"source": "property p; @(posedge clk) disable iff (!rst_n) req |-> ##[1:3] ack; endproperty\na_req_ack: assert property (p);",
                  "trace": {"times": [10, 20, 30, 40, 50, 60], "signals": {"rst_n": [0, 1, 1, 1, 1, 1], "req": ["0", "1", "0", "0", "1", "0"], "ack": [0, 0, 1, 0, 0, "x"]}},
                  "options": {"lane": true}}"#;
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(req)).unwrap();
    assert_eq!(out["clock"], "clk");
    assert_eq!(out["unit"], "ps");
    assert_eq!(out["cycles"], serde_json::json!([10, 20, 30, 40, 50, 60]));
    let a = &out["assertions"][0];
    assert_eq!(a["name"], "a_req_ack");
    assert_eq!(a["text"], "req |-> ##[1:3] ack");
    assert_eq!(a["steps"], serde_json::json!([{"id": "s1", "label": "req", "role": "ante", "group": 0}, {"id": "s2", "label": "##[1:3] ack", "role": "cons", "group": 0}]));
    assert_eq!(a["attempts"][0], serde_json::json!({"start": 1, "end": 2, "result": "pass", "trace": [["s1", 1], ["s2", 2]], "ante_end": [1]}));
    // ack is x in the last cycle and the range goes on after the dump: active, with the note
    assert_eq!(a["attempts"][1], serde_json::json!({"start": 4, "end": 5, "result": "active", "trace": [["s1", 4], ["s2", 5]], "note": "ack is unknown (x) at cycle 5",
        "reason": {"kind": "unknown", "step": "s2", "cycle": 5}, "ante_end": [4]}));
    assert_eq!(a["stats"], serde_json::json!({"attempts": 5, "pass": 1, "fail": 0, "vacuous": 3, "disabled": 0, "active": 1, "capped": 0}));
    assert_eq!(a["lane"], ".SP.S.");
    // values: hex strings, widths, 2-state signals, the assertion filter
    let req = r#"{"source": "a: assert property (@(posedge c) d == 8'h1f);\nb: assert property (@(posedge c) $past(e) == 0);",
                  "trace": {"signals": {"d": ["h1f", "h1x"], "e": [1, 0]}, "widths": {"d": 8}, "two_state": ["e"]}, "assert": ["a"]}"#;
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(req)).unwrap();
    assert_eq!(out["assertions"].as_array().unwrap().len(), 1);
    assert_eq!(out["assertions"][0]["attempts"][1]["note"], "d == 8'h1f is unknown (x) at cycle 1");
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(&req.replace(r#""assert": ["a"]"#, r#""assert": ["b"]"#))).unwrap();
    assert_eq!(out["assertions"][0]["attempts"][0]["result"], "pass", "$past of a 2-state signal before the dump is 0");
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(&req.replace(r#""assert": ["a"]"#, r#""assert": ["zz"]"#))).unwrap();
    assert_eq!(out["errors"][0]["msg"], "no assertion 'zz'");
    // an unknown top digit fills the width ('hx is 8 unknown bits of an 8-bit bus), a known one zero-extends
    let req = r#"{"source": "a: assert property (@(posedge c) $isunknown(d[7:4]));", "trace": {"signals": {"d": ["hx", "h0", "x", null, "h1x"]}, "widths": {"d": 8}}}"#;
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(req)).unwrap();
    let res: Vec<&str> = out["assertions"][0]["attempts"].as_array().unwrap().iter().map(|a| a["result"].as_str().unwrap()).collect();
    assert_eq!(res, ["pass", "fail", "pass", "pass", "fail"]);
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(r#"{"source": "a: assert property (@(posedge c) d);", "trace": {"signals": {"d": ["2"]}}}"#)).unwrap();
    assert!(out["errors"][0]["msg"].as_str().unwrap().contains("'2' is not a value"), "{out}");
}

// ---- attempts in the same state are stepped once

/// (start, end, result, failed_at, note) of every attempt, and the trace of every attempt.
type Shape = Vec<(usize, usize, Status, Option<usize>, Option<String>)>;

fn shape(o: &Outcome) -> (Shape, Vec<String>) {
    let a = o.attempts.iter().map(|a| (a.start, a.end, a.result, a.failed_at, a.note.clone())).collect();
    let t = o.attempts.iter().map(|a| a.trace.iter().map(|s| format!("{}@{}", s.id, s.cycle)).collect::<Vec<_>>().join(" ")).collect();
    (a, t)
}

#[test]
fn merged_attempts_give_the_same_results() {
    let props = [
        "a |-> ##[1:3] b", "a |=> b[*1:$] ##1 c", "a ##[0:2] b |-> c", "a |-> b[->2] ##1 c", "a |-> b[=2] ##1 c",
        "(a |-> b) or (c |-> ##1 d)", "(a |-> ##[1:4] b) and (c |=> d)", "not (a ##1 b)", "a |-> b throughout (c ##2 d)",
        "first_match(a ##[1:3] b) |-> c", "a |-> (b ##1 c) within (d ##[2:4] e)", "a |-> b[*1:5] intersect (c ##[1:6] d)",
        "a |-> always [1:3] b", "a |-> eventually [1:4] b", "a |-> s_eventually b", "a |-> nexttime [2] b",
        "a |-> if (b) ##1 c else ##2 d", "a ##1 b |-> ##[0:$] c ##1 d", "a |-> ##[1:$] b ##[1:2] c", "a #-# ##[0:3] b",
    ];
    let mut seed = 0x2545f4914f6cdd1du64;
    let mut bits = |n: usize, p: u64| {
        (0..n).map(|_| {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            if seed % 100 < p { '1' } else { '0' }
        }).collect::<String>()
    };
    let mut merged_traces_differ = 0;
    for prop in props {
        for round in 0..6 {
            let sigs = format!("a={} b={} c={} d={} e={}", bits(48, 30 + 10 * round), bits(48, 50), bits(48, 40), bits(48, 30), bits(48, 50));
            let one = outcome(prop, &sigs, &Options { merge: true, vacuous: true, ..Options::default() });
            let each = outcome(prop, &sigs, &Options { merge: false, vacuous: true, ..Options::default() });
            let (s1, t1) = shape(&one);
            let (s2, t2) = shape(&each);
            assert_eq!(s1, s2, "{prop} over {sigs}");
            assert_eq!(one.stats, each.stats, "{prop} over {sigs}");
            assert_eq!(one.lane, each.lane, "{prop} over {sigs}");
            merged_traces_differ += t1.iter().zip(&t2).filter(|(x, y)| x != y).count();
        }
    }
    // a merged attempt shows its own steps up to the merge, then the steps of the first attempt of its group: the
    // same steps, except where a thread set held several paths before the merge
    assert!(merged_traces_differ < 40, "{merged_traces_differ} traces differ");
}

#[test]
fn a_long_attempt_keeps_its_first_and_last_steps() {
    let n = 300;
    let sigs = format!("a=1{} b={} c={}", "0".repeat(n - 1), "1".repeat(n), "0".repeat(n));
    let o = outcome("a |-> b[*1:$] ##1 c", &sigs, &Options::default());
    assert_eq!(summary(&o), format!("0-{}A", n - 1));
    let a = &o.attempts[0];
    assert!(a.truncated && a.trace.len() == HEAD + TAIL, "{} steps", a.trace.len());
    assert_eq!((a.trace[0].id.as_str(), a.trace[0].cycle, a.trace[1].cycle), ("s1", 0, 0));
    assert_eq!(a.trace.last().unwrap().cycle, n - 1);
    let short = outcome("a |-> b[*1:$] ##1 c", "a=1000 b=1110 c=0001", &Options::default());
    assert!(!short.attempts[0].truncated);
}

#[test]
fn open_attempts_stay_cheap() {
    // every cycle starts an attempt that never ends: one group, linear time and memory
    let n = 20000;
    let sigs = format!("a={} b={} c={}", "1".repeat(n), "1".repeat(n), "0".repeat(n));
    let t = std::time::Instant::now();
    let o = outcome("a |-> b[*1:$] ##1 c", &sigs, &Options { lane: false, ..Options::default() });
    assert_eq!((o.stats.attempts, o.stats.active), (n, n));
    assert_eq!(o.attempts[n - 1].trace[0].cycle, n - 1);
    assert!(t.elapsed().as_secs_f64() < 5.0, "{:?}", t.elapsed());
}

#[test]
fn the_path_arena_is_collected() {
    // attempts in different states (the repetition count) do not merge; their paths are collected and renumbered
    let n = 3000;
    let sigs = format!("a={} b={} c={}", "1".repeat(n), "1".repeat(n), "0".repeat(n));
    let o = outcome("a |-> b[*1:40] ##1 c", &sigs, &Options::default());
    assert_eq!(o.stats.fail, n - 40);
    for a in o.attempts.iter().filter(|a| a.result == Status::Fail) {
        assert_eq!((a.end, a.trace[0].cycle, a.trace.len()), (a.start + 40, a.start, 41), "{a:?}");
        assert!(a.trace.windows(2).all(|w| w[0].cycle <= w[1].cycle));
    }
}

// ---- unknown values: x reads as false; a non-vacuous pass stands, anything else that read an x fails naming it

cases! {
    x_in_a_branch_that_does_not_decide: "a |-> (b ##1 b) or (d ##1 e)", "a=10 b=11 d=x0 e=00" => "0-1P";
    x_in_a_property_or: "(a |-> b) or (c |-> d)", "a=1 b=1 c=x d=0" => "0-0P";
    x_before_the_goto_hit: "a |-> b[->1]", "a=100 b=0x1" => "0-2P";
    x_that_decides_fails: "a |-> (b ##1 b) or (d ##1 e)", "a=10 b=10 d=x0 e=00" => "0-1F";
    x_in_the_antecedent_fails: "a |-> ##1 b", "a=x0 b=00" => "0-0F";
}

#[test]
fn unknown_values_decide_with_the_attempt() {
    let o = outcome("a |-> (b ##1 b) or (d ##1 e)", "a=10 b=10 d=x0 e=00", &Options::default());
    let a = &o.attempts[0];
    assert_eq!((a.failed_at, a.end, a.note.as_deref()), (Some(0), 1, Some("d is unknown (x) at cycle 0")), "failed at the read, decided later");
    // the IEEE results with x: "false"
    let f = Options { x: XMode::False, ..Default::default() };
    assert_eq!(summary(&outcome("a |-> (b ##1 b) or (d ##1 e)", "a=10 b=11 d=x0 e=00", &f)), "0-1P");
    assert_eq!(summary(&outcome("(a |-> b) or (c |-> d)", "a=1 b=1 c=x d=0", &f)), "0-0P");
    assert_eq!(summary(&outcome("a |-> b[->1]", "a=100 b=0x1", &f)), "0-2P");
    assert_eq!(summary(&outcome("a |-> (b ##1 b) or (d ##1 e)", "a=10 b=10 d=x0 e=00", &f)), "0-1F");
    assert_eq!(summary(&outcome("a |-> ##1 b", "a=x0 b=00", &f)), "", "an unknown antecedent is false: vacuous");
    // still pending at the end: active, with the note
    let o = outcome("a |-> b[->1]", "a=100 b=0x0", &Options::default());
    assert_eq!((summary(&o), o.attempts[0].note.as_deref()), ("0-2A".into(), Some("b is unknown (x) at cycle 1")));
    // a strong operator that fails at the end says both
    let o = outcome("a |-> s_eventually b", "a=100 b=0x0", &Options::default());
    assert_eq!(o.attempts[0].note.as_deref(), Some("not seen before the end of the dump; b is unknown (x) at cycle 1"));
}

// ---- traces of passing attempts cover start..end; or does not depend on the order; s_always; inside; notes

#[test]
fn passing_traces_have_every_consequent() {
    // two antecedent matches (end 0 and 1), two consequents (c at 1 and at 2): the trace shows both
    let o = outcome("a ##[0:1] b |-> ##1 c", "a=1000 b=1100 c=0110", &Options::default());
    assert_eq!((summary(&o), steps(&o)), ("0-2P".into(), "s1@0 s2@0 s2@1 s3@1 s3@2".into()));
    let o = outcome("a |-> always [1:2] b", "a=1000 b=0110", &Options::default());
    assert_eq!((summary(&o), steps(&o)), ("0-2P".into(), "s1@0 s2@1 s2@2".into()));
    let o = outcome("a |-> eventually [1:3] b", "a=1000 b=0010", &Options::default());
    assert_eq!((summary(&o), steps(&o)), ("0-2P".into(), "s1@0 s2@2".into()));
    let o = outcome("a |-> nexttime [2] b", "a=1000 b=0010", &Options::default());
    assert_eq!((summary(&o), steps(&o)), ("0-2P".into(), "s1@0 s2@2".into()));
}

cases! {
    or_vacuous_first_waits_for_the_other: "(a |-> b) or (c |-> d)", "a=0 b=0 c=1 d=1" => "0-0P";
    or_vacuous_second: "(c |-> d) or (a |-> b)", "a=0 b=0 c=1 d=1" => "0-0P";
    or_vacuous_waits_later: "(a |-> b) or (c |-> ##1 d)", "a=00 b=00 c=10 d=01" => "0-1P";
    s_always_range_covered_inner_open: "s_always [0:1] (a |-> ##[1:$] b)", "a=10 b=00" => "0-1A 1-1F";
    inside_wildcard: "st inside {2'b1x}", "st:2=2,3,1,b0x" => "0-0P 1-1P 2-2F 3-3F";
}

#[test]
fn or_settles_at_the_end_of_the_dump() {
    // one side vacuous, the other still open when the dump ends: the or holds (vacuously), it is not active
    let v = Options { vacuous: true, ..Default::default() };
    assert_eq!(summary(&outcome("(a |-> b) or (c |-> ##[1:$] d)", "a=00 b=00 c=10 d=00", &v)), "0-0V 1-1V");
    let o = outcome("(a |-> b) or (c |-> d)", "a=0 b=0 c=0 d=0", &v);
    assert_eq!(summary(&o), "0-0V", "both vacuous");
    let o = outcome("(a |-> b) or (c |-> d)", "a=1 b=0 c=1 d=0", &Options::default());
    assert_eq!(summary(&o), "0-0F");
}

#[test]
fn inside_reads_x_in_the_value_not_in_the_set() {
    let o = outcome("st inside {2'b10}", "st:2=b1x", &Options::default());
    assert_eq!(o.attempts[0].note.as_deref(), Some("st inside {2'b10} is unknown (x) at cycle 0"));
}

#[test]
fn short_columns_and_wide_values_are_noted() {
    let req = r#"{"source": "a: assert property (@(posedge c) d != 0);", "trace": {"cycles": 3, "signals": {"d": ["h1ffffffffffffffff", "h2"]}}}"#;
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(req)).unwrap();
    let notes = &out["assertions"][0]["notes"];
    assert_eq!(notes[0], "d: values wider than 64 bits keep their low 64 bits (cycle 0)");
    let req = r#"{"source": "a: assert property (@(posedge c) d);", "trace": {"cycles": 3, "signals": {"d": ["1"]}}}"#;
    let out: serde_json::Value = serde_json::from_str(&crate::run_json(req)).unwrap();
    assert_eq!(out["assertions"][0]["notes"][0], "d: 1 values for 3 cycles; the later cycles read its initial value (x)");
}

// ---- roles of the steps, antecedent matches, reasons

#[test]
fn steps_have_roles() {
    let o = outcome("a |=> (b throughout (c ##1 d)) |-> e", "a=0 b=0 c=0 d=0 e=0", &Options::default());
    let r: Vec<_> = o.steps.iter().map(|s| format!("{}:{}{}", s.id, s.role, s.group.map_or(String::new(), |g| g.to_string()))).collect();
    assert_eq!(r, ["s1:ante0", "s2:cond1", "s3:ante1", "s4:ante1", "s5:cons1"]);
    let o = outcome("a ##1 b", "a=0 b=0", &Options::default());
    assert_eq!(o.steps.iter().map(|s| s.role).collect::<Vec<_>>(), ["seq", "seq"]);
}

#[test]
fn antecedent_matches_are_listed() {
    // the latency a statistics table shows: consequent match cycle - antecedent match cycle
    let o = outcome("a ##[0:1] b |-> ##[1:2] c", "a=10000 b=11000 c=00100", &Options::default());
    assert_eq!((summary(&o), &o.attempts[0].ante_end), ("0-2P".into(), &vec![0, 1]));
    // merged attempts keep their own antecedent matches
    let n = 50;
    let sigs = format!("a={} b={} c={}", "1".repeat(n), "1".repeat(n), "0".repeat(n));
    let o = outcome("a |-> b[*1:$] ##1 c", &sigs, &Options::default());
    assert!(o.attempts.iter().all(|a| a.ante_end == [a.start]), "{:?}", o.attempts.iter().map(|a| &a.ante_end).collect::<Vec<_>>());
}

#[test]
fn reasons_name_the_kind_step_and_cycle() {
    let r = |prop: &str, sigs: &str, opt: &Options| {
        let o = outcome(prop, sigs, opt);
        let a = o.attempts.iter().find(|a| a.reason.is_some()).unwrap_or_else(|| panic!("{prop}: {:?}", o.attempts));
        let x = a.reason.as_ref().unwrap();
        format!("{} {} {}", x.kind, x.step.clone().unwrap_or_default(), x.cycle)
    };
    let d = Options::default();
    assert_eq!(r("a |-> b", "a=1 b=0", &d), "expected s2 0");
    assert_eq!(r("a |-> ##[1:2] b", "a=100 b=000", &d), "range s2 2");
    assert_eq!(r("a |-> b", "a=1 b=x", &d), "unknown s2 0");
    assert_eq!(r("not (a ##1 b)", "a=11 b=11", &d), "not_held  1");
    assert_eq!(r("a |-> s_eventually b", "a=10 b=00", &d), "strong_end  1");
    assert_eq!(r("a |-> eventually [1:2] b", "a=1000 b=0000", &d), "range  2");
    assert_eq!(r("a |-> (b ##1 c) or (b ##2 d)", "a=100 b=100 c=000 d=001", &Options { max_threads: 1, ..d.clone() }), "capped  1");
}

#[test]
fn throughout_condition_in_the_trace() {
    // the condition of throughout is a step of the trace at every cycle it held (its row in the page is not empty)
    let o = outcome("t: cover property (@(posedge clk) c throughout (a ##1 b));", "c=111 a=100 b=010", &Options::default());
    let t: Vec<(String, usize)> = o.attempts[0].trace.iter().map(|s| (s.id.clone(), s.cycle)).collect();
    assert!(t.contains(&("s1".into(), 0)) && t.contains(&("s1".into(), 1)), "{t:?}");
    assert_eq!(o.steps.iter().find(|s| s.id == "s1").map(|s| s.role), Some("cond"));
    // broken at cycle 1: the trace has the condition at 0, the failure names it
    let o = outcome("a |-> b throughout (c ##1 d)", "a=10 b=10 c=10 d=01", &Options::default());
    assert_eq!(summary(&o), "0-1F");
    assert!(o.attempts[0].trace.iter().any(|s| s.id == "s2" && s.cycle == 0), "{:?}", o.attempts[0].trace);
}

#[test]
fn repetition_of_a_sequence_that_can_match_empty() {
    // (a[*0:1])[*2] is a[*0:2] (an iteration may be empty: IEEE 1800-2017 16.9.2), not an error and not a stricter rule
    for prop in ["c |-> ##1 (a[*0:1])[*2] ##1 b", "c |-> ##1 a[*0:2] ##1 b"] {
        check(prop, "c=1000 a=0100 b=0010", "0-2P");
        check(prop, "c=1000 a=0000 b=0100", "0-1P");
        check(prop, "c=1000 a=0110 b=0001", "0-3P");
    }
    check("c |-> (a[*0:1])[*3:4] ##1 b", "c=100 a=000 b=100", "0-0P");
}

#[test]
fn a_pass_decided_by_an_unknown_has_a_note() {
    // m is x at cycle 0: the if takes its else branch and c holds; the pass stands (the x policy) but says so
    let o = outcome("a |-> if (m) b else c", "a=1 m=x b=0 c=1", &Options::default());
    assert_eq!(summary(&o), "0-0P");
    assert_eq!(o.attempts[0].note.as_deref(), Some("m is unknown (x) at cycle 0, read as false: the attempt passed with it"));
    let o = outcome("a |-> if (m) b else c", "a=1 m=0 b=0 c=1", &Options::default());
    assert_eq!(o.attempts[0].note, None);
}
