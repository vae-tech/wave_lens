//! `sva runs`: the runs you keep of a dump, to compare the dump of now with them over a window. A run is kept by hand
//! (`sva runs keep`, the Runs panel of VS Code, wave_runs of the MCP server): the dump as an FST (a VCD converted as
//! `sva fst` does it, its types file beside it read; an FST copied) in a directory of runs, `.wavelens-runs` beside the
//! dump by default, with a name, tags and a comment in its `runs.json`. A directory keep makes (or one named
//! `.wavelens-runs`) ignores itself in git; another one gets a `.gitignore` of the runs' files only, when it has none.
//! `sva runs diff` compares the dump with each run of it (or the ones named) as `sva diff` does, over a window: the
//! dumps streamed, nothing of them held but the values of now and the first difference.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use serde_json::{json, Value};

macro_rules! outln {
    ($($t:tt)*) => { crate::write_out(format_args!($($t)*), true) };
}

const USAGE: &str = "usage: sva runs [list] [DUMP | DIR] [--dir D] [--all] [--json]
       sva runs keep DUMP [--dir D] [--name N] [--tags T,...] [--comment C] [--json]
       sva runs set RUN [DUMP] [--dir D] [--name N] [--tags T,...] [--comment C] [--json]
       sva runs rm RUN... [DUMP] [--dir D] [--json]
       sva runs path RUN [DUMP] [--dir D]
       sva runs diff DUMP [--dir D] [--run RUN ...] [--all] [--from T] [--to T] [--signals PAT,...] [--signals-from FILE]
                [--scope S] [--map A=B ...] [--limit N] [--json]
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
is \"not in this window\". --json: the result as JSON (times in ps). --opt=value is taken as --opt value.
TIME is a number with a unit (100ns, 2.5us; ps without one).
Exit status: 0 done (diff: every run equal over the window); 1 diff: a run differs or does not cover the window; 2 usage,
a dump or run that does not read, a run that is not there, a window or signal list that is empty.";

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
}

/// The options each verb takes (--json and --dir: every one but path's --json).
fn takes(cmd: &str, opt: &str) -> bool {
    let own: &[&str] = match cmd {
        "list" => &["--all", "--json"],
        "keep" | "set" => &["--name", "--tags", "--tag", "--comment", "--json"],
        "rm" => &["--json"],
        "path" => &[],
        _ => &["--run", "--all", "--from", "--to", "--signals", "--signals-from", "--scope", "--map", "--limit", "--json"],
    };
    opt == "--dir" || own.contains(&opt)
}

fn opts(args: &[String]) -> Result<Opt, String> {
    let mut o = Opt { cmd: String::new(), pos: vec![], dir: None, name: None, tags: None, comment: None, json: false, all: false, runs: vec![],
                      diff: vec![], limit: 20 };
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
                         "--signals-from", "--scope", "--map"];
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

