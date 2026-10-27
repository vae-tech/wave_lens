//! sva — parse SystemVerilog assertions, evaluate them over a VCD / FST dump (read with wellen).
//!
//!   sva parse [--json] [--expand] [-D NAME[=VALUE]] FILE...      the assertions of the files (one compilation unit)
//!   sva eval --waves DUMP [--scope tb.dut] --sva FILE... [...]     attempts and counts of every assertion, results JSON
//!   sva FILE... --waves DUMP [...]                                 the same as `sva eval`
//!   sva --waves DUMP --info                                        scopes, variables, widths, enum tables
//!   sva vcd DUMP [--out FILE.vcd]                                  the dump (FST) as VCD text, as fst2vcd -e writes it
//!   sva fst DUMP.vcd [--out FILE.fst]                              the VCD as an FST beside it, as vcd2fst writes it
//!   sva report [--md F] [--junit F] [--html F] [--json F] RESULTS.json...   the report of results documents
//!
//! Exit status: 0 everything evaluated passed; 1 a failure, or an attempt without verdict (capped: the thread limit);
//! 2 nothing was checked as asked (a usage error, a syntax error, a signal the dump does not have, no assertion, a dump
//! or results file that does not read).
//!
//! Signal names resolve under --scope, then in the scopes above it (--resolve scope: only the clock looks above, as
//! when the page binds an assertion to an instance; the rule of docs/sva/ENGINE.md *Name resolution*, with
//! --ignore-prefix for the names without those prefixes, and a select wider than the variable does not resolve). Values are sampled just before each clock edge
//! (the preponed region), so a value written at the edge counts from the next sampling point, as in a simulator.

mod fst;
mod vcd;

use std::collections::BTreeMap;
use std::process::ExitCode;
use sva_core::{check_report_input, describe, diagnostic, evaluate, report_html, report_junit, report_markdown, summarize, time_text, Assertion, Column, Kind, Options, Outcome, Results, Trace, Unit, XMode, V};
use wellen::{simple, Hierarchy, SignalRef, TimeTableIdx, VarRef, VarType};

/// Set when stdout is closed (`sva eval … | head -1`): the rest of the output is dropped, the exit status stays the
/// evaluation's (println! would panic there).
static STDOUT_GONE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn write_out(args: std::fmt::Arguments, newline: bool) {
    use std::io::Write;
    use std::sync::atomic::Ordering::Relaxed;
    if STDOUT_GONE.load(Relaxed) {
        return;
    }
    let mut o = std::io::stdout().lock();
    let r = o.write_fmt(args).and_then(|_| if newline { o.write_all(b"\n") } else { Ok(()) });
    if r.is_err() {
        STDOUT_GONE.store(true, Relaxed);
    }
}

macro_rules! outln {
    () => { write_out(format_args!(""), true) };
    ($($t:tt)*) => { write_out(format_args!($($t)*), true) };
}
macro_rules! out {
    ($($t:tt)*) => { write_out(format_args!($($t)*), false) };
}

