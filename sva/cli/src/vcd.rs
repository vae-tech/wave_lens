//! `sva vcd`: a dump (FST, or a VCD) written out as VCD text, the way GTKWave's `fst2vcd -e` writes it, so a reader of
//! the text gets the same signals either way: tools/dumpscan.py reads an FST through it when fst2vcd is not installed,
//! and the WaveJSON is the same.
//!
//! An FST is read with fst-reader, as fst2vcd reads it with fstapi: the declarations in their order and with the names
//! the FST holds (`err[0]`, `data [7:0]`, `\e[1]`: no bit selects merged into a vector, no array scopes made), a
//! variable seen at several places under one id code, the enum tables as `$attrbegin misc 07 NAME COUNT LABEL…
//! VALUE… HANDLE $end` where the FST declares them, and a reference `$attrbegin misc 07 "" HANDLE $end` before each
//! variable of that type; then the value changes in time order, strings escaped as fstapi escapes them (`\040` for a
//! space, `\t`, `\n`, `\"`, `\\`), and the end time of the dump (`#10` after the last change at 5).
//!
//! Another dump (a VCD) goes through wellen: its adjacent bit selects of one vector are merged (`d[0]`, `d[1]` ->
//! `d [1:0]`), a lone one is written glued (`err[2]`), and the end time is the last change. Both are streamed, so a
//! large dump needs no more memory than its header.

use std::collections::HashMap;
use std::io::{BufRead, Seek, Write};
use std::process::ExitCode;
use fst_reader::{FstFilter, FstHierarchyEntry, FstReader, FstScopeType, FstSignalValue, FstVarType, ReadSignalsError};
use wellen::stream::{self, Filter};
use wellen::{Hierarchy, ItemRef, LoadOptions, ScopeType, SignalRef, SignalValueRef, TimescaleUnit, VarType};

const USAGE: &str = "usage: sva vcd [--waves] DUMP [--out FILE.vcd]
The dump (FST or VCD) as VCD text, to FILE or stdout, as GTKWave's fst2vcd -e writes it: the names as the FST holds
them, FST enum tables included, strings escaped as fstapi does (\\040 for a space), the end time of the dump kept.";

/// The VCD id code of signal `index` (an FST handle less one): base 94 over the printable characters `!`..`~`, as
/// fst2vcd numbers its handles.
fn code(index: usize) -> String {
    let mut n = index + 1;
    let mut out = Vec::new();
    while n > 0 {
        n -= 1;
        out.push(b'!' + (n % 94) as u8);
        n /= 94;
    }
    String::from_utf8(out).unwrap()
}

/// A string value as fstapi's `fstUtilityBinToEsc` writes it (what fst2vcd prints after `s`): the C escapes, the
/// printable characters but the space as they are, every other byte as three octal digits (`\040`, `\303\251`). A
/// value never holds a blank, so it stays one token of the VCD.
fn escape(s: &[u8]) -> String {
    let mut o = String::with_capacity(s.len());
    for &c in s {
        match c {
            0x07 => o.push_str("\\a"),
            0x08 => o.push_str("\\b"),
            0x0c => o.push_str("\\f"),
            b'\n' => o.push_str("\\n"),
            b'\r' => o.push_str("\\r"),
            b'\t' => o.push_str("\\t"),
            0x0b => o.push_str("\\v"),
            b'\'' | b'"' | b'\\' | b'?' => {
                o.push('\\');
                o.push(c as char);
            }
            b'!'..=b'~' => o.push(c as char),
            _ => o.push_str(&format!("\\{c:03o}")),
        }
    }
    o
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

// ---------------------------------------------------------------------------------------------------------------- FST

/// The time unit of an FST, 10^exponent s, as fst2vcd writes it: `100fs` for -13.
fn fst_timescale(exponent: i8) -> String {
    let e = i32::from(exponent).clamp(-21, 2);
    let u = e.div_euclid(3) * 3;
    let unit = match u {
        0 => "s",
        -3 => "ms",
        -6 => "us",
        -9 => "ns",
        -12 => "ps",
        -15 => "fs",
        -18 => "as",
        _ => "zs",
    };
    format!("{}{unit}", 10u32.pow((e - u) as u32))
}

/// A scope's type as fst2vcd names it.
fn fst_scope_word(t: FstScopeType) -> &'static str {
    use FstScopeType::*;
    match t {
        Task => "task",
        Function => "function",
        Begin => "begin",
        Fork => "fork",
        Generate => "generate",
        Struct => "struct",
        Union => "union",
        Class => "class",
        Interface => "interface",
        Package => "package",
        Program => "program",
        VhdlArchitecture => "vhdl_architecture",
        VhdlProcedure => "vhdl_procedure",
        VhdlFunction => "vhdl_function",
        VhdlRecord => "vhdl_record",
        VhdlProcess => "vhdl_process",
        VhdlBlock => "vhdl_block",
        VhdlForGenerate => "vhdl_for_generate",
        VhdlIfGenerate => "vhdl_if_generate",
        VhdlGenerate => "vhdl_generate",
        VhdlPackage => "vhdl_package",
        SvArray => "sv_array",
        _ => "module",
    }
}

