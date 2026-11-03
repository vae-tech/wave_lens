//! `sva diff --results A.json B.json`: the assertions' results of two runs (`sva eval --json`) compared: which failures
//! are new in B, which are gone, which moved. An assertion of A pairs with the one of B of the same name and scope (the
//! scope after --map, as `sva diff` maps paths). Its failed attempts pair by their start time: a failure of B with no
//! failure of A at its start is new, one of A with none in B is gone; a pair with another failed_at moved. When as many
//! are new as are gone they pair by their order instead: each moved (the same failures at other times). A cover has no
//! failures: its matches compare — one that matched in A and never in B is lost (a coverage regression), one that never
//! matched in A and does in B is found. An assertion present twice in a run (two files binding one label into a scope)
//! pairs by its order among those of its key. Times are ps.

use std::fmt::Write as _;
use std::process::ExitCode;
use serde_json::{json, Value};

macro_rules! outln {
    ($($t:tt)*) => { crate::write_out(format_args!($($t)*), true) };
}

pub const USAGE: &str = "usage: sva diff --results A.json B.json [--map A=B ...] [--json [FILE.json|-]] [--junit FILE] [--limit N] [--quiet]
The assertions' results of two runs (sva eval --json) compared: an assertion of A pairs with the one of B of its name and
scope (--map A=B renames A's scopes for B, the longest prefix). Their failed attempts pair by their start: a failure of B
without one of A at its start is new, one of A without one in B is gone, a pair whose failure is at another cycle moved;
as many new as gone pair by their order and are moved instead. An assertion only in B: its failures are new; only in A:
gone. A cover compares its matches: matched in A and never in B is lost (exit 1), never in A and matched in B found (exit 0);
the table shows its matches. One name present twice in a scope pairs by its order. Starts pair by their absolute time:
a run whose reset or stimulus moved shows its failures as moved, or as new and gone. --json: the result as JSON (times in ps); --junit: a test case per assertion, a failure for new or moved ones (a
gone one is said in its system-out: JUnit has no word for it); --limit: failures listed per assertion (default 20, 0 all).
Exit status: 0 no failure new, gone or moved and no cover lost; 1 some; 2 usage, a file that is no results JSON.";

#[derive(Default)]
struct Opt {
    a: String,
    b: String,
    map: Vec<(String, String)>,
    json: Option<String>,
    junit: Option<String>,
    limit: usize,
    quiet: bool,
}

fn opts(args: &[String]) -> Result<Opt, String> {
    let mut o = Opt { limit: 20, ..Opt::default() };
    let mut files = Vec::new();
    let mut i = 0;
    let val = |i: &mut usize, f: &str| -> Result<String, String> {
        *i += 1;
        args.get(*i).cloned().ok_or_else(|| format!("{f} needs a value\n{USAGE}"))
    };
    while i < args.len() {
        let a = args[i].as_str();
        match a {
            "-h" | "--help" => return Err(USAGE.into()),
            "--results" => {}
            "--map" => {
                let v = val(&mut i, a)?;
                let (x, y) = v.split_once('=').filter(|(x, y)| !x.is_empty() && !y.is_empty()).ok_or_else(|| format!("--map {v}: A=B, a scope of A and its scope in B"))?;
                o.map.push((x.trim().to_string(), y.trim().to_string()));
            }
            "--json" => {
                // a file only when it says so: `-`, or a name ending with .json once both results are given (they end so too)
                let f = args.get(i + 1).filter(|f| f.as_str() == "-" || (f.ends_with(".json") && files.len() >= 2));
                o.json = Some(f.cloned().unwrap_or_else(|| "-".into()));
                if f.is_some() {
                    i += 1;
                }
            }
            "--junit" => o.junit = Some(val(&mut i, a)?),
            "--limit" => o.limit = crate::count(&val(&mut i, a)?, "--limit")? as usize,
            "--quiet" | "-q" => o.quiet = true,
            "--signals" | "--signals-from" | "--scope" | "--from" | "--to" | "--offset" | "--segment" | "--align" | "--spans" | "--rank" => {
                return Err(format!("{a} is of two dumps: --results compares two results, not together"));
            }
            s if s.starts_with('-') && s.len() > 1 => return Err(format!("unknown option {s}\n{USAGE}")),
            s => files.push(s.to_string()),
        }
        i += 1;
    }
    let [a, b] = <[String; 2]>::try_from(files).map_err(|f| format!("two results, A and B ({} given: {})\n{USAGE}", f.len(), f.join(" ")))?;
    for f in [&a, &b] {
        let low = f.to_ascii_lowercase();
        if low.ends_with(".vcd") || low.ends_with(".fst") {
            return Err(format!("{f}: a dump; --results compares two results JSON (sva eval --json), not together with dumps"));
        }
    }
    (o.a, o.b) = (a, b);
    Ok(o)
}

/// A failed attempt: its start and the cycle it failed at, as times.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Fail {
    pub start: u64,
    pub at: u64,
}

