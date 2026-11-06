//! `sva runs`: the runs you keep of a dump, to compare the dump of now with them over a window. A run is kept by hand
//! (`sva runs keep`, the Runs panel of VS Code, wave_runs of the MCP server): the dump as an FST (a VCD converted as
//! `sva fst` does it, its types file beside it read; an FST copied) in a directory of runs, `.wavelens-runs` beside the
//! dump by default, with a name, tags and a comment in its `runs.json`. A directory keep makes (or one named
//! `.wavelens-runs`) ignores itself in git; another one gets a `.gitignore` of the runs' files only, when it has none.
//! `sva runs diff` compares the dump with each run of it (or the ones named) as `sva diff` does, over a window: the
//! dumps streamed, nothing of them held but the values of now and the first difference. A run keeps its test cases too
//! (a name, a window: cocotb's marks beside the dump, `--cases`): `sva runs diff --case NAME` compares the case of the
//! dump of now with that case of each run, wherever it is in the run. `--against RUN` makes a run A (the waves shown in
//! the Runs panel), `--run now` the dump a B; `--page` writes one run's compare in the shape a page takes (`sva diff
//! --page`'s), which the extension hands the viewer as it is.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use serde_json::{json, Value};

macro_rules! outln {
    ($($t:tt)*) => { crate::write_out(format_args!($($t)*), true) };
}

const USAGE: &str = "usage: sva runs [list] [DUMP | DIR] [--dir D] [--all] [--json]
       sva runs keep DUMP [--dir D] [--name N] [--tags T,...] [--comment C] [--cases FILE|-|none] [--json]
       sva runs set RUN [DUMP] [--dir D] [--name N] [--tags T,...] [--comment C] [--cases FILE|-|none] [--json]
       sva runs rm RUN... [DUMP] [--dir D] [--json]
       sva runs path RUN [DUMP] [--dir D]
       sva runs diff DUMP [--dir D] [--against RUN|now] [--run RUN|now ...] [--all] [--from T] [--to T] [--signals PAT,...]
                [--signals-from FILE] [--scope S] [--map A=B ...] [--limit N] [--case NAME [--cases FILE|-]] [--json]
                [--page [--cut-bytes N]] [--quiet]