/// A variable's type as fst2vcd names it.
fn fst_var_word(t: FstVarType) -> &'static str {
    use FstVarType::*;
    match t {
        Event => "event",
        Integer => "integer",
        Parameter => "parameter",
        Real => "real",
        RealParameter => "real_parameter",
        Reg => "reg",
        Supply0 => "supply0",
        Supply1 => "supply1",
        Time => "time",
        Tri => "tri",
        TriAnd => "triand",
        TriOr => "trior",
        TriReg => "trireg",
        Tri0 => "tri0",
        Tri1 => "tri1",
        Wand => "wand",
        Wire => "wire",
        Wor => "wor",
        Port => "port",
        SparseArray => "sparray",
        RealTime => "realtime",
        GenericString => "string",
        Bit => "bit",
        Logic => "logic",
        Int => "int",
        ShortInt => "shortint",
        LongInt => "longint",
        Byte => "byte",
        Enum => "enum",
        ShortReal => "shortreal",
    }
}

/// One entry of an FST's hierarchy as declarations; `strings[handle]` marks the string variables.
fn fst_declare(e: FstHierarchyEntry, strings: &mut [bool], o: &mut impl Write) -> std::io::Result<()> {
    match e {
        FstHierarchyEntry::Scope { tpe, name, .. } => writeln!(o, "$scope {} {name} $end", fst_scope_word(tpe)),
        FstHierarchyEntry::UpScope => writeln!(o, "$upscope $end"),
        FstHierarchyEntry::Var { tpe, name, length, handle, .. } => {
            if tpe == FstVarType::GenericString {
                if let Some(s) = strings.get_mut(handle.get_index()) {
                    *s = true;
                }
            }
            // a real is 8 bytes in the FST; fst2vcd declares it with its bits, a shortreal too
            let length = match tpe {
                FstVarType::ShortReal => 32,
                t if t.is_real() => 64,
                _ => length,
            };
            writeln!(o, "$var {} {length} {} {name} $end", fst_var_word(tpe), code(handle.get_index()))
        }
        FstHierarchyEntry::EnumTable { name, handle, mapping } => {
            // the table as the FST holds it: NAME COUNT LABEL… VALUE… (mapping: (value, label))
            let mut words = vec![name, mapping.len().to_string()];
            words.extend(mapping.iter().map(|(_, l)| l.clone()));
            words.extend(mapping.iter().map(|(v, _)| v.clone()));
            writeln!(o, "$attrbegin misc 07 {} {handle} $end", words.join(" "))
        }
        FstHierarchyEntry::EnumTableRef { handle } => writeln!(o, "$attrbegin misc 07 \"\" {handle} $end"),
        FstHierarchyEntry::Comment { string } => writeln!(o, "$comment\n\t{string}\n$end"),
        _ => Ok(()),   // source locations, VHDL types: nothing a reader of the text uses
    }
}

/// An FST as VCD text: the header, the declarations, the value changes, the end time.
fn fst_text<R: BufRead + Seek>(r: &mut FstReader<R>, o: &mut impl Write) -> std::io::Result<()> {
    let h = r.get_header();
    if !h.date.trim().is_empty() {
        writeln!(o, "$date\n\t{}\n$end", h.date.trim())?;
    }
    if !h.version.trim().is_empty() {
        writeln!(o, "$version\n\t{}\n$end", h.version.trim())?;
    }
    writeln!(o, "$timescale\n\t{}\n$end", fst_timescale(h.timescale_exponent))?;
    let mut strings = vec![false; h.max_handle as usize + 1];
    let mut res = Ok(());
    r.read_hierarchy(|e| {
        if res.is_ok() {
            res = fst_declare(e, &mut strings, o);
        }
    }).map_err(std::io::Error::other)?;
    res?;
    writeln!(o, "$enddefinitions $end")?;
    // every time of the dump is written, those without a change too (a `#6` of the VCD nothing changed at, the end),
    // as fst2vcd writes them: the times of the FST's blocks (8 bytes a time step) merged with the changes
    let times = r.get_time_table().map(<[u64]>::to_vec).unwrap_or_default();
    let mut next = 0;
    let mut now: Option<u64> = None;
    let mut step = |t: u64, now: &mut Option<u64>, o: &mut dyn Write| -> std::io::Result<()> {
        while let Some(&x) = times.get(next) {
            if x >= t {
                break;
            }
            if now.is_none_or(|n| x > n) {
                writeln!(o, "#{x}")?;
            }
            next += 1;
        }
        writeln!(o, "#{t}")?;
        *now = Some(t);
        Ok(())
    };
    let r = r.read_signals(&FstFilter::all(), |t, handle, v| -> std::io::Result<()> {
        if now != Some(t) {
            step(t, &mut now, o)?;
        }
        let c = code(handle.get_index());
        match v {
            FstSignalValue::Real(x) => writeln!(o, "r{} {c}", real(x)),
            FstSignalValue::String(s) if strings.get(handle.get_index()) == Some(&true) => writeln!(o, "s{} {c}", escape(s)),
            FstSignalValue::String(&[b]) => writeln!(o, "{}{c}", b as char),
            FstSignalValue::String(s) => writeln!(o, "b{} {c}", String::from_utf8_lossy(s)),
        }
    });
    match r {
        Ok(()) => {}
        Err(ReadSignalsError::CallbackError(e)) => return Err(e),
        Err(ReadSignalsError::ReadError(e)) => return Err(std::io::Error::other(e)),
    }
    // the times after the last change and the end of the dump: a final stretch without changes is part of the dump
    let end = times.last().map_or(h.end_time, |&t| t.max(h.end_time));
    if now.is_none_or(|n| n < end) {
        step(end, &mut now, o)?;
    }
    o.flush()
}

