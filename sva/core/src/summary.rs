//! The report of a set of results documents (stage 8): the numbers per assertion (first / last failure, longest
//! attempt, antecedent → consequent latency), the totals, the failure list; as JSON for the page's tables and as
//! Markdown, JUnit XML and an HTML section. One implementation for `sva eval --report / --junit`, `sva report`, the
//! page (through `run_json`) and `mkhtml.py`.
//!
//! Input: `{"meta": {"title", "dump", "tool", "date", ...}, "results": [results document, ...], "sources"?: [name per
//! document], "max_failures"?: n}` (a document of `sva eval`, or the one-assertion document of a page binding;
//! `sources` names the file each document came from when they are several; `max_failures`: the failures listed per
//! assertion in the texts, default 20, 0 = all — the JSON keeps every one). Capped attempts (no verdict) are counted
//! apart from failures everywhere; in JUnit they are an error of their test case.

use serde_json::{json, Map, Value};
use std::fmt::Write;

fn u(v: &Value, k: &str) -> u64 {
    v.get(k).and_then(Value::as_u64).unwrap_or(0)
}
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v.get(k).and_then(Value::as_str).unwrap_or("")
}

/// A time of the results' unit in words, exact (no digit lost, trailing zeros dropped): `125 ns`, `1.0004 us`,
/// `81.7164 us`, `2 ms`, `400 ps`, `cycle 7`.
pub fn time_text(t: u64, unit: &str) -> String {
    match unit {
        "ps" => {
            let (div, name, digits) = [(1_000_000_000_000u64, "s", 12), (1_000_000_000, "ms", 9), (1_000_000, "us", 6), (1_000, "ns", 3)]
                .into_iter().find(|(d, ..)| t >= *d).unwrap_or((1, "ps", 0));
            let (whole, frac) = (t / div, t % div);
            if frac == 0 {
                format!("{whole} {name}")
            } else {
                let f = format!("{frac:0digits$}");
                format!("{whole}.{} {name}", f.trim_end_matches('0'))
            }
        }
        "cycles" | "" => format!("cycle {t}"),
        u => format!("{t} {u}"),
    }
}

/// What `sva report` and the page's `run_json` accept: `{"results": [{"assertions": [{"name", "stats"?: {counts},
/// "attempts"?: [{"start", "end", ...}]}]}]}`. The first thing that is not so, in words.
pub fn check_input(input: &Value) -> Result<(), String> {
    const SUMMARY: &str = "this is a report summary (sva report --json), not results: give the results documents";
    if input.get("totals").is_some() {
        return Err(SUMMARY.into());
    }
    let docs = input.get("results").and_then(Value::as_array).ok_or("no \"results\" list (a results document of sva eval, or a page's report.json)")?;
    for (i, d) in docs.iter().enumerate() {
        if d.get("totals").is_some() {
            return Err(SUMMARY.into());
        }
        let list = d.get("assertions").and_then(Value::as_array).ok_or(format!("results[{i}]: no \"assertions\" list"))?;
        for (j, a) in list.iter().enumerate() {
            let at = format!("results[{i}].assertions[{j}]");
            a.get("name").and_then(Value::as_str).ok_or(format!("{at}: no name"))?;
            if let Some(st) = a.get("stats") {
                let st = st.as_object().ok_or(format!("{at}: stats is not an object"))?;
                for (k, v) in st {
                    if !v.is_u64() {
                        return Err(format!("{at}: stats.{k} is not a count"));
                    }
                }
            }
            for (k, x) in a.get("attempts").and_then(Value::as_array).into_iter().flatten().enumerate() {
                if !x.get("start").is_some_and(Value::is_u64) || !x.get("end").is_some_and(Value::is_u64) {
                    return Err(format!("{at}.attempts[{k}]: start / end are not cycles"));
                }
            }
        }
    }
    Ok(())
}