const USAGE: &str = "usage: sva parse [--json] [--expand] [-D NAME[=VALUE]] FILE...
       sva eval --waves DUMP [--scope tb.dut] --sva FILE [--sva FILE ...] [FILE ...] [--assert NAME ...]
                [--from TIME] [--to TIME] [--out results.json] [--json] [--attempts] [--x fail|false] [--vacuous]
                [--no-lane] [--resolve up|scope] [--ignore-prefix i_,o_] [--alias NAME=PATH ...] [-D NAME[=VALUE]]
                [--max-threads N] [--report report.md|.html|.json|.xml] [--junit report.xml] [--max-failures N]
       sva FILE... --waves DUMP [...]          (the same as sva eval)
       sva --waves DUMP --info
       sva vcd DUMP [--out FILE.vcd]          (an FST as VCD text, enum tables included, as fst2vcd -e writes it)
       sva fst DUMP.vcd [--out FILE.fst]      (a VCD as an FST, by default DUMP.fst; enum tables and tb.types.json's FSM states kept)
       sva report [--title T] [--md F] [--junit F] [--html F] [--json F] [--max-failures N] RESULTS.json...   (- for stdout)
TIME is a number with a unit (100ns, 2.5us; ps without one). --alias: a shown name of a config (the page's alias) for
the variable at PATH. --report: .md, .html, .xml (JUnit), .json (the results with the meta, as a page's report.json;
sva report --json writes the summary). --max-failures: failures listed per assertion in the texts (default 20, 0 all).
Exit status: 0 everything evaluated passed; 1 a failure or an attempt without verdict (capped, the thread limit:
--max-threads, default 256); 2 nothing checked as asked (usage, syntax error, a signal not in the dump, no assertion,
a file that does not read).";

#[derive(Default)]
struct Args {
    files: Vec<String>,
    waves: String,
    scope: String,
    asserts: Vec<String>,
    from: Option<u64>,
    to: Option<u64>,
    out: Option<String>,
    json: bool,
    attempts: bool,
    info: bool,
    opt: Options,
    defines: Vec<String>,
    /// --resolve scope: names only under --scope (the clock also above it); default: every name also above it
    strict: bool,
    report: Option<String>,
    junit: Option<String>,
    /// --ignore-prefix: a name also resolves to the variable whose name without these prefixes is the same
    prefixes: Vec<String>,
    /// --alias NAME=PATH: the shown name of the variable at PATH (a config's "alias", as the page has it)
    aliases: BTreeMap<String, String>,
    max_failures: Option<u64>,
}

/// `100ns`, `2.5us`, `40` (ps) -> ps.
fn time(s: &str) -> Result<u64, String> {
    let k = s.find(|c: char| c.is_ascii_alphabetic()).unwrap_or(s.len());
    let (n, unit) = s.split_at(k);
    let n: f64 = n.trim().parse().map_err(|_| format!("'{s}' is not a time"))?;
    if !n.is_finite() || n < 0.0 {
        return Err(format!("'{s}': a time is a number of 0 or more"));
    }
    let f = match unit.trim() {
        "fs" => 1e-3,
        "" | "ps" => 1.0,
        "ns" => 1e3,
        "us" => 1e6,
        "ms" => 1e9,
        "s" => 1e12,
        u => return Err(format!("'{u}' is not a time unit (fs ps ns us ms s)")),
    };
    Ok((n * f).round() as u64)
}

fn count(v: &str, what: &str) -> Result<u64, String> {
    v.parse().map_err(|_| format!("{what} is a number, not '{v}'"))
}

fn args(argv: &[String]) -> Result<Args, String> {
    let mut a = Args::default();
    let mut it = argv.iter();
    let next = |it: &mut std::slice::Iter<String>, what: &str| it.next().cloned().ok_or(format!("{what} needs a value\n{USAGE}"));
    while let Some(x) = it.next() {
        match x.as_str() {
            "--waves" => a.waves = next(&mut it, "--waves")?,
            "--scope" => a.scope = next(&mut it, "--scope")?,
            "--sva" => a.files.push(next(&mut it, "--sva")?),
            "--assert" => a.asserts.push(next(&mut it, "--assert")?),
            "--from" => a.from = Some(time(&next(&mut it, "--from")?)?),
            "--to" => a.to = Some(time(&next(&mut it, "--to")?)?),
            "--out" => a.out = Some(next(&mut it, "--out")?),
            "--report" => a.report = Some(next(&mut it, "--report")?),
            "--ignore-prefix" => {
                a.prefixes = next(&mut it, "--ignore-prefix")?.split(',').map(|p| p.trim().to_string()).filter(|p| !p.is_empty()).collect();
                a.prefixes.sort_by_key(|p| std::cmp::Reverse(p.len()));
            }
            "--junit" => a.junit = Some(next(&mut it, "--junit")?),
            "--alias" => {
                let v = next(&mut it, "--alias")?;
                let (n, p) = v.split_once('=').ok_or(format!("--alias is NAME=PATH, not '{v}'"))?;
                a.aliases.insert(p.trim().to_string(), n.trim().to_string());
            }
            "--max-threads" => a.opt.max_threads = count(&next(&mut it, "--max-threads")?, "--max-threads")?.max(1) as usize,
            "--max-failures" => a.max_failures = Some(count(&next(&mut it, "--max-failures")?, "--max-failures")?),
            "--x" => {
                a.opt.x = match next(&mut it, "--x")?.as_str() {
                    "fail" => XMode::Fail,
                    "false" => XMode::False,
                    v => return Err(format!("--x is fail or false, not '{v}'")),
                }
            }
            "--json" => a.json = true,
            "--attempts" => a.attempts = true,
            "--vacuous" => a.opt.vacuous = true,
            "--no-lane" => a.opt.lane = false,
            "--resolve" => {
                a.strict = match next(&mut it, "--resolve")?.as_str() {
                    "up" => false,
                    "scope" => true,
                    v => return Err(format!("--resolve is up or scope, not '{v}'")),
                }
            }
            "--info" => a.info = true,
            "-D" => a.defines.push(next(&mut it, "-D")?),
            d if d.starts_with("-D") => a.defines.push(d[2..].to_string()),
            "-h" | "--help" => return Err(USAGE.into()),
            s if s.starts_with('-') => return Err(format!("unknown option {s}\n{USAGE}")),
            s => a.files.push(s.into()),
        }
    }
    if a.waves.is_empty() || (a.files.is_empty() && !a.info) {
        return Err(USAGE.into());
    }
    if let (Some(f), Some(t)) = (a.from, a.to) {
        if t < f {
            return Err(format!("--to {} is before --from {}: nothing to check", ns(t), ns(f)));
        }
    }
    Ok(a)
}

/// `sva parse`: every file in one compilation unit, the description (or JSON) of each; exit 1 when a file has errors.
fn parse_cmd(args: &[String]) -> ExitCode {
    let (mut json, mut expand, mut files, mut unit) = (false, false, Vec::new(), Unit::new());
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--json" => json = true,
            "--expand" => expand = true,
            "-h" | "--help" => {
                outln!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            "-D" => match it.next() {
                Some(d) => define(&mut unit, d),
                None => {
                    eprintln!("-D needs NAME[=VALUE]\n{USAGE}");
                    return ExitCode::from(2);
                }
            },
            d if d.starts_with("-D") => define(&mut unit, &d[2..]),
            s if s.starts_with('-') => {
                eprintln!("unknown option {s}\n{USAGE}");
                return ExitCode::from(2);
            }
            f => files.push(f.to_string()),
        }
    }
    if files.is_empty() {
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    }
    let mut failed = false;
    let mut out = Vec::new();
    for f in &files {
        let src = match std::fs::read_to_string(f) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("sva: {f}: {e}");
                return ExitCode::from(2);
            }
        };
        let p = unit.parse(&src);
        failed |= !p.errors.is_empty();
        if json {
            let mut v = serde_json::to_value(&p).unwrap();
            v.as_object_mut().unwrap().insert("file".into(), f.clone().into());
            out.push(v);
        } else {
            out!("{}", describe(&p, &src, f, expand));
        }
    }
    if json {
        outln!("{}", serde_json::to_string_pretty(&serde_json::json!({ "files": out })).unwrap());
    }
    if failed { ExitCode::from(1) } else { ExitCode::SUCCESS }
}