/// The directory of runs: --dir, else the one a dump lies in (a run's FST kept again), else .wavelens-runs beside the
/// dump (a file) or in it (a directory), else here.
fn dir_of(o: &Opt, dump: Option<&str>) -> PathBuf {
    if let Some(d) = &o.dir {
        return PathBuf::from(d);
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
    let s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs()) as i64;
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
    let mut s = format!("#{:<3} {}  {}{}  {} ({}, {} … {})", r["id"].as_u64().unwrap_or(0), kept.trim_end_matches('Z').get(..16).unwrap_or(&kept),
                        r["name"].as_str().unwrap_or(""), if tags.is_empty() { String::new() } else { format!("  [{tags}]") },
                        r["dump"].as_str().unwrap_or(""), bytes_text(r["bytes"].as_u64().unwrap_or(0)),
                        crate::ns(r["start"].as_u64().unwrap_or(0)), crate::ns(r["end"].as_u64().unwrap_or(0)));
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
        let args = [dump.clone(), "--out".into(), target.to_string_lossy().into_owned(), "--quiet".into()];
        let _ = crate::fst::fst_cmd(&args);   // its error said on stderr
        if !target.exists() {
            return Err(format!("{dump}: not kept (the FST was not written)"));
        }
    }
    let (start, end, signals) = fst_facts(&target)?;
    let source = std::fs::canonicalize(dump).map_or_else(|_| dump.clone(), |p| p.to_string_lossy().into_owned());
    let name = o.name.clone().filter(|n| !n.is_empty()).unwrap_or_else(|| Path::new(dump).file_name().map_or(dump.clone(), |n| n.to_string_lossy().into_owned()));
    let run = json!({
        "id": id, "file": file, "name": name, "tags": o.tags.clone().unwrap_or_default(), "comment": o.comment.clone().unwrap_or_default(),
        "dump": Path::new(dump).file_name().map_or(dump.clone(), |n| n.to_string_lossy().into_owned()), "source": source,
        "kept": now_utc(), "bytes": std::fs::metadata(&target).map_or(0, |m| m.len()), "source_bytes": meta.len(),
        "start": start, "end": end, "signals": signals,
    });
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
    if o.name.is_none() && o.tags.is_none() && o.comment.is_none() {
        return Err(format!("sva runs set {key}: --name, --tags or --comment"));
    }
    if o.name.as_deref() == Some("") {
        return Err(format!("sva runs set {key}: a run has a name (--name with a text)"));
    }
    let dir = dir_of(o, dump.as_deref());
    load_some(&dir)?;
    let _l = Lock::take(&dir)?;
    let mut v = load(&dir)?;
    let i = find(&v, key)?;
    let r = &mut v["runs"][i];
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
    let mut others = 0;
    let runs: Vec<Value> = if o.runs.is_empty() {
        let mine: Vec<Value> = all.iter().rev().filter(|r| o.all || of_dump(r, dump)).cloned().collect();
        others = all.len() - mine.len();
        mine
    } else {
        o.runs.iter().map(|k| find(&v, k).map(|i| all[i].clone())).collect::<Result<_, _>>()?
    };
    if runs.is_empty() {
        return Err(format!("{}: no run of {dump} kept (sva runs keep {dump}){}", dir.display(),
                           if others > 0 { format!("; {others} of other dumps: --all") } else { String::new() }));
    }
    // the window and the signals checked once, before any run is read
    let mut args = o.diff.clone();
    let at = |k: &str| args.iter().position(|a| a == k).map(|i| args[i + 1].clone());
    let (from, to) = (at("--from").map(|t| crate::time(&t)).transpose()?, at("--to").map(|t| crate::time(&t)).transpose()?);
    if let (Some(f), Some(t)) = (from, to) {
        if t < f {
            return Err(format!("--to {} is before --from {}", crate::ns(t), crate::ns(f)));
        }
    }
    // --signals-from is read once (stdin: it can be read once): every run takes the same paths
    let mut _tmp = None;
    if let Some(k) = args.iter().position(|a| a == "--signals-from") {
        let src = args[k + 1].clone();
        let text = if src == "-" {
            let mut t = String::new();
            std::io::Read::read_to_string(&mut std::io::stdin(), &mut t).map_err(|e| format!("stdin: {e}"))?;
            t
        } else {
            std::fs::read_to_string(&src).map_err(|e| format!("{src}: {e}"))?
        };
        if text.lines().all(|l| l.trim().is_empty()) {
            return Err(format!("--signals-from {src}: no signal in it"));
        }
        let p = std::env::temp_dir().join(format!("sva-runs-{}.signals", std::process::id()));
        std::fs::write(&p, text).map_err(|e| format!("{}: {e}", p.display()))?;
        args[k + 1] = p.to_string_lossy().into_owned();
        _tmp = Some(TempFile(p));
    }
    let mut out = Vec::new();
    for r in &runs {
        // --limit 1: the first difference is what is read of the differences; none of the others is held
        let mut a = vec![dump.clone(), file_of(&dir, r).to_string_lossy().into_owned(), "--limit".into(), "1".into()];
        a.extend(args.iter().cloned());
        let mut x = json!({"id": r["id"], "name": r["name"], "tags": r["tags"], "kept": r["kept"], "file": r["file"], "dump": r["dump"]});
        match crate::diff::diff_doc(&a) {
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
        return Err(first.replace(&file_of(&dir, &runs[0]).to_string_lossy().into_owned(), "the run"));
    }
    let errors = errs.len();
    let differ = out.iter().any(|x| x["equal"].as_bool() == Some(false) && x["error"].is_null());
    if o.json {
        let doc = json!({"wavelens": "runs-diff", "version": 1, "unit": "ps", "dump": dump, "dir": dir.to_string_lossy(),
                         "from": from, "to": to, "others": others, "runs": out});
        outln!("{}", serde_json::to_string_pretty(&doc).unwrap_or_default());
    } else {
        text(dump, &out, others);
    }
    Ok(if errors > 0 { 2 } else if differ { 1 } else { 0 })
}

/// sva runs diff as text: a line per run; the window in the header when every run has the same, else on each line.
fn text(dump: &str, out: &[Value], others: usize) {
    let win = |x: &Value| x["from"].as_i64().zip(x["to"].as_i64());
    let wins: Vec<(i64, i64)> = out.iter().filter_map(win).collect();
    let one = !wins.is_empty() && wins.windows(2).all(|w| w[0] == w[1]) && out.iter().all(|x| win(x).is_some() || !x["error"].is_null());
    let t = |v: i64| crate::ns(v.max(0) as u64);
    let header = if one { format!(" over {} … {}", t(wins[0].0), t(wins[0].1)) } else { String::new() };
    outln!("{dump} against {} run{}{header}{}:", out.len(), if out.len() == 1 { "" } else { "s" },
           if others > 0 { format!(" ({others} of other dumps not compared: --all)") } else { String::new() });
    for x in out {
        let id = format!("#{} {}", x["id"].as_u64().unwrap_or(0), x["name"].as_str().unwrap_or(""));
        let at = if one { String::new() } else { win(x).map_or(String::new(), |(f, u)| format!(" over {} … {}", t(f), t(u))) };
        let (oa, ob) = (x["only_a_count"].as_u64().unwrap_or(0), x["only_b_count"].as_u64().unwrap_or(0));
        let sides = [(oa, "of the dump not in the run"), (ob, "of the run not in the dump")].iter().filter(|(n, _)| *n > 0)
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

struct TempFile(PathBuf);
impl Drop for TempFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
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
}
