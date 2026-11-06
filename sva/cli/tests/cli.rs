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
    // a window without an edge checks nothing (review 0.31 R3); the edge at --to is in the window (the posedge at 5 ns)
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &c, "--to", "1ns"]);
    assert_eq!(o.status.code(), Some(2), "{}", err(&o));
    assert!(err(&o).contains("--to 1 ns is before the first posedge of tb.clk (5 ns)"), "{}", err(&o));
    let d = clock_dump("window2.vcd", "1ns", "#0\n0!\n1\"\n1#\n#5\n1!\n#10\n0!\n#15\n1!\n#20\n0!\n");
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &c, "--from", "6ns", "--to", "9ns"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("no posedge of tb.clk from 6 ns to 9 ns: nothing to check"), "{}", err(&o));
    let o = sva(&["eval", "--waves", &d, "--scope", "tb", "--sva", &c, "--from", "6ns", "--to", "15ns", "--json"]);
    assert!(o.status.code() != Some(2), "the edge at --to is in the window: {}", err(&o));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["cycles"].as_array().and_then(|c| c.last()).and_then(|t| t.as_u64()), Some(15_000), "{v}");
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
    // sva diff: the reader's panic in its thread, said once, of the dump it is (review 0.31 R5)
    let good = write("good.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 2 % m $end\n$upscope $end\n$enddefinitions $end\n#0\nb10 %\n#1\nb1 %\n");
    let o = sva(&["diff", &good, &bad]);
    assert_eq!(o.status.code(), Some(2));
    let e = err(&o);
    assert!(e.contains("long.vcd: the dump does not read") && !e.contains("good.vcd") && e.trim_end().lines().count() == 1, "{e}");
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

/// A file written with its time an hour back (a part a run killed long ago left).
fn old_file(p: &std::path::Path) {
    std::fs::write(p, "x").unwrap();
    let back = std::time::SystemTime::now() - std::time::Duration::from_secs(3600);
    std::fs::File::options().write(true).open(p).unwrap().set_modified(back).unwrap();
}

