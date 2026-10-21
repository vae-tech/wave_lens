//! `sva vcd`: a dump (FST, or a VCD) written out as VCD text, the way GTKWave's `fst2vcd -e` writes it: the
//! declarations in their order, a variable seen at several places under one id code, the FST enum tables as
//! `$attrbegin misc 07 NAME COUNT LABEL… VALUE… HANDLE $end` with a reference `$attrbegin misc 07 "" HANDLE $end` before
//! each variable of that type, then the value changes in time order. The dump is streamed (wellen's stream interface),
//! so a large FST needs no more memory than its header. tools/dumpscan.py reads an FST through it when fst2vcd is not
//! installed; the WaveJSON is the same either way.

use std::collections::HashMap;
use std::io::Write;
use std::process::ExitCode;
use wellen::stream::{self, Filter};
use wellen::{Hierarchy, ItemRef, LoadOptions, ScopeType, SignalRef, SignalValueRef, TimescaleUnit, VarType};

const USAGE: &str = "usage: sva vcd [--waves] DUMP [--out FILE.vcd]
The dump (FST or VCD) as VCD text, to FILE or stdout, as GTKWave's fst2vcd -e writes it (FST enum tables included).";

/// The VCD id code of a signal: base 94 over the printable characters `!`..`~`, as fst2vcd numbers its handles.
fn code(s: SignalRef) -> String {
    let mut n = s.index() + 1;
    let mut out = Vec::new();
    while n > 0 {
        n -= 1;
        out.push(b'!' + (n % 94) as u8);
        n /= 94;
    }
    String::from_utf8(out).unwrap()
}

/// A scope's type as fst2vcd names it (FST's scope types; the others are modules).
fn scope_word(t: ScopeType) -> &'static str {
    match t {
        ScopeType::Task => "task",
        ScopeType::Function => "function",
        ScopeType::Begin => "begin",
        ScopeType::Fork => "fork",
        ScopeType::Generate => "generate",
        ScopeType::Struct => "struct",
        ScopeType::Union => "union",
        ScopeType::Class => "class",
        ScopeType::Interface => "interface",
        ScopeType::Package => "package",
        ScopeType::Program => "program",
        ScopeType::VhdlArchitecture => "vhdl_architecture",
        ScopeType::VhdlProcedure => "vhdl_procedure",
        ScopeType::VhdlFunction => "vhdl_function",
        ScopeType::VhdlRecord => "vhdl_record",
        ScopeType::VhdlProcess => "vhdl_process",
        ScopeType::VhdlBlock => "vhdl_block",
        ScopeType::VhdlForGenerate => "vhdl_for_generate",
        ScopeType::VhdlIfGenerate => "vhdl_if_generate",
        ScopeType::VhdlGenerate => "vhdl_generate",
        ScopeType::VhdlPackage => "vhdl_package",
        _ => "module",
    }
}

/// A variable's type as fst2vcd names it.
fn var_word(t: VarType) -> &'static str {
    match t {
        VarType::Event => "event",
        VarType::Integer => "integer",
        VarType::Parameter => "parameter",
        VarType::Real => "real",
        VarType::Reg => "reg",
        VarType::Supply0 => "supply0",
        VarType::Supply1 => "supply1",
        VarType::Time => "time",
        VarType::Tri => "tri",
        VarType::TriAnd => "triand",
        VarType::TriOr => "trior",
        VarType::TriReg => "trireg",
        VarType::Tri0 => "tri0",
        VarType::Tri1 => "tri1",
        VarType::WAnd => "wand",
        VarType::Wire => "wire",
        VarType::WOr => "wor",
        VarType::String => "string",
        VarType::Port => "port",
        VarType::SparseArray => "sparray",
        VarType::RealTime => "realtime",
        VarType::RealParameter => "real_parameter",
        VarType::Bit => "bit",
        VarType::Logic => "logic",
        VarType::Int => "int",
        VarType::ShortInt => "shortint",
        VarType::LongInt => "longint",
        VarType::Byte => "byte",
        VarType::Enum => "enum",
        VarType::ShortReal => "shortreal",
        VarType::EventParameter => "event",
        _ => "wire",   // VHDL's: their values are bits all the same
    }
}