The runs you keep of a dump, to compare the dump of now with them. keep: the dump (VCD or FST) as an FST in the
directory of runs: --dir, else .wavelens-runs beside DUMP (a dump inside a directory of runs: that one), else
./.wavelens-runs. A directory keep makes, or one named .wavelens-runs, has a .gitignore of * (git leaves it out);
another one without a .gitignore gets one of the runs' files only. A run has a name (default the dump's), tags (a comma
between them) and a comment, in runs.json. A RUN is its number (3 or #3) or its name; for set, rm, path the last word is
DUMP when it is a file or a directory there (rm 1 tb.vcd), else a RUN. list DUMP, diff DUMP: the runs of that dump (by
its file name), --all every run of the directory. set: a new name (not empty), tags (empty: none), comment. rm: the runs
and their FSTs. path: the FST's path (for sva diff, sva vcd). diff: DUMP (A) against each of its runs (B), or the ones of
--run, as sva diff over the window --from … --to (default: the time both cover), the signals of --signals /
--signals-from (- stdin; default every one of DUMP the run has): per run how many signals differ, the first difference,
the signals that differ (--limit, default 20, 0 all), the signals of one side only; a run that does not cover the window
is \"not in this window\". --json: the result as JSON (times in ps). --opt=value is taken as --opt value. keep writes the
dump's time on the disk too (source_mtime); a line of the list says \"of a dump of HH:MM\" when it is not the time kept.
--against RUN: A is that run's FST, not DUMP (now, or none: DUMP), against the other runs of DUMP or the ones of --run (the
run that is A, named in --run, is skipped and said); the window is in A's time. --run now: DUMP itself as a B (with
--against a run only); --run 1,3: a comma list. The JSON's \"against\": {id, name, file}, null for DUMP. --page: the
compare of one run (one --run, or the one run of DUMP; more: usage) as sva diff --page writes it for a page (B's values at
most --cut-bytes, 32 MiB), with run (B's number, 0 for now), a (A's number, null for DUMP) and with --case, case {name,
from, to, offset, shorter} (B's case, shorter: the length compared when the two differ, else null). --quiet: no notes.
Test cases: keep stores the run's cases, a name and a window each: --cases FILE (a marks file of python/wavelens_cocotb.py,
a list [{\"name\", \"from\", \"to\"}], or {\"spans\": [{\"label\", \"from\", \"to\"}]}; times in ps or with a unit; - stdin),
else wavelens.marks.json beside DUMP when it is not older than DUMP by 10 minutes; none: no cases. A case's name is its
name or label without a \"TC<n> \" before it and a \" · …\" after it (the result), the second of one name \"name (2)\". diff
--case NAME: each run over its case NAME against the dump's case NAME (--from/--to: that window of the dump; else its
cases as keep finds them), B's time offset to the run's case, over the shorter of the two; with --against RUN, A's case
NAME is that run's.
TIME is a number with a unit (100ns, 2.5us; ps without one).
Exit status: 0 done (diff: every run equal over the window); 1 diff: a run differs or does not cover the window; 2 usage,
a dump or run that does not read, a run that is not there, a window or signal list that is empty;
2 also when a run has an error row (a case it has not got: the other runs compared, their rows in the output).";

const INDEX: &str = "runs.json";
const DIR: &str = ".wavelens-runs";
const VERSION: u64 = 1;
/// a stem of a run's file at most this long: its name with `N-` before and `.fst.<pid>.part` after stays in NAME_MAX
const STEM: usize = 120;

struct Opt {
    cmd: String,
    pos: Vec<String>,
    dir: Option<String>,
    name: Option<String>,
    tags: Option<Vec<String>>,
    comment: Option<String>,
    json: bool,
    all: bool,
    runs: Vec<String>,
    diff: Vec<String>,
    limit: usize,
    cases: Option<String>,
    case: Option<String>,
    /// diff --against: A is this run (None or "now": DUMP)
    against: Option<String>,
    /// diff --page: the page's compare of one run; --cut-bytes passed to it
    page: bool,
    cut_bytes: Option<usize>,
    quiet: bool,
}

/// The bytes of changes in a block of a run kept from a VCD: the size grows 0.2 %, a late window of a 37 MB VCD is read
/// in 0.15 s, not 1.3 s (`docs/DEVELOPMENT.md`).
const RUN_BLOCK: usize = 1 << 20;

/// The options each verb takes (--json and --dir: every one but path's --json).
fn takes(cmd: &str, opt: &str) -> bool {
    let own: &[&str] = match cmd {
        "list" => &["--all", "--json"],
        "keep" | "set" => &["--name", "--tags", "--tag", "--comment", "--cases", "--json"],
        "rm" => &["--json"],
        "path" => &[],
        _ => &["--run", "--all", "--from", "--to", "--signals", "--signals-from", "--scope", "--map", "--limit", "--case", "--cases", "--json",
               "--against", "--page", "--cut-bytes", "--quiet"],
    };
    opt == "--dir" || own.contains(&opt)
}

fn opts(args: &[String]) -> Result<Opt, String> {
    let mut o = Opt { cmd: String::new(), pos: vec![], dir: None, name: None, tags: None, comment: None, json: false, all: false, runs: vec![],
                      diff: vec![], limit: 20, cases: None, case: None, against: None, page: false, cut_bytes: None, quiet: false };
    // --opt=value as --opt value
    let args: Vec<String> = args.iter().flat_map(|a| match a.split_once('=') {
        Some((k, v)) if k.starts_with("--") && !k.contains(' ') => vec![k.to_string(), v.to_string()],
        _ => vec![a.clone()],
    }).collect();
    let mut i = 0;
    if let Some(c) = args.first().filter(|c| matches!(c.as_str(), "list" | "keep" | "set" | "rm" | "path" | "diff")) {
        o.cmd = c.clone();
        i = 1;
    } else {
        o.cmd = "list".into();
    }
    let val = |i: &mut usize, f: &str| -> Result<String, String> {
        *i += 1;
        args.get(*i).cloned().ok_or_else(|| format!("{f} needs a value\n{USAGE}"))
    };
    while i < args.len() {
        let a = args[i].as_str();
        if a == "-h" || a == "--help" {
            return Err(USAGE.into());
        }
        if a.starts_with("--") && !takes(&o.cmd, a) {
            let known = ["--dir", "--name", "--tags", "--tag", "--comment", "--json", "--all", "--run", "--limit", "--from", "--to", "--signals",
                         "--signals-from", "--scope", "--map", "--case", "--cases", "--against", "--page", "--cut-bytes", "--quiet"];
            return Err(if known.contains(&a) { format!("{a}: not an option of sva runs {}\n{USAGE}", o.cmd) } else { format!("unknown option {a}\n{USAGE}") });
        }
        match a {
            "--dir" => o.dir = Some(val(&mut i, a)?),
            "--name" => o.name = Some(val(&mut i, a)?.trim().to_string()),
            "--tags" | "--tag" => o.tags = Some(val(&mut i, a)?.split(',').map(str::trim).filter(|s| !s.is_empty()).map(String::from).collect()),
            "--comment" => o.comment = Some(val(&mut i, a)?),
            "--json" => o.json = true,
            "--all" => o.all = true,
            "--run" => o.runs.push(val(&mut i, a)?),
            "--limit" => o.limit = crate::count(&val(&mut i, a)?, "--limit")? as usize,
            "--cases" => o.cases = Some(val(&mut i, a)?),
            "--case" => o.case = Some(val(&mut i, a)?),
            "--against" => o.against = Some(val(&mut i, a)?.trim().to_string()),
            "--page" => o.page = true,
            "--cut-bytes" => o.cut_bytes = Some(crate::count(&val(&mut i, a)?, "--cut-bytes")? as usize),
            "--quiet" => o.quiet = true,
            // sva diff's own, passed on as they are
            "--from" | "--to" | "--signals" | "--signals-from" | "--scope" | "--map" => {
                let v = val(&mut i, a)?;
                o.diff.extend([a.to_string(), v]);
            }
            s if s.starts_with('-') && s.len() > 1 => return Err(format!("unknown option {s}\n{USAGE}")),
            s => o.pos.push(s.to_string()),
        }
        i += 1;
    }
    Ok(o)
}

pub fn runs_cmd(args: &[String]) -> ExitCode {
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
    let r = match o.cmd.as_str() {
        "keep" => keep(&o),
        "set" => set(&o),
        "rm" => rm(&o),
        "path" => path_of(&o),
        "diff" => diff(&o),
        _ => list(&o),
    };
    match r {
        Ok(code) => ExitCode::from(code),
        Err(e) => {
            eprintln!("sva: {e}");
            ExitCode::from(2)
        }
    }
}

// ------------------------------------------------------------------------------------------------------------ the list

/// A directory of runs: one named .wavelens-runs, or one with a runs.json.
fn is_runs_dir(p: &Path) -> bool {
    p.file_name().is_some_and(|n| n == DIR) || p.join(INDEX).is_file()
}

/// JSON with comments (VS Code's settings.json): the comments and the commas before `}` `]` left out.
fn jsonc(t: &str) -> Option<Value> {
    let b = t.as_bytes();
    let (mut out, mut i, mut s) = (Vec::with_capacity(b.len()), 0, false);
    while i < b.len() {
        let c = b[i];
        if s {
            out.push(c);
            if c == b'\\' && i + 1 < b.len() {
                out.push(b[i + 1]);
                i += 1;
            } else if c == b'"' {
                s = false;
            }
        } else if c == b'"' {
            s = true;
            out.push(c);
        } else if b[i..].starts_with(b"//") {
            while i < b.len() && b[i] != b'\n' {
                i += 1;
            }
            continue;
        } else if b[i..].starts_with(b"/*") {
            i += 2;
            while i + 1 < b.len() && !b[i..].starts_with(b"*/") {
                i += 1;
            }
            i += 2;
            continue;
        } else if c == b',' && b[i + 1..].iter().find(|x| !x.is_ascii_whitespace()).is_some_and(|x| *x == b'}' || *x == b']') {
            // a trailing comma (comments after it already gone below: rare, then the file does not read)
        } else {
            out.push(c);
        }
        i += 1;
    }
    serde_json::from_slice(&out).ok()
}

/// VS Code's `wavelens.runsDir` of the workspace folder that holds `p` (the nearest `.vscode/settings.json` above it; a
/// relative one from that folder), as the Runs panel takes it: the shell and an agent use the panel's directory. A
/// setting of the user's profile only is VS Code's (it passes --dir).
fn setting_dir(p: &Path) -> Option<PathBuf> {
    let start = std::fs::canonicalize(p).ok()?;
    for folder in start.ancestors().skip(1) {
        let f = folder.join(".vscode").join("settings.json");
        if f.is_file() {
            let v = jsonc(&std::fs::read_to_string(&f).ok()?)?;
            let d = v.get("wavelens.runsDir")?.as_str().filter(|d| !d.trim().is_empty())?;
            let d = Path::new(d.trim());
            return Some(if d.is_absolute() { d.to_path_buf() } else { folder.join(d) });
        }
    }
    None
}

/// The directory of runs: --dir, else the one a dump lies in (a run's FST kept again), else VS Code's `wavelens.runsDir`
/// of the workspace (its .vscode/settings.json), else .wavelens-runs beside the dump (a file) or in it (a directory),
/// else here.
fn dir_of(o: &Opt, dump: Option<&str>) -> PathBuf {
    if let Some(d) = &o.dir {
        return PathBuf::from(d);
    }
    let set = dump.map(Path::new).filter(|p| !(p.is_dir() && is_runs_dir(p)) && !p.parent().is_some_and(|q| !q.as_os_str().is_empty() && is_runs_dir(q)))
        .and_then(setting_dir);
    if let Some(d) = set {
        return d;
    }
    match dump.map(Path::new) {
        Some(p) if p.is_dir() => if is_runs_dir(p) { p.to_path_buf() } else { p.join(DIR) },
        Some(p) => match p.parent().filter(|q| !q.as_os_str().is_empty()) {
            Some(q) if is_runs_dir(q) => q.to_path_buf(),
            Some(q) => q.join(DIR),
            None if is_runs_dir(Path::new(".")) && !Path::new(DIR).exists() => PathBuf::from("."),
            None => PathBuf::from(DIR),
        },
        None => PathBuf::from(DIR),
    }
}

/// set, rm, path: the RUNs and the DUMP (the last word, when there are more than `keys` and it is a file or directory).
fn keys_and_dump(o: &Opt, keys: usize) -> (Vec<String>, Option<String>) {
    let mut pos = o.pos.clone();
    let last_is_path = pos.last().is_some_and(|p| Path::new(p).exists());
    let dump = if pos.len() > keys && last_is_path { pos.pop() } else { None };
    (pos, dump)
}

/// runs.json: {"wavelens": "runs", "version": 1, "next": N, "runs": [...]}; none there: an empty list. Each run is
/// checked: a number, its file a plain file name in the directory (never a path out of it).
fn load(dir: &Path) -> Result<Value, String> {
    let f = dir.join(INDEX);
    let v: Value = match std::fs::read_to_string(&f) {
        Ok(t) => serde_json::from_str(&t).map_err(|e| format!("{}: {e}", f.display()))?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(json!({"wavelens": "runs", "version": VERSION, "next": 1, "runs": []})),
        Err(e) => return Err(format!("{}: {e}", f.display())),
    };
    if v.get("wavelens").and_then(Value::as_str) != Some("runs") || !v["runs"].is_array() {
        return Err(format!("{}: not a list of runs (\"wavelens\": \"runs\")", f.display()));
    }
    if v["version"].as_u64().unwrap_or(VERSION) > VERSION {
        return Err(format!("{}: version {}, written by a newer WaveLens (this one reads {VERSION})", f.display(), v["version"]));
    }
    for (k, r) in v["runs"].as_array().into_iter().flatten().enumerate() {
        let file = r["file"].as_str().unwrap_or("");
        let plain = !file.is_empty() && Path::new(file).file_name().is_some_and(|n| n == file) && file != "." && file != "..";
        if r["id"].as_u64().is_none() || !plain {
            return Err(format!("{}: run {} has {} (a number and a file name in the directory)", f.display(), k + 1,
                               if r["id"].as_u64().is_none() { "no number".to_string() } else { format!("the file {:?}", r["file"]) }));
        }
    }
    Ok(v)
}

/// The list of a directory that must have runs (set, rm, path): none -> "no runs kept in D".
fn load_some(dir: &Path) -> Result<Value, String> {
    if !dir.join(INDEX).is_file() {
        return Err(format!("no runs kept in {} (sva runs keep DUMP)", dir.display()));
    }
    load(dir)
}

/// runs.json written whole beside, then renamed over it: a reader never sees half of it.
fn save(dir: &Path, v: &Value) -> Result<(), String> {
    let f = dir.join(INDEX);
    let part = dir.join(format!("{INDEX}.{}.part", std::process::id()));
    std::fs::write(&part, serde_json::to_string_pretty(v).unwrap_or_default() + "\n").map_err(|e| format!("{}: {e}", part.display()))?;
    std::fs::rename(&part, &f).map_err(|e| format!("{}: {e}", f.display()))
}

/// The parts a keep killed left (`N-x.fst.<pid>.part`, `runs.json.<pid>.part`), older than 10 minutes: removed.
fn sweep(dir: &Path) {
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let old = e.metadata().and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok()).is_some_and(|d| d.as_secs() > 600);
        if old && e.file_name().to_string_lossy().ends_with(".part") {
            let _ = std::fs::remove_file(e.path());
        }
    }
}

