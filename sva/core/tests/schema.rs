//! docs/sva/ast.schema.json against the real output: every corpus file, parsed, must validate. The validator below is
//! the part of JSON Schema the file uses ($ref, type, properties, required, additionalProperties: false, items, enum,
//! const, oneOf, minimum, one pattern); the file must not use more.

use serde_json::{json, Value};
use std::path::Path;
use sva_core::parse;

mod common;

fn schema() -> Value {
    load("ast.schema.json")
}

fn load(name: &str) -> Value {
    let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../docs/sva").join(name);
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

struct V<'a> {
    root: &'a Value,
}

impl V<'_> {
    /// `Err(path: why)` for the first place `v` does not match `s`.
    fn check(&self, s: &Value, v: &Value, path: &str) -> Result<(), String> {
        let s = s.as_object().unwrap_or_else(|| panic!("schema at {path} is not an object"));
        for k in s.keys() {
            let known = ["$schema", "$id", "title", "description", "$defs", "$ref", "type", "properties", "required", "additionalProperties", "items", "enum", "const", "oneOf", "minimum", "pattern"];
            assert!(known.contains(&k.as_str()), "the schema uses '{k}', which this validator does not know");
        }
        if let Some(r) = s.get("$ref") {
            let name = r.as_str().unwrap().strip_prefix("#/$defs/").expect("only local $refs");
            return self.check(&self.root["$defs"][name], v, path);
        }
        if let Some(t) = s.get("type") {
            let ok = |t: &str| match t {
                "object" => v.is_object(),
                "array" => v.is_array(),
                "string" => v.is_string(),
                "integer" => v.is_i64() || v.is_u64(),
                "boolean" => v.is_boolean(),
                "null" => v.is_null(),
                _ => panic!("type {t}"),
            };
            let any = match t {
                Value::String(t) => ok(t),
                Value::Array(ts) => ts.iter().any(|t| ok(t.as_str().unwrap())),
                _ => panic!("type"),
            };
            if !any {
                return Err(format!("{path}: {v} is not of type {t}"));
            }
        }
        if let Some(c) = s.get("const") {
            if c != v {
                return Err(format!("{path}: {v} is not {c}"));
            }
        }
        if let Some(e) = s.get("enum") {
            if !e.as_array().unwrap().contains(v) {
                return Err(format!("{path}: {v} is not one of {e}"));
            }
        }
        if let (Some(m), Some(x)) = (s.get("minimum"), v.as_i64()) {
            if x < m.as_i64().unwrap() {
                return Err(format!("{path}: {x} < {m}"));
            }
        }
        if let Some(p) = s.get("pattern") {
            assert_eq!(p, "^s[1-9][0-9]*$", "a pattern this validator does not know");
            let t = v.as_str().unwrap_or("");
            let d = t.strip_prefix('s').unwrap_or("");
            if d.is_empty() || !d.bytes().all(|c| c.is_ascii_digit()) || d.starts_with('0') {
                return Err(format!("{path}: {t} does not match {p}"));
            }
        }
        if let Some(obj) = v.as_object() {
            let props = s.get("properties").and_then(|p| p.as_object());
            if let Some(req) = s.get("required") {
                for r in req.as_array().unwrap() {
                    if !obj.contains_key(r.as_str().unwrap()) {
                        return Err(format!("{path}: '{}' is missing", r.as_str().unwrap()));
                    }
                }
            }
            for (k, x) in obj {
                match props.and_then(|p| p.get(k)) {
                    Some(ps) => self.check(ps, x, &format!("{path}.{k}"))?,
                    None if s.get("additionalProperties") == Some(&Value::Bool(false)) => return Err(format!("{path}: '{k}' is not in the schema")),
                    None => {}
                }
            }
        }
        if let (Some(items), Some(arr)) = (s.get("items"), v.as_array()) {
            for (k, x) in arr.iter().enumerate() {
                self.check(items, x, &format!("{path}[{k}]"))?;
            }
        }
        if let Some(alts) = s.get("oneOf") {
            let errs: Vec<String> = alts.as_array().unwrap().iter().filter_map(|a| self.check(a, v, path).err()).collect();
            let matched = alts.as_array().unwrap().len() - errs.len();
            if matched != 1 {
                let kind = v.get("kind").map_or(String::new(), |k| format!(" (kind {k})"));
                return Err(format!("{path}{kind}: {matched} of the oneOf alternatives match; closest: {}", errs.iter().min_by_key(|e| std::cmp::Reverse(e.len())).cloned().unwrap_or_default()));
            }
        }
        Ok(())
    }
}

#[test]
fn every_corpus_file_validates() {
    let s = schema();
    let v = V { root: &s };
    let mut files = Vec::new();
    for (name, src) in common::corpus() {
        let mut j = serde_json::to_value(parse(&src)).unwrap();
        if let Err(e) = v.check(&s["$defs"]["parsed"], &j, "$") {
            panic!("{name}: {e}");
        }
        j.as_object_mut().unwrap().insert("file".into(), name.into());
        files.push(j);
    }
    // the whole `sva parse --json` output, against the root
    v.check(&s, &json!({ "files": files }), "$").unwrap();
}