fn unit_word(u: TimescaleUnit) -> &'static str {
    match u {
        TimescaleUnit::ZeptoSeconds => "zs",
        TimescaleUnit::AttoSeconds => "as",
        TimescaleUnit::FemtoSeconds => "fs",
        TimescaleUnit::PicoSeconds => "ps",
        TimescaleUnit::NanoSeconds => "ns",
        TimescaleUnit::MicroSeconds => "us",
        TimescaleUnit::MilliSeconds => "ms",
        TimescaleUnit::Seconds | TimescaleUnit::Unknown => "s",
    }
}

/// A real as C's `%.16g` (what fst2vcd writes): 16 significant digits, the exponent form below 1e-4 and from 1e16.
fn real(x: f64) -> String {
    if !x.is_finite() {
        return if x.is_nan() { "nan".into() } else if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0".into() } else { "0".into() };
    }
    let e = format!("{x:.15e}");   // d.ddddddddddddddde±N: 16 significant digits, rounded as printf rounds
    let (mant, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let trim = |s: &str| if s.contains('.') { s.trim_end_matches('0').trim_end_matches('.').to_string() } else { s.to_string() };
    if !(-4..16).contains(&exp) {
        return format!("{}e{}{:02}", trim(mant), if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    trim(&format!("{x:.*}", (15 - exp).max(0) as usize))
}

/// An enum table as fst2vcd writes it after `$attrbegin misc 07`, without its handle: NAME COUNT LABEL… VALUE….
fn table(name: &str, vals: &[(&str, &str)]) -> String {
    let labels: Vec<&str> = vals.iter().map(|(_, l)| *l).collect();
    let values: Vec<&str> = vals.iter().map(|(b, _)| *b).collect();
    format!("{} {} {} {}", if name.is_empty() { "\"\"" } else { name }, vals.len(), labels.join(" "), values.join(" "))
}

/// The declarations: the enum tables first, then every scope and variable in the order of the dump.
fn header(h: &Hierarchy, o: &mut impl Write) -> std::io::Result<()> {
    if !h.date().is_empty() {
        writeln!(o, "$date\n\t{}\n$end", h.date().trim())?;
    }
    if !h.version().is_empty() {
        writeln!(o, "$version\n\t{}\n$end", h.version().trim())?;
    }
    if let Some(ts) = h.timescale() {
        writeln!(o, "$timescale\n\t{}{}\n$end", ts.factor, unit_word(ts.unit))?;
    }
    // the enum tables, numbered in the order of their first variable
    let mut tables: HashMap<String, usize> = HashMap::new();
    let mut lines = Vec::new();
    for v in h.all_vars() {
        if let Some((name, vals)) = h[v].enum_type(h) {
            let line = table(name, &vals);
            if !tables.contains_key(&line) {
                tables.insert(line.clone(), tables.len() + 1);
                lines.push(line);
            }
        }
    }
    for (i, l) in lines.iter().enumerate() {
        writeln!(o, "$attrbegin misc 07 {l} {} $end", i + 1)?;
    }
    // pre: the names of the array scopes wellen made from an array element's name (`regs[0]` -> scope `regs`, variable
    // `[0]`), put back in front of the name, as the dump has it
    fn items(h: &Hierarchy, it: &mut dyn Iterator<Item = ItemRef>, pre: &str, tables: &HashMap<String, usize>, o: &mut dyn Write) -> std::io::Result<()> {
        for item in it {
            match item {
                ItemRef::Scope(s) if h[s].scope_type() == ScopeType::VhdlArray => {
                    items(h, &mut h[s].items(h), &format!("{pre}{}", h[s].name(h)), tables, o)?;
                }
                ItemRef::Scope(s) => {
                    let sc = &h[s];
                    writeln!(o, "$scope {} {pre}{} $end", scope_word(sc.scope_type()), sc.name(h))?;
                    items(h, &mut sc.items(h), "", tables, o)?;
                    writeln!(o, "$upscope $end")?;
                }
                ItemRef::Var(v) => {
                    let var = &h[v];
                    if let Some((name, vals)) = var.enum_type(h) {
                        writeln!(o, "$attrbegin misc 07 \"\" {} $end", tables[&table(name, &vals)])?;
                    }
                    let width = var.length(h).unwrap_or(if var.is_real(h) { 64 } else { 0 });
                    let range = var.index().map_or(String::new(), |i| format!(" [{}:{}]", i.msb(), i.lsb()));
                    writeln!(o, "$var {} {width} {} {pre}{}{range} $end", var_word(var.var_type()), code(var.signal_ref()), var.name(h))?;
                }
            }
        }
        Ok(())
    }
    items(h, &mut h.items(), "", &tables, o)?;
    writeln!(o, "$enddefinitions $end")
}

/// The value changes in time order: `#time`, then one change per line (`0!`, `b0101 "`, `r1.5 #`, `sHello $`).
fn body<R: std::io::BufRead + std::io::Seek>(w: &mut stream::StreamingWaveform<R>, o: &mut impl Write) -> std::io::Result<()> {
    // the code of every signal a variable refers to (a signal no variable names is left out)
    let h = w.hierarchy();
    let codes: HashMap<SignalRef, String> = h.all_vars().map(|v| (h[v].signal_ref(), code(h[v].signal_ref()))).collect();
    let mut now: Option<u64> = None;
    let r = w.stream_changes(Filter::all(), |t, s, v| -> std::io::Result<()> {
        let Some(c) = codes.get(&s) else { return Ok(()) };
        if now != Some(t) {
            writeln!(o, "#{t}")?;
            now = Some(t);
        }
        match v {
            SignalValueRef::Event => writeln!(o, "1{c}"),
            SignalValueRef::Real(x) => writeln!(o, "r{} {c}", real(x)),
            SignalValueRef::String(x) => writeln!(o, "s{} {c}", x.replace(' ', "\\x20")),
            SignalValueRef::BitVec(_) => {
                let b = v.to_bit_string().unwrap_or_default();
                if b.len() == 1 { writeln!(o, "{b}{c}") } else { writeln!(o, "b{b} {c}") }
            }
        }
    });
    r.map_err(|e| match e {
        stream::StreamError::Callback(e) => e,
        stream::StreamError::Wellen(e) => std::io::Error::other(e.to_string()),
    })?;
    o.flush()
}

pub fn vcd_cmd(args: &[String]) -> ExitCode {
    let (mut waves, mut out) = (None::<String>, None::<String>);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--waves" => waves = it.next().cloned(),
            "--out" | "-o" => out = it.next().cloned(),
            "-h" | "--help" => {
                println!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            s if s.starts_with('-') => {
                eprintln!("unknown option {s}\n{USAGE}");
                return ExitCode::from(2);
            }
            s => waves = Some(s.into()),
        }
    }
    let Some(waves) = waves else {
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    };
    if let Err(e) = std::fs::File::open(&waves) {
        eprintln!("sva: {waves}: {e}");
        return ExitCode::from(2);
    }
    let mut w = match stream::read_from_file(&waves, &LoadOptions::default()) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("sva: {waves}: {e}");
            return ExitCode::from(2);
        }
    };
    let sink: Box<dyn Write> = match &out {
        Some(f) => match std::fs::File::create(f) {
            Ok(f) => Box::new(f),
            Err(e) => {
                eprintln!("sva: {}: {e}", out.as_deref().unwrap_or(""));
                return ExitCode::from(2);
            }
        },
        None => Box::new(std::io::stdout().lock()),
    };
    let mut o = std::io::BufWriter::with_capacity(1 << 20, sink);
    let r = header(w.hierarchy(), &mut o).and_then(|_| body(&mut w, &mut o));
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) if e.kind() == std::io::ErrorKind::BrokenPipe => ExitCode::SUCCESS,   // `sva vcd x.fst | head`: the reader had enough
        Err(e) => {
            eprintln!("sva: {waves}: {e}");
            ExitCode::from(2)
        }
    }
}