fn define(unit: &mut Unit, d: &str) {
    let (n, v) = d.split_once('=').unwrap_or((d, ""));
    unit.define(n, v);
}

fn walk(h: &Hierarchy, s: wellen::ScopeRef, depth: usize) {
    let sc = &h[s];
    outln!("{}{} ({:?})", "  ".repeat(depth), sc.name(h), sc.scope_type());
    for v in sc.vars(h) {
        let var = &h[v];
        let en = var.enum_type(h).map(|(n, vals)| format!("  enum {n}: {}", vals.iter().map(|(k, v)| format!("{k}={v}")).collect::<Vec<_>>().join(" ")));
        outln!("{}{} [{}] {:?}{}", "  ".repeat(depth + 1), var.name(h), var.length(h).map_or("?".into(), |l| l.to_string()), var.var_type(), en.unwrap_or_default());
    }
    for c in sc.scopes(h) {
        walk(h, c, depth + 1);
    }
}

/// The parts of a hierarchical name: split at the dots, but not inside a select (`a[1.2]`) nor in an escaped
/// identifier (`\esc.x`, to the end: a dump drops the space that ends it).
fn segs(p: &str) -> Vec<&str> {
    let (mut out, mut from, mut depth) = (Vec::new(), 0, 0i32);
    for (i, c) in p.char_indices() {
        match c {
            '\\' if i == from => break,
            '[' => depth += 1,
            ']' => depth -= 1,
            '.' if depth == 0 => {
                out.push(&p[from..i]);
                from = i + 1;
            }
            _ => {}
        }
    }
    out.push(&p[from..]);
    out.retain(|x| !x.is_empty());
    out
}

fn strip<'a>(n: &'a str, pfx: &[String]) -> &'a str {
    pfx.iter().find(|p| n.starts_with(p.as_str()) && n.len() > p.len()).map_or(n, |p| &n[p.len()..])
}

/// What a name resolved to: a variable, or several equal ones (an ambiguous match without the prefixes).
enum Found {
    Var(VarRef),
    Many(Vec<String>),
}

/// `name` (maybe `u_core.busy`) under `scope`, by the rule of docs/sva/ENGINE.md *Name resolution*: the variable of
/// that name, else the one shown under that name (`aliases`: full path -> shown name), else the one whose name (or
/// shown name) without the ignored prefixes is the same — when that is several, it is ambiguous; else (`up`) the same
/// in each scope above it, nearest first, up to the top.
fn lookup(h: &Hierarchy, scope: &str, name: &str, up: bool, pfx: &[String], aliases: &BTreeMap<String, String>) -> Option<Found> {
    let sc: Vec<&str> = segs(scope);
    (if up { 0 } else { sc.len() }..=sc.len()).rev().find_map(|k| {
        let full: Vec<&str> = sc[..k].iter().copied().chain(segs(name)).collect();
        let (leaf, path) = full.split_last()?;
        if let Some(v) = h.lookup_var(path, leaf) {
            return Some(Found::Var(v));
        }
        if pfx.is_empty() && aliases.is_empty() {
            return None;
        }
        let vars: Vec<VarRef> = if path.is_empty() { h.vars().collect() } else { h[h.lookup_scope(path)?].vars(h).collect() };
        let shown = |v: &VarRef| aliases.get(&h[*v].full_name(h)).map(String::as_str);
        if let Some(v) = vars.iter().find(|v| shown(v) == Some(*leaf)) {
            return Some(Found::Var(*v));
        }
        if pfx.is_empty() {
            return None;
        }
        let b = strip(leaf, pfx);
        let hits: Vec<VarRef> = vars.into_iter().filter(|v| strip(h[*v].name(h), pfx) == b || shown(v).is_some_and(|n| strip(n, pfx) == b)).collect();
        match hits.len() {
            0 => None,
            1 => Some(Found::Var(hits[0])),
            _ => Some(Found::Many(hits.iter().map(|v| h[*v].full_name(h)).collect())),
        }
    })
}

