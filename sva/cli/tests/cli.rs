//! The sva binary end to end: `sva parse` (text, --json, -D, several files as one unit, exit codes) and the evaluation
//! over a small VCD written here.

use std::path::PathBuf;
use std::process::{Command, Output};

fn dir() -> PathBuf {
    let d = std::env::temp_dir().join(format!("sva-cli-test-{}", std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// A file of the tests' directory, written whole before it gets its name: tests run in parallel and some write the
/// same file (a reader never sees it half written).
fn write(name: &str, text: &str) -> String {
    let p = dir().join(name);
    let tmp = dir().join(format!("{name}.{:?}.tmp", std::thread::current().id()));
    std::fs::write(&tmp, text).unwrap();
    std::fs::rename(&tmp, &p).unwrap();
    p.to_string_lossy().into_owned()
}

fn sva(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_sva")).args(args).output().unwrap()
}

fn out(o: &Output) -> String {
    String::from_utf8_lossy(&o.stdout).into_owned()
}
fn err(o: &Output) -> String {
    String::from_utf8_lossy(&o.stderr).into_owned()
}

#[test]
fn parse_prints_the_assertions() {
    let f = write("ok.sv", "module m(input logic clk, req, ack);\n  a_req: assert property (@(posedge clk) req |-> ##[1:3] ack) else $error(\"late\");\nendmodule\n");
    let o = sva(&["parse", &f]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    assert!(t.contains("assert a_req in m, line 2"), "{t}");
    assert!(t.contains("  s2        ##[1:3] ack"), "{t}");
    assert!(t.contains("  message   error \"late\""), "{t}");
}

#[test]
fn parse_errors_exit_1_with_a_caret() {
    let f = write("bad.sv", "a: assert property (@(posedge clk) req |-> ##[3:1] ack);\nb: assert property (@(posedge clk) x);\n");
    let o = sva(&["parse", &f]);
    assert_eq!(o.status.code(), Some(1));
    let t = out(&o);
    assert!(t.contains("bad.sv:1:49: error: the range ends before it starts (3:1)"), "{t}");
    assert!(t.contains("    1 | a: assert property (@(posedge clk) req |-> ##[3:1] ack);\n      |                                                 ^\n"), "{t}");
    assert!(t.contains("assert b, line 2"), "the next assertion still loads:\n{t}");
}

#[test]
fn parse_json() {
    let f = write("j.sv", "a: assert property (@(posedge c) x |=> y);\n");
    let o = sva(&["parse", "--json", &f]);
    assert_eq!(o.status.code(), Some(0));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["files"][0]["file"], f.as_str());
    assert_eq!(v["files"][0]["assertions"][0]["prop"]["op"], "|=>");
    assert_eq!(v["files"][0]["assertions"][0]["elements"][1]["id"], "s2");
}

#[test]
fn defines_and_several_files() {
    let pkg = write("pkg.sv", "package p; typedef enum logic [1:0] {IDLE, BUSY} st_t; endpackage\n");
    let chk = write("chk.sv", "module m import p::*; (input logic clk, input st_t st);\n`ifdef STRICT\n  s: assert property (@(posedge clk) st == BUSY |=> st == IDLE);\n`else\n  l: assert property (@(posedge clk) st == BUSY |-> ##[1:4] st == IDLE);\n`endif\nendmodule\n");
    let t = out(&sva(&["parse", &pkg, &chk]));
    assert!(t.contains("assert l in m") && t.contains("signals   clk:1 st:2"), "{t}");
    let t = out(&sva(&["parse", "-D", "STRICT", &pkg, &chk]));
    assert!(t.contains("assert s in m"), "{t}");
    let t = out(&sva(&["parse", "-DSTRICT=1", &pkg, &chk]));
    assert!(t.contains("assert s in m"), "{t}");
    // without the package the enum labels are signals, and a warning says why
    let t = out(&sva(&["parse", &chk]));
    assert!(t.contains("warning: package 'p' is not loaded"), "{t}");
    assert!(t.contains("signals   clk:1 st BUSY IDLE"), "{t}");
}

#[test]
fn usage_errors_exit_2() {
    assert_eq!(sva(&["parse"]).status.code(), Some(2));
    assert_eq!(sva(&["parse", "--bogus", "x.sv"]).status.code(), Some(2));
    assert_eq!(sva(&["parse", "/no/such/file.sv"]).status.code(), Some(2));
    assert_eq!(sva(&[]).status.code(), Some(2));
    assert!(out(&sva(&["parse", "--help"])).contains("usage: sva parse"));
    for h in ["-h", "--help"] {
        let r = sva(&["report", h]);
        assert!(r.status.success() && out(&r).contains("sva report"), "sva report {h}");
    }
}

const VCD: &str = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 \" req $end\n$var wire 1 # ack $end\n\
$upscope $end\n$enddefinitions $end\n#0\n0!\n0\"\n0#\n#5\n1!\n#10\n0!\n1\"\n#15\n1!\n#20\n0!\n0\"\n1#\n#25\n1!\n#30\n0!\n0#\n#35\n1!\n#40\n0!\n";

#[test]
fn evaluates_over_a_vcd() {
    // sampled before each rising edge (5, 15, 25, 35 ns): req = 0 1 0 0, ack = 0 0 1 0
    let vcd = write("t.vcd", VCD);
    let pass = write("pass.sva", "a_next: assert property (@(posedge clk) req |=> ack);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &pass]);
    assert_eq!(o.status.code(), Some(0), "{}{}", out(&o), err(&o));
    assert!(out(&o).contains("a_next assert 4 attempts: 1 pass, 0 fail, 3 vacuous, 0 active, 0 disabled"), "{}", out(&o));
    // the old form, the same
    let o = sva(&[&pass, "--waves", &vcd, "--scope", "tb"]);
    assert!(out(&o).contains("4 attempts: 1 pass"), "{}", out(&o));
    let fail = write("fail.sva", "a_same: assert property (@(posedge clk) req |-> ack);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &fail, "--json"]);
    assert_eq!(o.status.code(), Some(1));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["clock"], "tb.clk");
    assert_eq!(v["unit"], "ps");
    assert_eq!(v["cycles"], serde_json::json!([5000, 15000, 25000, 35000]));
    let a = &v["assertions"][0];
    assert_eq!(a["stats"]["fail"], 1);
    assert_eq!(a["attempts"][0], serde_json::json!({"start": 1, "end": 1, "result": "fail", "trace": [["s1", 1]], "failed_at": 1, "note": "expected ack at cycle 1",
        "reason": {"kind": "expected", "step": "s2", "cycle": 1}, "ante_end": [1]}));
    assert_eq!(a["steps"], serde_json::json!([{"id": "s1", "label": "req", "role": "ante", "group": 0}, {"id": "s2", "label": "ack", "role": "cons", "group": 0}]));
    assert_eq!(a["signals"], serde_json::json!({"ack": "tb.ack", "clk": "tb.clk", "req": "tb.req"}));
    assert_eq!((a["file"].as_str(), a["scope"].as_str(), a["line"].as_u64()), (Some(fail.as_str()), Some("tb"), Some(1)));
    assert_eq!(a["lane"], ".F..");
    assert!(out(&o).contains("\"text\": \"req |-> ack\""));
    // --out, --assert, --from / --to, --attempts
    let both = write("both.sva", "a_next: assert property (@(posedge clk) req |=> ack);\na_same: assert property (@(posedge clk) req |-> ack);\n");
    let res = dir().join("res.json");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &both, "--assert", "a_next", "--out", res.to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&res).unwrap()).unwrap();
    assert_eq!(v["assertions"].as_array().unwrap().len(), 1);
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &both, "--from", "20ns", "--to", "40ns", "--attempts"]);
    assert_eq!(o.status.code(), Some(0), "the failing attempt starts before --from:\n{}", out(&o));
    assert!(out(&o).contains("a_same assert 2 attempts: 0 pass, 0 fail, 2 vacuous"), "{}", out(&o));
    // the cycles of the window: as many as the lane, none after --to
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &both, "--to", "40ns", "--json"]);
    let v: serde_json::Value = serde_json::from_str(&out(&o)).unwrap();
    assert_eq!(v["cycles"].as_array().unwrap().len(), v["assertions"][0]["lane"].as_str().unwrap().len(), "{v}");
    assert!(v["cycles"].as_array().unwrap().iter().all(|t| t.as_u64().unwrap() <= 40_000), "{v}");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &both, "--attempts"]);
    assert!(out(&o).contains("  @1..1 (15 ns) Fail [s1@1]  -- expected ack at cycle 1"), "{}", out(&o));
    assert_eq!(sva(&["eval", "--waves", &vcd, "--sva", &both, "--assert", "nope"]).status.code(), Some(2));
    // names the dump does not have: listed, the assertion skipped, exit 2
    let missing = write("missing.sva", "a: assert property (@(posedge clk) req |-> nope && gone);\nb: assert property (@(posedge clk) req |=> ack);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &missing]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("sva: a: no nope, gone in scope 'tb' (not evaluated)"), "{}", err(&o));
    assert!(out(&o).contains("b assert 4 attempts: 1 pass"), "{}", out(&o));
    let res = dir().join("missing.json");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &missing, "--out", res.to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(2));
    let doc: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&res).unwrap()).unwrap();
    let a = &doc["assertions"][0];
    assert_eq!((a["name"].as_str(), a["missing"].clone(), a["stats"]["attempts"].as_u64()), (Some("a"), serde_json::json!(["nope", "gone"]), Some(0)));
    assert_eq!(a["signals"]["req"], "tb.req");
    assert_eq!(doc["assertions"][1]["stats"]["pass"], 1);
    // a name resolves in the scopes above --scope too
    let up = write("up.sva", "a: assert property (@(posedge clk) req |=> ack);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb.u_dut.u_sub", "--sva", &up]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    // --resolve scope (the page's binding rules): only the clock is looked up above the scope
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb.u_dut.u_sub", "--sva", &up, "--resolve", "scope"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("sva: a: no req, ack in scope 'tb.u_dut.u_sub' (not evaluated)"), "{}", err(&o));
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &up, "--resolve", "scope"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert_eq!(sva(&["eval", "--waves", &vcd, "--sva", &up, "--resolve", "down"]).status.code(), Some(2));
    // parse errors stop the evaluation: nothing was checked (2)
    let bad = write("bad.sva", "a: assert property (@(posedge clk) req |-> );\n");
    let o = sva(&["eval", "--waves", &vcd, "--sva", &bad]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("bad.sva:1:44: error: expected an expression, found ')'"), "{}", err(&o));
    // usage
    assert_eq!(sva(&["eval", "--waves", &vcd]).status.code(), Some(2));
    assert_eq!(sva(&["eval", "--waves", &vcd, "--sva", &up, "--from", "3 parsecs"]).status.code(), Some(2));
    assert!(out(&sva(&["eval", "--help"])).contains("usage: sva parse"));
}