/// The failure `a` of assertion `o` (row `row`): where it started and failed, as cycles and times.
fn event(o: &Value, a: &Value, cycles: &[u64], unit: &str, row: usize, source: &str) -> Value {
    let start = u(a, "start");
    let at = a.get("failed_at").and_then(Value::as_u64).unwrap_or(u(a, "end"));
    let t = |c: u64| cycles.get(c as usize).copied();
    json!({
        "row": row, "source": source, "name": s(o, "name"), "scope": s(o, "scope"), "start": start, "failed_at": at, "unit": unit,
        "t_start": t(start), "t_fail": t(at), "time": t(start).map(|x| time_text(x, unit)), "time_fail": t(at).map(|x| time_text(x, unit)),
        "note": s(a, "note"), "kind": a.get("reason").map_or("", |r| s(r, "kind")),
    })
}

/// The average with two decimals at most and one at least: `2.0`, `7.66`, `54.0`.
fn avg_text(x: f64) -> String {
    let t = format!("{x:.2}");
    let t = t.trim_end_matches('0');
    if t.ends_with('.') { format!("{t}0") } else { t.to_string() }
}

/// One assertion of a results document -> its row of the report (with its failures, taken out by `summarize`).
fn assertion(o: &Value, doc: &Value, row: usize, source: &str) -> Value {
    let unit = s(doc, "unit");
    let cycles: Vec<u64> = o.get("cycles").or_else(|| doc.get("cycles")).and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_u64).collect()).unwrap_or_default();
    let empty = vec![];
    let attempts = o.get("attempts").and_then(Value::as_array).unwrap_or(&empty);
    let cover = s(o, "kind") == "cover";
    let at_fail = |a: &Value| (a.get("failed_at").and_then(Value::as_u64).unwrap_or(u(a, "end")), u(a, "start"));
    // in the order they were found (failed_at): the simulator's $error time
    let mut fails: Vec<&Value> = if cover { vec![] } else { attempts.iter().filter(|a| s(a, "result") == "fail").collect() };
    fails.sort_by_key(|a| at_fail(a));
    // the consequent steps of the outer implication (group 0): latency = last of them - the antecedent match before it
    let cons: Vec<&str> = o.get("steps").and_then(Value::as_array).map(|st| {
        st.iter().filter(|x| s(x, "role") == "cons" && u(x, "group") == 0).map(|x| s(x, "id")).collect()
    }).unwrap_or_default();
    let mut lat: Vec<u64> = Vec::new();
    let mut longest: Option<(u64, u64)> = None;
    for a in attempts {
        let (st, en) = (u(a, "start"), u(a, "end").max(u(a, "start")));
        let r = s(a, "result");
        // decided attempts only: an active one runs to the end of the dump, a capped one has no end of its own
        if !cover && r != "active" && r != "capped" && longest.is_none_or(|(l, _)| en - st > l) {
            longest = Some((en - st, st));
        }
        if r != "pass" {
            continue;
        }
        let ante: Vec<u64> = a.get("ante_end").and_then(Value::as_array).map(|x| x.iter().filter_map(Value::as_u64).collect()).unwrap_or_default();
        if ante.is_empty() {
            continue;
        }
        let last = a.get("trace").and_then(Value::as_array).and_then(|tr| {
            tr.iter().filter(|x| x.get(0).and_then(Value::as_str).is_some_and(|id| cons.contains(&id))).filter_map(|x| x.get(1).and_then(Value::as_u64)).max()
        }).unwrap_or(en);
        if let Some(&a0) = ante.iter().filter(|&&c| c <= last).max() {
            lat.push(last - a0);
        }
    }
    let latency = (!lat.is_empty()).then(|| {
        let sum: u64 = lat.iter().sum();
        let (mn, mx, avg) = (*lat.iter().min().unwrap(), *lat.iter().max().unwrap(), sum as f64 / lat.len() as f64);
        json!({ "min": mn, "max": mx, "avg": (avg * 100.0).round() / 100.0, "n": lat.len(), "text": format!("{mn} / {} / {mx}", avg_text(avg)) })
    });
    let stats = o.get("stats").cloned().unwrap_or(json!({}));
    let ev = |a: &&Value| event(o, a, &cycles, unit, row, source);
    json!({
        "row": row, "source": source, "name": s(o, "name"), "kind": s(o, "kind"), "scope": s(o, "scope"), "file": s(o, "file"), "line": u(o, "line"), "text": s(o, "text"),
        "unit": unit, "stats": stats,
        "first_fail": fails.first().map(ev),
        "last_fail": fails.last().map(ev),
        "longest": longest.map(|(l, st)| json!({ "cycles": l, "start": st, "time": cycles.get(st as usize).map(|t| time_text(*t, unit)) })),
        "latency": latency,
        "covered": if cover { json!(stats.get("matches").and_then(Value::as_u64).unwrap_or(u(&stats, "pass"))) } else { Value::Null },
        "missing": o.get("missing").cloned().unwrap_or(json!([])),
        "notes": o.get("notes").cloned().unwrap_or(json!([])),
        "failures": fails.iter().map(ev).collect::<Vec<_>>(),
    })
}