/// The list held while it changes: runs.json.lock made new (another run of sva waits for it, up to 30 s; one left by a
/// run killed: older than 10 minutes, taken).
struct Lock(PathBuf);
impl Lock {
    fn take(dir: &Path) -> Result<Lock, String> {
        let p = dir.join(format!("{INDEX}.lock"));
        for _ in 0..300 {
            match std::fs::OpenOptions::new().write(true).create_new(true).open(&p) {
                Ok(_) => return Ok(Lock(p)),
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    let old = std::fs::metadata(&p).and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok()).is_some_and(|d| d.as_secs() > 600);
                    if old {
                        let _ = std::fs::remove_file(&p);
                        continue;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
                Err(e) => return Err(format!("{}: {e}", p.display())),
            }
        }
        Err(format!("{}: another sva holds the list of runs (remove the file if none does)", p.display()))
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

/// A run by its number (3, #3) or its name -> its index in the list.
fn find(list: &Value, key: &str) -> Result<usize, String> {
    let runs = list["runs"].as_array().map_or(&[][..], Vec::as_slice);
    let n = key.strip_prefix('#').unwrap_or(key).parse::<u64>().ok();
    if let Some(i) = n.and_then(|n| runs.iter().position(|r| r["id"].as_u64() == Some(n))) {
        return Ok(i);
    }
    let named: Vec<usize> = runs.iter().enumerate().filter(|(_, r)| r["name"].as_str() == Some(key)).map(|(i, _)| i).collect();
    match named.as_slice() {
        [i] => Ok(*i),
        [] => Err(format!("no run {key} (sva runs lists them)")),
        _ => Err(format!("{} runs named {key}: give its number", named.len())),
    }
}

/// A run's FST in the directory (its file a plain name: load checked it).
fn file_of(dir: &Path, r: &Value) -> PathBuf {
    dir.join(r["file"].as_str().unwrap_or(""))
}

/// Whether a run is of this dump: its file name, or the dump's path as kept.
fn of_dump(r: &Value, dump: &str) -> bool {
    let name = Path::new(dump).file_name().map(|n| n.to_string_lossy().into_owned());
    let full = std::fs::canonicalize(dump).ok().map(|p| p.to_string_lossy().into_owned());
    r["dump"].as_str() == name.as_deref() || (full.is_some() && r["source"].as_str() == full.as_deref())
}

/// The time of now as UTC, ISO 8601 (2026-11-05T13:20:07Z).
fn now_utc() -> String {
    utc_of(std::time::SystemTime::now())
}

/// A time as UTC, ISO 8601 (a file's mtime: the dump's time on the disk, kept as source_mtime).
fn utc_of(t: std::time::SystemTime) -> String {
    let s = match t.duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => d.as_secs() as i64,
        Err(e) => -(e.duration().as_secs() as i64),
    };
    let (days, rem) = (s.div_euclid(86_400), s.rem_euclid(86_400));
    // civil from days (Howard Hinnant)
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", rem / 3600, rem % 3600 / 60, rem % 60)
}

/// An ISO 8601 UTC time as `utc_of` writes it -> seconds since 1970 (None: not that shape).
fn secs_of(t: &str) -> Option<i64> {
    let b = t.as_bytes();
    if b.len() < 19 || b[4] != b'-' || b[7] != b'-' || b[10] != b'T' || b[13] != b':' || b[16] != b':' {
        return None;
    }
    let n = |r: std::ops::Range<usize>| t.get(r)?.parse::<i64>().ok();
    let (y, m, d) = (n(0..4)?, n(5..7)?, n(8..10)?);
    // days from civil (Howard Hinnant)
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    Some((era * 146_097 + doe - 719_468) * 86_400 + n(11..13)? * 3600 + n(14..16)? * 60 + n(17..19)?)
}

fn bytes_text(n: u64) -> String {
    match n {
        n if n >= 1 << 30 => format!("{:.1} GB", n as f64 / (1u64 << 30) as f64),
        n if n >= 1 << 20 => format!("{:.1} MB", n as f64 / (1u64 << 20) as f64),
        n if n >= 1 << 10 => format!("{:.0} kB", n as f64 / 1024.0),
        n => format!("{n} B"),
    }
}

/// A run as a line of the list (and its comment under it).
fn line(r: &Value) -> String {
    let tags = r["tags"].as_array().map(|t| t.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", ")).unwrap_or_default();
    let kept = r["kept"].as_str().unwrap_or("").replace('T', " ");
    let kept = kept.trim_end_matches('Z').get(..16).unwrap_or(&kept);
    // the dump's time on the disk when it is not the time kept (a run kept later than its simulation): HH:MM, the day too
    // when it is another
    let src = r["source_mtime"].as_str().unwrap_or("");
    let of = match (secs_of(r["kept"].as_str().unwrap_or("")), secs_of(src)) {
        (Some(k), Some(m)) if k.abs_diff(m) > 60 => {
            let m = src.replace('T', " ");
            format!(" (of a dump of {})", if m.get(..10) == kept.get(..10) { m.get(11..16) } else { m.get(..16) }.unwrap_or(""))
        }
        _ => String::new(),
    };
    let mut s = format!("#{:<3} {kept}{of}  {}{}  {} ({}, {} … {})", r["id"].as_u64().unwrap_or(0),
                        r["name"].as_str().unwrap_or(""), if tags.is_empty() { String::new() } else { format!("  [{tags}]") },
                        r["dump"].as_str().unwrap_or(""), bytes_text(r["bytes"].as_u64().unwrap_or(0)),
                        crate::ns(r["start"].as_u64().unwrap_or(0)), crate::ns(r["end"].as_u64().unwrap_or(0)));
    let n = r["cases"].as_array().map_or(0, Vec::len);
    if n > 0 {
        s += &format!(", {n} case{}", if n == 1 { "" } else { "s" });
    }
    if let Some(c) = r["comment"].as_str().filter(|c| !c.is_empty()) {
        s += &format!("\n      {}", c.replace('\n', "\n      "));
    }
    s
}