#[test]
fn covers_and_unknown_values() {
    // x until 10 ns: the first sample of req is x
    let vcd = write("x.vcd", &VCD.replace("#0\n0!\n0\"\n0#\n", "#0\n0!\nx\"\n0#\n"));
    let f = write("x.sva", "a: assert property (@(posedge clk) req |-> 1);\nc: cover property (@(posedge clk) req ##1 ack);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &f]);
    assert_eq!(o.status.code(), Some(1));
    assert!(out(&o).contains("first fail at cycle 0 (5 ns): req is unknown (x) at cycle 0"), "{}", out(&o));
    assert!(out(&o).contains("c cover  1 match in 4 attempts · first at cycle 2 (25 ns)"), "{}", out(&o));
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &f, "--x", "false"]);
    assert_eq!(o.status.code(), Some(0), "{}", out(&o));
}

#[test]
fn reports_markdown_junit_and_sva_report() {
    let vcd = write("r.vcd", VCD);
    let both = write("rboth.sva", "a_next: assert property (@(posedge clk) req |=> ack);\na_same: assert property (@(posedge clk) req |-> ack);\nc_req: cover property (@(posedge clk) req);\n");
    let (md, xml, res) = (dir().join("r.md"), dir().join("r.xml"), dir().join("r.json"));
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &both, "--report", md.to_str().unwrap(), "--junit", xml.to_str().unwrap(), "--out", res.to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(1), "a failure: exit 1 for CI\n{}", err(&o));
    let m = std::fs::read_to_string(&md).unwrap();
    assert!(m.contains("**Totals:** 3 assertions (3 evaluated, 1 with failures): 8 attempts, 1 pass, 1 fail, 6 vacuous"), "{m}");
    assert!(m.contains("| `a_next` | tb | assert | 4 | 1 | 0 | 3 | 0 | 0 | 0 | — | — | 1 | 1 / 1.0 / 1 |"), "{m}");
    assert!(m.contains("| 1 | `a_same` | tb | 15 ns (cycle 1) | 15 ns (cycle 1) | expected | expected ack at cycle 1 |"), "{m}");
    let x = std::fs::read_to_string(&xml).unwrap();
    assert!(x.contains("<testsuite name=\"Assertions\" tests=\"3\" failures=\"1\" errors=\"0\" skipped=\"0\" time=\"0\">"), "{x}");
    assert!(x.contains("name=\"a_same\"") && x.contains("<failure type=\"expected\" message=\"1 fail of 4 attempts; first at 15 ns: expected ack at cycle 1\">"), "{x}");
    // sva report over the results document: the same Markdown (but the tool line), exit 1
    let o = sva(&["report", res.to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(1));
    assert!(out(&o).contains("| 1 | `a_same` | tb | 15 ns (cycle 1)"), "{}", out(&o));
    let h = dir().join("r.html");
    let o = sva(&["report", "--html", h.to_str().unwrap(), "--json", "-", res.to_str().unwrap()]);
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!((v["totals"]["fail"].as_u64(), v["failures"][0]["name"].as_str(), v["assertions"][2]["covered"].as_u64()), (Some(1), Some("a_same"), Some(1)));
    assert!(std::fs::read_to_string(&h).unwrap().contains("<section class=\"sva-report\" id=\"assertions\">"));
}

#[test]
fn ignored_prefixes_and_wide_selects() {
    // the page's rule: a name also matches without the sortIgnore prefixes; a select wider than the variable does not bind
    let vcd = write("p.vcd", &VCD.replace("$var wire 1 \" req $end", "$var wire 1 \" s_req $end"));
    let f = write("p.sva", "a: assert property (@(posedge clk) req |=> ack);\nw: assert property (@(posedge clk) ack[3:0] == 0);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--resolve", "scope", "--sva", &f, "--assert", "a"]);
    assert_eq!(o.status.code(), Some(2), "req is not there without the prefixes:\n{}", err(&o));
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--resolve", "scope", "--ignore-prefix", "i_,s_", "--sva", &f, "--assert", "a", "--json"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["assertions"][0]["signals"]["req"], "tb.s_req");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--resolve", "scope", "--sva", &f, "--assert", "w"]);
    assert!(o.status.code() == Some(2) && err(&o).contains("ack (a select needs 4 bits, tb.ack has 1)"), "{}", err(&o));
}

#[test]
fn exit_codes_and_report_inputs() {
    let vcd = write("e.vcd", VCD);
    let both = write("eboth.sva", "a_next: assert property (@(posedge clk) req |=> ack);\na_same: assert property (@(posedge clk) req |-> ack);\n");
    // a dump that is not there, a file without assertions: 2, not an abort or a green run
    let o = sva(&["eval", "--waves", "nofile.vcd", "--sva", &both]);
    assert!(o.status.code() == Some(2) && err(&o).contains("nofile.vcd"), "{:?} {}", o.status, err(&o));
    let none = write("none.sva", "module m; endmodule\n");
    let o = sva(&["eval", "--waves", &vcd, "--sva", &none]);
    assert!(o.status.code() == Some(2) && err(&o).contains("nothing to check"), "{}", err(&o));
    // the thread limit: no verdict is not a pass (1); --max-threads raises it
    let cap = write("cap.sva", "c: assert property (@(posedge clk) req |-> ##[0:3] ack ##[0:3] ack ##[0:3] ack);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &cap, "--max-threads", "1"]);
    assert!(o.status.code() == Some(1) && out(&o).contains("capped"), "{}", out(&o));
    // --report x.json: the page's report.json form, which sva report reads back with its failures
    let rj = dir().join("e.json");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &both, "--report", rj.to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(1));
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&rj).unwrap()).unwrap();
    assert!(v["meta"]["dump"].is_string() && v["results"][0]["assertions"].is_array(), "{v}");
    let o = sva(&["report", rj.to_str().unwrap()]);
    assert!(o.status.code() == Some(1) && out(&o).contains("## Failures (1)") && out(&o).contains("| 1 | `a_same`"), "{}", out(&o));
    // a summary is refused; so is anything that is not results
    let sj = dir().join("e.sum.json");
    sva(&["report", "--json", sj.to_str().unwrap(), rj.to_str().unwrap()]);
    let o = sva(&["report", sj.to_str().unwrap()]);
    assert!(o.status.code() == Some(2) && err(&o).contains("summary"), "{}", err(&o));
    for (k, bad) in ["{}", "[]", "42", "{\"results\": 5}"].iter().enumerate() {
        let f = write(&format!("bad{k}.json"), bad);
        assert_eq!(sva(&["report", &f]).status.code(), Some(2), "{bad}");
    }
    // two files: each row and failure with its file, the meta of the first, --title wins
    let rj2 = dir().join("e2.json");
    std::fs::copy(&rj, &rj2).unwrap();
    let o = sva(&["report", "--title", "Nightly", "--junit", "-", rj.to_str().unwrap(), rj2.to_str().unwrap()]);
    let x = out(&o);
    assert!(x.contains("name=\"Nightly\"") && x.matches("classname=\"tb [").count() == 4 && x.matches("expected ack at cycle 1\n").count() == 2, "{x}");
}