/// One assertion of one run: its key (scope + name), its counts, its failures by start.
struct Asr {
    name: String,
    scope: String,
    stats: Value,
    fails: Vec<Fail>,
    /// a cover's matches (`stats.matches`, else its passes); None: an assert / assume
    matches: Option<u64>,
}

fn read(f: &str) -> Result<Vec<Asr>, String> {
    let text = std::fs::read_to_string(f).map_err(|e| format!("{f}: {e}"))?;
    let doc: Value = serde_json::from_str(&text).map_err(|e| format!("{f}: not JSON: {e}"))?;
    let list = doc["assertions"].as_array().ok_or_else(|| format!("{f}: no \"assertions\": a results JSON of sva eval --json"))?;
    let top = doc["cycles"].as_array();
    let mut out = Vec::new();
    for x in list {
        let cycles = x["cycles"].as_array().or(top);
        let at = |c: &Value| -> u64 {
            let k = c.as_u64().unwrap_or(0) as usize;
            cycles.and_then(|cs| cs.get(k)).and_then(Value::as_u64).unwrap_or(k as u64)
        };
        let mut fails: Vec<Fail> = x["attempts"].as_array().into_iter().flatten().filter(|t| t["result"] == "fail")
            .map(|t| Fail { start: at(&t["start"]), at: at(if t["failed_at"].is_null() { &t["end"] } else { &t["failed_at"] }) }).collect();
        fails.sort_by_key(|f| (f.start, f.at));
        let matches = (x["kind"] == "cover").then(|| x["stats"]["matches"].as_u64().or(x["stats"]["pass"].as_u64()).unwrap_or(0));
        out.push(Asr { name: x["name"].as_str().unwrap_or("").to_string(), scope: x["scope"].as_str().unwrap_or("").to_string(), stats: x["stats"].clone(),
            fails: if matches.is_some() { Vec::new() } else { fails }, matches });
    }
    Ok(out)
}

/// A scope of A for B: the longest --map prefix (a whole name), else as it is.
fn mapped(scope: &str, map: &[(String, String)]) -> String {
    map.iter().filter(|(a, _)| scope == a || scope.starts_with(&format!("{a}."))).max_by_key(|(a, _)| a.len())
        .map_or_else(|| scope.to_string(), |(a, b)| format!("{b}{}", &scope[a.len()..]))
}

/// The failures of A and B of one assertion -> (new, gone, moved [(a, b)]).
pub fn pair(a: &[Fail], b: &[Fail]) -> (Vec<Fail>, Vec<Fail>, Vec<(Fail, Fail)>) {
    let (mut new, mut gone, mut moved) = (Vec::new(), Vec::new(), Vec::new());
    let mut used = vec![false; b.len()];
    for x in a {
        match b.iter().enumerate().position(|(k, y)| !used[k] && y.start == x.start) {
            Some(k) => {
                used[k] = true;
                if b[k].at != x.at {
                    moved.push((*x, b[k]));
                }
            }
            None => gone.push(*x),
        }
    }
    new.extend(b.iter().enumerate().filter(|(k, _)| !used[*k]).map(|(_, y)| *y));
    if !new.is_empty() && new.len() == gone.len() {   // the same failures at other times
        moved.extend(gone.drain(..).zip(new.drain(..)));
        moved.sort_by_key(|(x, _)| x.start);
    }
    (new, gone, moved)
}