fn list(o: &Opt) -> Result<u8, String> {
    if o.pos.len() > 1 {
        return Err(format!("sva runs list: one dump or directory ({} given)\n{USAGE}", o.pos.len()));
    }
    let arg = o.pos.first().map(String::as_str);
    let dir = dir_of(o, arg);
    let mut v = load(&dir)?;
    v["dir"] = dir.to_string_lossy().into();
    // list DUMP (a file): its runs, the others counted
    let dump = arg.filter(|a| Path::new(a).is_file() && !o.all);
    let mut others = 0;
    if let Some(d) = dump {
        let all = v["runs"].as_array().cloned().unwrap_or_default();
        let (mine, rest): (Vec<Value>, Vec<Value>) = all.into_iter().partition(|r| of_dump(r, d));
        others = rest.len();
        v["runs"] = mine.into();
        v["others"] = others.into();
    }
    if o.json {
        outln!("{}", serde_json::to_string_pretty(&v).unwrap_or_default());
        return Ok(0);
    }
    let runs = v["runs"].as_array().cloned().unwrap_or_default();
    let total: u64 = runs.iter().filter_map(|r| r["bytes"].as_u64()).sum();
    outln!("{}: {} run{}, {}{}", dir.display(), runs.len(), if runs.len() == 1 { "" } else { "s" }, bytes_text(total),
           if others > 0 { format!(" ({others} of other dumps: --all)") } else { String::new() });
    for r in runs.iter().rev() {
        outln!("  {}", line(r));
    }
    Ok(0)
}

// ------------------------------------------------------------------------------------------------------------ test cases

/// The marks file python/wavelens_cocotb.py writes beside the dump (WAVELENS_MARKS: another name, given with --cases).
const MARKS: &str = "wavelens.marks.json";

/// A case's name of a test's name or a span's label: without the number before it (`TC3 `) and the result after it
/// (` · FAIL`), as a page of cocotb's marks labels its spans; the same rule as runs.js caseName.
pub(crate) fn case_name(label: &str) -> String {
    let s = label.split(" \u{b7} ").next().unwrap_or("").trim();
    let s = match s.split_once(' ') {
        Some((tc, rest)) if tc.len() > 2 && tc.starts_with("TC") && tc[2..].bytes().all(|c| c.is_ascii_digit()) => rest.trim(),
        _ => s,
    };
    s.to_string()
}

/// A time of a case: ps as a number, or a text with a unit.
fn case_time(v: &Value) -> Option<u64> {
    match v {
        Value::Number(n) => n.as_u64().or_else(|| n.as_f64().filter(|f| *f >= 0.0).map(|f| f.round() as u64)),
        Value::String(t) => crate::time(t).ok(),
        _ => None,
    }
}

/// The cases of a JSON text: a marks file's tests, a list of {name|label, from, to}, or {"spans": [...]} -> [{name, from,
/// to}] (ps; a case without its end or with an end before its start left out; the second of a name "name (2)").
fn cases_of(text: &str, src: &str) -> Result<Vec<Value>, String> {
    let v: Value = serde_json::from_str(text.trim_start_matches('\u{feff}')).map_err(|e| format!("{src}: not JSON: {e}"))?;
    let items = if v["wavelens"] == "marks" {
        v["tests"].as_array().cloned().unwrap_or_default()
    } else if let Some(a) = v.as_array() {
        a.clone()
    } else if let Some(a) = v["spans"].as_array() {
        a.clone()
    } else {
        return Err(format!("{src}: no cases in it (a marks file, a list [{{\"name\", \"from\", \"to\"}}], or {{\"spans\": [...]}})"));
    };
    let mut out: Vec<Value> = Vec::new();
    for it in &items {
        let label = it["name"].as_str().or_else(|| it["label"].as_str()).unwrap_or("");
        let name = case_name(label);
        let (Some(from), Some(to)) = (case_time(&it["from"]), case_time(&it["to"])) else { continue };
        if name.is_empty() || to < from {
            continue;
        }
        let same = out.iter().filter(|c| c["base"] == name.as_str()).count();
        let shown = if same == 0 { name.clone() } else { format!("{name} ({})", same + 1) };
        out.push(json!({"name": shown, "from": from, "to": to, "base": name}));
    }
    for c in &mut out {
        c.as_object_mut().map(|o| o.remove("base"));
    }
    Ok(out)
}

/// The cases of a dump: --cases (a file, - stdin, none), else the marks beside it when they are not older than it by 10
/// minutes (said on stderr) -> None when there are none to take.
fn cases_for(given: Option<&str>, dump: &str, quiet: bool) -> Result<Option<Vec<Value>>, String> {
    match given {
        Some("none") => return Ok(None),
        Some("-") => {
            let mut t = String::new();
            std::io::Read::read_to_string(&mut std::io::stdin(), &mut t).map_err(|e| format!("stdin: {e}"))?;
            return cases_of(&t, "--cases -").map(Some);
        }
        Some(f) => return cases_of(&std::fs::read_to_string(f).map_err(|e| format!("{f}: {e}"))?, f).map(Some),
        None => {}
    }
    let marks = Path::new(dump).parent().map_or_else(|| PathBuf::from(MARKS), |d| d.join(MARKS));
    let (Ok(mm), Ok(dm)) = (std::fs::metadata(&marks).and_then(|m| m.modified()), std::fs::metadata(dump).and_then(|m| m.modified())) else {
        return Ok(None);
    };
    if dm.duration_since(mm).is_ok_and(|d| d.as_secs() > 600) {
        if !quiet {
            eprintln!("sva: {}: older than {dump} (another run's?): its cases not taken (--cases it)", marks.display());
        }
        return Ok(None);
    }
    let text = std::fs::read_to_string(&marks).map_err(|e| format!("{}: {e}", marks.display()))?;
    let cases = cases_of(&text, &marks.to_string_lossy())?;
    if !quiet {
        eprintln!("sva: the cases of {}: {} (--cases none: no cases)", marks.display(), cases.len());
    }
    Ok(Some(cases))
}