#[test]
fn aliases_ambiguous_prefixes_and_widths() {
    // tb has i_req, o_req (both "req" without the prefixes) and a 1-bit ack
    let vcd = write("a.vcd", &VCD.replace("$var wire 1 \" req $end", "$var wire 1 \" i_req $end\n$var wire 1 \" o_req $end"));
    let f = write("a.sva", "a: assert property (@(posedge clk) req |=> ack);\nb: assert property (@(posedge clk) rdy |-> ack);\nw: assert property (@(posedge clk) ack[3:0] == 0);\n");
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--resolve", "scope", "--ignore-prefix", "i_,o_", "--sva", &f, "--assert", "a"]);
    assert!(o.status.code() == Some(2) && err(&o).contains("req (ambiguous: tb.i_req or tb.o_req)"), "{}", err(&o));
    // the shown name of a config: rdy is tb.ack
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--resolve", "scope", "--alias", "rdy=tb.ack", "--sva", &f, "--assert", "b", "--json"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["assertions"][0]["signals"]["rdy"], "tb.ack");
    // an escaped identifier with a dot is one name, not a scope and a variable
    let ev = write("esc.vcd", &VCD.replace("$var wire 1 # ack $end", "$var wire 1 # \\esc.x $end"));
    let fe = write("esc.sva", "e: assert property (@(posedge clk) req |=> \\esc.x );\n");
    let o = sva(&["eval", "--waves", &ev, "--scope", "tb", "--resolve", "scope", "--sva", &fe, "--json"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["assertions"][0]["signals"]["\\esc.x"], "tb.\\esc.x");
    // a select wider than the variable does not bind with the default resolution either
    let o = sva(&["eval", "--waves", &vcd, "--scope", "tb", "--sva", &f, "--assert", "w"]);
    assert!(o.status.code() == Some(2) && err(&o).contains("a select needs 4 bits"), "{}", err(&o));
}

/// A clock and two signals; `body` the value changes.
fn clock_dump(name: &str, timescale: &str, body: &str) -> String {
    write(name, &format!("$timescale {timescale} $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 \" req $end\n$var wire 1 # ack $end\n$upscope $end\n$enddefinitions $end\n{body}"))
}

fn checks() -> String {
    write("edges.sv", "module tb;\n  a_req: assert property (@(posedge clk) req |-> ack);\n  a_neg: assert property (@(negedge clk) req |-> ack);\nendmodule\n")
}

fn cycles(o: &Output) -> Vec<u64> {
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap_or_default();
    v["cycles"].as_array().map(|a| a.iter().filter_map(|x| x.as_u64()).collect()).unwrap_or_default()
}

#[test]
fn one_edge_per_time_step() {
    // a glitch written in one time step (1 0 1 at #5) is no edge of its own: one cycle there, not two
    let d = clock_dump("glitch.vcd", "1ns", "#0\nx!\n1\"\n1#\n#5\n1!\n0!\n1!\n#10\n0!\n#15\n1!\n#20\n0!\n");
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &checks(), "--assert", "a_req", "--json"]);
    assert_eq!(cycles(&o), [5000, 15000], "{}", err(&o));
}

#[test]
fn edges_as_ieee_9_4_2() {
    // posedge: 0->1, 0->x, 0->z, x->1, z->1 (not 1->x, x->z); negedge the mirror
    let d = clock_dump("ieee.vcd", "1ns", "#0\n0!\n1\"\n1#\n#5\nx!\n#10\n1!\n#15\nz!\n#20\n0!\n#25\nz!\n#30\n1!\n");
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &checks(), "--assert", "a_req", "--json"]);
    assert_eq!(cycles(&o), [5000, 10000, 25000, 30000], "{}", err(&o));
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &checks(), "--assert", "a_neg", "--json"]);
    assert_eq!(cycles(&o), [15000, 20000], "{}", err(&o));
}

#[test]
fn nothing_to_check_exits_2() {
    let c = checks();
    let d = clock_dump("noedge.vcd", "1ns", "#0\n0!\n1\"\n1#\n#10\n1\"\n");
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &c, "--assert", "a_req"]);
    assert_eq!(o.status.code(), Some(2), "no edge of the clock: {}", err(&o));
    assert!(err(&o).contains("tb.clk has no posedge in the dump"), "{}", err(&o));
    let d = clock_dump("window.vcd", "1ns", "#0\n0!\n1\"\n1#\n#5\n1!\n#10\n0!\n");
    for (args, msg) in [(["--from", "1ms"], "is after the last posedge"), (["--from", "-5ns"], "a time is a number of 0 or more")] {
        let o = sva(&[&["eval", "--waves", &d, "--scope", "tb", "--sva", &c][..], &args[..]].concat());
        assert_eq!(o.status.code(), Some(2), "{args:?}: {}", err(&o));
        assert!(err(&o).contains(msg), "{args:?}: {}", err(&o));
    }
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &c, "--from", "8ns", "--to", "2ns"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("--to 2 ns is before --from 8 ns"), "{}", err(&o));
}

#[test]
fn finer_than_ps_warns() {
    let d = clock_dump("fs.vcd", "1fs", "#0\n0!\n1\"\n1#\n#5\n1!\n#10\n0!\n#15\n1!\n");
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &checks(), "--assert", "a_req", "--json"]);
    assert!(err(&o).contains("finer than 1 ps"), "{}", err(&o));
    assert_eq!(cycles(&o).len(), 2, "the edges are the cycles, whatever their rounded times");
}

#[test]
fn a_closed_stdout_is_no_crash() {
    // sva eval … | head -1: the rest of the output is dropped, the status is the evaluation's (no abort, no 134)
    let d = clock_dump("pipe.vcd", "1ns", &(0..200).map(|t| format!("#{}\n{}!\n1\"\n1#\n", t * 5, t % 2)).collect::<String>());
    let mut child = Command::new(env!("CARGO_BIN_EXE_sva"))
        .args(["eval", "--waves", &d, "--scope", "tb", "--sva", &checks(), "--attempts"])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    drop(child.stdout.take());   // the reader is gone before the first line
    let o = child.wait_with_output().unwrap();
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(!err(&o).contains("panicked"), "{}", err(&o));
}