pub fn results_cmd(args: &[String]) -> ExitCode {
    let o = match opts(args) {
        Ok(o) => o,
        Err(e) if e == USAGE => {
            outln!("{USAGE}");
            return ExitCode::SUCCESS;
        }
        Err(e) => {
            eprintln!("sva: {e}");
            return ExitCode::from(2);
        }
    };
    match run(&o) {
        Ok(same) => ExitCode::from(if same { 0 } else { 1 }),
        Err(e) => {
            eprintln!("sva: {e}");
            ExitCode::from(2)
        }
    }
}

fn run(o: &Opt) -> Result<bool, String> {
    let (a, b) = (read(&o.a)?, read(&o.b)?);
    let key = |x: &Asr, scope: &str| format!("{scope}\u{0}{}", x.name);
    let mut rows: Vec<Value> = Vec::new();
    let (mut n_new, mut n_gone, mut n_moved, mut n_lost, mut n_found) = (0usize, 0usize, 0usize, 0usize, 0usize);
    let lim = |v: Vec<Value>| -> (Vec<Value>, usize) {
        let n = v.len();
        let k = if o.limit == 0 { n } else { o.limit.min(n) };
        (v.into_iter().take(k).collect(), n - k)
    };
    let f = |x: &Fail| json!({"start": x.start, "failed_at": x.at});
    let mut seen_b = vec![false; b.len()];
    let mut one = |x: Option<&Asr>, y: Option<&Asr>, rows: &mut Vec<Value>| {
        let Some(z) = x.or(y) else { return };
        let (name, scope) = (z.name.as_str(), z.scope.as_str());
        let (fa, fb) = (x.map_or(&[][..], |x| &x.fails[..]), y.map_or(&[][..], |y| &y.fails[..]));
        let (sa, sb) = (x.map_or(Value::Null, |x| x.stats.clone()), y.map_or(Value::Null, |y| y.stats.clone()));
        let (new, gone, moved) = pair(fa, fb);
        n_new += new.len();
        n_gone += gone.len();
        n_moved += moved.len();
        let (nl, nm) = lim(new.iter().map(f).collect());
        let (gl, gm) = lim(gone.iter().map(f).collect());
        let (ml, mm) = lim(moved.iter().map(|(x, y)| json!({"a": f(x), "b": f(y)})).collect());
        let mut r = json!({"name": name, "scope": scope, "a": {"fails": fa.len(), "stats": sa}, "b": {"fails": fb.len(), "stats": sb},
            "new": nl, "gone": gl, "moved": ml, "first_new": new.first().map(|x| x.start)});
        if nm + gm + mm > 0 {
            r["more"] = json!({"new": nm, "gone": gm, "moved": mm});
        }
        if z.matches.is_some() {   // a cover: its matches
            let (ma, mb) = (x.and_then(|x| x.matches), y.and_then(|y| y.matches));
            r["kind"] = json!("cover");
            r["a"]["matches"] = json!(ma);
            r["b"]["matches"] = json!(mb);
            let (lost, found) = (ma.unwrap_or(0) > 0 && mb.unwrap_or(0) == 0, ma.unwrap_or(0) == 0 && mb.unwrap_or(0) > 0);
            r["lost"] = json!(lost);
            r["found"] = json!(found);
            n_lost += usize::from(lost);
            n_found += usize::from(found);
        }
        rows.push(r);
    };
    for x in &a {   // the first of B with its key not paired yet: one name twice in a scope pairs by its order
        let k = key(x, &mapped(&x.scope, &o.map));
        let y = b.iter().enumerate().position(|(j, y)| !seen_b[j] && key(y, &y.scope) == k);
        if let Some(j) = y {
            seen_b[j] = true;
        }
        one(Some(x), y.map(|j| &b[j]), &mut rows);
    }
    for (_, y) in b.iter().enumerate().filter(|(j, _)| !seen_b[*j]) {
        one(None, Some(y), &mut rows);
    }
    let fails = |v: &[Asr]| v.iter().map(|x| x.fails.len()).sum::<usize>();
    let doc = json!({"wavelens": "diff", "kind": "results", "version": 1,
        "a": {"file": o.a, "assertions": a.len(), "fails": fails(&a)}, "b": {"file": o.b, "assertions": b.len(), "fails": fails(&b)},
        "map": o.map.iter().map(|(x, y)| json!({"a": x, "b": y})).collect::<Vec<_>>(),
        "assertions": rows, "new": n_new, "gone": n_gone, "moved": n_moved, "lost": n_lost, "found": n_found});
    if let Some(j) = &o.junit {
        std::fs::write(j, junit(&doc, o)).map_err(|e| format!("{j}: {e}"))?;
    }
    match o.json.as_deref() {
        Some("-") => outln!("{}", serde_json::to_string_pretty(&doc).unwrap_or_default()),
        Some(file) => {
            std::fs::write(file, serde_json::to_string_pretty(&doc).unwrap_or_default() + "\n").map_err(|e| format!("{file}: {e}"))?;
            if !o.quiet {
                text(&doc);
            }
        }
        None => text(&doc),
    }
    Ok(n_new + n_gone + n_moved + n_lost == 0)
}