/// `{"meta", "results": [...]}` -> `{"meta", "totals", "assertions": [row], "failures": [event by failure time],
/// "max_failures", "sources"}`. Every row and failure carries `row` (its index) and `source`.
pub fn summarize(input: &Value) -> Value {
    let names: Vec<&str> = input.get("sources").and_then(Value::as_array).map(|a| a.iter().map(|x| x.as_str().unwrap_or("")).collect()).unwrap_or_default();
    let mut rows = Vec::new();
    for (i, doc) in input.get("results").and_then(Value::as_array).into_iter().flatten().enumerate() {
        for o in doc.get("assertions").and_then(Value::as_array).into_iter().flatten() {
            let n = rows.len();
            rows.push(assertion(o, doc, n, names.get(i).copied().unwrap_or("")));
        }
    }
    let mut failures: Vec<Value> = Vec::new();
    for r in rows.iter_mut() {
        if let Some(Value::Array(f)) = r.as_object_mut().and_then(|m| m.remove("failures")) {
            failures.extend(f);
        }
    }
    // by the time they were found; times of another unit (cycles) after the ones in ps
    failures.sort_by(|a, b| (s(a, "unit") != "ps").cmp(&(s(b, "unit") != "ps")).then(u(a, "t_fail").cmp(&u(b, "t_fail"))).then(u(a, "t_start").cmp(&u(b, "t_start"))).then(s(a, "name").cmp(s(b, "name"))));
    let mut t = Map::new();
    let evaluated = |r: &Value| r["missing"].as_array().is_none_or(Vec::is_empty);
    let sum = |k: &str, cover: bool| -> u64 { rows.iter().filter(|r| (s(r, "kind") == "cover") == cover && evaluated(r)).map(|r| u(&r["stats"], k)).sum() };
    let checks: Vec<&Value> = rows.iter().filter(|r| s(r, "kind") != "cover").collect();
    t.insert("assertions".into(), json!(rows.len()));
    t.insert("evaluated".into(), json!(rows.iter().filter(|r| evaluated(r)).count()));
    t.insert("with_failures".into(), json!(checks.iter().filter(|r| u(&r["stats"], "fail") > 0).count()));
    t.insert("not_proven".into(), json!(rows.iter().filter(|r| evaluated(r) && u(&r["stats"], "capped") > 0).count()));
    for k in ["attempts", "pass", "fail", "vacuous", "disabled", "active", "capped"] {
        t.insert(k.into(), json!(sum(k, false)));
    }
    t.insert("covers".into(), json!(rows.len() - checks.len()));
    t.insert("covered".into(), json!(rows.iter().filter(|r| r["covered"].as_u64().is_some_and(|n| n > 0)).count()));
    let mut srcs: Vec<&str> = names.iter().copied().filter(|x| !x.is_empty()).collect();
    srcs.dedup();
    json!({ "meta": input.get("meta").cloned().unwrap_or(json!({})), "totals": t, "assertions": rows, "failures": failures,
        "max_failures": input.get("max_failures").and_then(Value::as_u64).unwrap_or(20), "sources": srcs })
}