/// The evaluation goldens: `sva eval --attempts` over the example dumps of `make examples` (skipped, with a message,
/// when they are not built), compared with tests/sva/golden/eval/<ex>.txt; `make sva-bless` (SVA_BLESS=1) rewrites
/// them. The parse goldens (tests/corpus.rs) pin the parser, these the verdicts, the traces and the notes.
#[test]
fn examples_evaluation_goldens() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let build = std::env::var("BUILD").map(std::path::PathBuf::from).unwrap_or_else(|_| root.join("out"));
    let cases: [(&str, &str, &[&str]); 3] = [
        ("apb", "apb_tb", &["examples/apb/apb_tb.sv", "examples/apb/apb.sva"]),
        ("axi_lite", "axi_lite_tb.u_slave", &["examples/axi_lite/axi_lite.sva"]),
        ("fsm", "fsm_tb.u_rx", &["examples/fsm/uart_pkg.sv", "examples/fsm/fsm.sva"]),
    ];
    let mut differ = Vec::new();
    for (ex, scope, files) in cases {
        let dump = build.join(format!("examples/{ex}/{ex}.fst"));
        if !dump.exists() {
            // make check (WAVELENS_STRICT): the gate builds the examples first, a dump missing there fails
            assert!(std::env::var("WAVELENS_STRICT").is_err(), "examples_evaluation_goldens: {} is missing (make examples)", dump.display());
            eprintln!("examples_evaluation_goldens: {} is missing (make examples): {ex} skipped", dump.display());
            continue;
        }
        let mut args = vec!["eval".to_string(), "--waves".into(), dump.to_string_lossy().into_owned(), "--scope".into(), scope.into(), "--attempts".into()];
        for f in files {
            args.extend(["--sva".into(), root.join(f).to_string_lossy().into_owned()]);
        }
        let o = Command::new(env!("CARGO_BIN_EXE_sva")).args(&args).output().unwrap();
        assert!(matches!(o.status.code(), Some(0 | 1)), "{ex}: {}", err(&o));
        let got = out(&o);
        let golden = root.join(format!("tests/sva/golden/eval/{ex}.txt"));
        if std::env::var("SVA_BLESS").is_ok() {
            std::fs::create_dir_all(golden.parent().unwrap()).unwrap();
            std::fs::write(&golden, &got).unwrap();
        } else if std::fs::read_to_string(&golden).unwrap_or_default() != got {
            differ.push(format!("{ex} (diff {} against the output; make sva-bless after a reviewed change)", golden.display()));
        }
    }
    assert!(differ.is_empty(), "evaluation goldens differ: {differ:?}");
}