/// A value of the dump as a 4-state value: the low 64 bits; nine-valued `h` / `l` are 1 / 0, the rest unknown.
fn value(v: wellen::SignalValueRef) -> V {
    match v.to_bit_string() {
        Some(b) if !b.is_empty() => V::parse(&b[b.len().saturating_sub(64)..]).map_or(V::unknown(64), |x| x.0),
        _ => V::unknown(64),
    }
}

/// The values of one signal just before each edge (x before its first value).
fn sample(w: &simple::Waveform, s: SignalRef, edges: &[TimeTableIdx], width: u32, two_state: bool) -> Column {
    let sig = w.get_signal(s).unwrap();
    let mut it = sig.iter_changes().peekable();
    let mut cur = if two_state { V::known(0) } else { V::unknown(64) };
    let mask = if width >= 64 { u64::MAX } else { (1u64 << width) - 1 };
    let mut vals = Vec::with_capacity(edges.len());
    for &ti in edges {
        while let Some((t, v)) = it.peek() {
            if *t >= ti {
                break;
            }
            cur = value(*v);
            it.next();
        }
        vals.push(V::new(cur.v & mask, cur.x & mask));
    }
    let mut c = Column::new(width, &vals);
    c.two_state = two_state;
    c
}

/// The level of a clock bit: 0, 1, z, or x for anything else (nine-valued `h` / `l` are 1 / 0).
fn level(v: wellen::SignalValueRef) -> char {
    match v.to_bit_string().and_then(|s| s.chars().last()) {
        Some('1' | 'h' | 'H') => '1',
        Some('0' | 'l' | 'L') => '0',
        Some('z' | 'Z') => 'z',
        _ => 'x',
    }
}

/// Is `p` -> `b` an edge of that kind (IEEE 1800-2017 9.4.2: posedge 0->1, 0->x, 0->z, x->1, z->1; negedge the mirror)?
fn is_edge(p: char, b: char, edge: &str) -> bool {
    let rise = (p == '0' && b != '0') || (matches!(p, 'x' | 'z') && b == '1');
    let fall = (p == '1' && b != '1') || (matches!(p, 'x' | 'z') && b == '0');
    match edge {
        "posedge" => rise,
        "negedge" => fall,
        _ => rise || fall,
    }
}

/// The time-table indexes of the edges of a clock: one per time step, its last value against the step before (a glitch
/// written in one time step, 1 0 1, is no edge; the first value is none).
fn edges(w: &simple::Waveform, clk: SignalRef, edge: &str) -> Vec<TimeTableIdx> {
    let sig = w.get_signal(clk).unwrap();
    let mut out = Vec::new();
    let mut prev: Option<char> = None;
    let mut step: Option<(TimeTableIdx, char)> = None;
    let mut close = |s: Option<(TimeTableIdx, char)>, prev: &mut Option<char>| {
        if let Some((ti, b)) = s {
            if prev.is_some_and(|p| is_edge(p, b, edge)) {
                out.push(ti);
            }
            *prev = Some(b);
        }
    };
    for (ti, v) in sig.iter_changes() {
        if step.is_some_and(|(t, _)| t != ti) {
            close(step, &mut prev);
        }
        step = Some((ti, level(v)));
    }
    close(step, &mut prev);
    out
}

fn ns(ps: u64) -> String {
    time_text(ps, "ps")
}

fn summary(o: &Outcome, times: &[u64], width: usize) -> String {
    let s = &o.stats;
    let at = |c: usize| times.get(c).map_or(String::new(), |t| format!(" ({})", ns(*t)));
    let head = format!("{:<width$} {:<6}", o.name, o.kind.word());
    if o.kind == Kind::Cover {
        let first = o.attempts.first().map_or(String::new(), |a| format!(" · first at cycle {}{}", a.end, at(a.end)));
        let m = s.matches.unwrap_or(s.pass);
        return format!("{head} {m} match{} in {} attempts{first}", if m == 1 { "" } else { "es" }, s.attempts);
    }
    let fail = o.first_fail().map_or(String::new(), |f| {
        let c = f.failed_at.unwrap_or(f.end);
        format!(" · first fail at cycle {c}{}: {}", at(c), f.note.as_deref().unwrap_or(""))
    });
    let capped = if s.capped > 0 { format!(", {} capped (thread limit: no verdict)", s.capped) } else { String::new() };
    format!("{head} {} attempts: {} pass, {} fail, {} vacuous, {} active, {} disabled{capped}{fail}", s.attempts, s.pass, s.fail, s.vacuous, s.active, s.disabled)
}