/// A case of a list by its name (as `case_name` makes it).
fn case_in<'a>(cases: &'a Value, name: &str) -> Option<&'a Value> {
    cases.as_array()?.iter().find(|c| c["name"].as_str() == Some(name))
}

/// The names of a list of cases, for a message.
fn case_names(cases: &Value) -> String {
    let n: Vec<&str> = cases.as_array().map(|a| a.iter().filter_map(|c| c["name"].as_str()).collect()).unwrap_or_default();
    if n.is_empty() { "none".into() } else if n.len() > 8 { format!("{} … ({} cases)", n[..8].join(", "), n.len()) } else { n.join(", ") }
}

// ------------------------------------------------------------------------------------------------------------ keep, set, rm

/// The FST of a run: its header's times (ps) and the number of its signals.
fn fst_facts(p: &Path) -> Result<(u64, u64, u64), String> {
    let f = std::io::BufReader::new(std::fs::File::open(p).map_err(|e| format!("{}: {e}", p.display()))?);
    let r = fst_reader::FstReader::open_and_read_time_table(f).map_err(|e| format!("{}: {e:?}", p.display()))?;
    let h = r.get_header();
    let ps = 10f64.powi(i32::from(h.timescale_exponent) + 12);
    let last = r.get_time_table().and_then(|t| t.last().copied()).unwrap_or(0).max(h.end_time);
    let to_ps = |t: u64| if ps >= 1.0 { t.saturating_mul(ps as u64) } else { (t as f64 * ps).round() as u64 };
    Ok((to_ps(h.start_time), to_ps(last), h.var_count))
}

fn keep(o: &Opt) -> Result<u8, String> {
    let [dump] = o.pos.as_slice() else {
        return Err(format!("sva runs keep DUMP: one dump ({} given)\n{USAGE}", o.pos.len()));
    };
    let meta = std::fs::metadata(dump).map_err(|e| format!("{dump}: {e}"))?;
    if !meta.is_file() {
        return Err(format!("{dump}: not a file"));
    }
    let cases = cases_for(o.cases.as_deref(), dump, o.json)?;
    let dir = dir_of(o, Some(dump));
    let made = !dir.exists();
    if made {
        std::fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    }
    // git leaves the runs out: a directory of their own whole, another one only their files (never a folder of yours)
    let ignore = dir.join(".gitignore");
    if !ignore.exists() {
        let own = made || dir.file_name().is_some_and(|n| n == DIR);
        let text = if own { "# the runs kept by WaveLens (sva runs keep, the Runs panel): not for git\n*\n" } else {
            "# the runs kept by WaveLens (sva runs keep, the Runs panel): their files, not for git\n*.fst\n*.part\nruns.json*\n" };
        std::fs::write(&ignore, text).map_err(|e| format!("{}: {e}", ignore.display()))?;
        if !own {
            eprintln!("sva: {}: written, git leaves the runs' files out (*.fst, *.part, runs.json*)", ignore.display());
        }
    }
    sweep(&dir);
    let is_fst = {
        let mut f = std::io::BufReader::new(std::fs::File::open(dump).map_err(|e| format!("{dump}: {e}"))?);
        fst_reader::is_fst_file(&mut f)
    };
    // the number now (under the lock), the FST written after it (long: the list free meanwhile), the entry added at the end
    let (id, file) = {
        let _l = Lock::take(&dir)?;
        let mut v = load(&dir)?;
        let id = v["next"].as_u64().unwrap_or(1).max(v["runs"].as_array().map_or(0, |r| r.iter().filter_map(|x| x["id"].as_u64()).max().unwrap_or(0)) + 1);
        v["next"] = (id + 1).into();
        v["version"] = VERSION.into();
        save(&dir, &v)?;
        let stem = Path::new(dump).file_stem().map_or("dump".into(), |s| s.to_string_lossy().into_owned());
        let stem: String = stem.chars().map(|c| if c.is_alphanumeric() || "-_.".contains(c) { c } else { '_' }).take(STEM).collect();
        (id, format!("{id}-{stem}.fst"))
    };
    let target = dir.join(&file);
    if is_fst {
        let part = dir.join(format!("{file}.{}.part", std::process::id()));
        std::fs::copy(dump, &part).and_then(|_| std::fs::rename(&part, &target)).map_err(|e| {
            let _ = std::fs::remove_file(&part);
            format!("{}: {e}", target.display())
        })?;
    } else {
        // blocks of 1 MiB of changes (sva fst's are 64): a late window reads the blocks from it on, one block held at a time
        let mut job = crate::fst::FstJob::new(dump);
        (job.out, job.limit, job.quiet) = (Some(target.clone()), RUN_BLOCK, true);
        crate::fst::write_fst(job).map_err(|e| format!("{e} (not kept)"))?;
    }
    let (start, end, signals) = fst_facts(&target)?;
    let source = std::fs::canonicalize(dump).map_or_else(|_| dump.clone(), |p| p.to_string_lossy().into_owned());
    let name = o.name.clone().filter(|n| !n.is_empty()).unwrap_or_else(|| Path::new(dump).file_name().map_or(dump.clone(), |n| n.to_string_lossy().into_owned()));
    let run = json!({
        "id": id, "file": file, "name": name, "tags": o.tags.clone().unwrap_or_default(), "comment": o.comment.clone().unwrap_or_default(),
        "dump": Path::new(dump).file_name().map_or(dump.clone(), |n| n.to_string_lossy().into_owned()), "source": source,
        "kept": now_utc(), "bytes": std::fs::metadata(&target).map_or(0, |m| m.len()), "source_bytes": meta.len(),
        "source_mtime": meta.modified().map_or(Value::Null, |t| utc_of(t).into()),
        "start": start, "end": end, "signals": signals,
    });
    let mut run = run;
    if let Some(c) = cases.filter(|c| !c.is_empty()) {
        run["cases"] = c.into();
    }
    {
        let _l = Lock::take(&dir)?;
        let mut v = load(&dir)?;
        if let Some(a) = v["runs"].as_array_mut() {
            a.push(run.clone());
        }
        save(&dir, &v)?;
    }
    if o.json {
        let mut r = run;
        r["dir"] = dir.to_string_lossy().into();
        r["path"] = target.to_string_lossy().into();
        outln!("{}", serde_json::to_string_pretty(&r).unwrap_or_default());
    } else {
        outln!("{}: kept as\n  {}", dir.display(), line(&run));
    }
    Ok(0)
}