fn t(v: &Value) -> String {
    v.as_u64().map_or("?".into(), crate::ns)
}

fn name_of(r: &Value) -> String {
    let (s, n) = (r["scope"].as_str().unwrap_or(""), r["name"].as_str().unwrap_or(""));
    if s.is_empty() { n.to_string() } else { format!("{n} @ {s}") }
}

fn text(d: &Value) {
    let n = |v: &Value| v.as_u64().unwrap_or(0);
    outln!("A: {}  {} assertions, {} failures", d["a"]["file"].as_str().unwrap_or(""), n(&d["a"]["assertions"]), n(&d["a"]["fails"]));
    outln!("B: {}  {} assertions, {} failures", d["b"]["file"].as_str().unwrap_or(""), n(&d["b"]["assertions"]), n(&d["b"]["fails"]));
    outln!("{} new, {} gone, {} moved{}", n(&d["new"]), n(&d["gone"]), n(&d["moved"]),
        if n(&d["lost"]) + n(&d["found"]) > 0 { format!("; covers: {} lost, {} found", n(&d["lost"]), n(&d["found"])) } else { String::new() });
    let covers: Vec<&Value> = d["assertions"].as_array().into_iter().flatten().filter(|r| r["lost"] == true || r["found"] == true).collect();
    for r in &covers {
        let m = |v: &Value| v.as_u64().map_or("—".to_string(), |k| k.to_string());
        outln!("  cover {}: {} — matches A {}, B {}", name_of(r), if r["lost"] == true { "lost" } else { "found" }, m(&r["a"]["matches"]), m(&r["b"]["matches"]));
    }
    let rows: Vec<&Value> = d["assertions"].as_array().into_iter().flatten()
        .filter(|r| r["new"].as_array().is_some_and(|x| !x.is_empty()) || r["gone"].as_array().is_some_and(|x| !x.is_empty())
            || r["moved"].as_array().is_some_and(|x| !x.is_empty())).collect();
    if rows.is_empty() {
        return;
    }
    let w = rows.iter().map(|r| name_of(r).len()).max().unwrap_or(9).max(9);
    outln!("  {:<w$}  {:>7}  {:>7}  {:>4}  {:>4}  {:>5}  first new at", "assertion", "A fails", "B fails", "new", "gone", "moved");
    for r in rows {
        let len = |k: &str| r[k].as_array().map_or(0, Vec::len) + r["more"][k].as_u64().unwrap_or(0) as usize;
        outln!("  {:<w$}  {:>7}  {:>7}  {:>4}  {:>4}  {:>5}  {}", name_of(r), n(&r["a"]["fails"]), n(&r["b"]["fails"]), len("new"), len("gone"), len("moved"),
            if r["first_new"].is_null() { "—".into() } else { t(&r["first_new"]) });
    }
}