fn eval_cmd(a: Args) -> ExitCode {
    let t0 = std::time::Instant::now();
    if let Err(e) = std::fs::File::open(&a.waves) {   // a one-line message with the path (wellen's error does not name the file)
        eprintln!("sva: {}: {e}", a.waves);
        return ExitCode::from(2);
    }
    reading(&a.waves);
    // a VCD whose vectors are glued to their codes (Questa 2023's integers): wellen stops at one, its FST is read instead
    let glued = match fst::glued_fst(&a.waves) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("sva: {e}");
            return ExitCode::from(2);
        }
    };
    if glued.is_some() {
        eprintln!("sva: {}: values written without b, glued to their codes (Questa 2023's integers): read through an FST of it", a.waves);
    }
    let src = glued.as_ref().map_or(a.waves.clone(), |g| g.0.to_string_lossy().into_owned());
    let mut w = match simple::read(&src) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("sva: {}: {e}", a.waves);
            return ExitCode::from(2);
        }
    };
    let h = w.hierarchy();
    if a.info {
        outln!("{:?}, timescale {:?}, {} time points", h.file_format(), h.timescale(), w.time_table().len());
        for s in h.scopes() {
            walk(h, s, 0);
        }
        return ExitCode::SUCCESS;
    }
    // the files are one compilation unit (a package first, then the assertions that import it)
    let mut unit = Unit::new();
    for d in &a.defines {
        define(&mut unit, d);
    }
    let mut asserts: Vec<(Assertion, String)> = Vec::new();
    let mut bad = false;
    for file in &a.files {
        let src = match std::fs::read_to_string(file) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("sva: {file}: {e}");
                return ExitCode::from(2);
            }
        };
        let parsed = unit.parse(&src);
        for x in &parsed.warnings {
            eprint!("{}", diagnostic(x, "warning", &src, file));
        }
        for e in &parsed.errors {
            eprint!("{}", diagnostic(e, "error", &src, file));
        }
        bad |= !parsed.errors.is_empty();
        asserts.extend(parsed.assertions.into_iter().map(|x| (x, file.clone())));
    }
    if bad {
        return ExitCode::from(2);
    }
    for n in &a.asserts {
        if !asserts.iter().any(|(x, _)| &x.label == n) {
            eprintln!("sva: no assertion '{n}' in {}", a.files.join(" "));
            return ExitCode::from(2);
        }
    }
    asserts.retain(|(x, _)| a.asserts.is_empty() || a.asserts.contains(&x.label));
    if asserts.is_empty() {
        eprintln!("sva: no assertion in {}: nothing to check", a.files.join(" "));
        return ExitCode::from(2);
    }
    let ps = h.timescale().and_then(|t| t.unit.to_exponent().map(|e| t.factor as f64 * 10f64.powi(e as i32 + 12))).unwrap_or(1.0);
    if ps < 1.0 {
        eprintln!("sva: the dump's timescale is finer than 1 ps: the cycles are its edges, their times are rounded to ps in the results");
    }
    let read_s = t0.elapsed().as_secs_f64();

    // resolve the signals; group the assertions by clock
    let mut missing_any = false;
    let mut skipped: Vec<(usize, Vec<String>)> = Vec::new();
    let mut groups: Vec<((VarRef, String), Vec<usize>)> = Vec::new();
    let mut paths: Vec<BTreeMap<String, (String, VarRef)>> = Vec::new();
    for (k, (x, _)) in asserts.iter().enumerate() {
        let mut m = BTreeMap::new();
        let mut missing = Vec::new();
        for s in &x.signals {
            match lookup(h, &a.scope, &s.name, !a.strict || s.name == x.clock.signal, &a.prefixes, &a.aliases) {
                Some(Found::Var(v)) if s.width.is_some_and(|w| h[v].length(h).is_some_and(|l| l < w)) => {
                    missing.push(format!("{} (a select needs {} bits, {} has {})", s.name, s.width.unwrap(), h[v].full_name(h), h[v].length(h).unwrap_or(0)));
                }
                Some(Found::Var(v)) => {
                    m.insert(s.name.clone(), (h[v].full_name(h), v));
                }
                Some(Found::Many(l)) => missing.push(format!("{} (ambiguous: {})", s.name, l.join(" or "))),
                None => missing.push(s.name.clone()),
            }
        }
        paths.push(m);
        if !missing.is_empty() {
            let at = if a.scope.is_empty() { String::new() } else { format!(" in scope '{}'", a.scope) };
            eprintln!("sva: {}: no {}{at} (not evaluated)", x.label, missing.join(", "));
            missing_any = true;
            skipped.push((k, missing));
            continue;
        }
        let clk = (paths[k][&x.clock.signal].1, x.clock.edge.clone());
        match groups.iter_mut().find(|g| h[g.0 .0].signal_ref() == h[clk.0].signal_ref() && g.0 .1 == clk.1) {
            Some(g) => g.1.push(k),
            None => groups.push((clk, vec![k])),
        }
    }

    let mut doc = Results { clock: String::new(), unit: "ps".into(), cycles: Vec::new(), assertions: Vec::new() };
    let mut outs: Vec<(usize, Outcome, Vec<u64>)> = Vec::new();
    for (gi, ((clk, edge), members)) in groups.iter().enumerate() {
        let h = w.hierarchy();
        let mut refs: Vec<(String, VarRef)> = Vec::new();
        for &k in members {
            for (name, (_, v)) in &paths[k] {
                if !refs.iter().any(|r| &r.0 == name) {
                    refs.push((name.clone(), *v));
                }
            }
        }
        let sigs: Vec<SignalRef> = refs.iter().map(|r| h[r.1].signal_ref()).chain([h[*clk].signal_ref()]).collect();
        let info: Vec<(u32, bool)> = refs.iter().map(|r| {
            let v = &h[r.1];
            let two = matches!(v.var_type(), VarType::Bit | VarType::Int | VarType::ShortInt | VarType::LongInt | VarType::Byte | VarType::Boolean);
            (v.length(h).unwrap_or(1).clamp(1, 64), two)
        }).collect();
        let clk_name = h[*clk].full_name(h);
        let clk_sig = h[*clk].signal_ref();
        let wide: Vec<(String, u32)> = refs.iter().filter_map(|r| h[r.1].length(h).filter(|l| *l > 64).map(|l| (r.0.clone(), l))).collect();
        w.load_signals(&sigs);
        let ed = edges(&w, clk_sig, edge);
        let times: Vec<u64> = ed.iter().map(|&ti| (w.time_table()[ti as usize] as f64 * ps).round() as u64).collect();
        // nothing to check is not a pass: no edge of the clock, or a window after the last one (exit 2)
        if ed.is_empty() {
            eprintln!("sva: {clk_name} has no {edge} in the dump: {} not evaluated", members.iter().map(|&k| asserts[k].0.label.as_str()).collect::<Vec<_>>().join(", "));
            bad = true;
        } else if a.from.is_some_and(|f| f > times[times.len() - 1]) {
            eprintln!("sva: --from {} is after the last {edge} of {clk_name} ({}): nothing to check", ns(a.from.unwrap()), ns(times[times.len() - 1]));
            bad = true;
        }
        let mut tr = Trace { cycles: ed.len(), times: times.clone(), unit: Some("ps".into()), ..Default::default() };
        for ((name, _), (sig, (width, two))) in refs.iter().zip(sigs.iter().zip(&info)) {
            tr.signals.insert(name.clone(), sample(&w, *sig, &ed, *width, *two));
        }
        for (name, l) in wide {
            eprintln!("sva: {name} is {l} bits wide: its low 64 bits are evaluated");
        }
        let mut opt = a.opt.clone();
        opt.from = a.from.map_or(0, |f| times.partition_point(|t| *t < f));
        opt.to = a.to.map(|t| times.partition_point(|x| *x <= t));
        // the cycles of the window (the lane has as many): an edge after --to is not one of them
        let shown = times[..opt.to.unwrap_or(times.len()).min(times.len())].to_vec();
        if gi == 0 {
            doc.clock = clk_name.clone();
            doc.cycles = shown.clone();
        }
        for &k in members {
            let (x, file) = &asserts[k];
            match evaluate(x, &tr, &opt) {
                Ok(mut o) => {
                    o.file = Some(file.clone());
                    o.scope = (!a.scope.is_empty()).then(|| a.scope.clone());
                    o.signals = paths[k].iter().map(|(n, (p, _))| (n.clone(), p.clone())).collect();
                    if gi > 0 {
                        o.clock = Some(clk_name.clone());
                        o.cycles = Some(shown.clone());
                    }
                    outs.push((k, o, times.clone()));
                }
                Err(e) => {
                    eprintln!("sva: {file}:{}:{}: {}", e.line, e.col, e.msg);
                    bad = true;
                }
            }
        }
    }
    outs.sort_by_key(|o| o.0);
    let width = outs.iter().map(|o| o.1.name.len()).max().unwrap_or(0);
    let mut failed = false;
    for (_, o, times) in &outs {
        // a failure of an assert / assume, or an attempt without verdict (capped) of any kind, a cover too: exit 1
        failed |= (o.kind != Kind::Cover && o.stats.fail > 0) || o.stats.capped > 0;
        if !a.json {
            outln!("{}", summary(o, times, width));
            if a.attempts {
                for x in &o.attempts {
                    let steps: Vec<String> = x.trace.iter().map(|s| format!("{}@{}", s.id, s.cycle)).collect();
                    let note = x.note.as_ref().map_or(String::new(), |n| format!("  -- {n}"));
                    let t = times.get(x.start).map_or(String::new(), |t| format!(" ({})", ns(*t)));
                    outln!("  @{}..{}{t} {:?} [{}]{note}", x.start, x.end, x.result, steps.join(" "));
                }
            }
        }
    }
    // the ones not evaluated are in the document too, with their missing signals (no counts)
    for (k, missing) in skipped {
        let (x, file) = &asserts[k];
        if let Ok(mut o) = evaluate(x, &Trace::default(), &a.opt) {
            o.file = Some(file.clone());
            o.scope = (!a.scope.is_empty()).then(|| a.scope.clone());
            o.signals = paths[k].iter().map(|(n, (p, _))| (n.clone(), p.clone())).collect();
            o.missing = missing;
            o.lane = None;
            outs.push((k, o, Vec::new()));
        }
    }
    outs.sort_by_key(|o| o.0);
    doc.assertions = outs.into_iter().map(|o| o.1).collect();
    if a.json {
        outln!("{}", serde_json::to_string_pretty(&doc).unwrap());
    }
    if let Some(f) = &a.out {
        if let Err(e) = std::fs::write(f, serde_json::to_string(&doc).unwrap()) {
            eprintln!("sva: {f}: {e}");
            return ExitCode::from(2);
        }
    }
    if a.report.is_some() || a.junit.is_some() {
        let meta = serde_json::json!({ "title": "Assertions", "dump": a.waves, "scope": a.scope, "tool": format!("sva eval {}", version()), "date": today() });
        let input = serde_json::json!({ "meta": meta, "results": [serde_json::to_value(&doc).unwrap()], "max_failures": a.max_failures });
        let sum = summarize(&input);
        for (f, fmt) in [(&a.report, None), (&a.junit, Some("junit"))] {
            if let Some(f) = f {
                // .json: the results with the meta, as a page's report.json (sva report reads it back)
                let r = if fmt.is_none() && f.ends_with(".json") { write_text(&serde_json::to_string_pretty(&input).unwrap(), f) } else { write_report(&sum, f, fmt) };
                if let Err(e) = r {
                    eprintln!("sva: {f}: {e}");
                    return ExitCode::from(2);
                }
            }
        }
    }
    eprintln!("sva: {} assertions over {} cycles; read {:.3} s, total {:.3} s", doc.assertions.len(), doc.cycles.len(), read_s, t0.elapsed().as_secs_f64());
    if missing_any || bad {
        ExitCode::from(2)
    } else if failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