fn set(o: &Opt) -> Result<u8, String> {
    let (keys, dump) = keys_and_dump(o, 1);
    let [key] = keys.as_slice() else {
        return Err(format!("sva runs set RUN [DUMP]: one run ({} given)\n{USAGE}", keys.len()));
    };
    if o.name.is_none() && o.tags.is_none() && o.comment.is_none() && o.cases.is_none() {
        return Err(format!("sva runs set {key}: --name, --tags, --comment or --cases"));
    }
    if o.name.as_deref() == Some("") {
        return Err(format!("sva runs set {key}: a run has a name (--name with a text)"));
    }
    let dir = dir_of(o, dump.as_deref());
    load_some(&dir)?;
    // --cases none: the run's cases gone; a file (- stdin): these (the marks beside a dump: --cases them)
    let cases = match o.cases.as_deref() {
        None => None,
        Some("none") => Some(Vec::new()),
        Some(src) => cases_for(Some(src), "", true)?,
    };
    let _l = Lock::take(&dir)?;
    let mut v = load(&dir)?;
    let i = find(&v, key)?;
    let r = &mut v["runs"][i];
    if let Some(c) = cases {
        match r.as_object_mut() {
            Some(m) if c.is_empty() => {
                m.remove("cases");
            }
            Some(m) => {
                m.insert("cases".into(), c.into());
            }
            None => {}
        }
    }
    if let Some(n) = &o.name {
        r["name"] = n.clone().into();
    }
    if let Some(t) = &o.tags {
        r["tags"] = t.clone().into();
    }
    if let Some(c) = &o.comment {
        r["comment"] = c.clone().into();
    }
    let r = r.clone();
    save(&dir, &v)?;
    if o.json {
        outln!("{}", serde_json::to_string_pretty(&r).unwrap_or_default());
    } else {
        outln!("  {}", line(&r));
    }
    Ok(0)
}

/// Every run found first, the list saved without them, then their files removed (one that does not go: said).
fn rm(o: &Opt) -> Result<u8, String> {
    let (keys, dump) = keys_and_dump(o, 1);
    if keys.is_empty() {
        return Err(format!("sva runs rm RUN... [DUMP]: the runs to remove\n{USAGE}"));
    }
    let dir = dir_of(o, dump.as_deref());
    load_some(&dir)?;
    let gone = {
        let _l = Lock::take(&dir)?;
        let mut v = load(&dir)?;
        let mut at = keys.iter().map(|k| find(&v, k)).collect::<Result<Vec<_>, _>>()?;
        at.sort_unstable();
        at.dedup();
        let runs = v["runs"].as_array_mut().ok_or("runs.json: no runs")?;
        let mut gone: Vec<Value> = at.iter().rev().map(|&i| runs.remove(i)).collect();   // the last first: the indexes stay right
        gone.reverse();
        save(&dir, &v)?;
        gone
    };
    for r in &gone {
        let p = file_of(&dir, r);
        if let Err(e) = std::fs::remove_file(&p) {
            if e.kind() != std::io::ErrorKind::NotFound {
                eprintln!("sva: {}: {e} (the run is out of the list)", p.display());
            }
        }
    }
    sweep(&dir);
    if o.json {
        outln!("{}", serde_json::to_string_pretty(&json!({"removed": gone})).unwrap_or_default());
    } else {
        for r in &gone {
            outln!("removed #{} {}", r["id"].as_u64().unwrap_or(0), r["name"].as_str().unwrap_or(""));
        }
    }
    Ok(0)
}

fn path_of(o: &Opt) -> Result<u8, String> {
    let (keys, dump) = keys_and_dump(o, 1);
    let [key] = keys.as_slice() else {
        return Err(format!("sva runs path RUN [DUMP]: one run ({} given)\n{USAGE}", keys.len()));
    };
    let dir = dir_of(o, dump.as_deref());
    let v = load_some(&dir)?;
    outln!("{}", file_of(&dir, &v["runs"][find(&v, key)?]).display());
    Ok(0)
}

// ------------------------------------------------------------------------------------------------------------ diff

/// The signals of a run's comparison that differ (or are of another kind).
fn differing(d: &Value) -> Vec<&Value> {
    d["signals"].as_array().map(|s| s.iter().filter(|x| x["differ"].as_u64().unwrap_or(0) > 0 || !x["other"].is_null()).collect()).unwrap_or_default()
}

