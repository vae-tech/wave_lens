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
