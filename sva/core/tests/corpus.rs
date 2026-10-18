//! The corpus tests/sva/*.sv: every file parses or fails exactly as its annotations say, its description equals the
//! golden file tests/sva/golden/NAME.txt (`SVA_BLESS=1 cargo test` or `make sva-bless` rewrites them), and the
//! declarations print and parse back to the same tree.
//!
//! Annotations of expected errors (warnings are not annotated; they are in the golden files):
//!   a comment line with a caret `//      ^ message part` — an error at the caret's column of the line above;
//!   `// expect-error: -1:5 message part` — an error at a line relative to the comment (+N / -N) and a column.

mod common;

use common::{corpus, corpus_dir};
use serde_json::Value;
use sva_core::{describe, parse, parse_prop, Parsed, Printer};

/// (line, col, message part) of every annotation.
fn expected(src: &str) -> Vec<(usize, usize, String)> {
    let mut out = Vec::new();
    for (k, l) in src.lines().enumerate() {
        let line = k + 1;
        let t = l.trim_start();
        if let Some(rest) = t.strip_prefix("// expect-error:") {
            let rest = rest.trim();
            let (pos, msg) = rest.split_once(' ').unwrap();
            let (dl, col) = pos.split_once(':').unwrap();
            let target = (line as i64 + dl.parse::<i64>().unwrap()) as usize;
            out.push((target, col.parse().unwrap(), msg.trim().to_string()));
        } else if let Some(rest) = t.strip_prefix("//") {
            if rest.trim_start().starts_with('^') {
                let col = l.chars().take_while(|&ch| ch != '^').count() + 1;
                out.push((line - 1, col, rest.trim_start()[1..].trim().to_string()));
            }
        }
    }
    out
}

#[test]
fn errors_are_exactly_the_annotated_ones() {
    let mut negatives = 0;
    for (name, src) in corpus() {
        let p = parse(&src);
        let want = expected(&src);
        negatives += want.len();
        let got: Vec<_> = p.errors.iter().map(|e| (e.line, e.col, e.msg.clone())).collect();
        for w in &want {
            assert!(got.iter().any(|g| g.0 == w.0 && g.1 == w.1 && g.2.contains(&w.2)), "{name}: expected an error at {}:{} containing {:?}; got {got:#?}", w.0, w.1, w.2);
        }
        for g in &got {
            assert!(want.iter().any(|w| g.0 == w.0 && g.1 == w.1 && g.2.contains(&w.2)), "{name}: unexpected error {}:{} {}", g.0, g.1, g.2);
        }
        if name.starts_with("err_") {
            assert!(!want.is_empty(), "{name}: a negative file without annotations");
        } else {
            assert!(want.is_empty(), "{name}: only err_*.sv files have errors");
        }
    }
    assert!(negatives >= 15, "{negatives} negative cases, want at least 15");
}

#[test]
fn the_corpus_covers_enough() {
    let mut asserts = 0;
    for (name, src) in corpus() {
        if !name.starts_with("err_") {
            asserts += parse(&src).assertions.len();
        }
    }
    assert!(asserts >= 40, "{asserts} assertions, want at least 40");
}

#[test]
fn descriptions_match_the_golden_files() {
    let bless = std::env::var_os("SVA_BLESS").is_some();
    let dir = corpus_dir().join("golden");
    let mut stale = Vec::new();
    for (name, src) in corpus() {
        let text = describe(&parse(&src), &src, &name, false);
        let path = dir.join(name.replace(".sv", ".txt"));
        if bless {
            std::fs::write(&path, &text).unwrap();
            continue;
        }
        match std::fs::read_to_string(&path) {
            Ok(g) if g == text => {}
            Ok(g) => {
                let line = g.lines().zip(text.lines()).position(|(a, b)| a != b).unwrap_or(g.lines().count().min(text.lines().count()));
                stale.push(format!("{name}: differs from {} at line {}:\n  golden: {:?}\n  now:    {:?}", path.display(), line + 1, g.lines().nth(line), text.lines().nth(line)));
            }
            Err(_) => stale.push(format!("{name}: no golden file {}", path.display())),
        }
    }
    assert!(stale.is_empty(), "{}\n(SVA_BLESS=1 cargo test, or make sva-bless, rewrites them after a review)", stale.join("\n"));
}

fn strip(v: Value) -> Value {
    match v {
        Value::Object(m) => Value::Object(m.into_iter().filter(|(k, _)| k != "at").map(|(k, v)| (k, strip(v))).collect()),
        Value::Array(a) => Value::Array(a.into_iter().map(strip).collect()),
        v => v,
    }
}

#[test]
fn declarations_print_and_parse_back() {
    let mut n = 0;
    for (name, src) in corpus() {
        let p: Parsed = parse(&src);
        let bodies = p.properties.iter().map(|d| d.body.clone()).chain(p.sequences.iter().map(|d| sva_core::Prop::Seq { seq: d.body.clone() }));
        for b in bodies {
            for pr in [Printer::default(), Printer::full()] {
                let text = pr.prop(&b);
                let back = parse_prop(&text).unwrap_or_else(|e| panic!("{name}: {text}: {e}"));
                assert_eq!(strip(serde_json::to_value(&back).unwrap()), strip(serde_json::to_value(&b).unwrap()), "{name}: {text}");
            }
            n += 1;
        }
    }
    assert!(n >= 20, "{n} declarations");
}

/// tests/sva/third_party/units.json: assertion files of others (README.md there), each unit parsed as one compilation
/// unit with no error into the listed number of assertions; descriptions in golden/third_party/<unit>.txt.
#[test]
fn third_party_units_parse() {
    let dir = corpus_dir().join("third_party");
    let manifest: Value = serde_json::from_str(&std::fs::read_to_string(dir.join("units.json")).unwrap()).unwrap();
    let bless = std::env::var_os("SVA_BLESS").is_some();
    let golden = corpus_dir().join("golden").join("third_party");
    let (mut stale, mut total) = (Vec::new(), 0);
    for u in manifest["units"].as_array().unwrap() {
        let name = u["name"].as_str().unwrap();
        let mut unit = sva_core::Unit::new();
        let (mut text, mut n) = (String::new(), 0);
        for f in u["files"].as_array().unwrap() {
            let f = f.as_str().unwrap();
            let src = std::fs::read_to_string(dir.join(f)).unwrap_or_else(|e| panic!("{name}: {f}: {e}"));
            let p = unit.parse(&src);
            assert!(p.errors.is_empty(), "{name}: {f}: {:#?}", p.errors);
            n += p.assertions.len();
            text += &describe(&p, &src, f, false);
        }
        assert_eq!(n as u64, u["assertions"].as_u64().unwrap(), "{name}: assertions");
        total += n;
        let path = golden.join(format!("{name}.txt"));
        if bless {
            std::fs::create_dir_all(&golden).unwrap();
            std::fs::write(&path, &text).unwrap();
        } else if std::fs::read_to_string(&path).ok().as_deref() != Some(text.as_str()) {
            stale.push(format!("{name}: {} differs or is missing", path.display()));
        }
    }
    assert!(stale.is_empty(), "{}\n(SVA_BLESS=1 cargo test, or make sva-bless, rewrites them after a review)", stale.join("\n"));
    assert!(total >= 80, "{total} third-party assertions");
}