fn diff(o: &Opt) -> Result<u8, String> {
    let [dump] = o.pos.as_slice() else {
        return Err(format!("sva runs diff DUMP: one dump ({} given)\n{USAGE}", o.pos.len()));
    };
    let dir = dir_of(o, Some(dump));
    let v = load(&dir)?;
    let all = v["runs"].as_array().cloned().unwrap_or_default();
    let quiet = o.quiet || o.json || o.page;
    // A: the run of --against (its FST), or DUMP (none, now)
    let against = match o.against.as_deref() {
        None | Some("now") => None,
        Some("") => return Err("--against: a run's number or name, or now (the dump)".into()),
        Some(k) => Some(all[find(&v, k)?].clone()),
    };
    let a_id = against.as_ref().and_then(|r| r["id"].as_u64());
    let a_file = against.as_ref().map_or_else(|| dump.clone(), |r| file_of(&dir, r).to_string_lossy().into_owned());
    let (who, a_word) = match &against {
        Some(r) => (run_label(r), format!("#{}", r["id"].as_u64().unwrap_or(0))),
        None => (dump.clone(), "the dump".to_string()),
    };
    let base_name = Path::new(dump).file_name().map_or(dump.clone(), |n| n.to_string_lossy().into_owned());
    let mut others = 0;
    let mut notes: Vec<String> = Vec::new();
    // B: each run of DUMP (but A), or the ones of --run (a comma list too; now: DUMP itself, against a run only)
    let mut runs: Vec<(Value, PathBuf)> = Vec::new();
    if o.runs.is_empty() {
        let mine: Vec<Value> = all.iter().rev().filter(|r| o.all || of_dump(r, dump)).cloned().collect();
        others = all.len() - mine.len();
        runs = mine.into_iter().filter(|r| a_id.is_none() || r["id"].as_u64() != a_id).map(|r| {
            let f = file_of(&dir, &r);
            (r, f)
        }).collect();
        if runs.is_empty() && a_id.is_some() && others == 0 {
            return Err(format!("{}: no run of {dump} but {who}, the run compared against (--run now: the dump)", dir.display()));
        }
    } else {
        let keys: Vec<String> = o.runs.iter().flat_map(|k| if k.contains(',') && find(&v, k).is_err() {
            k.split(',').map(str::trim).filter(|s| !s.is_empty()).map(String::from).collect()
        } else {
            vec![k.trim().to_string()]
        }).collect();
        for k in &keys {
            if k == "now" {
                if a_id.is_none() {
                    return Err("--run now: the dump itself, compared against a run (--against RUN)".into());
                }
                let mut r = json!({"id": 0, "name": "now", "tags": [], "kept": null, "file": base_name, "dump": base_name});
                if o.case.is_some() {
                    if let Some(c) = cases_for(o.cases.as_deref(), dump, quiet)? {
                        r["cases"] = c.into();
                    }
                }
                runs.push((r, PathBuf::from(dump)));
                continue;
            }
            let r = all[find(&v, k)?].clone();
            if a_id.is_some() && r["id"].as_u64() == a_id {
                let n = format!("{}: the run compared against, skipped", run_label(&r));
                if !notes.contains(&n) {
                    notes.push(n);
                }
                continue;
            }
            let f = file_of(&dir, &r);
            runs.push((r, f));
        }
        if runs.is_empty() {
            return Err(format!("no run to compare: {who} is the run compared against (--run another, or now: the dump)"));
        }
    }
    if runs.is_empty() {
        return Err(format!("{}: no run of {dump} kept (sva runs keep {dump}){}", dir.display(),
                           if others > 0 { format!("; {others} of other dumps: --all") } else { String::new() }));
    }
    if o.page && runs.len() > 1 {
        return Err(format!("--page: the compare of one run ({} here: name one with --run)", runs.len()));
    }
    if !quiet {
        for n in &notes {
            eprintln!("sva: {n}");
        }
    }
    // the comparison's options parsed and checked once, before any run is read (B: each run's FST in turn)
    let mut base = crate::diff::opts(&[&[a_file.clone(), String::new()][..], &o.diff].concat())?;
    let (from, to) = (base.from, base.to);
    // --signals-from read once (stdin can be read once): every run takes the same paths
    if let Some(src) = base.signals_from.take() {
        let l = crate::diff::read_list(&src)?;
        if l.is_empty() {
            return Err(format!("--signals-from {src}: no signal in it"));
        }
        base.listed = Some(l);
    }
    // --limit 1: the first difference is what is read of the differences; none of the others is held
    base.limit = 1;
    // --case: the dump's window of that case (--from/--to, else its cases), each run's window its own case of that name
    let case = o.case.as_deref().map(case_name);
    if case.as_deref() == Some("") {
        return Err("--case: a case's name".into());
    }
    if o.cases.is_some() && case.is_none() {
        return Err("--cases gives the dump's cases for --case NAME".into());
    }
    if o.cases.as_deref() == Some("-") && base.listed.is_some() && o.diff.windows(2).any(|w| w[0] == "--signals-from" && w[1] == "-") {
        return Err("--cases - and --signals-from -: one of them on stdin".into());
    }
    let mut case_a: Option<(u64, u64)> = None;
    if let Some(name) = &case {
        case_a = Some(match (from, to) {
            (Some(f), Some(t)) => (f, t),
            (None, None) => {
                // A's cases: the run's of --against, else the dump's
                let c: Value = match &against {
                    Some(r) if r["cases"].is_array() => r["cases"].clone(),
                    Some(_) => return Err(format!("{who}: kept without cases (sva runs set {a_word} --cases FILE, or --from/--to: the window of the case)")),
                    None => cases_for(o.cases.as_deref(), dump, quiet)?
                        .ok_or_else(|| format!("{dump}: no cases (cocotb's {MARKS} beside it, --cases FILE, or --from/--to: the window of the case)"))?.into(),
                };
                let x = case_in(&c, name).ok_or_else(|| format!("{who}: no case {name} (its cases: {})", case_names(&c)))?;
                (x["from"].as_u64().unwrap_or(0), x["to"].as_u64().unwrap_or(0))
            }
            _ => return Err("--case with --from and --to (the dump's window of the case), or neither (its cases)".into()),
        });
    }
    // a run's comparison: B its FST (or DUMP), with --case its case of that name (B offset to it, over the shorter) ->
    // the options and the case ({name, from, to, offset, shorter, note?}: B's case), or why the run is not compared
    let prep = |r: &Value, f: &Path| -> Result<(crate::diff::Opt, Option<Value>), String> {
        let mut a = base.clone();
        a.b = f.to_string_lossy().into_owned();
        if let Some(n) = o.cut_bytes {
            a.cut_bytes = n;
        }
        let (Some(name), Some((af, at))) = (&case, case_a) else { return Ok((a, None)) };
        let Some(c) = case_in(&r["cases"], name) else {
            return Err(if r["cases"].is_array() { format!("no case {name} in this run (its cases: {})", case_names(&r["cases"])) }
                else if r["id"] == 0 { format!("no cases of {dump} (cocotb's {MARKS} beside it, --cases FILE)") }
                else { "kept without cases (sva runs set RUN --cases FILE)".to_string() });
        };
        let (bf, bt) = (c["from"].as_u64().unwrap_or(0), c["to"].as_u64().unwrap_or(0));
        let len = (at - af).min(bt - bf);
        let offset = bf as i64 - af as i64;
        (a.from, a.to, a.offset) = (Some(af), Some(af + len), offset);
        // shorter: the length compared when the two cases differ (the page's spelling), note: the same in words
        let mut x = json!({"name": name, "from": bf, "to": bt, "offset": offset, "shorter": if bt - bf != at - af { Value::from(len) } else { Value::Null }});
        if bt - bf != at - af {
            let d = (bt - bf).abs_diff(at - af);
            x["note"] = format!("the run's case is {} {}: compared over the shorter", crate::ns(d),
                                if bt - bf > at - af { "longer" } else { "shorter" }).into();
        }
        Ok((a, Some(x)))
    };
    let a_json = a_id.map_or(Value::Null, Value::from);
    if o.page {
        // the page's compare of the one run (sva diff --page's shape), the run and A named on it
        let (r, f) = &runs[0];
        let (a, c) = prep(r, f).map_err(|e| format!("{}: {e}", run_label(r)))?;
        let (equal, mut d) = crate::diff::page_doc(&a)?;
        d["run"] = r["id"].clone();
        d["a"] = a_json;
        if let Some(mut c) = c {
            c.as_object_mut().map(|m| m.remove("note"));
            d["case"] = c;
        }
        outln!("{}", serde_json::to_string(&d).unwrap_or_default());
        return Ok(if equal { 0 } else { 1 });
    }
    let mut out = Vec::new();
    for (r, f) in &runs {
        let mut x = json!({"id": r["id"], "name": r["name"], "tags": r["tags"], "kept": r["kept"], "file": r["file"], "dump": r["dump"]});
        let a = match prep(r, f) {
            Ok((a, c)) => {
                if let Some(mut c) = c {
                    c.as_object_mut().map(|m| m.remove("shorter"));
                    x["case"] = c;
                }
                a
            }
            Err(e) => {
                x["error"] = e.into();
                out.push(x);
                continue;
            }
        };
        match crate::diff::run_doc(&a) {
            Ok(d) => {
                let sigs = differing(&d);
                let n = sigs.len();
                for k in ["from", "to", "signals_compared", "signals_differ", "compared", "differ", "first", "only_a", "only_b", "only_a_count", "only_b_count"] {
                    x[k] = d[k].clone();
                }
                x["equal"] = (n == 0).into();
                let shown = if o.limit == 0 { n } else { n.min(o.limit) };
                x["signals"] = sigs.iter().take(shown).map(|s| json!({"path": s["path"], "differ": s["differ"], "first": s["first"], "other": s["other"]}))
                    .collect::<Vec<_>>().into();
                x["more"] = (n - shown).into();
            }
            Err(e) if e.starts_with("no time in common") => {
                x["outside"] = true.into();
                x["equal"] = false.into();
                x["note"] = e.lines().next().unwrap_or("").into();
            }
            Err(e) => x["error"] = e.lines().next().unwrap_or("").into(),
        }
        out.push(x);
    }
    // one error for every run (a pattern that matches nothing, a dump that does not read): said once
    let errs: Vec<&str> = out.iter().filter_map(|x| x["error"].as_str()).collect();
    if errs.len() == out.len() && errs.windows(2).all(|w| w[0] == w[1]) {
        let first = errs[0].to_string();
        return Err(first.replace(&runs[0].1.to_string_lossy().into_owned(), "the run"));
    }
    let errors = errs.len();
    let differ = out.iter().any(|x| x["equal"].as_bool() == Some(false) && x["error"].is_null());
    if o.json {
        let against = against.as_ref().map_or(Value::Null, |r| json!({"id": r["id"], "name": r["name"], "file": r["file"]}));
        let mut doc = json!({"wavelens": "runs-diff", "version": 1, "unit": "ps", "dump": dump, "dir": dir.to_string_lossy(), "against": against,
                         "from": from, "to": to, "others": others, "runs": out});
        if let (Some(name), Some((af, at))) = (&case, case_a) {
            doc["case"] = json!({"name": name, "from": af, "to": at});
        }
        if !notes.is_empty() {
            doc["notes"] = notes.into();
        }
        outln!("{}", serde_json::to_string_pretty(&doc).unwrap_or_default());
    } else {
        text(&who, &a_word, &out, others, case.as_deref());
    }
    Ok(if errors > 0 { 2 } else if differ { 1 } else { 0 })
}