/// Markdown text outside code: `|` and line breaks would end the cell, `<` and `&` would be HTML.
fn md(x: &str) -> String {
    x.replace('&', "&amp;").replace('<', "&lt;").replace('|', "\\|").replace(['\n', '\r'], " ")
}
/// A code span that holds any text: fenced by more backticks than the longest run in it.
fn code(x: &str) -> String {
    let run = x.split(|c| c != '`').map(str::len).max().unwrap_or(0);
    let f = "`".repeat(run + 1);
    let pad = if x.starts_with('`') || x.ends_with('`') { " " } else { "" };
    format!("{f}{pad}{}{pad}{f}", x.replace('|', "\\|").replace(['\n', '\r'], " "))
}
fn fail_text(e: &Value) -> String {
    if e.is_null() { "—".into() } else { format!("{} (cycle {})", e["time_fail"].as_str().unwrap_or(""), u(e, "failed_at")) }
}
fn totals_text(t: &Value) -> String {
    let mut x = format!("{} assertions ({} evaluated, {} with failures): {} attempts, {} pass, {} fail, {} vacuous, {} disabled, {} active",
        u(t, "assertions"), u(t, "evaluated"), u(t, "with_failures"), u(t, "attempts"), u(t, "pass"), u(t, "fail"), u(t, "vacuous"), u(t, "disabled"), u(t, "active"));
    if u(t, "capped") > 0 {
        let _ = write!(x, ", {} capped (no verdict)", u(t, "capped"));
    }
    if u(t, "covers") > 0 {
        let _ = write!(x, "; {} of {} covers hit", u(t, "covered"), u(t, "covers"));
    }
    x
}
fn meta_lines(m: &Value) -> Vec<(String, String)> {
    m.as_object().map(|o| o.iter().filter(|(k, _)| k.as_str() != "title").map(|(k, v)| (k.clone(), v.as_str().map_or(v.to_string(), String::from))).collect()).unwrap_or_default()
}
fn several(r: &Value) -> bool {
    r["sources"].as_array().is_some_and(|a| a.len() > 1)
}

/// The cells of one assertion's row, as text (Markdown and HTML escape them their way).
struct Cells {
    name: String,
    miss: String,
    scope: String,
    source: String,
    kind: String,
    counts: Vec<String>,
    first: String,
    last: String,
    longest: String,
    latency: String,
}
fn cells(a: &Value) -> Cells {
    let cover = s(a, "kind") == "cover";
    let st = &a["stats"];
    Cells {
        name: s(a, "name").into(),
        miss: a["missing"].as_array().filter(|m| !m.is_empty()).map(|m| format!("not evaluated: no {}", m.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", "))).unwrap_or_default(),
        scope: s(a, "scope").into(),
        source: s(a, "source").into(),
        kind: if cover { format!("cover: {} hit", a["covered"]) } else { s(a, "kind").into() },
        // a cover's attempts that did not match are no failures: no number in Fail
        counts: ["attempts", "pass", "fail", "vacuous", "disabled", "active", "capped"].iter().map(|k| if cover && *k == "fail" { "—".into() } else { u(st, k).to_string() }).collect(),
        first: fail_text(&a["first_fail"]),
        last: fail_text(&a["last_fail"]),
        longest: a["longest"].get("cycles").map_or("—".into(), |l| l.to_string()),
        latency: a["latency"].get("text").and_then(Value::as_str).unwrap_or("—").into(),
    }
}
const HEAD: [&str; 14] = ["Assertion", "Scope", "Kind", "Attempts", "Pass", "Fail", "Vacuous", "Disabled", "Active", "Capped", "First failure", "Last failure", "Longest (cycles)", "Latency min / avg / max"];

/// The failures to list: at most `max_failures` per assertion (0: all), in time order; and how many were left out
/// per row.
fn listed(r: &Value) -> (Vec<&Value>, Vec<(usize, usize)>) {
    let max = r["max_failures"].as_u64().unwrap_or(20) as usize;
    let mut n: std::collections::BTreeMap<usize, usize> = Default::default();
    let mut out = Vec::new();
    for e in r["failures"].as_array().into_iter().flatten() {
        let k = n.entry(u(e, "row") as usize).or_default();
        *k += 1;
        if max == 0 || *k <= max {
            out.push(e);
        }
    }
    let more = n.into_iter().filter(|(_, k)| max > 0 && *k > max).map(|(row, k)| (row, k - max)).collect();
    (out, more)
}
/// Notes of the assertions (thread limit, values cut to 64 bits, short columns): (row, note).
fn notes(r: &Value) -> Vec<(usize, String)> {
    r["assertions"].as_array().into_iter().flatten().enumerate()
        .flat_map(|(k, a)| a["notes"].as_array().into_iter().flatten().filter_map(Value::as_str).map(move |n| (k, n.to_string()))).collect()
}