/// The files a killed sva left (review of the runs T-08 d): its FST's part beside the target (`tb.fst.<pid>.part`) and
/// the FST of a glued VCD in the temp directory are removed by the next run once their process is gone and they are
/// 10 minutes old; a young part (a run going on), another target's and another program's file stay.
#[test]
fn the_files_a_killed_run_left_are_removed() {
    let vcd = own("parts-left", "tb.vcd", ALL_KINDS);
    let d = vcd.parent().unwrap();
    // a pid no system gives (Linux: at most 4194304)
    let (gone, young, other, theirs) = (d.join("tb.fst.4000000001.part"), d.join("tb.fst.4000000002.part"), d.join("tb.vcd.4000000003.part"),
                                       d.join("tb.fst.4000000004.bak"));
    for p in [&gone, &other, &theirs] {
        old_file(p);
    }
    std::fs::write(&young, "x").unwrap();
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(!gone.exists(), "an old part of a process gone: removed");
    assert!(young.exists() && other.exists() && theirs.exists(), "a young part, another target's, another file: kept");
    let glued = std::env::temp_dir().join("sva-glued-4000000005-1.fst");
    old_file(&glued);
    let src = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/unit/vcd/glued.vcd");
    let o = sva(&["vcd", &src.to_string_lossy(), "--out", &d.join("glued.vcd").to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(!glued.exists(), "the FST of a glued VCD a killed run left in the temp directory: removed");
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

/// A dump cut off in the middle of a value (tests/unit/vcd/cut.vcd: the simulator still writing it) or of a time
/// (cut_time.vcd: #1 of #1000, back in time): the FST is written with everything before it, and a note says what was
/// left out (it was "not written").
#[test]
fn fst_of_a_dump_cut_off() {
    let vcd = own("fst-cut", "cut.vcd", &std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../../tests/unit/vcd/cut.vcd")).unwrap());
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(err(&o).contains("cut.vcd:19: a value without its code at the end of the file (cut off: still being written?"), "{}", err(&o));
    let t = out(&sva(&["vcd", &vcd.with_extension("fst").to_string_lossy()]));
    assert!(t.ends_with("#5\n1!\nb0001 \"\n#10\n0!\n"), "{t}");
    // a time cut short at the end (#1 after #10): left out; before the end it is the error it was
    let text = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../../tests/unit/vcd/cut_time.vcd")).unwrap();
    let vcd = own("fst-cut", "cut_time.vcd", &text);
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(err(&o).contains("cut_time.vcd:16: #1 after #10 at the end of the file (cut off"), "{}", err(&o));
    assert!(out(&sva(&["vcd", &vcd.with_extension("fst").to_string_lossy()])).ends_with("#10\n0!\n"));
    let vcd = own("fst-cut", "back.vcd", &(text + "\n1!\n"));
    let o = sva(&["fst", &vcd.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(2), "{}", err(&o));
    assert!(err(&o).contains("#1 after #10: the time goes back"), "{}", err(&o));
}

/// A dump whose time goes back: wellen says so with println!, and left on stdout that broke --json - and the VCD of a cut
/// (review 0.31 C1, R7). Skipped steps with the warning on stderr: diff, vcd, eval; sva fst refuses (above).
#[test]
fn time_back_warns_on_stderr() {
    let head = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n";
    let a = own("back-out", "a.vcd", &format!("{head}#0\n0!\n#100\n1!\n#120\n"));
    let b = own("back-out", "b.vcd", &format!("{head}#0\n0!\n#100\n1!\n#90\n0!\n#120\n"));
    let (a, b) = (a.to_string_lossy(), b.to_string_lossy());
    let o = sva(&["diff", &a, &b, "--json", "-", "--quiet"]);
    let j: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap_or_else(|e| panic!("{e}: {}", out(&o)));
    assert_eq!(j["wavelens"], "diff");
    assert!(err(&o).contains("time decreased from 100 to 90"), "{}", err(&o));
    let o = sva(&["vcd", &b, "--from", "0", "--to", "110ns"]);
    assert!(out(&o).starts_with('$') && !out(&o).contains("WARN"), "{}", out(&o));
    assert!(err(&o).contains("time decreased from 100 to 90"), "{}", err(&o));
    assert!(out(&sva(&["vcd", "--help"])).contains("usage: sva vcd"), "the help on stdout");
    assert!(out(&sva(&["diff", "--help"])).contains("usage: sva diff"), "the help on stdout");
}

/// A VCD whose integers are written without b, glued to their codes (Questa 2023: tests/unit/vcd/glued.vcd; st3 an enum
/// declared at its own width, its value in 32 digits all the same): sva fst reads them, and sva vcd and sva eval, which
/// read a VCD through wellen (it stops at the first one), read its FST.
#[test]
fn glued_vectors_are_read() {
    let vcd = concat!(env!("CARGO_MANIFEST_DIR"), "/../../tests/unit/vcd/glued.vcd");
    let o = sva(&["vcd", vcd]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    for want in ["b00000000000000000000000000000011 \"", "b0000000000000000000000000000xxxx #", "b1111 $", "b101 %", "#20\n0!"] {
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

// ---------------------------------------------------------------------------------------------------------- sva diff

/// A small test bench: a clock, a bus, a test case number (an int), a real, a string; `top` its top scope, `d30` the
/// bus at 30 ns, `shift` ns added to every time.
fn bench(top: &str, d30: &str, shift: u64) -> String {
    let mut t = format!("$timescale 1ns $end\n$scope module {top} $end\n$var wire 1 ! clk $end\n$var wire 4 \" d [3:0] $end\n\
        $var integer 32 # tb_test $end\n$var real 64 $ r $end\n$var string 1 % s $end\n$upscope $end\n$enddefinitions $end\n");
    for (at, vals) in [(0, "0!\nb0000 \"\nb0 #\nr0.5 $\nsidle %\n"), (10, "1!\nb1010 \"\nb1 #\n"), (20, "0!\n"),
                       (30, &*format!("1!\nb{d30} \"\nb10 #\n")), (40, "0!\nr1.5 $\nsdone %\n"), (50, "")] {
        t.push_str(&format!("#{}\n{vals}", at + shift));
    }
    t
}

fn diff_json(args: &[&str]) -> (Option<i32>, serde_json::Value, String) {
    let mut a = vec!["diff", "--json", "-"];
    a.extend_from_slice(args);
    let o = sva(&a);
    (o.status.code(), serde_json::from_slice(&o.stdout).unwrap_or_default(), err(&o))
}

/// `sva diff`: equal dumps exit 0 with every change counted once (a change in both at one time is one); one value
/// apart exits 1 with the first difference, the list and the stretch it differs over; the tops pair by themselves.
#[test]
fn diff_counts_the_changes_and_the_first_difference() {
    let a = write("da.vcd", &bench("tb", "1011", 0));
    let b = write("db.vcd", &bench("top", "1011", 0));
    let c = write("dc.vcd", &bench("top", "1111", 0));
    let (code, v, e) = diff_json(&[&a, &b]);
    assert_eq!(code, Some(0), "{e}");
    assert_eq!((v["compared"].as_u64(), v["differ"].as_u64(), v["signals_compared"].as_u64()), (Some(15), Some(0), Some(5)), "{v}");
    assert_eq!(v["map"], serde_json::json!([{"a": "tb", "b": "top", "auto": true, "signals": 5}]));
    assert_eq!((v["from"].as_u64(), v["to"].as_u64(), v["unit"].as_str()), (Some(0), Some(50_000), Some("ps")));
    let (code, v, _) = diff_json(&[&a, &c, "--spans", "4"]);
    assert_eq!(code, Some(1));
    assert_eq!(v["first"], serde_json::json!({"t": 30_000, "signal": "tb.d", "a": "1011", "b": "1111"}));
    assert_eq!((v["differ"].as_u64(), v["signals_differ"].as_u64(), v["more"].as_u64()), (Some(1), Some(1), Some(0)));
    let d = v["signals"].as_array().unwrap().iter().find(|s| s["path"] == "tb.d").unwrap();
    assert_eq!((d["b"].as_str(), d["width"].as_u64(), d["changes"].as_u64()), (Some("top.d"), Some(4), Some(3)));
    assert_eq!(d["spans"], serde_json::json!([[30_000, 50_000]]), "it differs from 30 ns to the end");
    let t = out(&sva(&["diff", &a, &c]));
    assert!(t.contains("5 signals compared, 0 ps … 50 ns") && t.contains("15 changes compared, 1 differ in 1 signal; the first at 30 ns: tb.d A=1011 B=1111"), "{t}");
}

/// Values compare as the viewer compares them: a bus of another width differs everywhere (not counted as changes),
/// inf and nan are values, a string is its text, x before a signal's first value; the signals of one dump only are
/// listed apart and change nothing.
#[test]
fn diff_compares_values_as_the_viewer_does() {
    let head = |w: u32, only: &str| format!("$timescale 1ps $end\n$scope module tb $end\n$var wire {w} \" d [{}:0] $end\n$var real 64 $ r $end\n\
        $var string 1 % s $end\n$var wire 1 & {only} $end\n$var wire 2 ' late [1:0] $end\n$upscope $end\n$enddefinitions $end\n", w - 1);
    let a = write("dka.vcd", &(head(4, "onlya") + "#0\nb0 \"\nrinf $\nshello %\n0&\n#5\nb10 '\n#10\nrnan $\nsworld %\n#20\n"));
    let b = write("dkb.vcd", &(head(8, "onlyb") + "#0\nb0 \"\nrinf $\nshello %\n0&\n#7\nb10 '\n#10\nrnan $\nsworld! %\n#20\n"));
    let (code, v, e) = diff_json(&[&a, &b, "--spans", "3"]);
    assert_eq!(code, Some(1), "{e}");
    let sig = |p: &str| v["signals"].as_array().unwrap().iter().find(|s| s["path"] == p).unwrap().clone();
    assert_eq!((sig("tb.d")["other"].as_str(), sig("tb.d")["changes"].as_u64()), (Some("8 bits"), Some(0)));
    assert_eq!(sig("tb.d")["spans"], serde_json::json!([[0, 20]]));
    assert_eq!(sig("tb.r")["differ"].as_u64(), Some(0), "inf = inf, nan = nan");
    assert_eq!(sig("tb.s")["first"], serde_json::json!({"t": 10, "signal": "tb.s", "a": "world", "b": "world!"}));
    assert_eq!(sig("tb.late")["spans"], serde_json::json!([[5, 7]]), "x in B until its first value");
    assert_eq!((v["only_a"].clone(), v["only_b"].clone()), (serde_json::json!(["tb.onlya"]), serde_json::json!(["tb.onlyb"])));
    assert_eq!(v["signals_differ"].as_u64(), Some(3));
}

/// --map: a scope pair (the longest one wins) and an exact pair of paths (it wins over a scope); a rule that pairs
/// nothing is a note; --signals: paths and patterns, a path without its pair in B is exit 2.
#[test]
fn diff_maps_names_and_picks_signals() {
    let a = write("dma.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! x $end\n$scope module bus $end\n$var wire 1 \" v $end\n\
        $var wire 1 # w $end\n$upscope $end\n$var wire 1 $ data $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n0\"\n0#\n0$\n#5\n1!\n1\"\n1$\n#9\n");
    let b = write("dmb.vcd", "$timescale 1ns $end\n$scope module top $end\n$var wire 1 ! x $end\n$scope module bif $end\n$var wire 1 \" v $end\n\
        $var wire 1 # w $end\n$var wire 1 $ data $end\n$upscope $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n0\"\n0#\n0$\n#5\n1!\n1\"\n1$\n#9\n");
    let (code, v, e) = diff_json(&[&a, &b, "--map", "tb.bus=top.bif", "--map", "tb.data=top.bif.data", "--map", "tb.nothing=top.no"]);
    assert_eq!(code, Some(0), "{e}");
    assert_eq!(v["signals_compared"].as_u64(), Some(4), "{v}");
    let pairs: Vec<(String, String)> = v["signals"].as_array().unwrap().iter().map(|s| (s["path"].as_str().unwrap().into(), s["b"].as_str().unwrap().into())).collect();
    assert!(pairs.contains(&("tb.bus.v".into(), "top.bif.v".into())) && pairs.contains(&("tb.data".into(), "top.bif.data".into()))
            && pairs.contains(&("tb.x".into(), "top.x".into())), "{pairs:?}");
    assert!(v["notes"][0].as_str().unwrap().contains("--map tb.nothing=top.no: no signal paired by it"), "{v}");
    // without the alias tb.data has no pair: listed, not an error; asked for by name, exit 2
    let (code, v, _) = diff_json(&[&a, &b, "--map", "tb.bus=top.bif"]);
    assert_eq!((code, v["only_a"].clone()), (Some(0), serde_json::json!(["tb.data"])));
    let (code, _, e) = diff_json(&[&a, &b, "--signals", "data"]);
    assert_eq!(code, Some(2));
    assert!(e.contains("no signal top.data (the pair of tb.data"), "{e}");
    let (code, v, _) = diff_json(&[&a, &b, "--map", "tb.bus=top.bif", "--signals", "tb.bus.*"]);
    assert_eq!((code, v["signals_compared"].as_u64(), v["only_b"].as_array().map(Vec::len)), (Some(0), Some(2), Some(0)));
    // --signals-from: a page's rows; one not in A or without its pair is listed, not an error
    let list = write("dm.list", "tb.x\ntb.data\ntb.nothing\n");
    let (code, v, e) = diff_json(&[&a, &b, "--signals-from", &list]);
    assert_eq!((code, v["signals_compared"].as_u64()), (Some(0), Some(1)), "{e}");
    assert_eq!((v["only_a"].clone(), v["not_in_a"].clone(), v["only_b"].clone()), (serde_json::json!(["tb.data"]), serde_json::json!(["tb.nothing"]), serde_json::json!([])));
    let (code, _, e) = diff_json(&[&a, &b, "--signals", "tb.nope*"]);
    assert_eq!(code, Some(2));
    assert!(e.contains("no signal matches tb.nope*"), "{e}");
}

/// --from / --to: the window in A's time, its ends included; --offset: B later by that much (the same run 5 ns
/// later: equal with it, not without); no time in common is exit 2.
#[test]
fn diff_windows_and_offsets() {
    let a = write("dwa.vcd", &bench("tb", "1011", 0));
    let b = write("dwb.vcd", &bench("tb", "1011", 5));
    let (code, v, _) = diff_json(&[&a, &b]);
    assert_eq!((code, v["from"].as_u64()), (Some(1), Some(5_000)), "the window both cover");
    let (code, v, e) = diff_json(&[&a, &b, "--offset", "5ns"]);
    assert_eq!((code, v["compared"].as_u64(), v["offset"].as_i64()), (Some(0), Some(15), Some(5_000)), "{e}");
    let (code, v, _) = diff_json(&[&a, &b, "--offset", "5ns", "--from", "10ns", "--to", "30ns"]);
    assert_eq!((code, v["compared"].as_u64(), v["from"].as_u64(), v["to"].as_u64()), (Some(0), Some(7), Some(10_000), Some(30_000)));
    let (code, _, e) = diff_json(&[&b, &a, "--offset", "-5ns"]);
    assert_eq!(code, Some(0), "{e}");
    let (code, _, e) = diff_json(&[&a, &b, "--from", "60ns"]);
    assert_eq!(code, Some(2));
    assert!(e.contains("no time in common"), "{e}");
}

/// --segment: the counts per change of the test case number in A (its value as a number); --align: segment k of B
/// from the k-th change in B, compared on the length both have (B's case 1 is 10 ns longer: cut there, equal).
#[test]
fn diff_segments_and_aligns_them() {
    let a = write("dsa.vcd", &bench("tb", "1011", 0));
    let c = write("dsc.vcd", &bench("tb", "1111", 0));
    let (code, v, _) = diff_json(&[&a, &c, "--segment", "tb_test"]);
    assert_eq!(code, Some(1));
    let segs: Vec<(u64, String, u64, u64)> = v["segments"].as_array().unwrap().iter()
        .map(|s| (s["n"].as_u64().unwrap(), s["value"].as_str().unwrap().into(), s["changes"].as_u64().unwrap(), s["differ"].as_u64().unwrap())).collect();
    assert_eq!(segs, [(1, "0".into(), 5, 0), (2, "1".into(), 4, 0), (3, "2".into(), 6, 1)], "{v}");
    let t = out(&sva(&["diff", &a, &c, "--segment", "tb_test"]));
    assert!(t.contains("segment 3 (tb_test = 2): 30 ns … 50 ns: 6 changes, 1 differ; the first at 30 ns: tb.d A=1011 B=1111"), "{t}");
    // B: case 1 runs 30 ns, not 20
    let long = bench("tb", "1011", 0).replace("#30\n1!\nb1011 \"\nb10 #\n#40\n0!\nr1.5 $\nsdone %\n#50\n",
        "#30\n1!\n#35\n0!\n#40\n1!\nb1011 \"\nb10 #\n#50\n0!\nr1.5 $\nsdone %\n#60\n");
    let g = write("dsg.vcd", &long);
    assert_eq!(diff_json(&[&a, &g, "--segment", "tb_test"]).0, Some(1), "not aligned: they differ from 30 ns");
    let (code, v, e) = diff_json(&[&a, &g, "--segment", "tb_test", "--align"]);
    assert_eq!(code, Some(0), "{e}");
    let s = &v["segments"][2];
    assert_eq!((s["from"].as_u64(), s["b_from"].as_u64(), s["compared_to"].as_u64()), (Some(30_000), Some(40_000), Some(50_000)), "{v}");
    assert_eq!(v["segments"][1]["compared_to"].as_u64(), Some(30_000), "case 1 compared on A's 20 ns");
    assert_eq!(diff_json(&[&a, &g, "--align"]).0, Some(2), "--align without --segment");
    // B stops in case 1 (at 25 ns, no case 2): case 1 compared to there, case 2 not compared, said in a note
    let short = bench("tb", "0000", 0).split("#30\n").next().unwrap().to_string() + "#25\n";
    let h = write("dsh.vcd", &short);
    let (code, v, e) = diff_json(&[&a, &h, "--segment", "tb_test", "--align"]);
    assert_eq!(code, Some(0), "{e} {v}");
    assert_eq!((v["segments"][1]["compared_to"].as_u64(), v["segments"][2]["b_from"].clone()), (Some(25_000), serde_json::Value::Null), "{v}");
    assert_eq!(v["segments"][2]["differ"].as_u64(), Some(0));
    assert!(v["notes"][0].as_str().unwrap().contains("3 segments in A, 2 in B"), "{v}");
    // B has two segments more (review 0.31 R2): compared up to where B left the last common one, said in a note
    let more = bench("tb", "1011", 0).replace("#40\n0!\nr1.5 $\nsdone %\n#50\n", "#40\n0!\nr1.5 $\nsdone %\nb11 #\n#45\nb100 #\n#50\n");
    let m = write("dsm.vcd", &more);
    let (_, v, e) = diff_json(&[&a, &m, "--segment", "tb_test", "--align"]);
    assert_eq!(v["segments"].as_array().map(Vec::len), Some(3), "{e} {v}");
    assert_eq!(v["segments"][2]["compared_to"].as_u64(), Some(40_000), "{v}");
    assert!(v["notes"][0].as_str().unwrap().contains("3 segments in A, 5 in B: the last ones of B are not compared"), "{v}");
}

/// The JUnit report (review 0.31 T20): names and values escaped, failures counted. `--spans` keeps as many as it is told and
/// counts the rest (T21); a real of -0 is 0 (T24); --json takes a name ending with .json (R4); a width of 1 is one bit (R6).
#[test]
fn diff_reports_escaped_and_capped() {
    let head = |w: u32| format!("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a<b $end\n$var string 1 \" s $end\n$var real 64 # r $end\n\
        $var wire {w} $ v $end\n$upscope $end\n$enddefinitions $end\n");
    let a = write("dea.vcd", &(head(1) + "#0\n0!\nsx&y \"\nr0 #\n0$\n#10\n1!\n#20\n0!\n#30\n1!\n#40\n0!\n#50\n"));
    let b = write("deb.vcd", &(head(4) + "#0\n1!\nsy&z \"\nr-0 #\nb0 $\n#10\n0!\n#20\n1!\n#30\n0!\n#40\n1!\n#50\n"));
    let dir = std::env::temp_dir();
    let (ju, js) = (dir.join("sva-de.xml"), dir.join("sva-de-out.json"));
    let o = sva(&["diff", &a, &b, "--junit", &ju.to_string_lossy(), "--json", &js.to_string_lossy()]);
    assert_eq!(o.status.code(), Some(1), "{}", err(&o));
    let x = std::fs::read_to_string(&ju).unwrap();
    assert!(x.contains("tb.a&lt;b") && !x.contains("a<b") && x.contains("x&amp;y") && x.contains("failures=\"2\""), "{x}");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&js).unwrap()).unwrap();
    let sig = |n: &str| v["signals"].as_array().unwrap().iter().find(|s| s["path"] == n).unwrap().clone();
    assert_eq!(sig("tb.r")["differ"].as_u64(), Some(0), "-0 is 0: {v}");
    assert_eq!(sig("tb.v")["other"], "4 bits", "{v}");
    let one = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n";
    let flat = write("def.vcd", &format!("{one}#0\n0!\n#50\n"));
    let three = write("det.vcd", &format!("{one}#0\n0!\n#10\n1!\n#15\n0!\n#20\n1!\n#25\n0!\n#30\n1!\n#35\n0!\n#50\n"));
    let once = write("deo.vcd", &format!("{one}#0\n0!\n#10\n1!\n#50\n"));
    assert_eq!(sva(&["diff", &flat, &once, "--junit", &ju.to_string_lossy()]).status.code(), Some(1));
    let x = std::fs::read_to_string(&ju).unwrap();
    assert!(x.contains("failures=\"1\""), "one change that differs is a failure: {x}");
    let (_, w, _) = diff_json(&[&flat, &three, "--spans", "1"]);
    let s = &w["signals"][0];
    assert_eq!((s["spans"].as_array().map(Vec::len), s["more"].as_u64()), (Some(1), Some(2)), "{w}");
    let t = out(&sva(&["diff", &b, &a]));
    assert!(t.contains("4 bits in A, 1 bit in B"), "{t}");
    let o = sva(&["diff", &a, &b, "--json", "out.txt"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("two dumps, A and B (3 given:") && err(&o).contains("out.txt"), "{}", err(&o));
}

/// A VCD whose last step is longer than the tail read for its end (review 0.31 R1, T23): the end is its last #time for
/// sva diff and a cut; a cut word of the tail, or an id code, is not taken for one.
#[test]
fn the_end_of_a_long_last_step() {
    let head = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$var wire 1 #12 c $end\n$var wire 8 #5 d [7:0] $end\n$upscope $end\n$enddefinitions $end\n";
    let long = "0!\n".repeat(30_000);
    assert!(long.len() > 1 << 16);
    let v = write("eol.vcd", &format!("{head}#0\n0!\n1#12\n#9000\n1#12\n{long}"));
    let a = write("eol-a.vcd", &format!("{head}#0\n0!\n1#12\n#9000\n1#12\n"));
    let o = sva(&["vcd", &v, "--signals", "tb.a"]);
    assert_eq!(out(&o).lines().rfind(|l| l.starts_with('#')), Some("#9000"), "{}", err(&o));
    let (_, j, e) = diff_json(&[&a, &v]);
    assert_eq!(j["to"].as_u64(), Some(9_000_000), "{e}");
    // the tail starts right after the 1 of 1#12: "#12" is no time, and no more is the id code of `b1 #5` at the end
    let tail = format!("#12\n{}", "0!\n".repeat((1 << 16) / 3 - 3));
    let n = (1 << 16) - tail.len() - 6;
    let tail = tail + &"\n".repeat(n) + "b1 #5\n";
    let v = write("eol-2.vcd", &format!("{head}#0\n0!\n#9000\n1{tail}"));
    assert_eq!(out(&sva(&["vcd", &v, "--signals", "tb.a"])).lines().rfind(|l| l.starts_with('#')), Some("#9000"));
}

/// The times of --from / --to as the tools and the page read them (review 0.31 P2): any case, µs, an exponent.
#[test]
fn times_read_as_everywhere() {
    let head = "$timescale 1ps $end\n$scope module tb $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n";
    let v = write("tr.vcd", &format!("{head}#0\n0!\n#50000\n1!\n#100000\n"));
    for t in ["0.04µs", "40NS", "4E-2us", "4e4", " 40 ns"] {
        let o = sva(&["vcd", &v, "--from", t]);
        assert_eq!(o.status.code(), Some(0), "{t}: {}", err(&o));
        assert!(out(&o).contains("#40000\n"), "{t}: {}", out(&o));
    }
    for (t, msg) in [("5 parsecs", "not a time unit"), ("1.2.3ns", "not a time"), ("ns", "not a time"), ("-5ns", "0 or more")] {
        let o = sva(&["vcd", &v, "--from", t]);
        assert_eq!(o.status.code(), Some(2), "{t}");
        assert!(err(&o).contains(msg), "{t}: {}", err(&o));
    }
}

/// A cut (review 0.31 T25): a bit without a value at --from is x, a time rounded to the dump's unit; --signals-from and
/// --codes read stdin (T27); a word that is no id code is an error.
#[test]
fn cuts_rounding_and_stdin_lists() {
    let head = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$var wire 1 \" late $end\n$upscope $end\n$enddefinitions $end\n";
    let v = write("cr.vcd", &format!("{head}#0\n0!\n#10\n1\"\n#20\n1!\n#30\n"));
    let t = out(&sva(&["vcd", &v, "--from", "2.6ns", "--to", "20ns"]));
    assert!(t.contains("#3\n$dumpvars\n0!\nx\"\n$end") || t.contains("#3\n"), "{t}");
    assert!(t.contains("x\""), "a bit without a value yet: {t}");
    let piped = |args: &[&str], input: &str| {
        use std::io::Write;
        let mut c = Command::new(env!("CARGO_BIN_EXE_sva")).args(args).stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).spawn().unwrap();
        c.stdin.take().unwrap().write_all(input.as_bytes()).unwrap();
        c.wait_with_output().unwrap()
    };
    let o = piped(&["vcd", &v, "--signals-from", "-"], "tb.a\n");
    assert!(out(&o).contains("a $end") && !out(&o).contains("late"), "{}", out(&o));
    let o = piped(&["diff", &v, &v, "--signals-from", "-", "--json", "-", "--quiet"], "tb.a\ntb.nope\n");
    let j: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!((j["signals_compared"].as_u64(), j["not_in_a"][0].as_str()), (Some(1), Some("tb.nope")), "{j}");
    let f = own("cr-fst", "c.vcd", &format!("{head}#0\n0!\n#10\n1\"\n#20\n1!\n#30\n"));
    assert_eq!(sva(&["fst", &f.to_string_lossy(), "--no-types", "-q"]).status.code(), Some(0));
    let fst = f.with_extension("fst");
    let o = piped(&["vcd", &fst.to_string_lossy(), "--codes", "-"], "!\n");
    assert!(out(&o).contains("#20"), "{}", out(&o));
    let o = piped(&["vcd", &fst.to_string_lossy(), "--codes", "-"], "é\n");
    assert_eq!(o.status.code(), Some(2), "{}", err(&o));
}

/// The outputs: --json FILE beside the text, --junit a test case per segment with the first differences, --limit the
/// differences listed; a dump that is not one is exit 2.
#[test]
fn diff_writes_json_and_junit() {
    let a = write("doa.vcd", &bench("tb", "1011", 0));
    let b = write("dob.vcd", &bench("tb", "1011", 5));
    let (j, x) = (dir().join("do.json"), dir().join("do.xml"));
    let o = sva(&["diff", &a, &b, "--json", &j.to_string_lossy(), "--junit", &x.to_string_lossy(), "--limit", "2", "--segment", "tb_test"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(out(&o).contains("… and"), "{}", out(&o));
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&j).unwrap()).unwrap();
    assert_eq!(v["differences"].as_array().map(Vec::len), Some(2));
    assert_eq!(v["more"].as_u64(), Some(v["differ"].as_u64().unwrap() - 2));
    let xml = std::fs::read_to_string(&x).unwrap();
    assert!(xml.contains("<testsuite name=\"diff ") && xml.contains("name=\"segment 2 (tb_test = 1)\"") && xml.contains("<failure type=\"differ\" message=\""), "{xml}");
    assert_eq!(xml.matches("<testcase ").count(), 3, "{xml}");
    let bad = write("dbad.vcd", "not a dump\n");
    let o = sva(&["diff", &a, &bad]);
    assert_eq!(o.status.code(), Some(2), "{}", err(&o));
    assert_eq!(sva(&["diff", &a]).status.code(), Some(2));
    assert!(out(&sva(&["diff", "--help"])).contains("usage: sva diff"));
}

/// A VCD pair and the FST pair made of it (sva fst) give the same result, byte for byte but the file names; a Questa
/// 2023 VCD with values glued to their codes is read through its FST.
#[test]
fn diff_of_fsts_is_the_diff_of_their_vcds() {
    let a = write("dfa.vcd", &bench("tb", "1011", 0));
    let c = write("dfc.vcd", &bench("top", "1111", 0));
    for f in [&a, &c] {
        assert_eq!(sva(&["fst", f, "-q"]).status.code(), Some(0));
    }
    let fa = a.replace(".vcd", ".fst");
    let fc = c.replace(".vcd", ".fst");
    let args = ["--segment", "tb_test", "--spans", "9"];
    let (_, v, _) = diff_json(&[&[a.as_str(), c.as_str()][..], &args].concat());
    let (_, f, e) = diff_json(&[&[fa.as_str(), fc.as_str()][..], &args].concat());
    assert_eq!(v.to_string().replace(".vcd", ".X"), f.to_string().replace(".fst", ".X"), "{e}");
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let glued = root.join("tests/unit/vcd/glued.vcd").to_string_lossy().into_owned();
    let o = sva(&["diff", &glued, &glued]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(err(&o).contains("glued to their codes"), "{}", err(&o));
}

/// `sva vcd --from --to --signals`: those signals' declarations only (their scope), their values at --from as
/// $dumpvars (x when none yet), the changes up to --to, then #to; the same of the FST; with --header, exit 2.
#[test]
fn vcd_cuts_a_window_out_of_a_dump() {
    let a = write("cut_src.vcd", &bench("tb", "1011", 0));
    let o = sva(&["vcd", &a, "--from", "15ns", "--to", "35ns", "--signals", "tb.d,tb.c*"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let t = out(&o);
    assert!(t.contains("$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 4 \" d [3:0] $end\n$upscope $end\n$enddefinitions $end\n\
        #15\n$dumpvars\n1!\nb1010 \"\n$end\n#20\n0!\n#30\n1!\nb1011 \"\n#35\n"), "{t}");
    assert!(!t.contains("tb_test") && t.ends_with("#35\n"), "{t}");
    assert_eq!(sva(&["fst", &a, "-q"]).status.code(), Some(0));
    let f = out(&sva(&["vcd", &a.replace(".vcd", ".fst"), "--from", "15ns", "--to", "35ns", "--signals", "tb.d,tb.c*"]));
    assert!(f.contains("$enddefinitions $end\n#15\n$dumpvars\n1!\nb1010 \"\n$end\n#20\n0!\n#30\n1!\nb1011 \"\n#35\n"), "{f}");
    // a signal without a value at --from: x; a window past the end ends at the end
    let late = write("cut_late.vcd", "$timescale 1ns $end\n$scope module tb $end\n$var wire 2 ! q [1:0] $end\n$var wire 1 \" b $end\n$upscope $end\n\
        $enddefinitions $end\n#0\n0\"\n#8\nb10 !\n#9\n");
    let t = out(&sva(&["vcd", &late, "--from", "2ns", "--to", "1us"]));
    assert!(t.contains("#2\n$dumpvars\nbxx !\n0\"\n$end\n#8\nb10 !\n#9\n") && t.ends_with("#9\n"), "{t}");
    assert_eq!(sva(&["vcd", &late, "--signals", "tb.zz"]).status.code(), Some(2));
    assert!(out(&sva(&["vcd", &late, "--signals", "q"])).contains("$var wire 2 ! q [1:0] $end\n$upscope"), "a name: the one path ending with it");
    assert_eq!(sva(&["vcd", &late, "--from", "1ns", "--header"]).status.code(), Some(2));
    // --signals-from: a list in a file, one a line (a list too long for a command line)
    let list = write("cut_list.txt", "tb.q\n\n  tb.b  \n");
    let t = out(&sva(&["vcd", &late, "--signals-from", &list]));
    assert!(t.contains("$var wire 2 ! q [1:0] $end\n$var wire 1 \" b $end\n$upscope"), "{t}");
    assert_eq!(sva(&["vcd", &late, "--signals-from", "cut_no_such_list.txt"]).status.code(), Some(2));
}

/// Stage 23: `sva diff --rank`: the signals by the time of their first difference, with the time from the first one;
/// N cuts the list.
#[test]
fn diff_ranks_who_differed_first() {
    let head = "$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$var wire 1 \" b $end\n$var wire 1 # c $end\n$upscope $end\n$enddefinitions $end\n";
    let a = write("rka.vcd", &format!("{head}#0\n0!\n0\"\n0#\n#40\n"));
    let b = write("rkb.vcd", &format!("{head}#0\n0!\n0\"\n0#\n#10\n1#\n#18\n1!\n#30\n1\"\n#40\n"));
    let (code, v, e) = diff_json(&[&a, &b, "--rank"]);
    assert_eq!(code, Some(1), "{e}");
    let r: Vec<(String, i64)> = v["rank"].as_array().unwrap().iter().map(|x| (x["signal"].as_str().unwrap().to_string(), x["after_first_ps"].as_i64().unwrap())).collect();
    assert_eq!(r, vec![("tb.c".into(), 0), ("tb.a".into(), 8000), ("tb.b".into(), 20000)], "by time, not by name: {v}");
    let (_, v, _) = diff_json(&[&a, &b, "--rank", "2"]);
    assert_eq!(v["rank"].as_array().unwrap().len(), 2);
    let t = out(&sva(&["diff", &a, &b, "--rank"]));
    assert!(t.contains("first to differ: tb.c at 10 ns; then tb.a (+8 ns), tb.b (+20 ns)"), "{t}");
    let (_, v, _) = diff_json(&[&a, &b]);
    assert!(v.get("rank").is_none(), "no rank unless asked");
}

/// A results JSON of `sva eval` as the test writes it: assertion name -> [(start cycle, failed cycle)], cycles every 10 ns.
fn results(name: &str, fails: &[(&str, &[(u64, u64)])]) -> String {
    let cycles: Vec<u64> = (0..20).map(|k| k * 10_000).collect();
    let asr: Vec<serde_json::Value> = fails.iter().map(|(n, f)| serde_json::json!({"name": n, "kind": "assert", "scope": "tb",
        "stats": {"fail": f.len()}, "attempts": f.iter().map(|(s, a)| serde_json::json!({"start": s, "end": a, "result": "fail", "failed_at": a}))
            .chain(std::iter::once(serde_json::json!({"start": 1, "end": 2, "result": "pass"}))).collect::<Vec<_>>()})).collect();
    write(name, &serde_json::json!({"clock": "tb.clk", "unit": "ps", "cycles": cycles, "assertions": asr}).to_string())
}

/// Stage 23: `sva diff --results`: the failures of two runs paired by their start: new, gone, moved; the exit; JUnit; a
/// dump with them is refused.
#[test]
fn diff_results_new_gone_moved() {
    let a = results("ra.json", &[("p", &[(3, 5), (8, 9)]), ("q", &[]), ("old", &[(2, 4)])]);
    let same = sva(&["diff", "--results", &a, &a]);
    assert_eq!(same.status.code(), Some(0), "{}", err(&same));
    assert!(out(&same).contains("0 new, 0 gone, 0 moved"));
    let b = results("rb.json", &[("p", &[(3, 6), (8, 9)]), ("q", &[(4, 7)]), ("fresh", &[(1, 2), (5, 6)])]);
    let o = sva(&["diff", "--results", &a, &b, "--json", "-", "--junit", &format!("{}/r.xml", dir().display())]);
    assert_eq!(o.status.code(), Some(1), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!((v["new"].as_u64(), v["gone"].as_u64(), v["moved"].as_u64()), (Some(3), Some(1), Some(1)), "{v}");
    let row = |n: &str| v["assertions"].as_array().unwrap().iter().find(|r| r["name"] == n).unwrap().clone();
    assert_eq!(row("p")["moved"], serde_json::json!([{"a": {"start": 30_000, "failed_at": 50_000}, "b": {"start": 30_000, "failed_at": 60_000}}]));
    assert_eq!((row("q")["new"].as_array().unwrap().len(), row("fresh")["new"].as_array().unwrap().len(), row("old")["gone"].as_array().unwrap().len()), (1, 2, 1));
    assert_eq!(row("q")["first_new"].as_u64(), Some(40_000));
    let x = std::fs::read_to_string(dir().join("r.xml")).unwrap();
    assert!(x.contains("tests=\"4\" failures=\"3\"") && x.contains("1 gone"), "p moved, q and fresh new; old gone in its system-out: {x}");
    // as many new as gone: moved
    let c = results("rc.json", &[("p", &[(4, 5), (9, 9)]), ("q", &[]), ("old", &[(2, 4)])]);
    let (code, v, _) = diff_json(&["--results", &a, &c]);
    assert_eq!((code, v["moved"].as_u64(), v["new"].as_u64(), v["gone"].as_u64()), (Some(1), Some(2), Some(0), Some(0)), "{v}");
    let d = write("rd.vcd", "$timescale 1ns $end\n$enddefinitions $end\n#0\n");
    assert_eq!(sva(&["diff", "--results", &a, &d]).status.code(), Some(2), "a dump is not a results JSON");
    assert_eq!(sva(&["diff", "--results", &a, &b, "--rank"]).status.code(), Some(2), "--rank is of two dumps");
}

/// Review S23-1, S23-3: a cover compares its matches (one that stops matching in B is lost: exit 1, a coverage regression);
/// one name present twice in a scope pairs by its order (a file against itself: exit 0).
#[test]
fn diff_results_covers_and_twice_one_name() {
    let cover = |name: &str, m: u64| {
        let asr = serde_json::json!([{"name": "c", "kind": "cover", "scope": "tb", "stats": {"attempts": 19, "pass": m, "fail": 19 - m, "matches": m},
            "attempts": (0..m).map(|k| serde_json::json!({"start": k, "end": k + 1, "result": "pass"})).collect::<Vec<_>>()}]);
        write(name, &serde_json::json!({"clock": "tb.clk", "unit": "ps", "cycles": (0..20).map(|k| k * 10_000).collect::<Vec<u64>>(),
            "assertions": asr}).to_string())
    };
    let (a, b) = (cover("ca.json", 2), cover("cb.json", 0));
    assert_eq!(sva(&["diff", "--results", &a, &a]).status.code(), Some(0));
    let (code, v, _) = diff_json(&["--results", &a, &b]);
    assert_eq!((code, v["lost"].as_u64(), v["found"].as_u64()), (Some(1), Some(1), Some(0)), "{v}");
    assert_eq!((v["assertions"][0]["lost"].as_bool(), v["assertions"][0]["a"]["matches"].as_u64()), (Some(true), Some(2)), "{v}");
    let o = sva(&["diff", "--results", &a, &b]);
    assert!(out(&o).contains("cover c @ tb: lost — matches A 2, B 0"), "{}", out(&o));
    let (code, v, _) = diff_json(&["--results", &b, &a]);
    assert_eq!((code, v["found"].as_u64()), (Some(0), Some(1)), "a cover that starts matching is no failure: {v}");
    // one name twice in one scope (two files bound the same label): the same file is no change
    let twice = write("tw.json", &serde_json::json!({"clock": "tb.clk", "unit": "ps", "cycles": [0, 10_000, 20_000, 30_000], "assertions": [
        {"name": "p", "kind": "assert", "scope": "tb", "stats": {"fail": 1}, "attempts": [{"start": 0, "end": 1, "result": "fail", "failed_at": 1}]},
        {"name": "p", "kind": "assert", "scope": "tb", "stats": {"fail": 1}, "attempts": [{"start": 2, "end": 3, "result": "fail", "failed_at": 3}]}]})
        .to_string());
    let (code, v, _) = diff_json(&["--results", &twice, &twice]);
    assert_eq!((code, v["new"].as_u64(), v["gone"].as_u64(), v["moved"].as_u64()), (Some(0), Some(0), Some(0), Some(0)), "{v}");
}

// ------------------------------------------------------------------------------------------------ sva runs (review 2026-11-05 runs)

/// A directory of its own for a test of sva runs (they run in parallel).
fn runs_dir(name: &str) -> PathBuf {
    let d = dir().join(format!("runs-{name}"));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// 40 ns of a counter: cnt counts each rising edge of clk; from `bad` on, ok goes 0; `extra`: one more signal.
fn counter(bad: Option<u64>, extra: bool) -> String {
    let mut s = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 4 \" cnt [3:0] $end\n$var wire 1 # ok $end\n");
    if extra {
        s += "$var wire 1 $ extra $end\n";
    }
    s += "$upscope $end\n$enddefinitions $end\n#0\n0!\nb0 \"\n1#\n";
    if extra {
        s += "0$\n";
    }
    for t in (5..=40).step_by(5) {
        s += &format!("#{t}\n{}!\n", t / 5 % 2);
        if t % 10 == 5 {
            s += &format!("b{:b} \"\n", t / 10);
        }
        if bad == Some(t) {
            s += "0#\n";
        }
    }
    s
}

fn put(d: &std::path::Path, name: &str, text: &str) -> String {
    let p = d.join(name);
    std::fs::write(&p, text).unwrap();
    p.to_string_lossy().into_owned()
}

fn runs_json(d: &std::path::Path) -> serde_json::Value {
    serde_json::from_str(&std::fs::read_to_string(d.join("runs.json")).unwrap()).unwrap()
}

#[test]
fn runs_gitignore_only_of_their_own() {
    let d = runs_dir("gitignore");
    let dump = put(&d, "d.vcd", &counter(None, false));
    put(&d, "main.sv", "module m; endmodule\n");
    let o = sva(&["runs", "keep", &dump, "--dir", &d.to_string_lossy()]);
    assert!(o.status.success(), "{}", err(&o));
    let gi = std::fs::read_to_string(d.join(".gitignore")).unwrap();
    assert!(!gi.lines().any(|l| l == "*") && gi.contains("*.fst") && gi.contains("runs.json*"), "a folder of yours: only the runs' files\n{gi}");
    assert!(err(&o).contains(".gitignore"), "said: {}", err(&o));
    let sub = d.join("made");
    assert!(sva(&["runs", "keep", &dump, "--dir", &sub.to_string_lossy()]).status.success());
    assert!(std::fs::read_to_string(sub.join(".gitignore")).unwrap().lines().any(|l| l == "*"), "a directory keep made: ignored whole");
}

#[test]
fn runs_rm_finds_every_run_first() {
    let d = runs_dir("rm");
    let dump = put(&d, "d.vcd", &counter(None, false));
    for n in ["a", "b"] {
        assert!(sva(&["runs", "keep", &dump, "--name", n]).status.success());
    }
    let r = d.join(".wavelens-runs");
    let rs = r.to_string_lossy();
    let o = sva(&["runs", "rm", "a", "nope", "--dir", &rs]);
    assert_eq!(o.status.code(), Some(2));
    assert!(r.join("1-d.fst").exists(), "a run not found: nothing removed");
    assert_eq!(runs_json(&r)["runs"].as_array().unwrap().len(), 2);
    assert!(sva(&["runs", "rm", "a", "#2", "--dir", &rs]).status.success());
    assert!(!r.join("1-d.fst").exists() && !r.join("2-d.fst").exists());
    assert_eq!(runs_json(&r)["runs"].as_array().unwrap().len(), 0);
    let empty = runs_dir("rm-empty");
    let o = sva(&["runs", "rm", "1", "--dir", &empty.join(".wavelens-runs").to_string_lossy()]);
    assert!(err(&o).contains("no runs kept"), "{}", err(&o));
}

#[test]
fn runs_index_checked() {
    let d = runs_dir("index");
    let ds = d.to_string_lossy().into_owned();
    std::fs::write(d.join("runs.json"), r#"{"wavelens": "runs", "version": 1, "next": 2, "runs": [{"id": 1, "name": "x", "file": "../victim.fst"}]}"#).unwrap();
    put(&d.join(".."), "victim.fst", "x");
    for args in [vec!["runs", "--dir", &ds], vec!["runs", "rm", "1", "--dir", &ds], vec!["runs", "path", "1", "--dir", &ds]] {
        let o = sva(&args);
        assert_eq!(o.status.code(), Some(2), "{args:?}");
        assert!(err(&o).contains("runs.json") && err(&o).contains("a file name"), "{args:?}: {}", err(&o));
    }
    assert!(d.join("../victim.fst").exists(), "never reached");
    std::fs::write(d.join("runs.json"), r#"{"wavelens": "runs", "version": 2, "runs": []}"#).unwrap();
    assert!(err(&sva(&["runs", "--dir", &ds])).contains("newer WaveLens"));
}

#[test]
fn runs_the_directory_rule() {
    let d = runs_dir("rule");
    let dump = put(&d, "d.vcd", &counter(None, false));
    assert!(sva(&["runs", "keep", &dump, "--name", "one"]).status.success());
    // set / path / rm take the dump, from another directory
    let o = sva(&["runs", "set", "1", &dump, "--name", "two"]);
    assert!(o.status.success(), "{}", err(&o));
    assert_eq!(out(&sva(&["runs", "path", "two", &dump])).trim(), d.join(".wavelens-runs").join("1-d.fst").to_string_lossy());
    // a run's FST kept again: into its own directory, not a nested one
    let fst = d.join(".wavelens-runs").join("1-d.fst");
    assert!(sva(&["runs", "keep", &fst.to_string_lossy(), "--name", "again"]).status.success());
    assert!(!d.join(".wavelens-runs").join(".wavelens-runs").exists());
    assert_eq!(runs_json(&d.join(".wavelens-runs"))["runs"].as_array().unwrap().len(), 2);
}

#[test]
fn runs_of_one_dump_in_a_shared_directory() {
    let d = runs_dir("shared");
    let ds = d.join("shared").to_string_lossy().into_owned();
    let a = put(&d, "a.vcd", &counter(None, false));
    let b = put(&d, "b.vcd", &counter(Some(25), false));
    assert!(sva(&["runs", "keep", &a, "--dir", &ds, "--name", "A1"]).status.success());
    assert!(sva(&["runs", "keep", &b, "--dir", &ds, "--name", "B1"]).status.success());
    let l: serde_json::Value = serde_json::from_str(&out(&sva(&["runs", "list", &a, "--dir", &ds, "--json"]))).unwrap();
    assert_eq!((l["runs"].as_array().unwrap().len(), l["others"].as_u64()), (1, Some(1)), "{l}");
    let o = sva(&["runs", "diff", &a, "--dir", &ds]);
    assert_eq!(o.status.code(), Some(0), "only a's run: equal\n{}", out(&o));
    assert!(out(&o).contains("1 of other dumps not compared"), "{}", out(&o));
    assert_eq!(sva(&["runs", "diff", &a, "--dir", &ds, "--all"]).status.code(), Some(1), "--all: b's run too");
}

#[test]
fn runs_options_and_edges() {
    let d = runs_dir("edges");
    let dump = put(&d, "d.vcd", &counter(None, false));
    assert!(err(&sva(&["runs", "keep", &dump, "--from", "5ns"])).contains("not an option of sva runs keep"));
    assert!(sva(&["runs", "keep", &dump, "--name=eq"]).status.success(), "--opt=value");
    let r = d.join(".wavelens-runs").to_string_lossy().into_owned();
    assert_eq!(runs_json(&d.join(".wavelens-runs"))["runs"][0]["name"], "eq");
    let o = sva(&["runs", "set", "1", "--dir", &r, "--name", ""]);
    assert_eq!(o.status.code(), Some(2), "an empty name refused");
    let o = sva(&["runs", "diff", &dump, "--from", "30ns", "--to", "10ns"]);
    assert_eq!((o.status.code(), err(&o).matches("before --from").count()), (Some(2), 1), "said once: {}", err(&o));
    let o = sva(&["runs", "diff", &dump, "--from", "50ns", "--to", "80ns", "--json"]);
    let v: serde_json::Value = serde_json::from_str(&out(&o)).unwrap();
    assert_eq!((o.status.code(), v["runs"][0]["outside"].as_bool(), v["from"].as_u64()), (Some(1), Some(true), Some(50000)), "{v}");
    // the signals one side has, in the text
    let extra = put(&d, "d.vcd", &counter(None, true));
    let o = sva(&["runs", "diff", &extra]);
    assert!(out(&o).contains("equal (3 signals; 1 of the dump not in the run)"), "{}", out(&o));
    // a long stem leaves room for the part's suffix
    let long = put(&d, &format!("{}.vcd", "x".repeat(240)), &counter(None, false));
    assert!(sva(&["runs", "keep", &long]).status.success(), "a long name kept");
}

#[test]
fn runs_diff_holds_the_first_difference_only() {
    // 400 signals, 2000 steps, every value other in the run: the counts whole, no difference list kept
    let d = runs_dir("wide");
    let gen = |seed: u64| {
        let mut s = String::from("$timescale 1ns $end\n$scope module tb $end\n");
        for i in 0..400 {
            s += &format!("$var wire 8 s{i} sig{i} [7:0] $end\n");
        }
        s += "$upscope $end\n$enddefinitions $end\n";
        for t in 0..2000u64 {
            s += &format!("#{t}\n");
            for i in 0..400u64 {
                s += &format!("b{:b} s{i}\n", (t * 7 + i * 13 + seed) % 256);
            }
        }
        s
    };
    let a = put(&d, "a.vcd", &gen(0));
    assert!(sva(&["runs", "keep", &a]).status.success());
    let a = put(&d, "a.vcd", &gen(1));
    let o = sva(&["runs", "diff", &a, "--json", "--limit", "0"]);
    assert_eq!(o.status.code(), Some(1), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_str(&out(&o)).unwrap();
    let r = &v["runs"][0];
    assert_eq!((r["signals_differ"].as_u64(), r["signals"].as_array().unwrap().len()), (Some(400), 400));
    assert!(r["differences"].is_null(), "no list of differences carried");
    // sva diff --limit 1: only_a whole
    let b = put(&d, "b.vcd", &counter(None, true));
    let c = put(&d, "c.vcd", &counter(None, false));
    let v: serde_json::Value = serde_json::from_str(&out(&sva(&["diff", &b, &c, "--json", "-", "--limit", "1"]))).unwrap();
    assert_eq!(v["only_a"].as_array().unwrap().len(), 1, "{v}");
}

#[test]
fn runs_two_keeps_at_once() {
    let d = runs_dir("lock");
    let dump = put(&d, "d.vcd", &counter(None, false));
    // their output not the test's (T-05 of the review 2026-11-06): --json, to nowhere
    let ks: Vec<_> = (0..4).map(|_| Command::new(env!("CARGO_BIN_EXE_sva")).args(["runs", "keep", &dump, "--json"])
        .stdout(std::process::Stdio::null()).spawn().unwrap()).collect();
    for mut k in ks {
        assert!(k.wait().unwrap().success());
    }
    let v = runs_json(&d.join(".wavelens-runs"));
    let mut ids: Vec<u64> = v["runs"].as_array().unwrap().iter().map(|r| r["id"].as_u64().unwrap()).collect();
    ids.sort_unstable();
    assert_eq!(ids, [1, 2, 3, 4], "each its own number, every one listed");
}

/// A dump of 24 signals over 3000 ns: buses, bits with x and z, one changed in B late (`bad`); `shift`: every time later
/// by it; `real`: a real signal too.
fn many_changes(bad: bool, shift: u64, real: bool) -> String {
    let mut s = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n");
    for i in 0..20 {
        s += &format!("$var wire 12 a{i} bus{i} [11:0] $end\n");
    }
    s += "$var wire 1 q bit0 $end\n$var wire 1 w bit1 $end\n$var wire 3 e tri [2:0] $end\n";
    if real {
        s += "$var real 64 r level $end\n";
    }
    s += "$upscope $end\n$enddefinitions $end\n";
    let mut x = 12345u64;
    for t in 0..3000u64 {
        s += &format!("#{}\n{}!\n", t + shift, t % 2);
        for k in 0..3 {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let i = (x >> 33) % 20;
            let mut v = (x >> 40) % 4096;
            if bad && t == 2500 && k == 0 {
                v ^= 1;
            }
            s += &format!("b{v:b} a{i}\n");
        }
        if t % 97 == 0 {
            s += &format!("{}q\n{}w\nb{} e\n", ["0", "1", "x", "z"][(t / 97 % 4) as usize], ["X", "1", "0", "Z"][(t / 97 % 4) as usize],
                ["x1z", "101", "zz0", "X0X"][(t / 97 % 4) as usize]);
        }
        if real && t % 50 == 0 {
            s += &format!("r{}.25 r\n", t);
        }
    }
    s += &format!("#{}\n", 3000 + shift);
    s
}

/// `sva diff --json` without what differs by the files read: their names, where each was read from.
fn diff_doc(args: &[&str]) -> serde_json::Value {
    let o = sva(args);
    assert!(o.status.code().is_some_and(|c| c < 2), "{args:?}: {}", err(&o));
    let mut v: serde_json::Value = serde_json::from_str(&out(&o)).unwrap();
    for k in ["a", "b"] {
        let side = v[k].as_object_mut().unwrap();
        side.remove("file");
        side.remove("read_from");
    }
    v
}

#[test]
fn a_late_window_of_an_fst_reads_its_blocks_from_there() {
    let d = runs_dir("late");
    let (a, b) = (put(&d, "a.vcd", &many_changes(false, 0, false)), put(&d, "b.vcd", &many_changes(true, 0, false)));
    let fst = |v: &str, name: &str, block: Option<&str>| {
        let p = d.join(name).to_string_lossy().into_owned();
        let mut args = vec!["fst", v, "--out", &p, "--quiet"];
        args.extend(block.map(|b| ["--block-bytes", b]).into_iter().flatten());
        assert!(sva(&args).status.success());
        p
    };
    let (am, bm) = (fst(&a, "am.fst", Some("2000")), fst(&b, "bm.fst", Some("2000")));
    let a1 = fst(&a, "a1.fst", None);
    for (from, to) in [("2400ns", "2600ns"), ("1000ns", "1003ns"), ("2999ns", "3000ns"), ("0ns", "50ns"), ("2500ns", "2500ns")] {
        let w = ["--from", from, "--to", to, "--json", "-", "--limit", "0"];
        let whole = diff_doc(&[&["diff", &a, &b][..], &w].concat());
        assert_eq!(diff_doc(&[&["diff", &am, &bm][..], &w].concat()), whole, "{from} … {to}: the FSTs of many blocks");
        assert_eq!(diff_doc(&[&["diff", &a, &bm][..], &w].concat()), whole, "{from} … {to}: a VCD and an FST");
        // the cut of the run's values (the panel's second half): the same text from one block or many
        for sig in [None, Some("tb.bus7,tb.bit1,tb.tri,tb.clk")] {
            let mut c = vec!["vcd", &a1, "--from", from, "--to", to];
            c.extend(sig.map(|s| ["--signals", s]).into_iter().flatten());
            // the changes of a time step in any order (as the blocks hold them)
            let steps = |t: String| -> Vec<Vec<String>> {
                t.split('#').map(|s| {
                    let mut l: Vec<String> = s.lines().map(String::from).collect();
                    l.sort();
                    l
                }).collect()
            };
            let one = steps(out(&sva(&c)));
            c[1] = &am;
            assert_eq!(steps(out(&sva(&c))), one, "{from} … {to} {sig:?}: the cut of the FST of many blocks");
        }
    }
    let late: serde_json::Value = serde_json::from_str(&out(&sva(&["diff", &am, &bm, "--from", "2400ns", "--json", "-"]))).unwrap();
    assert_eq!(late["differ"], 1, "{late}");
    let (ra, rb) = (late["a"]["read_from"].as_i64().unwrap(), late["b"]["read_from"].as_i64().unwrap());
    assert!(ra > 0 && ra <= 2_400_000 && rb > 0, "read from a block near the window: {late}");
    assert_eq!(late["a"]["start"], 0, "the dump's start, not the block's");
    // B later by 7 ns: --offset reads B from its own block
    let bs = fst(&put(&d, "bs.vcd", &many_changes(true, 7, false)), "bs.fst", Some("2000"));
    let w = ["--from", "2400ns", "--to", "2600ns", "--offset", "7ns", "--json", "-", "--limit", "0"];
    let whole = diff_doc(&[&["diff", &a, &d.join("bs.vcd").to_string_lossy()][..], &w].concat());
    assert_eq!(diff_doc(&[&["diff", &am, &bs][..], &w].concat()), whole, "--offset");
    // a real among the signals has no value in a block's frame here: read from the start, the same counts
    let (ar, br) = (put(&d, "ar.vcd", &many_changes(false, 0, true)), put(&d, "br.vcd", &many_changes(true, 0, true)));
    let (arm, brm) = (fst(&ar, "arm.fst", Some("2000")), fst(&br, "brm.fst", Some("2000")));
    let w = ["--from", "2400ns", "--to", "2600ns", "--json", "-", "--limit", "0"];
    let v: serde_json::Value = serde_json::from_str(&out(&sva(&[&["diff", &arm, &brm][..], &w].concat()))).unwrap();
    assert_eq!(v["a"]["read_from"], 0, "{v}");
    assert_eq!(diff_doc(&[&["diff", &arm, &brm][..], &w].concat()), diff_doc(&[&["diff", &ar, &br][..], &w].concat()));
}

#[test]
fn runs_keep_writes_blocks_a_late_window_reads_from() {
    let d = runs_dir("blocks");
    let dump = put(&d, "d.vcd", &many_changes(false, 0, false));
    assert!(sva(&["runs", "keep", &dump]).status.success());
    let v = runs_json(&d.join(".wavelens-runs"));
    assert_eq!(v["runs"][0]["end"], 3_000_000, "{v}");
    let o = sva(&["runs", "diff", &dump, "--from", "2900ns", "--json"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
}

/// Two test cases: test_a holds cnt at 0 for 20 ns (+ `longer`), test_b counts cnt up every 5 ns for 20 ns (+ `tail`).
/// -> the dump and its marks (python/wavelens_cocotb.py's file).
fn two_cases(longer: u64, tail: u64) -> (String, String) {
    let mut s = String::from("$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 4 \" cnt [3:0] $end\n");
    s += "$upscope $end\n$enddefinitions $end\n#0\n0!\nb0 \"\n";
    let b = 20 + longer;
    let end = b + 20 + tail;
    let mut t = 5;
    while t <= end {
        s += &format!("#{t}\n{}!\n", t / 5 % 2);
        if t > b {
            s += &format!("b{:b} \"\n", ((t - b) / 5) % 16);
        }
        t += 5;
    }
    let marks = format!(r#"{{"wavelens": "marks", "version": 1, "signal": "tb.test", "tests": [
        {{"n": 1, "name": "test_a", "result": "pass", "from": 0, "to": {}}},
        {{"n": 2, "name": "test_b", "result": "pass", "from": {}, "to": {}}}]}}"#, b * 1000, b * 1000, end * 1000);
    (s, marks)
}

#[test]
fn runs_compared_by_test_case() {
    let d = runs_dir("cases");
    let (v0, m0) = two_cases(0, 0);
    let dump = put(&d, "d.vcd", &v0);
    put(&d, "wavelens.marks.json", &m0);
    let o = sva(&["runs", "keep", &dump, "--name", "first"]);
    assert!(o.status.success(), "{}", err(&o));
    assert!(err(&o).contains("the cases of") && err(&o).contains(": 2"), "said: {}", err(&o));
    let runs = runs_json(&d.join(".wavelens-runs"));
    assert_eq!(runs["runs"][0]["cases"][1], serde_json::json!({"name": "test_b", "from": 20000, "to": 40000}));
    assert!(out(&sva(&["runs", "list", &dump])).contains("2 cases"));
    // the run of now: test_a 10 ns longer, test_b 5 ns longer: test_b later, the same values from its start
    let (v1, m1) = two_cases(10, 5);
    put(&d, "d.vcd", &v1);
    put(&d, "wavelens.marks.json", &m1);
    let by_case = sva(&["runs", "diff", &dump, "--case", "TC2 test_b \u{b7} PASS", "--json"]);
    assert_eq!(by_case.status.code(), Some(0), "{}{}", out(&by_case), err(&by_case));
    let v: serde_json::Value = serde_json::from_str(&out(&by_case)).unwrap();
    assert_eq!(v["case"], serde_json::json!({"name": "test_b", "from": 30000, "to": 55000}));
    let r = &v["runs"][0];
    assert_eq!((r["case"]["offset"].as_i64(), r["equal"].as_bool()), (Some(-10000), Some(true)), "{r}");
    assert_eq!((r["from"].as_i64(), r["to"].as_i64()), (Some(30000), Some(50000)), "over the shorter: {r}");
    assert!(r["case"]["note"].as_str().unwrap().contains("5 ns shorter"), "{r}");
    let text = out(&sva(&["runs", "diff", &dump, "--case", "test_b"]));
    assert!(text.contains("over the case test_b") && text.contains("its case at 20 ns"), "{text}");
    // the same window without the case: the run's test_b is 10 ns earlier
    assert_eq!(sva(&["runs", "diff", &dump, "--from", "30ns", "--to", "50ns"]).status.code(), Some(1));
    // the dump's window given, the case of the run by its name
    let w = sva(&["runs", "diff", &dump, "--case", "test_b", "--from", "30ns", "--to", "40ns", "--json"]);
    assert_eq!(w.status.code(), Some(0), "{}", err(&w));
    // a case nowhere: said with the cases there are
    let no = sva(&["runs", "diff", &dump, "--case", "test_z"]);
    assert_eq!(no.status.code(), Some(2));
    assert!(err(&no).contains("no case test_z (its cases: test_a, test_b)"), "{}", err(&no));
    assert_eq!(sva(&["runs", "diff", &dump, "--case", "test_b", "--from", "30ns"]).status.code(), Some(2));
    assert!(err(&sva(&["runs", "diff", &dump, "--cases", "x.json"])).contains("--cases gives the dump's cases for --case"));
    // a run without its cases: an error on its row
    assert!(sva(&["runs", "set", "1", &dump, "--cases", "none"]).status.success());
    let none = sva(&["runs", "diff", &dump, "--case", "test_b"]);
    assert_eq!(none.status.code(), Some(2));
    assert!(err(&none).contains("kept without cases"), "{}", err(&none));
    // cases given back from a list on stdin, times with units, a label as a page's span has it
    let mut p = Command::new(env!("CARGO_BIN_EXE_sva")).args(["runs", "set", "1", &dump, "--cases", "-"])
        .stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::piped()).spawn().unwrap();
    std::io::Write::write_all(p.stdin.as_mut().unwrap(), "[{\"label\": \"TC2 test_b \u{b7} FAIL\", \"from\": \"20ns\", \"to\": \"40ns\"}, {\"label\": \"x\", \"from\": 5, \"to\": 1}]".as_bytes()).unwrap();
    assert!(p.wait_with_output().unwrap().status.success());
    assert_eq!(runs_json(&d.join(".wavelens-runs"))["runs"][0]["cases"], serde_json::json!([{"name": "test_b", "from": 20000, "to": 40000}]));
    assert_eq!(sva(&["runs", "diff", &dump, "--case", "test_b"]).status.code(), Some(0));
    // marks older than the dump by more than 10 minutes: another run's, not taken
    let old = std::time::SystemTime::now() - std::time::Duration::from_secs(3600);
    std::fs::File::options().write(true).open(d.join("wavelens.marks.json")).unwrap().set_modified(old).unwrap();
    let k = sva(&["runs", "keep", &dump]);
    assert!(err(&k).contains("older than"), "{}", err(&k));
    assert!(runs_json(&d.join(".wavelens-runs"))["runs"][1]["cases"].is_null());
}

#[test]
fn diff_page_is_the_shape_a_page_takes() {
    let d = runs_dir("page");
    let (a, b) = (put(&d, "a.vcd", &counter(None, true)), put(&d, "b.vcd", &counter(Some(25), false)));
    let o = sva(&["diff", &a, &b, "--page", "--from", "20ns"]);
    assert_eq!(o.status.code(), Some(1), "{}", err(&o));
    let v: serde_json::Value = serde_json::from_str(&out(&o)).unwrap();
    assert_eq!((v["name"].as_str(), v["from"].as_i64(), v["differ"].as_u64(), v["first"].as_i64()), (Some("b.vcd"), Some(20000), Some(1), Some(25000)), "{v}");
    assert_eq!(v["signals"]["tb.ok"], serde_json::json!({"spans": [[25000, 40000]], "b": "tb.ok"}));
    assert_eq!(v["missing"], serde_json::json!(["tb.extra"]), "the rows B has not got");
    assert!(v["vcd"].as_str().unwrap().contains("$var") && v["shift"] == 0, "B's values of the signals that differ: {v}");
    assert!(!v["vcd"].as_str().unwrap().contains(" cnt "), "only the ones that differ");
    // more than the page takes: why, the bands stay
    let small: serde_json::Value = serde_json::from_str(&out(&sva(&["diff", &a, &b, "--page", "--cut-bytes", "10"]))).unwrap();
    assert!(small["vcd"].is_null() && small["cutError"].as_str().unwrap().contains("compare fewer signals"), "{small}");
    // equal: no values of B
    let eq: serde_json::Value = serde_json::from_str(&out(&sva(&["diff", &a, &a, "--page"]))).unwrap();
    assert!(eq["vcd"].is_null() && eq["differ"] == 0, "{eq}");
}

#[test]
fn runs_go_where_the_workspace_says() {
    let d = runs_dir("workspace");
    std::fs::create_dir_all(d.join(".vscode")).unwrap();
    std::fs::create_dir_all(d.join("sim")).unwrap();
    put(&d.join(".vscode"), "settings.json", "{\n  // where the Runs panel keeps them\n  \"wavelens.runsDir\": \"kept/runs\",\n}\n");
    let dump = put(&d.join("sim"), "d.vcd", &counter(None, false));
    let o = sva(&["runs", "keep", &dump, "--json"]);
    assert!(o.status.success(), "{}", err(&o));
    assert!(d.join("kept/runs/runs.json").is_file(), "the workspace's wavelens.runsDir, as the panel");
    assert!(!d.join("sim/.wavelens-runs").exists());
    assert!(out(&sva(&["runs", "list", &dump])).contains("1 run"), "list finds it the same way");
    assert!(out(&sva(&["runs", "path", "1", &dump])).contains("kept/runs/1-d.fst"));
}

// ------------------------------------------------------------------------------------------------ the run pick (review 2026-11-06)

/// Three runs of the counter: #1 golden, #2 broken at 25 ns, #3 golden again; the dump of now golden -> (dir, dump).
fn three_runs(name: &str) -> (PathBuf, String) {
    let d = runs_dir(name);
    let dump = put(&d, "d.vcd", &counter(None, false));
    assert!(sva(&["runs", "keep", &dump, "--name", "golden", "--json"]).status.success());
    put(&d, "d.vcd", &counter(Some(25), false));
    assert!(sva(&["runs", "keep", &dump, "--name", "broken", "--json"]).status.success());
    put(&d, "d.vcd", &counter(None, false));
    assert!(sva(&["runs", "keep", &dump, "--name", "again", "--json"]).status.success());
    (d, dump)
}

fn json_of(o: &Output) -> serde_json::Value {
    serde_json::from_str(&out(o)).unwrap_or_else(|e| panic!("{e}: {}{}", out(o), err(o)))
}

/// A chosen: `--against RUN` compares that run's FST with the other runs of the dump (or the ones of --run; the run that
/// is A skipped and said), `--run now` the dump itself against it.
#[test]
fn runs_diff_against_a_run() {
    let (_d, dump) = three_runs("against");
    let o = sva(&["runs", "diff", &dump, "--against", "1", "--json"]);
    assert_eq!(o.status.code(), Some(1), "{}", err(&o));
    let v = json_of(&o);
    assert_eq!(v["against"], serde_json::json!({"id": 1, "name": "golden", "file": "1-d.fst"}), "{v}");
    let rows: Vec<(u64, bool)> = v["runs"].as_array().unwrap().iter().map(|x| (x["id"].as_u64().unwrap(), x["equal"].as_bool().unwrap())).collect();
    assert_eq!(rows, [(3, true), (2, false)], "A not compared with itself: {v}");
    let text = out(&sva(&["runs", "diff", &dump, "--against", "golden"]));
    assert!(text.starts_with("#1 golden against 2 runs over 0 ps … 40 ns:"), "{text}");
    assert!(text.contains("#2 broken: 1 of 3 signals differ, first at 25 ns (tb.ok)"), "{text}");
    // the dump of now: A by default, and "now"
    assert_eq!(sva(&["runs", "diff", &dump, "--json"]).status.code(), Some(1));
    assert!(json_of(&sva(&["runs", "diff", &dump, "--against", "now", "--json"]))["against"].is_null());
    let one = json_of(&sva(&["runs", "diff", &dump, "--against", "1", "--run", "3", "--json"]));
    assert_eq!(one["runs"].as_array().unwrap().len(), 1, "{one}");
    // A named in --run too: skipped, said
    let o = sva(&["runs", "diff", &dump, "--against", "1", "--run", "1"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("the run compared against"), "{}", err(&o));
    let o = sva(&["runs", "diff", &dump, "--against", "1", "--run", "1,3"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    assert!(err(&o).contains("#1 golden: the run compared against, skipped") && out(&o).contains("against 1 run "), "{}{}", out(&o), err(&o));
    assert_eq!(json_of(&sva(&["runs", "diff", &dump, "--against", "1", "--run", "1", "--run", "2", "--json"]))["notes"][0],
               "#1 golden: the run compared against, skipped");
    let o = sva(&["runs", "diff", &dump, "--against", "9"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("no run 9"), "{}", err(&o));
    // the dump of now as a B: against a run only
    let o = sva(&["runs", "diff", &dump, "--run", "now"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("--against RUN"), "{}", err(&o));
    let now = json_of(&sva(&["runs", "diff", &dump, "--against", "broken", "--run", "now", "--json"]));
    let r = &now["runs"][0];
    assert_eq!((r["id"].as_u64(), r["name"].as_str(), r["first"]["t"].as_u64()), (Some(0), Some("now"), Some(25000)), "{now}");
    assert!(out(&sva(&["runs", "diff", &dump, "--against", "2", "--run", "now"])).contains("  now: 1 of 3 signals differ"));
}

/// A's case of --case NAME is the A run's (not the dump's marks); B = now takes the dump's.
#[test]
fn runs_diff_against_a_run_by_test_case() {
    let d = runs_dir("against-case");
    let (v0, m0) = two_cases(0, 0);
    let dump = put(&d, "d.vcd", &v0);
    put(&d, "wavelens.marks.json", &m0);
    assert!(sva(&["runs", "keep", &dump, "--name", "first", "--json"]).status.success());
    // now: test_b 10 ns later and 5 ns longer, kept as #2
    let (v1, m1) = two_cases(10, 5);
    put(&d, "d.vcd", &v1);
    put(&d, "wavelens.marks.json", &m1);
    assert!(sva(&["runs", "keep", &dump, "--name", "second", "--json"]).status.success());
    let o = sva(&["runs", "diff", &dump, "--against", "1", "--case", "test_b", "--json"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let v = json_of(&o);
    assert_eq!(v["case"], serde_json::json!({"name": "test_b", "from": 20000, "to": 40000}), "#1's case, not the dump's: {v}");
    let r = &v["runs"][0];
    assert_eq!((r["id"].as_u64(), r["case"]["offset"].as_i64(), r["equal"].as_bool()), (Some(2), Some(10000), Some(true)), "{r}");
    assert!(r["case"]["note"].as_str().unwrap().contains("5 ns longer") && r["case"].get("shorter").is_none(), "{r}");
    let text = out(&sva(&["runs", "diff", &dump, "--against", "1", "--case", "test_b"]));
    assert!(text.starts_with("#1 first against 1 run over the case test_b (20 ns … 40 ns of #1):"), "{text}");
    // B = now over the dump's own case (its marks)
    let n = json_of(&sva(&["runs", "diff", &dump, "--against", "1", "--run", "now", "--case", "test_b", "--json"]));
    assert_eq!((n["runs"][0]["case"]["from"].as_u64(), n["runs"][0]["equal"].as_bool()), (Some(30000), Some(true)), "{n}");
    // the page's compare of one run by its case: the spelling the page reads (case.shorter: the length compared)
    let p = sva(&["runs", "diff", &dump, "--against", "1", "--run", "2", "--case", "test_b", "--page"]);
    assert_eq!(p.status.code(), Some(0), "{}", err(&p));
    let p = json_of(&p);
    assert_eq!(p["case"], serde_json::json!({"name": "test_b", "from": 30000, "to": 55000, "offset": 10000, "shorter": 20000}), "{p}");
    assert_eq!((p["run"].as_u64(), p["a"].as_u64(), p["from"].as_u64(), p["to"].as_u64()), (Some(2), Some(1), Some(20000), Some(40000)), "{p}");
    // A kept without cases: said as a run without them is
    assert!(sva(&["runs", "set", "1", &dump, "--cases", "none"]).status.success());
    let o = sva(&["runs", "diff", &dump, "--against", "1", "--case", "test_b"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("#1 first: kept without cases"), "{}", err(&o));
}

/// `--page`: one run's compare in the page's shape, as `sva diff --page` of the two files writes it, with the run and A.
#[test]
fn runs_diff_page_of_one_run() {
    let (d, dump) = three_runs("page-one");
    let o = sva(&["runs", "diff", &dump, "--run", "2", "--page", "--quiet"]);
    assert_eq!(o.status.code(), Some(1), "{}", err(&o));
    let v = json_of(&o);
    assert!(v["vcd"].as_str().is_some_and(|t| t.contains("$var")), "B's values: {v}");
    assert_eq!((v["run"].as_u64(), v["a"].is_null()), (Some(2), true), "{v}");
    assert_eq!(v["signals"]["tb.ok"]["spans"], serde_json::json!([[25000, 40000]]), "{v}");
    // the same as sva diff --page of the dump and the run's FST (what the extension asked before)
    let fst = d.join(".wavelens-runs").join("2-d.fst").to_string_lossy().into_owned();
    let same = json_of(&sva(&["diff", &dump, &fst, "--page", "--from", "10ns", "--to", "35ns"]));
    let mut page = json_of(&sva(&["runs", "diff", &dump, "--run", "2", "--page", "--from", "10ns", "--to", "35ns"]));
    for k in ["run", "a"] {
        page.as_object_mut().unwrap().remove(k);
    }
    assert_eq!(page, same);
    let a = json_of(&sva(&["runs", "diff", &dump, "--against", "1", "--run", "2", "--page"]));
    assert_eq!((a["a"].as_u64(), a["run"].as_u64(), a["first"].as_u64()), (Some(1), Some(2), Some(25000)), "{a}");
    // --cut-bytes passed on: the bands stay, why the values are not there
    let small = json_of(&sva(&["runs", "diff", &dump, "--run", "2", "--page", "--cut-bytes", "10"]));
    assert!(small["vcd"].is_null() && small["cutError"].is_string(), "{small}");
    // more than one run: a usage error
    let o = sva(&["runs", "diff", &dump, "--page"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(err(&o).contains("--page: the compare of one run (3 here"), "{}", err(&o));
    assert_eq!(sva(&["runs", "diff", &dump, "--run", "1,2", "--page"]).status.code(), Some(2));
}

/// keep writes the dump's time on the disk (source_mtime); the list says it when it is not the time kept.
#[test]
fn runs_keep_writes_the_dump_time() {
    let d = runs_dir("mtime");
    let dump = put(&d, "d.vcd", &counter(None, false));
    let new_year = std::time::UNIX_EPOCH + std::time::Duration::from_secs(1_577_836_800);   // 2020-01-01T00:00:00Z
    std::fs::File::options().write(true).open(&dump).unwrap().set_modified(new_year).unwrap();
    let k = json_of(&sva(&["runs", "keep", &dump, "--json"]));
    assert_eq!(k["source_mtime"], "2020-01-01T00:00:00Z", "{k}");
    assert_eq!(runs_json(&d.join(".wavelens-runs"))["runs"][0]["source_mtime"], "2020-01-01T00:00:00Z");
    assert!(out(&sva(&["runs", "list", &dump])).contains("(of a dump of 2020-01-01 00:00)"));
    assert_eq!(json_of(&sva(&["runs", "list", &dump, "--json"]))["runs"][0]["source_mtime"], "2020-01-01T00:00:00Z");
    // a dump kept as it is written: no word of it
    put(&d, "d.vcd", &counter(None, false));
    let k = json_of(&sva(&["runs", "keep", &dump, "--json"]));
    assert!(k["source_mtime"].as_str().is_some_and(|t| t.starts_with("20") && t.ends_with('Z')), "{k}");
    let l = out(&sva(&["runs", "list", &dump]));
    assert_eq!(l.matches("of a dump of").count(), 1, "{l}");
}

/// T-04: the text of runs whose windows differ: the window on each line, the note of a case of another length.
#[test]
fn runs_diff_text_of_windows_apart() {
    let d = runs_dir("windows");
    let (v0, m0) = two_cases(0, 0);
    let dump = put(&d, "d.vcd", &v0);
    put(&d, "wavelens.marks.json", &m0);
    assert!(sva(&["runs", "keep", &dump, "--name", "whole", "--json"]).status.success());
    let short = put(&d, "short.json", r#"[{"name": "test_b", "from": 20000, "to": 35000}]"#);
    assert!(sva(&["runs", "keep", &dump, "--name", "short", "--cases", &short, "--json"]).status.success());
    let o = sva(&["runs", "diff", &dump, "--case", "test_b"]);
    assert_eq!(o.status.code(), Some(0), "{}", err(&o));
    let text = out(&o);
    assert!(text.starts_with(&format!("{dump} against 2 runs over the case test_b:\n")), "no window in the header: {text}");
    assert!(text.contains("  #2 short: equal over 20 ns … 35 ns (its case at 20 ns; the run's case is 5 ns shorter: compared over the shorter) (2 signals)"),
            "{text}");
    assert!(text.contains("  #1 whole: equal over 20 ns … 40 ns (2 signals)"), "{text}");
}