/// A test case per assertion: a failure when it has new or moved failures; the gone ones said in its system-out.
fn junit(d: &Value, o: &Opt) -> String {
    let x = sva_core::xml_text;
    let rows = d["assertions"].as_array().cloned().unwrap_or_default();
    let count = |r: &Value, k: &str| r[k].as_array().map_or(0, Vec::len) + r["more"][k].as_u64().unwrap_or(0) as usize;
    let fails = rows.iter().filter(|r| count(r, "new") + count(r, "moved") > 0 || r["lost"] == true).count();
    let mut out = format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites>\n<testsuite name=\"{}\" tests=\"{}\" failures=\"{fails}\" errors=\"0\" skipped=\"0\" time=\"0\">\n",
        x(&format!("diff --results {} {}", o.a, o.b)), rows.len());
    for r in &rows {
        let (nn, nm, ng) = (count(r, "new"), count(r, "moved"), count(r, "gone"));
        let _ = write!(out, "  <testcase classname=\"sva.diff.results\" name=\"{}\" time=\"0\">", x(&name_of(r)));
        if nn + nm > 0 {
            let _ = write!(out, "<failure type=\"changed\" message=\"{nn} new, {nm} moved\">");
            for f in r["new"].as_array().into_iter().flatten() {
                let _ = writeln!(out, "{}", x(&format!("new: starts {}, fails {}", t(&f["start"]), t(&f["failed_at"]))));
            }
            for m in r["moved"].as_array().into_iter().flatten() {
                let _ = writeln!(out, "{}", x(&format!("moved: {} → {}", t(&m["a"]["failed_at"]), t(&m["b"]["failed_at"]))));
            }
            out.push_str("</failure>");
        } else if r["lost"] == true {
            let _ = write!(out, "<failure type=\"lost\" message=\"{}\"/>", x(&format!("the cover matched {} times in A, never in B", r["a"]["matches"])));
        }
        let _ = write!(out, "<system-out>{} failures in A, {} in B{}</system-out>", r["a"]["fails"], r["b"]["fails"],
            if ng > 0 { format!("; {ng} gone") } else { String::new() });
        out.push_str("</testcase>\n");
    }
    out.push_str("</testsuite>\n</testsuites>\n");
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn f(start: u64, at: u64) -> Fail {
        Fail { start, at }
    }

    #[test]
    fn failures_pair_by_their_start() {
        let (new, gone, moved) = pair(&[f(10, 30), f(50, 70)], &[f(10, 30), f(50, 90), f(80, 100)]);
        assert_eq!((new, gone, moved), (vec![f(80, 100)], vec![], vec![(f(50, 70), f(50, 90))]));
    }

    #[test]
    fn as_many_new_as_gone_moved() {
        let (new, gone, moved) = pair(&[f(10, 30), f(50, 70)], &[f(20, 40), f(60, 80)]);
        assert_eq!((new.len(), gone.len()), (0, 0));
        assert_eq!(moved, vec![(f(10, 30), f(20, 40)), (f(50, 70), f(60, 80))]);
        let (new, gone, moved) = pair(&[f(10, 30)], &[]);
        assert_eq!((new.len(), gone, moved.len()), (0, vec![f(10, 30)], 0));
    }

    #[test]
    fn a_scope_maps_by_its_longest_prefix() {
        let m = vec![("tb".to_string(), "top".to_string()), ("tb.u".to_string(), "top.v".to_string())];
        assert_eq!(mapped("tb.u.x", &m), "top.v.x");
        assert_eq!(mapped("tb.w", &m), "top.w");
        assert_eq!(mapped("tbx", &m), "tbx");
    }
}