// ------------------------------------------------------------------------------------------------------ other dumps

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
                    // one bit of a vector glued to its name (`err[2]`), as a simulator writes it; a range apart
                    let range = match var.index() {
                        Some(i) if i.msb() == i.lsb() && width == 1 => format!("[{}]", i.lsb()),
                        Some(i) => format!(" [{}:{}]", i.msb(), i.lsb()),
                        None => String::new(),
                    };
                    writeln!(o, "$var {} {width} {} {pre}{}{range} $end", var_word(var.var_type()), code(var.signal_ref().index()), var.name(h))?;
                }
            }
        }
        Ok(())
    }
    items(h, &mut h.items(), "", &tables, o)?;
    writeln!(o, "$enddefinitions $end")
}

/// The value changes in time order: `#time`, then one change per line (`0!`, `b0101 "`, `r1.5 #`, `sHello $`).
fn body<R: BufRead + Seek>(w: &mut stream::StreamingWaveform<R>, o: &mut impl Write) -> std::io::Result<()> {
    // the code of every signal a variable refers to (a signal no variable names is left out)
    let h = w.hierarchy();
    let codes: HashMap<SignalRef, String> = h.all_vars().map(|v| (h[v].signal_ref(), code(h[v].signal_ref().index()))).collect();
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
            SignalValueRef::String(x) => writeln!(o, "s{} {c}", escape(x.as_bytes())),
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

/// The dump as VCD text into `o`: an FST by fst-reader, anything else by wellen.
fn convert(waves: &str, o: &mut impl Write) -> Result<(), String> {
    let mut f = std::io::BufReader::new(std::fs::File::open(waves).map_err(|e| e.to_string())?);
    if fst_reader::is_fst_file(&mut f) {
        let mut r = FstReader::open_and_read_time_table(f).map_err(|e| e.to_string())?;
        return fst_text(&mut r, o).map_err(io_text);
    }
    let mut w = stream::read_from_file(waves, &LoadOptions::default()).map_err(|e| e.to_string())?;
    header(w.hierarchy(), o).and_then(|_| body(&mut w, o)).map_err(io_text)
}

/// An I/O error as text; a closed pipe (`sva vcd x.fst | head`: the reader had enough) as the empty text.
fn io_text(e: std::io::Error) -> String {
    if e.kind() == std::io::ErrorKind::BrokenPipe { String::new() } else { e.to_string() }
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
    crate::reading(&waves);
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
    match convert(&waves, &mut o) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) if e.is_empty() => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("sva: {waves}: {e}");
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strings_escape_as_fstapi_does() {
        assert_eq!(escape(b"a b"), "a\\040b");
        assert_eq!(escape(b"a\tb\nc\r"), "a\\tb\\nc\\r");
        assert_eq!(escape(b"q\"'?\\"), "q\\\"\\'\\?\\\\");
        assert_eq!(escape(b"\x01\x7f\xc3\xa9"), "\\001\\177\\303\\251");
        assert_eq!(escape(b"Hello!~"), "Hello!~");
        assert!(!escape(b" \t\n\x0b\x0c\r").bytes().any(|c| c.is_ascii_whitespace()), "one token, whatever the string");
    }

    #[test]
    fn timescales_as_fst2vcd_writes_them() {
        assert_eq!(fst_timescale(-9), "1ns");
        assert_eq!(fst_timescale(-13), "100fs");
        assert_eq!(fst_timescale(-10), "100ps");
        assert_eq!(fst_timescale(-12), "1ps");
        assert_eq!(fst_timescale(0), "1s");
        assert_eq!(fst_timescale(-2), "10ms");
    }

    #[test]
    fn id_codes_count_from_the_first_printable_character() {
        assert_eq!(code(0), "!");
        assert_eq!(code(93), "~");
        assert_eq!(code(94), "!!");
    }
}