/// `sva vcd`: a dump written back as VCD text, as fst2vcd -e writes it — the declarations with their ranges, an array
/// element under its own name, a real, the changes in time order; the FSM example's FST with its enum table, the
/// reference before the variable and the struct scope (when `make examples` built it); a missing dump is exit 2.
#[test]
fn vcd_writes_a_dump_as_vcd_text() {
    let src = write("conv.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 4 \" d [3:0] $end\n\
        $var reg 8 # mem[1] [7:0] $end\n$var real 64 $ r $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\nb0000 \"\nb00000001 #\nr0.5 $\n\
        #10\n1!\nb1010 \"\nr1e+20 $\n#20\n0!\nbx01z \"\n");
    let o = sva(&["vcd", &src]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    for line in ["$timescale\n\t1ns\n$end", "$scope module tb $end", "$var wire 4 \" d [3:0] $end", "$var reg 8 # mem[1] [7:0] $end",
                 "$enddefinitions $end\n#0\n", "#10\n1!\nb1010 \"\nr1e+20 $\n#20\n0!\nbx01z \"\n"] {
        assert!(t.contains(line), "{line:?} not in:\n{t}");
    }
    let to = dir().join("conv.out.vcd");
    let o = sva(&["vcd", "--waves", &src, "--out", &to.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert_eq!(std::fs::read_to_string(&to).unwrap(), t, "--out writes what stdout gets");
    let o = sva(&["vcd", "no_such.fst"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("no_such.fst"), "{}", err(&o));

    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let build = std::env::var("BUILD").map(std::path::PathBuf::from).unwrap_or_else(|_| root.join("out"));
    let fst = build.join("examples/fsm/fsm.fst");
    if !fst.exists() {
        assert!(std::env::var("WAVELENS_STRICT").is_err(), "vcd_writes_a_dump_as_vcd_text: {} is missing (make examples)", fst.display());
        eprintln!("vcd_writes_a_dump_as_vcd_text: {} is missing (make examples): the FST part skipped", fst.display());
        return;
    }
    let t = out(&sva(&["vcd", &fst.to_string_lossy()]));
    for line in ["$attrbegin misc 07 uart_pkg::state_t 5 IDLE START DATA STOP ERROR 000 001 010 011 100 1 $end\n$scope module fsm_tb $end",
                 "$attrbegin misc 07 \"\" 1 $end\n$var logic 3 ) state [2:0] $end", "$scope struct status $end"] {
        assert!(t.contains(line), "{line:?} not in the FSM example's VCD text");
    }
}

/// `sva vcd` of an FST writes what fst2vcd writes: the names as the FST holds them (bit selects glued or apart, not
/// merged into vectors; escaped names with brackets), strings escaped as fstapi does (a tab, a newline, a space: one
/// token each), the end of the dump after the last change. A VCD goes through wellen: a lone bit select glued, the
/// strings escaped the same way. The FST is made by vcd2fst (GTKWave) when it is installed, else that part is skipped.
#[test]
fn vcd_of_an_fst_keeps_names_strings_and_the_end() {
    let src = write("sel.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! err[0] $end\n$var wire 1 \" err[2] $end\n\
        $var wire 1 # d[4] $end\n$var wire 1 $ d[5] $end\n$var wire 8 % data [7:0] $end\n$var wire 1 & \\e[0] $end\n\
        $var wire 1 ' \\e[1] $end\n$var string 1 ( s $end\n$upscope $end\n$enddefinitions $end\n\
        #0\n1!\n0\"\n0#\n1$\nb1 %\n0&\n1'\nsx (\n#1\nsa\\x09b\\x20c (\n#2\nsq\\x0a1\\x22 (\n#5\n0!\n#10\n");
    let o = sva(&["vcd", &src]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    for line in ["$var wire 1 \" err[2] $end\n", " d [5:4] $end\n", "sa\\tb\\040c (\n", "sq\\n1\\\" (\n"] {
        assert!(t.contains(line), "{line:?} not in:\n{t}");
    }

    let fst = dir().join(format!("sel.{:?}.fst", std::thread::current().id()));
    if !Command::new("vcd2fst").arg(&src).arg(&fst).output().is_ok_and(|o| o.status.success()) {
        eprintln!("vcd_of_an_fst_keeps_names_strings_and_the_end: no vcd2fst (GTKWave): the FST part skipped");
        return;
    }
    let o = sva(&["vcd", &fst.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    for line in ["$var wire 1 ! err[0] $end\n$var wire 1 \" err[2] $end\n$var wire 1 # d[4] $end\n$var wire 1 $ d[5] $end\n\
                  $var wire 8 % data [7:0] $end\n$var wire 1 & \\e[0] $end\n$var wire 1 ' \\e[1] $end\n$var string 0 ( s $end\n",
                 "#1\nsa\\tb\\040c (\n#2\nsq\\n1\\\" (\n#5\n0!\n#10\n"] {
        assert!(t.contains(line), "{line:?} not in:\n{t}");
    }
    assert!(t.ends_with("#5\n0!\n#10\n"), "the end of the dump is the last line:\n{t}");
}

/// A dump its reader cannot take (a value longer than its variable: wellen asserts) is one line naming the file, exit
/// 2, not an internal error.
#[test]
fn a_dump_that_does_not_read_is_named() {
    let bad = write("long.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 2 % m $end\n$upscope $end\n\
        $enddefinitions $end\n#0\nb101 %\n#1\nb1 %\n");
    for args in [&["vcd", &bad][..], &["--waves", &bad, "--info"][..]] {
        let o = sva(args);
        assert_eq!(o.status.code(), Some(2), "{args:?}");
        let e = err(&o);
        assert!(e.contains("long.vcd") && !e.contains("internal error") && e.trim_end().lines().count() == 1, "{args:?}: {e}");
    }
}

/// A VCD of the fst tests in a directory of its own (they run in parallel, and `sva fst` writes beside the dump).
fn own(test: &str, name: &str, text: &str) -> PathBuf {
    let d = dir().join(test);
    std::fs::create_dir_all(&d).unwrap();
    let p = d.join(name);
    std::fs::write(&p, text).unwrap();
    p
}

/// The value changes of a VCD text by time, each time's lines sorted (an FST's readers give one time's changes in
/// their own order).
fn changes(t: &str) -> Vec<(String, Vec<String>)> {
    let body = t.split("$enddefinitions $end").nth(1).unwrap_or("");
    let mut out: Vec<(String, Vec<String>)> = Vec::new();
    for l in body.lines().map(str::trim).filter(|l| !l.is_empty() && !l.starts_with('$')) {
        if l.starts_with('#') {
            out.push((l.to_string(), Vec::new()));
        } else if let Some(last) = out.last_mut() {
            last.1.push(l.to_string());
        }
    }
    out.iter_mut().for_each(|x| x.1.sort());
    out
}

/// The part files beside a dump (tb.fst.<pid>.part: a run not finished, or killed).
fn parts(vcd: &std::path::Path) -> Vec<String> {
    std::fs::read_dir(vcd.parent().unwrap()).unwrap().filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".part")).collect()
}

/// GTKWave's fst2vcd of an FST, None when it is not installed; under make check (WAVELENS_STRICT) it must be: the
/// gate's machine has GTKWave, the FST's other reader.
fn fst2vcd(fst: &std::path::Path) -> Option<String> {
    match Command::new("fst2vcd").arg(fst).output() {
        Ok(g) => {
            assert!(g.status.success(), "fst2vcd {}: {}", fst.display(), String::from_utf8_lossy(&g.stderr));
            Some(String::from_utf8_lossy(&g.stdout).into_owned())
        }
        Err(e) => {
            assert!(std::env::var("WAVELENS_STRICT").is_err(), "fst2vcd: {e} (GTKWave is needed by make check)");
            None
        }
    }
}

/// The fields of an FST's header block (fstapi's FST_BL_HDR): start, end, scopes, variables, signals, blocks of
/// changes, the exponent of its timescale, $timezero.
fn fst_header(fst: &std::path::Path) -> [i64; 8] {
    let b = std::fs::read(fst).unwrap();
    assert_eq!(b[0], 0, "the header block first");
    let u = |at: usize| u64::from_be_bytes(b[at..at + 8].try_into().unwrap()) as i64;
    [u(9), u(17), u(41), u(49), u(57), u(65), b[73] as i8 as i64, u(322)]
}

const ALL_KINDS: &str = "$date\n  Sun Oct 25 10:00:00 2026\n$end\n$version Questa 2021.1 $end\n$comment made by hand $end\n\
    $timescale 10ps $end\n$attrbegin misc 07 pkg::state_t 3 IDLE RUN DONE 00 01 10 1 $end\n$scope module tb $end\n\
    $var wire 1 ! clk $end\n$attrbegin misc 07 \"\" 1 $end\n$var logic 2 \" state [1:0] $end\n$var wire 8 # data [7:0] $end\n\
    $var wire 1 $ err[2] $end\n$var real 64 % r $end\n$var string 1 & msg $end\n$var event 1 ' ev $end\n\
    $scope module u $end\n$var wire 1 ! clk_copy $end\n$var wire 1 ( s $end\n$upscope $end\n$upscope $end\n$enddefinitions $end\n\
    #0\n$dumpvars\n0!\nb0 \"\nb1x #\n1$\nr1.5 %\nsHello\\040world &\nU(\n$end\n#5\n1!\nb1 \"\nbz #\nr-2.5e-9 %\n1'\nH(\n\
    #10\n0!\nb10 \"\nb10100101 #\n0$\nsq\\x22 &\nL(\n#20\n";

/// `sva fst` writes the FST beside the VCD under its name, and `sva vcd` reads back what the VCD has: the date and
/// version, the comment, the timescale, the enum table and its reference, every name as the VCD writes it, an alias,
/// vectors extended as VCD extends them, reals, strings, an event, VHDL's 1-bit values, the end of the dump.
#[test]
fn fst_of_a_vcd_keeps_what_it_declares_and_its_values() {
    let vcd = own("fst-all", "all.vcd", ALL_KINDS);
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let fst = vcd.with_extension("fst");
    assert!(out(&o).contains("all.fst: 9 variables (8 signals), ") && out(&o).contains(" 1 enum table"), "{}", out(&o));
    assert!(parts(&vcd).is_empty(), "the part file is renamed");
    let t = out(&sva(&["vcd", &fst.to_string_lossy()]));
    for line in ["$date\n\tSun Oct 25 10:00:00 2026\n$end\n$version\n\tQuesta 2021.1\n$end\n$timescale\n\t10ps\n$end\n$comment\n\tmade by hand\n$end\n",
                 "$attrbegin misc 07 pkg::state_t 3 IDLE RUN DONE 00 01 10 1 $end\n$scope module tb $end\n$var wire 1 ! clk $end\n\
                  $attrbegin misc 07 \"\" 1 $end\n$var logic 2 \" state [1:0] $end\n$var wire 8 # data [7:0] $end\n$var wire 1 $ err[2] $end\n\
                  $var real 64 % r $end\n$var string 0 & msg $end\n$var event 1 ' ev $end\n$scope module u $end\n$var wire 1 ! clk_copy $end\n"] {
        assert!(t.contains(line), "{line:?} not in:\n{t}");
    }
    // a 1-bit U H L comes back as u h l: the FST's code of a bit (fstapi's "xzhuwl-?")
    let want = [("#0", vec!["0!", "1$", "u(", "b00 \"", "b0000001x #", "r1.5 %", "sHello\\040world &"]),
                ("#5", vec!["1!", "1'", "h(", "b01 \"", "bzzzzzzzz #", "r-2.5e-09 %"]),
                ("#10", vec!["0!", "0$", "l(", "b10 \"", "b10100101 #", "sq\\\" &"]), ("#20", vec![])];
    let want: Vec<(String, Vec<String>)> = want.iter().map(|(t, v)| {
        let mut v: Vec<String> = v.iter().map(|s| s.to_string()).collect();
        v.sort();
        (t.to_string(), v)
    }).collect();
    assert_eq!(changes(&t), want, "{t}");

    // GTKWave reads it the same
    if let Some(g) = fst2vcd(&fst) {
        assert_eq!(changes(&g), want, "fst2vcd:\n{g}");
    }
    // the header: 9 variables in 2 scopes, 8 signals (clk_copy an alias), one block, 10ps, from #0 to #20
    assert_eq!(fst_header(&fst), [0, 20, 2, 9, 8, 1, -11, 0]);
}

/// The header of the FST as the VCD gives it: no $timescale is 1 ps (as WaveLens reads a VCD; vcd2fst takes 1 ns),
/// $timezero below 0, the times from the first to the last (an empty last #); a code declared again at another width
/// is a signal of its own with the values on its width; a port is a wire of its width, its EVCD values left out.
#[test]
fn fst_header_of_a_vcd_and_its_odd_declarations() {
    let vcd = own("fst-header", "nots.vcd", "$timezero -100 $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n\
        $enddefinitions $end\n#5\n0!\n#10\n1!\n#30\n");
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(err(&o).contains("nots.vcd: no $timescale: 1ps taken"), "{}", err(&o));
    let fst = vcd.with_extension("fst");
    assert_eq!(fst_header(&fst), [5, 30, 1, 1, 1, 1, -12, -100]);
    assert!(out(&sva(&["vcd", &fst.to_string_lossy()])).contains("$timescale\n\t1ps\n$end\n"));
    if let Some(g) = fst2vcd(&fst) {
        assert!(g.contains("$timescale\n\t1ps\n$end\n") && g.contains("$timezero\n\t-100\n$end\n"), "{g}");
    }
    for (ts, e) in [("100fs", -13), ("10ps", -11), ("1 s", 0), ("1 us", -6)] {
        let vcd = own("fst-header", "ts.vcd", &format!("$timescale {ts} $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n\
            $enddefinitions $end\n#0\n0!\n"));
        assert_eq!(sva(&["fst", &vcd.to_string_lossy(), "-q"]).status.code(), Some(0));
        assert_eq!(fst_header(&vcd.with_extension("fst"))[6], e, "{ts}");
    }

    let vcd = own("fst-header", "odd.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! bit $end\n\
        $var wire 8 ! bus [7:0] $end\n$var wire 8 ! bus2 [7:0] $end\n$var port 4 \" p [3:0] $end\n$upscope $end\n$enddefinitions $end\n\
        #0\nb10101010 !\nb1010 \"\n#10\npD 6 6 \"\n1!\n");
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(out(&o).contains("odd.fst: 4 variables (3 signals)"), "bus2 an alias of bus, bit and bus apart: {}", out(&o));
    let e = err(&o);
    assert!(e.contains("odd.vcd:6: $var port p [3:0]: written as a wire") && e.contains("odd.vcd:13: \"pD\": a port value"), "{e}");
    let fst = vcd.with_extension("fst");
    let t = out(&sva(&["vcd", &fst.to_string_lossy()]));
    assert!(t.contains("$var wire 1 ! bit $end\n$var wire 8 \" bus [7:0] $end\n$var wire 8 \" bus2 [7:0] $end\n$var wire 4 # p [3:0] $end\n"), "{t}");
    let want = vec![("#0".to_string(), vec!["0!".to_string(), "b1010 #".into(), "b10101010 \"".into()]),
                    ("#10".to_string(), vec!["1!".to_string(), "b00000001 \"".into()])];
    assert_eq!(changes(&t), want, "{t}");
    if let Some(g) = fst2vcd(&fst) {
        assert!(g.contains("$var wire 4 # p [3:0] $end"), "{g}");
        assert_eq!(changes(&g), want, "fst2vcd:\n{g}");
    }
}

/// The parts of an FST a viewer reads as it needs them: `--header` every declaration and the dump's first and last
/// times, no value; `--codes` the variables of those id codes (an alias's too, their enum tables) and their changes, as
/// the whole text has them.
#[test]
fn vcd_parts_of_an_fst() {
    let vcd = own("vcd-parts", "all.vcd", ALL_KINDS);
    assert_eq!(sva(&["fst", &vcd.to_string_lossy(), "-q"]).status.code(), Some(0));
    let fst = vcd.with_extension("fst");
    let whole = out(&sva(&["vcd", &fst.to_string_lossy()]));
    let head = out(&sva(&["vcd", &fst.to_string_lossy(), "--header"]));
    let decl = |t: &str| t.split("$enddefinitions $end").next().unwrap().to_string();
    assert_eq!(decl(&head), decl(&whole));
    assert!(head.ends_with("$enddefinitions $end\n#0\n#20\n"), "{head}");
    // state (") with its enum table and its reference, r (%); clk (!) is clk_copy too
    let codes = own("vcd-parts", "codes.txt", "\" %\n!");
    let part = out(&sva(&["vcd", &fst.to_string_lossy(), "--codes", &codes.to_string_lossy()]));
    assert!(part.contains("$attrbegin misc 07 pkg::state_t 3 IDLE RUN DONE 00 01 10 1 $end\n$scope module tb $end\n$var wire 1 ! clk $end\n\
        $attrbegin misc 07 \"\" 1 $end\n$var logic 2 \" state [1:0] $end\n$var real 64 % r $end\n$scope module u $end\n$var wire 1 ! clk_copy $end\n\
        $upscope $end\n$upscope $end\n$enddefinitions $end\n"), "{part}");
    let only = |t: &str| changes(t).into_iter().map(|(t, v)| (t, v.into_iter().filter(|l| l.ends_with('!') || l.ends_with('"') || l.ends_with('%'))
        .collect::<Vec<_>>())).filter(|(_, v)| !v.is_empty()).collect::<Vec<_>>();
    assert_eq!(only(&part), only(&whole), "{part}");
    assert!(part.trim_end().ends_with("#20"), "the end of the dump: {part}");
    // the codes on stdin; one that is no code, and a VCD (no part of it): said
    let o = Command::new(env!("CARGO_BIN_EXE_sva")).args(["vcd", &fst.to_string_lossy(), "--codes", "-"]).stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped()).spawn().and_then(|mut c| {
            use std::io::Write as _;
            c.stdin.take().unwrap().write_all(b"%")?;
            c.wait_with_output()
        }).unwrap();
    assert_eq!(only(&out(&o)).iter().map(|x| x.1.len()).sum::<usize>(), 2, "r at #0 and #5: {}", out(&o));
    let bad = own("vcd-parts", "bad.txt", "! a\u{7f}b");
    assert!(err(&sva(&["vcd", &fst.to_string_lossy(), "--codes", &bad.to_string_lossy()])).contains("is not an id code"));
    assert!(err(&sva(&["vcd", &vcd.to_string_lossy(), "--header"])).contains("read an FST"));
}

/// The blocks of changes (64 MiB each; `--block-bytes` makes them small) and the aliases of equal changes read back as
/// one block does; --out names another file.
#[test]
fn fst_in_many_blocks_reads_as_one() {
    let mut text = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 \" clk2 $end\n\
        $var wire 16 # n [15:0] $end\n$var real 64 $ r $end\n$upscope $end\n$enddefinitions $end\n");
    for i in 0..400 {
        text += &format!("#{}\n{}!\n{}\"\nb{:b} #\nr{} $\n", i * 5, i % 2, i % 2, i * 7 % 65536, i as f64 / 4.0);
    }
    let vcd = own("fst-blocks", "b.vcd", &text);
    let (one, many) = (vcd.with_extension("fst"), vcd.with_extension("many.fst"));
    assert_eq!(sva(&["fst", &vcd.to_string_lossy(), "-q"]).status.code(), Some(0));
    let o = sva(&["fst", &vcd.to_string_lossy(), "--out", &many.to_string_lossy(), "--block-bytes", "64"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let a = out(&sva(&["vcd", &one.to_string_lossy()]));
    let b = out(&sva(&["vcd", &many.to_string_lossy()]));
    assert_eq!(changes(&a).len(), 400);
    assert_eq!(changes(&a), changes(&b));
    assert_eq!(fst_header(&one)[5], 1);
    assert!(fst_header(&many)[5] > 100, "blocks: {:?}", fst_header(&many));
    if let Some(g) = fst2vcd(&many) {
        assert_eq!(changes(&g), changes(&a), "fst2vcd of the blocks");
    }
    // blocks whose alias (clk2 of clk) is longer than 32 bytes: fstapi's reader needs its memory counted too
    let mid = vcd.with_extension("mid.fst");
    assert_eq!(sva(&["fst", &vcd.to_string_lossy(), "--out", &mid.to_string_lossy(), "--block-bytes", "2000", "-q"]).status.code(), Some(0));
    assert!((2..20).contains(&fst_header(&mid)[5]), "{:?}", fst_header(&mid));
    if let Some(g) = fst2vcd(&mid) {
        assert_eq!(changes(&g), changes(&a), "fst2vcd of the blocks with aliases");
    }

    // times without a change fill a block too (its table of times is in memory until the block is written)
    let mut text = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n");
    for i in 1..1000 {
        text += &format!("#{i}\n");
    }
    let vcd = own("fst-blocks", "times.vcd", &text);
    assert_eq!(sva(&["fst", &vcd.to_string_lossy(), "--block-bytes", "800", "-q"]).status.code(), Some(0));
    let h = fst_header(&vcd.with_extension("fst"));
    assert!(h[5] >= 8 && h[1] == 999, "{h:?}");
    if let Some(g) = fst2vcd(&vcd.with_extension("fst")) {
        assert!(g.contains("#0\n$dumpvars\n0!\n$end\n#1\n#2\n") && g.trim_end().ends_with("#998\n#999"), "{g}");
    }
}

/// The words of a VCD read through the 1 MiB buffer: a value and its code across its end (LF and CRLF), a word longer
/// than the buffer, give what they give in one piece.
#[test]
fn fst_reads_words_across_its_buffer() {
    const BUF: usize = 1 << 20;
    let head = "$timescale 1ns $end\n$scope module tb $end\n$var wire 8 # v [7:0] $end\n$var wire 1 ! s $end\n$upscope $end\n$enddefinitions $end\n#0\n";
    for nl in ["\n", "\r\n"] {
        for k in 0..12 {
            // the value "b10100101 #" starts k bytes before the end of the buffer (sva vcd numbers the codes anew)
            let pre = format!("{head}$comment ");
            let fill = BUF - k - pre.len() - format!(" $end{nl}").len();
            let text = format!("{pre}{} $end{nl}b10100101 #{nl}1!{nl}#5{nl}0!{nl}", "c".repeat(fill)).replace('\n', nl).replace("\r\r", "\r");
            assert_eq!(text.find("b10100101").unwrap() + k, BUF + if nl == "\n" { 0 } else { 7 }, "{k}");
            let vcd = own("fst-words", "w.vcd", &text);
            let o = sva(&["fst", &vcd.to_string_lossy(), "-q"]);
            assert_eq!(o.status.code(), Some(0), "{k} {nl:?}: {}", err(&o));
            assert!(err(&o).is_empty(), "{k} {nl:?}: {}", err(&o));
            let t = out(&sva(&["vcd", &vcd.with_extension("fst").to_string_lossy()]));
            assert_eq!(changes(&t), vec![("#0".to_string(), vec!["1\"".to_string(), "b10100101 !".into()]), ("#5".to_string(), vec!["0\"".to_string()])],
                       "{k} {nl:?}");
        }
    }
    // a word of 1.5 MiB in a $comment of the header, cut to what an FST's readers take, a long name too; a value after
    let text = format!("$comment {} $end\n{}b1 #\n", "w".repeat(BUF * 3 / 2), head.replace(" s $end", &format!(" {} $end", "n".repeat(70000))));
    let vcd = own("fst-words", "long.vcd", &text);
    let o = sva(&["fst", &vcd.to_string_lossy(), "-q"]);
    assert_eq!(o.status.code(), Some(0));
    assert!(err(&o).contains("long.vcd:1: a $comment of 1572864 bytes: cut to 69631") && err(&o).contains("long.vcd:5: a $var name of 70000 bytes: cut to 65535"),
            "{}", err(&o));
    let t = sva(&["vcd", &vcd.with_extension("fst").to_string_lossy()]);
    assert_eq!(t.status.code(), Some(0), "{}", err(&t));
    assert_eq!(changes(&out(&t)), vec![("#0".to_string(), vec!["b00000001 !".to_string()])]);
    if let Some(g) = fst2vcd(&vcd.with_extension("fst")) {
        assert_eq!(changes(&g), changes(&out(&t)));
    }
}

/// The FSM states of the types file beside the VCD (tb.types.json by tb.vcd) become enum tables of the variables of
/// their paths whose width is the type's: Questa's describe and "signals", an instance's own table, an array element
/// the array's; a width that differs gets none, and a table the VCD gives stays.
#[test]
fn fst_writes_the_fsm_states_of_the_types_file() {
    let vcd = own("fst-types", "tb.vcd", "$timescale 1ns $end\n$attrbegin misc 07 own_t 2 A B 0 1 1 $end\n$scope module tb $end\n\
        $var reg 3 ! state [2:0] $end\n$scope module u $end\n$var reg 2 \" state [1:0] $end\n$upscope $end\n\
        $var reg 4 # wide [3:0] $end\n$var reg 2 $ arr[1] $end\n$attrbegin misc 07 \"\" 1 $end\n$comment between $end\n$var reg 1 % mine $end\n\
        $var reg 3 & glued[2:0] $end\n$upscope $end\n$enddefinitions $end\n#0\nb0 !\nb0 \"\nb0 #\nb0 $\n0%\nb0 &\n");
    std::fs::write(vcd.with_extension("types.json"), r#"{"wavelens": "types", "version": 1,
        "describe": {"tb.state": "Verilog enum: (2 downto 0) [3 enumeration values]\n  (IDLE=0,RUN=1,\n DONE=4)",
                     "tb.wide": "Verilog enum: (2 downto 0) [2 enumeration values]\n  (P=0,Q=1)", "tb.mine": "Verilog enum: (0 downto 0) [2 enumeration values]\n  (X0=0,X1=1)",
                     "tb.glued": "Verilog enum: (2 downto 0) [2 enumeration values]\n  (G0=0,G7=7)"},
        "signals": {"tb.u.state": {"width": 2, "enum": {"0": "U_IDLE", "3": "U_LAST"}}, "tb.arr": {"width": 2, "enum": {"1": "ONE"}}}}"#).unwrap();
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(out(&o).contains("5 enum tables, 4 of them from tb.types.json (4 variables)"), "{}", out(&o));
    let t = out(&sva(&["vcd", &vcd.with_extension("fst").to_string_lossy()]));
    for line in ["$attrbegin misc 07 state_t 3 IDLE RUN DONE 000 001 100 2 $end\n$attrbegin misc 07 \"\" 2 $end\n$var reg 3 ! state [2:0] $end\n",
                 "$attrbegin misc 07 state_t 2 U_IDLE U_LAST 00 11 3 $end\n$attrbegin misc 07 \"\" 3 $end\n$var reg 2 \" state [1:0] $end\n",
                 "$upscope $end\n$var reg 4 # wide [3:0] $end\n",
                 "$attrbegin misc 07 arr_t 1 ONE 01 4 $end\n$attrbegin misc 07 \"\" 4 $end\n$var reg 2 $ arr[1] $end\n",
                 "$attrbegin misc 07 \"\" 1 $end\n$comment\n\tbetween\n$end\n$var reg 1 % mine $end\n",
                 "$attrbegin misc 07 glued_t 2 G0 G7 000 111 5 $end\n$attrbegin misc 07 \"\" 5 $end\n$var reg 3 & glued[2:0] $end\n"] {
        assert!(t.contains(line), "{line:?} not in:\n{t}");
    }
    // --no-types: the VCD's own table only; --map then has nothing to map, and says so
    let o = sva(&["fst", &vcd.to_string_lossy(), "--no-types", "--map", "top=tb"]);
    assert!(out(&o).contains(", 1 enum table\n"), "{}", out(&o));
    assert!(err(&o).contains("tb.vcd: --map given, but no types file (tb.types.json beside the dump, or --types): --no-types"), "{}", err(&o));
}

/// The cases of tests/unit/types/contract.json (what svtypes.py and the page's svApply give the signals of a dump)
/// through `sva fst`, the fourth twin: each case's signals as a VCD ($var as the case's `ref`, else from its path: x.[3] is
/// x[3]; its own labels as the VCD's enum table), its types beside it -> which $var gets which enum table, and a file
/// the twins refuse is refused. The notes, fields and the run are the others' (an FST holds enum tables only).
#[test]
fn fst_gives_the_enum_tables_the_twins_give() {
    let text = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../../tests/unit/types/contract.json")).unwrap();
    let doc: serde_json::Value = serde_json::from_str(&text).unwrap();
    let cases = doc["cases"].as_array().unwrap();
    for (k, c) in cases.iter().enumerate() {
        let name = c["name"].as_str().unwrap();
        let sigs = c["signals"].as_array().unwrap();
        let mut vcd = String::from("$timescale 1ns $end\n");
        let mut open: Vec<String> = Vec::new();
        let mut body = String::from("#0\n");
        for (i, s) in sigs.iter().enumerate() {
            let path = s["path"].as_str().unwrap().replace(".[", "[");
            let mut comps: Vec<String> = path.split('.').map(String::from).collect();
            let leaf = comps.pop().unwrap();
            let r = s.get("ref").and_then(|x| x.as_str()).map_or(leaf, String::from);
            let same = open.iter().zip(&comps).take_while(|(a, b)| a == b).count();
            while open.len() > same {
                open.pop();
                vcd += "$upscope $end\n";
            }
            for c in &comps[same..] {
                vcd += &format!("$scope module {c} $end\n");
                open.push(c.clone());
            }
            let w = s["width"].as_u64().unwrap() as usize;
            if let Some(own) = s.get("enum").and_then(|x| x.as_object()) {
                let (labels, values): (Vec<_>, Vec<_>) = own.iter().map(|(v, l)| (l.as_str().unwrap().to_string(),
                    format!("{:0w$b}", v.parse::<u128>().unwrap()))).unzip();
                vcd += &format!("$attrbegin misc 07 own_t {} {} {} {} $end\n$attrbegin misc 07 \"\" {} $end\n", own.len(), labels.join(" "),
                                values.join(" "), 100 + i, 100 + i);
            }
            let code = (b'!' + i as u8) as char;
            let kind = s.get("kind").and_then(|x| x.as_str()).unwrap_or("reg");
            vcd += &format!("$var {kind} {w} {code} {r} $end\n");
            body += &format!("b0 {code}\n");
        }
        vcd += &"$upscope $end\n".repeat(open.len());
        vcd += "$enddefinitions $end\n";
        let p = own("fst-contract", &format!("c{k}.vcd"), &(vcd + &body));
        std::fs::write(p.with_extension("types.json"), c["types"].to_string()).unwrap();
        let o = sva(&["fst", &p.to_string_lossy(), "-q"]);
        if c["want"].get("error").is_some() {
            assert_eq!(o.status.code(), Some(2), "{name}: the twins refuse the types file: {}", err(&o));
            assert!(err(&o).contains(&format!("c{k}.types.json")), "{name}: {}", err(&o));
            continue;
        }
        assert_eq!(o.status.code(), Some(0), "{name}: {}", err(&o));
        // the tables of the FST, and the one each $var refers to (in the order of the case's signals)
        let t = out(&sva(&["vcd", &p.with_extension("fst").to_string_lossy()]));
        let mut tables: std::collections::HashMap<String, (String, serde_json::Map<String, serde_json::Value>)> = Default::default();
        let (mut pending, mut got) = (None, Vec::new());
        for l in t.lines() {
            let w: Vec<&str> = l.split_whitespace().collect();
            if l.starts_with("$attrbegin misc 07 \"\" ") {
                pending = Some(w[4].to_string());
            } else if l.starts_with("$attrbegin misc 07 ") {
                let n: usize = w[4].parse().unwrap();
                let map = (0..n).map(|j| (u128::from_str_radix(w[5 + n + j], 2).unwrap().to_string(), serde_json::Value::from(w[5 + j]))).collect();
                tables.insert(w[5 + 2 * n].to_string(), (w[3].to_string(), map));
            } else if l.starts_with("$var ") {
                got.push(pending.take().map(|h| tables[&h].clone()));
            }
        }
        assert_eq!(got.len(), sigs.len(), "{name}:\n{t}");
        for (s, g) in sigs.iter().zip(&got) {
            let path = s["path"].as_str().unwrap();
            let want = s.get("enum").or_else(|| c["want"].get("labels").and_then(|l| l.get(path))).and_then(|x| x.as_object());
            assert_eq!(g.as_ref().map(|x| &x.1), want, "{name}: {path}:\n{t}");
            if let Some((tname, _)) = g {
                assert_eq!(tname == "own_t", s.get("enum").is_some(), "{name}: {path}: the VCD's own table stays");
            }
        }
    }
}

/// A VCD whose integers are written without b, glued to their codes (Questa 2023: tests/unit/vcd/glued.vcd): sva fst
/// reads them, and sva vcd and sva eval, which read a VCD through wellen (it stops at the first one), read its FST.
#[test]
fn glued_vectors_are_read() {
    let vcd = concat!(env!("CARGO_MANIFEST_DIR"), "/../../tests/unit/vcd/glued.vcd");
    let o = sva(&["vcd", vcd]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    for want in ["b00000000000000000000000000000011 \"", "b0000000000000000000000000000xxxx #", "b1111 $", "#20\n0!"] {
        assert!(t.contains(want), "{want}:\n{t}");
    }
    let s = own("glued", "g.sva", "module m;\n  a_p: assert property (@(posedge clk) next == 1 |-> ##1 next == 2);\nendmodule\n");
    let o = sva(&["eval", "--waves", vcd, "--scope", "tb", "--sva", &s.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(err(&o).contains("glued to their codes (Questa 2023's integers): read through an FST of it"), "{}", err(&o));
    assert!(out(&o).contains("a_p assert 2 attempts: 1 pass, 0 fail, 1 vacuous"), "{}", out(&o));
}

/// A dump that does not convert is one message with its file and line, exit 2, and no FST (an older one stays);
/// the notes of one kind are shown five times, then counted.
#[test]
fn fst_errors_name_the_line_and_notes_are_counted() {
    let vcd = own("fst-errors", "back.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n\
        $enddefinitions $end\n#0\n0!\n#20\n1!\n#5\n0!\n");
    std::fs::write(vcd.with_extension("fst"), "older").unwrap();
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("back.vcd:10: #5 after #20: the time goes back"), "{}", err(&o));
    assert_eq!(std::fs::read_to_string(vcd.with_extension("fst")).unwrap(), "older");
    assert!(parts(&vcd).is_empty(), "the part is removed");

    let mut text = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n$enddefinitions $end\n#0\n");
    for i in 0..12 {
        text += &format!("1{}\n", ["%", "&"][i % 2]);
    }
    let vcd = own("fst-errors", "codes.vcd", &text);
    let o = sva(&["fst", &vcd.to_string_lossy(), "-q"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let e = err(&o);
    assert_eq!(e.matches("which no $var declares").count(), 3, "two codes shown once each, and the summary:\n{e}");
    assert!(e.contains("codes.vcd:7: a value of \"%\", which no $var declares: left out"), "{e}");
    assert!(out(&o).is_empty(), "-q: no last line");

    let mut text = String::from("$timescale 1ns $end\n$scope module tb $end\n$var real 64 ! r $end\n$upscope $end\n$enddefinitions $end\n#0\n");
    for i in 0..8 {
        text += &format!("rbad{i} !\n");
    }
    let o = sva(&["fst", &own("fst-errors", "reals.vcd", &text).to_string_lossy(), "-q"]);
    let e = err(&o);
    assert_eq!(e.matches("is not a number: NaN taken").count(), 6, "five shown, then the count:\n{e}");
    assert!(e.contains("8 such notes in all, the first 5 above"), "{e}");
    let o = sva(&["fst", &vcd.with_extension("fst").to_string_lossy()]);
    assert!(err(&o).contains("already an FST"), "{}", err(&o));
}

/// The FST appears whole: each run writes a part of its own (tb.fst.<pid>.part, never a file there before) and renames
/// it; runs at once each finish, a run killed leaves only its part and the next one is not stopped by it, a dump named
/// like a part is not touched; a large dump's progress lines say "progress:", told from the notes.
#[test]
fn fst_runs_at_once_and_killed() {
    let mut text = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 8 ! n [7:0] $end\n$upscope $end\n$enddefinitions $end\n");
    for i in 0..200_000 {
        text += &format!("#{i}\nb{:b} !\n", i % 251);
    }
    let vcd = own("fst-runs", "two.vcd", &text);
    let fst = vcd.with_extension("fst");
    let runs: Vec<_> = (0..4).map(|_| Command::new(env!("CARGO_BIN_EXE_sva")).args(["fst", &vcd.to_string_lossy(), "-q"])
        .stderr(std::process::Stdio::piped()).spawn().unwrap()).collect();
    for r in runs {
        let o = r.wait_with_output().unwrap();
        assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    }
    assert!(parts(&vcd).is_empty(), "{:?}", parts(&vcd));
    let t = out(&sva(&["vcd", &fst.to_string_lossy()]));
    assert_eq!(changes(&t).len(), 200_000);

    // killed while it writes: its part stays (named by its pid), the FST before it stays, the next run is not stopped
    let mut k = Command::new(env!("CARGO_BIN_EXE_sva")).args(["fst", &vcd.to_string_lossy(), "-q"]).spawn().unwrap();
    let pid = k.id();
    let part = vcd.with_file_name(format!("two.fst.{pid}.part"));
    let t0 = std::time::Instant::now();
    while !part.exists() && t0.elapsed().as_secs() < 10 {
        std::thread::yield_now();
    }
    k.kill().unwrap();
    let killed = k.wait().unwrap().code().is_none();   // not done before the kill (a fast machine may finish first)
    assert_eq!(parts(&vcd), if killed { vec![format!("two.fst.{pid}.part")] } else { vec![] });
    assert_eq!(changes(&out(&sva(&["vcd", &fst.to_string_lossy()]))).len(), 200_000, "the FST of before is whole");
    assert_eq!(sva(&["fst", &vcd.to_string_lossy(), "-q"]).status.code(), Some(0));
    let _ = std::fs::remove_file(&part);

    // a dump named as a part, written to the FST it would be the part of: read, not emptied
    let odd = own("fst-runs", "x.fst.part", "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n$enddefinitions $end\n#0\n1!\n");
    let o = sva(&["fst", &odd.to_string_lossy(), "--out", &odd.with_file_name("x.fst").to_string_lossy(), "-q"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(std::fs::read_to_string(&odd).unwrap().contains("$enddefinitions"));

    // progress of a large dump (--large-bytes makes this one large): its own lines, none a note
    let o = sva(&["fst", &vcd.to_string_lossy(), "--large-bytes", "1000"]);
    let e = err(&o);
    let (progress, notes): (Vec<&str>, Vec<&str>) = e.lines().partition(|l| l.contains("two.vcd: progress: "));
    assert!(progress.len() >= 4 && notes.is_empty(), "{e}");   // a tenth at most each 1 MiB read: 3 MB, three or four
    assert!(progress[0].contains("progress: 1 variables (1 signals) in 1 scopes, 0 enum tables; the values next")
            && progress[1].contains("% (line "), "{e}");
}