/// The report as Markdown: totals, the table per assertion, notes, the failure list.
pub fn markdown(r: &Value) -> String {
    let mut o = String::new();
    let rows = r["assertions"].as_array().cloned().unwrap_or_default();
    let src = several(r);
    let _ = writeln!(o, "# {}\n", md(r["meta"]["title"].as_str().unwrap_or("Assertions")));
    for (k, v) in meta_lines(&r["meta"]) {
        let _ = writeln!(o, "- {}: {}", md(&k), md(&v));
    }
    let _ = writeln!(o, "\n**Totals:** {}\n", totals_text(&r["totals"]));
    let head: Vec<&str> = HEAD.iter().copied().take(2).chain(src.then_some("Source")).chain(HEAD.iter().copied().skip(2)).collect();
    let _ = writeln!(o, "## Per assertion\n\n| {} |\n|{}|", head.join(" | "), head.iter().map(|h| if ["Attempts", "Pass", "Fail", "Vacuous", "Disabled", "Active", "Capped", "Longest (cycles)"].contains(h) { "--:" } else { "---" }).collect::<Vec<_>>().join("|"));
    for a in &rows {
        let c = cells(a);
        let mut line = vec![format!("{}{}", code(&c.name), if c.miss.is_empty() { String::new() } else { format!(" ({})", md(&c.miss)) }), md(&c.scope)];
        if src {
            line.push(md(&c.source));
        }
        line.push(md(&c.kind));
        line.extend(c.counts);
        line.extend([c.first, c.last, c.longest, c.latency]);
        let _ = writeln!(o, "| {} |", line.join(" | "));
    }
    let ns = notes(r);
    if !ns.is_empty() {
        o.push_str("\n## Notes\n\n");
        for (k, n) in &ns {
            let _ = writeln!(o, "- {} {}: {}", code(s(&rows[*k], "name")), md(s(&rows[*k], "scope")), md(n));
        }
    }
    let total = r["failures"].as_array().map_or(0, Vec::len);
    let (list, more) = listed(r);
    let _ = writeln!(o, "\n## Failures ({total})\n");
    if list.is_empty() {
        o.push_str("None.\n");
    } else {
        let _ = writeln!(o, "| # | Assertion | Scope |{} Failed at | Start | Reason | Note |\n|--:|---|---|{}---|---|---|---|", if src { " Source |" } else { "" }, if src { "---|" } else { "" });
        for (i, e) in list.iter().enumerate() {
            let _ = writeln!(o, "| {} | {} | {} |{} {} (cycle {}) | {} (cycle {}) | {} | {} |", i + 1, code(s(e, "name")), md(s(e, "scope")), if src { format!(" {} |", md(s(e, "source"))) } else { String::new() },
                s(e, "time_fail"), u(e, "failed_at"), s(e, "time"), u(e, "start"), md(s(e, "kind")), md(s(e, "note")));
        }
        for (row, m) in more {
            let _ = writeln!(o, "\n… and {m} more failures of {} (report.json lists every one)", code(s(&rows[row], "name")));
        }
    }
    o
}