/// A run as a diff names it: #3 golden (DUMP itself as a B: now).
fn run_label(r: &Value) -> String {
    match r["id"].as_u64() {
        Some(0) => "now".into(),
        id => format!("#{} {}", id.unwrap_or(0), r["name"].as_str().unwrap_or("")),
    }
}

/// sva runs diff as text: a line per run; the window in the header when every run has the same, else on each line.
/// `who`: A as the header names it (the dump, or `#1 golden` of --against); `a_word`: A in a run's line (the dump, #1).
fn text(who: &str, a_word: &str, out: &[Value], others: usize, case: Option<&str>) {
    let win = |x: &Value| x["from"].as_i64().zip(x["to"].as_i64());
    let wins: Vec<(i64, i64)> = out.iter().filter_map(win).collect();
    let one = !wins.is_empty() && wins.windows(2).all(|w| w[0] == w[1]) && out.iter().all(|x| win(x).is_some() || !x["error"].is_null());
    let t = |v: i64| crate::ns(v.max(0) as u64);
    let header = match case {
        Some(c) => format!(" over the case {c}{}", if one { format!(" ({} … {} of {a_word})", t(wins[0].0), t(wins[0].1)) } else { String::new() }),
        None if one => format!(" over {} … {}", t(wins[0].0), t(wins[0].1)),
        None => String::new(),
    };
    outln!("{who} against {} run{}{header}{}:", out.len(), if out.len() == 1 { "" } else { "s" },
           if others > 0 { format!(" ({others} of other dumps not compared: --all)") } else { String::new() });
    let (only_a, only_b) = (format!("of {a_word} not in the run"), format!("of the run not in {a_word}"));
    for x in out {
        let id = run_label(x);
        let mut at = if one { String::new() } else { win(x).map_or(String::new(), |(f, u)| format!(" over {} … {}", t(f), t(u))) };
        if let Some(c) = x.get("case").filter(|c| c["offset"].as_i64().unwrap_or(0) != 0 || !c["note"].is_null()) {
            at += &format!(" (its case at {}{})", t(c["from"].as_i64().unwrap_or(0)), c["note"].as_str().map_or(String::new(), |n| format!("; {n}")));
        }
        let (oa, ob) = (x["only_a_count"].as_u64().unwrap_or(0), x["only_b_count"].as_u64().unwrap_or(0));
        let sides = [(oa, &only_a), (ob, &only_b)].iter().filter(|(n, _)| *n > 0)
            .map(|(n, w)| format!("; {n} {w}")).collect::<String>();
        if let Some(e) = x["error"].as_str() {
            outln!("  {id}: {e}");
        } else if x["outside"].as_bool() == Some(true) {
            outln!("  {id}: not in this window ({})", x["note"].as_str().unwrap_or(""));
        } else if x["equal"].as_bool() == Some(true) {
            outln!("  {id}: equal{at} ({} signals{sides})", x["signals_compared"]);
        } else {
            let f = &x["first"];
            let first = if f.is_null() { String::new() } else {
                format!(", first at {} ({})", t(f["t"].as_i64().unwrap_or(0)), f["signal"].as_str().unwrap_or(""))
            };
            let names: Vec<String> = x["signals"].as_array().map(|s| s.iter().filter_map(|s| {
                let p = s["path"].as_str()?;
                Some(match s["other"].as_str() { Some(k) => format!("{p} (another kind: {k})"), None => p.to_string() })
            }).collect()).unwrap_or_default();
            let more = x["more"].as_u64().unwrap_or(0);
            outln!("  {id}: {} of {} signals differ{at}{first}{sides}", x["signals_differ"], x["signals_compared"]);
            if !names.is_empty() {
                outln!("      {}{}", names.join(" "), if more > 0 { format!(" … {more} more") } else { String::new() });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runs_by_number_or_name() {
        let v = json!({"wavelens": "runs", "runs": [{"id": 1, "name": "a"}, {"id": 3, "name": "b"}, {"id": 4, "name": "b"}]});
        assert_eq!(find(&v, "3"), Ok(1));
        assert_eq!(find(&v, "#4"), Ok(2));
        assert_eq!(find(&v, "a"), Ok(0));
        assert!(find(&v, "b").unwrap_err().contains("2 runs named b"));
        assert!(find(&v, "7").is_err());
    }

    #[test]
    fn the_time_of_now_reads() {
        let t = now_utc();
        assert_eq!(t.len(), 20, "{t}");
        assert!(t.starts_with("20") && t.ends_with('Z') && &t[10..11] == "T", "{t}");
        // a file's time and back (source_mtime against kept)
        for s in [0u64, 951_782_400, 1_577_836_799, 1_798_000_007] {
            let iso = utc_of(std::time::UNIX_EPOCH + std::time::Duration::from_secs(s));
            assert_eq!(secs_of(&iso), Some(s as i64), "{iso}");
        }
        assert_eq!(utc_of(std::time::UNIX_EPOCH + std::time::Duration::from_secs(951_782_400)), "2000-02-29T00:00:00Z");
        assert_eq!(secs_of("2026-11-06"), None);
    }

    #[test]
    fn options_by_verb() {
        let a = |s: &str| s.split(' ').map(String::from).collect::<Vec<_>>();
        assert!(opts(&a("keep d.vcd --from 5ns")).err().unwrap().starts_with("--from: not an option of sva runs keep"));
        assert!(opts(&a("list d.vcd --name x")).is_err());
        let o = opts(&a("set 1 --name=eq --dir=r")).unwrap();
        assert_eq!((o.name.as_deref(), o.dir.as_deref()), (Some("eq"), Some("r")));
        assert_eq!(opts(&a("d.vcd --all")).unwrap().cmd, "list");
    }

    #[test]
    fn settings_with_comments() {
        let v = jsonc("{\n  // the runs\n  \"wavelens.runsDir\": \"runs//x\", /* here */\n  \"a\": [1, 2,],\n}").unwrap();
        assert_eq!(v["wavelens.runsDir"], "runs//x");
        assert_eq!(v["a"], json!([1, 2]));
    }

    #[test]
    fn cases_by_name() {
        assert_eq!(case_name("TC3 test_scratch \u{b7} FAIL (expected)"), "test_scratch");
        assert_eq!(case_name("  reset "), "reset");
        assert_eq!(case_name("TC test"), "TC test");
        assert_eq!(case_name("TC12x y"), "TC12x y");
        let c = cases_of(r#"[{"name": "a", "from": 0, "to": 5}, {"label": "TC2 a", "from": "1ns", "to": "2ns"}, {"name": "", "from": 0, "to": 1},
                             {"name": "b", "from": 3}]"#, "x").unwrap();
        assert_eq!(c, vec![json!({"name": "a", "from": 0, "to": 5}), json!({"name": "a (2)", "from": 1000, "to": 2000})]);
        assert!(cases_of("{}", "x").unwrap_err().contains("no cases in it"));
    }
}