#[test]
fn the_validator_rejects_what_it_should() {
    let s = schema();
    let v = V { root: &s };
    let ok = serde_json::to_value(parse("a: assert property (@(posedge c) x |-> ##[1:2] y);")).unwrap();
    v.check(&s, &ok, "$").unwrap();
    let mut no_label = ok.clone();
    no_label["assertions"][0].as_object_mut().unwrap().remove("label");
    assert!(v.check(&s, &no_label, "$").unwrap_err().contains("'label' is missing"));
    let mut extra = ok.clone();
    extra["assertions"][0]["prop"]["cons"]["seq"]["surprise"] = json!(1);
    assert!(v.check(&s, &extra, "$").is_err());
    let mut bad_kind = ok.clone();
    bad_kind["assertions"][0]["kind"] = json!("check");
    assert!(v.check(&s, &bad_kind, "$").unwrap_err().contains("is not one of"));
    let mut bad_id = ok.clone();
    bad_id["assertions"][0]["elements"][0]["id"] = json!("x1");
    assert!(v.check(&s, &bad_id, "$").unwrap_err().contains("does not match"));
    let mut bad_bound = ok;
    bad_bound["assertions"][0]["prop"]["cons"]["seq"]["range"]["max"] = json!("inf");
    assert!(v.check(&s, &bad_bound, "$").is_err());
}

/// docs/sva/results.schema.json against evaluations that give every kind of result, step role, reason and field.
#[test]
fn results_validate() {
    let s = load("results.schema.json");
    let v = V { root: &s };
    let src = r#"
        module m (input logic clk, rst, a, b, c, d, e, input logic [7:0] bus);
          default clocking @(posedge clk); endclocking
          default disable iff (rst);
          r_imp:    assert property (a |-> ##[1:2] b);
          r_thr:    assert property (a |=> (c throughout (b ##1 d)) |-> d);
          r_bus:    assert property (a |-> bus == 8'h1f);
          r_x:      assert property (b |-> d);
          r_strong: assert property (a |-> s_eventually (c && !c));
          r_not:    assert property (not (a ##1 b));
          r_cap:    assert property (a |-> (b ##1 c) or (b ##2 d));
          r_long:   assert property (a |-> e[*1:$] ##1 (c && !c));
          r_open:   assert property (a |-> ##[1:$] (c && !c));
          r_range:  assert property (a |-> eventually [1:2] (c && !c));
          r_follow: assert property (a ##1 a #-# b);
          c_seq:    cover sequence (a ##1 b);
          c_prop:   cover property (a ##1 b);
          r_miss:   assert property (a |-> nope);
        endmodule"#;
    let n = 300;
    let bits = |f: &dyn Fn(usize) -> bool| (0..n).map(|k| if f(k) { "1" } else { "0" }).collect::<Vec<_>>();
    let mut d = bits(&|k| k % 7 == 3);
    d[5] = "x";
    let trace = json!({
        "times": (0..n).map(|k| 10 * k as u64 + 5).collect::<Vec<_>>(),
        "signals": { "rst": bits(&|k| k == 250), "a": bits(&|k| k % 5 == 0), "b": bits(&|k| k % 3 != 0), "c": bits(&|k| k % 4 < 2), "d": d, "e": bits(&|_| true),
                     "bus": (0..n).map(|k| if k % 2 == 0 { json!(31) } else { json!("hx1") }).collect::<Vec<_>>() },
        "widths": { "bus": 8 } });
    let mut kinds = std::collections::BTreeSet::new();
    let mut fields = std::collections::BTreeSet::new();
    for opt in [json!({}), json!({"vacuous": true, "max_threads": 1, "lane": false})] {
        let req = json!({ "source": src, "trace": trace, "options": opt }).to_string();
        let out: Value = serde_json::from_str(&sva_core::run_json(&req)).unwrap();
        assert!(out.get("errors").is_none(), "{out}");
        v.check(&s, &out, "$").unwrap_or_else(|e| panic!("{e}"));
        for a in out["assertions"].as_array().unwrap() {
            for t in a["attempts"].as_array().unwrap() {
                kinds.insert(t["result"].as_str().unwrap().to_string());
                fields.extend(t.as_object().unwrap().keys().cloned());
                if let Some(r) = t.get("reason") {
                    kinds.insert(format!("reason {}", r["kind"].as_str().unwrap()));
                }
            }
            fields.extend(a.as_object().unwrap().keys().cloned());
        }
    }
    let want = ["active", "capped", "disabled", "fail", "pass", "vacuous", "reason capped", "reason expected", "reason no_match", "reason not_held",
                "reason range", "reason strong_end", "reason unknown"];
    for w in want {
        assert!(kinds.contains(w), "no {w} in {kinds:?}");
    }
    for f in ["truncated", "ante_end", "reason", "failed_at", "note", "missing", "notes", "lane"] {
        assert!(fields.contains(f), "no {f} in {fields:?}");
    }
    // and it rejects a result it does not know
    let mut bad: Value = serde_json::from_str(&sva_core::run_json(&json!({ "source": src, "trace": trace }).to_string())).unwrap();
    bad["assertions"][0]["attempts"][0]["result"] = json!("maybe");
    assert!(v.check(&s, &bad, "$").unwrap_err().contains("is not one of"));
}