/// XML text: the five entities, and no control characters (XML 1.0 has none but tab, line feed, carriage return).
fn xml(x: &str) -> String {
    x.chars().filter(|c| !c.is_control() || matches!(c, '\t' | '\n' | '\r')).collect::<String>()
        .replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

/// JUnit XML: one test case per assertion; a failure with its first note and the list; an error when attempts had no
/// verdict (capped: the thread limit); `skipped` when it was not evaluated (missing signals) or a cover never hit.
pub fn junit(r: &Value) -> String {
    let rows = r["assertions"].as_array().cloned().unwrap_or_default();
    let failing = |a: &Value| s(a, "kind") != "cover" && u(&a["stats"], "fail") > 0;
    let missing = |a: &Value| a["missing"].as_array().is_some_and(|m| !m.is_empty());
    let fails = rows.iter().filter(|a| !missing(a) && failing(a)).count();
    let errors = rows.iter().filter(|a| !missing(a) && !failing(a) && u(&a["stats"], "capped") > 0).count();
    let skipped = rows.iter().filter(|a| missing(a) || a["covered"].as_u64() == Some(0)).count();
    let mut o = format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites>\n<testsuite name=\"{}\" tests=\"{}\" failures=\"{fails}\" errors=\"{errors}\" skipped=\"{skipped}\" time=\"0\">\n",
        xml(r["meta"]["title"].as_str().unwrap_or("sva")), rows.len());
    let _ = writeln!(o, "  <properties><property name=\"capped\" value=\"{}\"/><property name=\"attempts\" value=\"{}\"/></properties>", u(&r["totals"], "capped"), u(&r["totals"], "attempts"));
    let max = r["max_failures"].as_u64().unwrap_or(20) as usize;
    let mut by_row: Vec<Vec<&Value>> = vec![Vec::new(); rows.len()];
    for e in r["failures"].as_array().into_iter().flatten() {
        if let Some(v) = by_row.get_mut(u(e, "row") as usize) {
            v.push(e);
        }
    }
    let src = several(r);
    let ns = notes(r);
    for (k, a) in rows.iter().enumerate() {
        let st = &a["stats"];
        let mut class = if s(a, "scope").is_empty() { "sva".to_string() } else { s(a, "scope").to_string() };
        if src {
            let _ = write!(class, " [{}]", s(a, "source"));
        }
        let _ = write!(o, "  <testcase classname=\"{}\" name=\"{}\" file=\"{}\" line=\"{}\" time=\"0\">", xml(&class), xml(s(a, "name")), xml(s(a, "file")), u(a, "line"));
        if let Some(m) = a["missing"].as_array().filter(|m| !m.is_empty()) {
            let _ = write!(o, "<skipped message=\"not evaluated: no {}\"/>", xml(&m.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", ")));
        } else if a["covered"].as_u64() == Some(0) {
            o.push_str("<skipped message=\"cover never hit\"/>");
        } else if failing(a) {
            let first = &a["first_fail"];
            let _ = write!(o, "<failure type=\"{}\" message=\"{} fail of {} attempts; first at {}: {}\">", xml(s(first, "kind")), u(st, "fail"), u(st, "attempts"),
                xml(s(first, "time_fail")), xml(s(first, "note")));
            let list = &by_row[k];
            for e in list.iter().take(if max == 0 { usize::MAX } else { max }) {
                let _ = writeln!(o, "{} (cycle {}), started {} (cycle {}): {}", xml(s(e, "time_fail")), u(e, "failed_at"), xml(s(e, "time")), u(e, "start"), xml(s(e, "note")));
            }
            if max > 0 && list.len() > max {
                let _ = writeln!(o, "… and {} more", list.len() - max);
            }
            o.push_str("</failure>");
        } else if u(st, "capped") > 0 {
            let _ = write!(o, "<error type=\"capped\" message=\"{} attempts without verdict (thread limit)\"/>", u(st, "capped"));
        }
        let _ = write!(o, "<system-out>{} attempts: {} pass, {} fail, {} vacuous, {} disabled, {} active, {} capped", u(st, "attempts"), u(st, "pass"), u(st, "fail"),
            u(st, "vacuous"), u(st, "disabled"), u(st, "active"), u(st, "capped"));
        for (_, n) in ns.iter().filter(|(r, _)| *r == k) {
            let _ = write!(o, "\nnote: {}", xml(n));
        }
        o.push_str("</system-out></testcase>\n");
    }
    o.push_str("</testsuite>\n</testsuites>\n");
    o
}