/// The date (UTC) as yyyy-mm-dd, for the report's meta.
/// The project's version (the file VERSION at the top of the repository; the crates keep their own semver).
fn version() -> &'static str {
    include_str!("../../../VERSION").trim()
}

fn today() -> String {
    let d = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |x| x.as_secs() / 86400) as i64;
    // days since 1970-01-01 -> civil date (H. Hinnant)
    let z = d + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    format!("{:04}-{month:02}-{day:02}", yoe + era * 400 + (month <= 2) as i64)
}

/// A report file: the format from `fmt`, else from the extension (.md, .html, .xml = JUnit, else the summary JSON);
/// `-` is stdout.
fn write_report(sum: &serde_json::Value, f: &str, fmt: Option<&str>) -> std::io::Result<()> {
    let ext = fmt.unwrap_or_else(|| f.rsplit('.').next().unwrap_or(""));
    let text = match ext {
        "md" => report_markdown(sum),
        "html" | "htm" => report_html(sum),
        "junit" | "xml" => report_junit(sum),
        _ => serde_json::to_string_pretty(sum).unwrap(),
    };
    write_text(&text, f)
}
fn write_text(text: &str, f: &str) -> std::io::Result<()> {
    if f == "-" {
        out!("{text}");
        Ok(())
    } else {
        std::fs::write(f, text)
    }
}

