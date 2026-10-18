//! The sva binary end to end: `sva parse` (text, --json, -D, several files as one unit, exit codes) and the evaluation
//! over a small VCD written here.

use std::path::PathBuf;
use std::process::{Command, Output};

fn dir() -> PathBuf {
    let d = std::env::temp_dir().join(format!("sva-cli-test-{}", std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write(name: &str, text: &str) -> String {
    let p = dir().join(name);
    std::fs::write(&p, text).unwrap();
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