/// The report as an HTML section (mkhtml.py's printable "Assertions" section): plain tables, classes for the page's CSS.
pub fn html(r: &Value) -> String {
    let rows = r["assertions"].as_array().cloned().unwrap_or_default();
    let src = several(r);
    let mut o = format!("<section class=\"sva-report\" id=\"assertions\">\n<h2>{}</h2>\n<p class=\"tot\">{}</p>\n", xml(r["meta"]["title"].as_str().unwrap_or("Assertions")), xml(&totals_text(&r["totals"])));
    let ml = meta_lines(&r["meta"]);
    if !ml.is_empty() {
        let _ = writeln!(o, "<p class=\"meta\">{}</p>", ml.iter().map(|(k, v)| format!("{}: <code>{}</code>", xml(k), xml(v))).collect::<Vec<_>>().join(" · "));
    }
    let head: Vec<&str> = HEAD.iter().copied().take(2).chain(src.then_some("Source")).chain(HEAD.iter().copied().skip(2)).collect();
    let _ = writeln!(o, "<table class=\"per\"><thead><tr>{}</tr></thead><tbody>", head.iter().map(|h| format!("<th>{h}</th>")).collect::<String>());
    for a in &rows {
        let c = cells(a);
        let bad = s(a, "kind") != "cover" && u(&a["stats"], "fail") > 0;
        let cls = if bad { " class=\"bad\"" } else if !c.miss.is_empty() { " class=\"miss\"" } else { "" };
        let miss = if c.miss.is_empty() { String::new() } else { format!(" <span class=\"muted\">({})</span>", xml(&c.miss)) };
        let _ = write!(o, "<tr{cls}><td><code title=\"{}\">{}</code>{miss}</td><td>{}</td>", xml(s(a, "text")), xml(&c.name), xml(&c.scope));
        if src {
            let _ = write!(o, "<td>{}</td>", xml(&c.source));
        }
        let _ = write!(o, "<td>{}</td>", xml(&c.kind));
        for x in &c.counts {
            let _ = write!(o, "<td class=\"n\">{x}</td>");
        }
        let _ = writeln!(o, "<td>{}</td><td>{}</td><td class=\"n\">{}</td><td>{}</td></tr>", xml(&c.first), xml(&c.last), c.longest, xml(&c.latency));
    }
    o.push_str("</tbody></table>\n");
    let ns = notes(r);
    if !ns.is_empty() {
        let _ = writeln!(o, "<ul class=\"notes\">{}</ul>", ns.iter().map(|(k, n)| format!("<li><code>{}</code> {}: {}</li>", xml(s(&rows[*k], "name")), xml(s(&rows[*k], "scope")), xml(n))).collect::<String>());
    }
    let total = r["failures"].as_array().map_or(0, Vec::len);
    let (list, more) = listed(r);
    let _ = writeln!(o, "<h3>Failures ({total})</h3>");
    if list.is_empty() {
        o.push_str("<p>None.</p>\n");
    } else {
        let _ = writeln!(o, "<table class=\"fails\"><thead><tr><th>#</th><th>Assertion</th><th>Scope</th>{}<th>Failed at</th><th>Start</th><th>Reason</th><th>Note</th></tr></thead><tbody>", if src { "<th>Source</th>" } else { "" });
        for (i, e) in list.iter().enumerate() {
            let _ = writeln!(o, "<tr><td class=\"n\">{}</td><td><code>{}</code></td><td>{}</td>{}<td>{} (cycle {})</td><td>{} (cycle {})</td><td>{}</td><td>{}</td></tr>", i + 1, xml(s(e, "name")),
                xml(s(e, "scope")), if src { format!("<td>{}</td>", xml(s(e, "source"))) } else { String::new() }, xml(s(e, "time_fail")), u(e, "failed_at"), xml(s(e, "time")), u(e, "start"), xml(s(e, "kind")), xml(s(e, "note")));
        }
        o.push_str("</tbody></table>\n");
        for (row, m) in more {
            let _ = writeln!(o, "<p class=\"more\">… and {m} more failures of <code>{}</code> (report.json lists every one)</p>", xml(s(&rows[row], "name")));
        }
    }
    o.push_str("</section>\n");
    o
}