/// `sva report`: results documents (sva eval --out, a page's report.json) -> Markdown / JUnit / HTML / summary JSON.
fn report_cmd(argv: &[String]) -> ExitCode {
    let (mut outs, mut ins, mut title, mut max) = (Vec::new(), Vec::new(), None, None);
    let mut it = argv.iter();
    while let Some(x) = it.next() {
        match x.as_str() {
            "--md" | "--junit" | "--html" | "--json" => match it.next() {
                Some(f) => outs.push((f.clone(), &x[2..])),
                None => {
                    eprintln!("{x} needs a file\n{USAGE}");
                    return ExitCode::from(2);
                }
            },
            "--title" => title = it.next().cloned(),
            "-h" | "--help" => {
                outln!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            "--max-failures" => match it.next().map(|v| count(v, "--max-failures")) {
                Some(Ok(n)) => max = Some(n),
                Some(Err(e)) => {
                    eprintln!("{e}");
                    return ExitCode::from(2);
                }
                None => {
                    eprintln!("--max-failures needs a number\n{USAGE}");
                    return ExitCode::from(2);
                }
            },
            s if s.starts_with('-') && s != "-" => {
                eprintln!("unknown option {s}\n{USAGE}");
                return ExitCode::from(2);
            }
            s => ins.push(s.to_string()),
        }
    }
    if ins.is_empty() {
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    }
    let (mut results, mut sources, mut dumps) = (Vec::new(), Vec::new(), Vec::<String>::new());
    let mut meta = serde_json::json!({ "title": "Assertions", "tool": format!("sva report {}", version()), "date": today() });
    let mut titled = false;
    for f in &ins {
        let v: serde_json::Value = match std::fs::read_to_string(f).map_err(|e| e.to_string()).and_then(|t| serde_json::from_str(&t).map_err(|e| e.to_string())) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("sva: {f}: {e}");
                return ExitCode::from(2);
            }
        };
        // a page's report.json ({"meta", "results"}) or one results document; the meta of the first file that has one
        // (the dumps of all of them); every document remembers its file
        let (docs, m) = match v.get("results") {
            Some(_) => (v.clone(), v.get("meta").cloned()),
            None => (serde_json::json!({ "results": [v] }), None),
        };
        if let Err(e) = check_report_input(&docs) {
            eprintln!("sva: {f}: {e}");
            return ExitCode::from(2);
        }
        for d in docs["results"].as_array().unwrap() {
            results.push(d.clone());
            sources.push(f.clone());
        }
        if let Some(m) = m.as_ref().and_then(|m| m.as_object()) {
            if let Some(d) = m.get("dump").and_then(|d| d.as_str()) {
                if !dumps.iter().any(|x| x == d) {
                    dumps.push(d.to_string());
                }
            }
            if !titled {
                titled = true;
                for (k, x) in m {
                    meta[k] = x.clone();
                }
            }
        }
    }
    if let Some(t) = title {
        meta["title"] = t.into();
    }
    if dumps.len() > 1 {
        meta["dump"] = dumps.join(", ").into();
    }
    let several = ins.len() > 1;
    let sum = summarize(&serde_json::json!({ "meta": meta, "results": results, "sources": if several { sources } else { Vec::new() }, "max_failures": max }));
    if outs.is_empty() {
        outs.push(("-".into(), "md"));
    }
    for (f, fmt) in &outs {
        if let Err(e) = write_report(&sum, f, Some(fmt)) {
            eprintln!("sva: {f}: {e}");
            return ExitCode::from(2);
        }
    }
    let t = &sum["totals"];
    let n = |k: &str| t[k].as_u64().unwrap_or(0);
    if n("evaluated") < n("assertions") || n("assertions") == 0 {
        ExitCode::from(2) // not evaluated (missing signals), or nothing at all
    } else if n("fail") > 0 || n("capped") > 0 {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

/// The dump being read, for the message of a panic in its reader.
static READING: std::sync::Mutex<String> = std::sync::Mutex::new(String::new());

/// `path` is the dump read from now on: a panic of its reader (wellen, fst-reader) is about that file.
pub(crate) fn reading(path: &str) {
    if let Ok(mut r) = READING.lock() {
        path.clone_into(&mut r);
    }
}

fn main() -> ExitCode {
    // a panic is a bug of the engine: one line that says so and exit 2 ("nothing checked as asked"), not a core dump;
    // one in the dump's reader is a dump it cannot read (a value longer than its variable: wellen asserts), named so
    std::panic::set_hook(Box::new(|info| {
        let dump = READING.lock().map(|r| r.clone()).unwrap_or_default();
        let file = info.location().map_or("", |l| l.file());
        let p = info.payload();
        let msg = p.downcast_ref::<&str>().copied().or_else(|| p.downcast_ref::<String>().map(String::as_str));
        match msg {
            Some(m) if !dump.is_empty() && (file.contains("wellen") || file.contains("fst-reader")) => {
                eprintln!("sva: {dump}: the dump does not read: {}", m.lines().next().unwrap_or(""));
            }
            _ => eprintln!("sva: internal error, please report it with the input that caused it: {info}"),
        }
    }));
    std::panic::catch_unwind(run).unwrap_or(ExitCode::from(2))
}

fn run() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let rest = match argv.first().map(String::as_str) {
        Some("parse") => return parse_cmd(&argv[1..]),
        Some("report") => return report_cmd(&argv[1..]),
        Some("vcd") => return vcd::vcd_cmd(&argv[1..]),
        Some("fst") => return fst::fst_cmd(&argv[1..]),
        Some("eval") => &argv[1..],
        _ => &argv[..],
    };
    match args(rest) {
        Ok(a) => eval_cmd(a),
        Err(e) => {
            if e == USAGE && rest.iter().any(|x| x == "-h" || x == "--help") {
                outln!("{e}");
                return ExitCode::SUCCESS;
            }
            eprintln!("{e}");
            ExitCode::from(2)
        }
    }
}
