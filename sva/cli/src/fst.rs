//! `sva fst`: a VCD written as an FST, the way GTKWave's vcd2fst writes it (blocks of value changes packed with LZ4,
//! the hierarchy with LZ4, the geometry and the time tables with zlib, as fstapi lays them out), by default beside the
//! dump under its name (tb.vcd -> tb.fst). `sva vcd` reads it back as the VCD was: the same scopes, variables, names
//! and values, so a VCD and its FST give the same WaveJSON.
//!
//! What vcd2fst drops is kept: the enum tables (`$attrbegin misc 07 NAME COUNT LABEL… VALUE… HANDLE $end`) and their
//! references before a `$var` (an FST read back by `sva vcd` or fst2vcd, or a VCD written by them, has its FSM states
//! there), every other `$attrbegin` / `$attrend`, the `$comment`s of the header, a 1-bit VHDL value (`U`, `H`, `L`, `-`),
//! a dump on one line. The FSM states of the design's types file (tb.types.json beside tb.vcd, by path, as
//! tools/svtypes.py gives them) become enum tables too, on the variables whose width is the type's (or an integer
//! wider than the enum: Questa 2023's VCD of an enum type, its code the value), so GTKWave and Surfer show the state
//! names. Times that go back are an error, as in tools/dumpscan.py (vcd2fst merges them).
//!
//! The VCD is read as a stream of words (any line breaks), so a large dump needs the memory of its signals' values and
//! of one block of changes (64 MiB, then the block is written).

use std::collections::{HashMap, HashSet};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const USAGE: &str = "usage: sva fst [--waves] DUMP.vcd [--out FILE.fst] [--types FILE.types.json | --no-types] [--map DUMP=TYPES ...] [--quiet]
The VCD as an FST, as GTKWave's vcd2fst writes it, by default beside the dump under its name (tb.vcd -> tb.fst; an
FST there is replaced, the file appears only when it is complete). Every scope and variable with its type and name,
one id code at several places as aliases, the attributes ($attrbegin: the enum tables of FSM states and their
references), the $comment lines of the header, $timezero, $dumpoff / $dumpon. The FSM states of the design's types
file (tb.types.json beside tb.vcd, or --types; --map as in svtypes.py check) become enum tables of the variables
whose width is the type's (or an integer wider than the enum: a Questa VCD of an enum type); a table the VCD gives a
variable stays. The last line says what was written.";

/// Bytes of value changes held before a block is written (`--block-bytes`, for the tests: many small blocks).
const BLOCK: usize = 64 << 20;

// ------------------------------------------------------------------------------------------------- FST encoding

fn varint(o: &mut Vec<u8>, mut v: u64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        if v == 0 {
            o.push(b);
            return;
        }
        o.push(b | 0x80);
    }
}

/// A signed varint (fstapi's fstWriterSVarint): 7 bits a byte, the sign in bit 6 of the last.
fn svarint(o: &mut Vec<u8>, mut v: i64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        if (v == 0 && b & 0x40 == 0) || (v == -1 && b & 0x40 != 0) {
            o.push(b);
            return;
        }
        o.push(b | 0x80);
    }
}

fn u64be(o: &mut Vec<u8>, v: u64) {
    o.extend_from_slice(&v.to_be_bytes());
}

/// zlib at `level` when it is shorter, else the bytes as they are (a reader tells them apart by the two lengths).
fn zlib(b: &[u8], level: u8) -> Vec<u8> {
    let z = miniz_oxide::deflate::compress_to_vec_zlib(b, level);
    if z.len() < b.len() { z } else { b.to_vec() }
}

/// The scope types of a VCD as fstapi numbers them (FST_ST_*); another word is a module.
fn scope_type(w: &[u8]) -> u8 {
    match w {
        b"module" => 0,
        b"task" => 1,
        b"function" => 2,
        b"begin" => 3,
        b"fork" => 4,
        b"generate" => 5,
        b"struct" => 6,
        b"union" => 7,
        b"class" => 8,
        b"interface" => 9,
        b"package" => 10,
        b"program" => 11,
        b"vhdl_architecture" => 12,
        b"vhdl_procedure" => 13,
        b"vhdl_function" => 14,
        b"vhdl_record" => 15,
        b"vhdl_process" => 16,
        b"vhdl_block" => 17,
        b"vhdl_for_generate" => 18,
        b"vhdl_if_generate" => 19,
        b"vhdl_generate" => 20,
        b"vhdl_package" => 21,
        b"sv_array" => 22,
        _ => 0,
    }
}

/// The variable types of a VCD as fstapi numbers them (FST_VT_*); another word is a wire.
fn var_type(w: &[u8]) -> u8 {
    match w.to_ascii_lowercase().as_slice() {
        b"event" => 0,
        b"integer" => 1,
        b"parameter" => 2,
        b"real" => 3,
        b"real_parameter" => 4,
        b"reg" => 5,
        b"supply0" => 6,
        b"supply1" => 7,
        b"time" => 8,
        b"tri" => 9,
        b"triand" => 10,
        b"trior" => 11,
        b"trireg" => 12,
        b"tri0" => 13,
        b"tri1" => 14,
        b"wand" => 15,
        b"wire" => 16,
        b"wor" => 17,
        b"port" => 18,
        b"sparray" => 19,
        b"realtime" => 20,
        b"string" => 21,
        b"bit" => 22,
        b"logic" => 23,
        b"int" => 24,
        b"shortint" => 25,
        b"longint" => 26,
        b"byte" => 27,
        b"enum" => 28,
        b"shortreal" => 29,
        _ => 16,
    }
}

const VT_PORT: u8 = 18;
const VT_WIRE: u8 = 16;
const VT_STRING: u8 = 21;

fn is_real(t: u8) -> bool {
    matches!(t, 3 | 4 | 20 | 29)
}

/// integer, int, shortint, longint, byte: Questa 2023's VCD writes a variable of an enum type as integer 32
fn is_int(t: u8) -> bool {
    matches!(t, 1 | 24 | 25 | 26 | 27)
}

/// The attribute types of `$attrbegin` as fst2vcd writes them (FST_AT_*: `class` is the pack type).
fn attr_type(w: &[u8]) -> Option<u8> {
    match w {
        b"misc" => Some(0),
        b"array" => Some(1),
        b"enum" => Some(2),
        b"class" | b"pack" => Some(3),
        _ => None,
    }
}

const MT_COMMENT: u8 = 0;
const MT_ENUMTABLE: u8 = 7;

/// A timescale (`1ns`, `10 ps`, `100fs`) as the exponent of 10 an FST keeps: -9, -11, -13.
fn exponent(t: &str) -> Option<i8> {
    let t: String = t.chars().filter(|c| !c.is_whitespace()).collect();
    let i = t.find(|c: char| !c.is_ascii_digit()).unwrap_or(t.len());
    let (n, u) = t.split_at(i);
    let f = match n {
        "" | "1" => 0,
        "10" => 1,
        "100" => 2,
        _ => return None,
    };
    let e = match u {
        "s" => 0,
        "ms" => -3,
        "us" => -6,
        "ns" => -9,
        "ps" => -12,
        "fs" => -15,
        "as" => -18,
        "zs" => -21,
        _ => return None,
    };
    Some(e + f)
}

/// A VCD string value back to its bytes: the C escapes and `\ooo` / `\xhh` fstapi's fstUtilityEscToBin reads.
fn unescape(s: &[u8]) -> Vec<u8> {
    let mut o = Vec::with_capacity(s.len());
    let mut i = 0;
    while i < s.len() {
        let c = s[i];
        i += 1;
        if c != b'\\' || i >= s.len() {
            o.push(c);
            continue;
        }
        let e = s[i];
        i += 1;
        let digit = |c: u8, radix: u32| (c as char).to_digit(radix);
        match e {
            b'a' => o.push(0x07),
            b'b' => o.push(0x08),
            b'f' => o.push(0x0c),
            b'n' => o.push(b'\n'),
            b'r' => o.push(b'\r'),
            b't' => o.push(b'\t'),
            b'v' => o.push(0x0b),
            b'x' | b'X' if s.get(i).and_then(|&c| digit(c, 16)).is_some() => {
                let mut v = 0u32;
                let mut n = 0;
                while n < 2 && i < s.len() && digit(s[i], 16).is_some() {
                    v = v * 16 + digit(s[i], 16).unwrap();
                    i += 1;
                    n += 1;
                }
                o.push(v as u8);
            }
            b'0'..=b'7' => {
                let mut v = (e - b'0') as u32;
                let mut n = 1;
                while n < 3 && i < s.len() && (b'0'..=b'7').contains(&s[i]) {
                    v = v * 8 + (s[i] - b'0') as u32;
                    i += 1;
                    n += 1;
                }
                o.push(v as u8);
            }
            _ => o.push(e),
        }
    }
    o
}

// ---------------------------------------------------------------------------------------------------- the VCD

/// The words of a VCD, read in pieces: whatever the line breaks, with the line of each.
struct Words<R> {
    r: R,
    buf: Box<[u8]>,
    pos: usize,
    end: usize,
    line: usize,
    tok: Vec<u8>,
    read: u64,
}

impl<R: Read> Words<R> {
    fn new(r: R) -> Self {
        Words { r, buf: vec![0; 1 << 20].into_boxed_slice(), pos: 0, end: 0, line: 1, tok: Vec::new(), read: 0 }
    }

    fn fill(&mut self) -> std::io::Result<bool> {
        while self.pos >= self.end {
            match self.r.read(&mut self.buf) {
                Ok(0) => return Ok(false),
                Ok(n) => {
                    self.pos = 0;
                    self.end = n;
                    self.read += n as u64;
                }
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
                Err(e) => return Err(e),
            }
        }
        Ok(true)
    }

    /// The next word into `tok`; false at the end of the file.
    fn next(&mut self) -> std::io::Result<bool> {
        self.tok.clear();
        loop {
            if !self.fill()? {
                return Ok(false);
            }
            let s = &self.buf[self.pos..self.end];
            let i = s.iter().position(|c| !c.is_ascii_whitespace()).unwrap_or(s.len());
            self.line += s[..i].iter().filter(|&&c| c == b'\n').count();
            self.pos += i;
            if i < s.len() {
                break;
            }
        }
        loop {
            if !self.fill()? {
                return Ok(true);
            }
            let s = &self.buf[self.pos..self.end];
            match s.iter().position(|c| c.is_ascii_whitespace()) {
                Some(i) => {
                    self.tok.extend_from_slice(&s[..i]);
                    self.pos += i;
                    return Ok(true);
                }
                None => {
                    self.tok.extend_from_slice(s);
                    self.pos = self.end;
                }
            }
        }
    }

    /// The words up to `$end` (not included); None when the file ends first.
    fn upto_end(&mut self) -> std::io::Result<Option<Vec<Vec<u8>>>> {
        let mut out = Vec::new();
        loop {
            if !self.next()? {
                return Ok(None);
            }
            if self.tok == b"$end" {
                return Ok(Some(out));
            }
            out.push(self.tok.clone());
        }
    }
}

/// The notes of a conversion on stderr as they come, each with the file and its line: the first few of each kind (a
/// dump with a million values of an undeclared code says so in one line at the end, not a million), and for a large
/// dump how far it is, in tenths (`sva: tb.vcd: progress: …`: a line the tools show, not a note).
struct Log {
    file: String,
    kinds: Vec<(&'static str, u64, String)>,
    quiet: bool,
    size: u64,
    next: u64,
    large: u64,
}

/// Notes of one kind shown; the rest counted.
const SHOWN: u64 = 5;
/// A dump this large says how far it is (`--large-bytes`, for the tests).
const LARGE: u64 = 64 << 20;

impl Log {
    fn new(file: &str, quiet: bool, large: u64) -> Self {
        let size = std::fs::metadata(file).map_or(0, |m| m.len());
        Log { file: file.to_string(), kinds: Vec::new(), quiet, size, next: size / 10, large }
    }

    /// A note of `kind` at `line` (0: the file).
    fn note(&mut self, kind: &'static str, line: usize, msg: String) {
        let at = if line > 0 { format!("{}:{line}", self.file) } else { self.file.clone() };
        let n = match self.kinds.iter_mut().find(|k| k.0 == kind) {
            Some(k) => {
                k.1 += 1;
                k.1
            }
            None => {
                self.kinds.push((kind, 1, format!("{at}: {msg}")));
                1
            }
        };
        if n <= SHOWN {
            eprintln!("sva: {at}: {msg}");
        }
    }

    fn large(&self) -> bool {
        !self.quiet && self.size >= self.large
    }

    /// How far the reading is, at each tenth of a large dump.
    fn progress(&mut self, read: u64, line: usize, now: Option<u64>) {
        if read < self.next || !self.large() {
            return;
        }
        let pct = (read.min(self.size) * 100 / self.size.max(1)).min(99);
        eprintln!("sva: {}: progress: {pct}% (line {line}{})", self.file, now.map_or(String::new(), |t| format!(", #{t}")));
        self.next = read + self.size / 10;
    }

    /// The kinds of which more were seen than shown, with their count and the first.
    fn finish(&self) {
        for (_, n, first) in &self.kinds {
            if *n > SHOWN {
                eprintln!("sva: {}: {n} such notes in all, the first {SHOWN} above ({first})", self.file);
            }
        }
    }
}

/// One entry of the hierarchy, in the order of the VCD.
enum Entry {
    Scope(u8, Vec<u8>),
    Up,
    /// type, name, its length in bits, its handle (from 1), an alias of an earlier variable's handle, its path
    /// for the types file (the scopes and the name without a range apart: tb.u.state)
    Var { tpe: u8, name: Vec<u8>, len: u32, handle: u32, alias: bool, path: String },
    Attr { tpe: u8, sub: u8, name: Vec<u8>, arg: u64 },
    AttrEnd,
    Comment(Vec<u8>),
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    Bits(u32),
    Real,
    Str,
}

/// What the header of the VCD declares.
#[derive(Default)]
struct Header {
    entries: Vec<Entry>,
    kinds: Vec<Kind>,
    /// the handles of each id code: one, or one per kind when a code is declared again at another width (each
    /// variable gets the values on its width, as a reader of the VCD gives them)
    codes: HashMap<Vec<u8>, Vec<u32>>,
    date: String,
    version: String,
    exponent: i8,
    timezero: i64,
    scopes: u64,
    vars: u64,
}

fn text(words: &[Vec<u8>]) -> String {
    words.iter().map(|w| String::from_utf8_lossy(w)).collect::<Vec<_>>().join(" ")
}

/// The longest name of a scope or a variable, and of an attribute's or a comment's text, an FST's readers take
/// (fst-reader refuses the whole hierarchy past them; fstapi's HIERARCHY_NAME_MAX_SIZE, FST_ID_NAM_ATTR_SIZ).
const NAME_MAX: usize = 65535;
const ATTR_MAX: usize = 65536 + 4096 - 1;

/// A name or a text as an FST holds it: UTF-8 (fst-reader reads nothing else; another byte becomes U+FFFD), cut to
/// `max` bytes with a note.
fn clip(b: &[u8], max: usize, log: &mut Log, line: usize, what: &str) -> Vec<u8> {
    let s = String::from_utf8_lossy(b);
    if s.len() <= max {
        return s.into_owned().into_bytes();
    }
    let mut k = max;
    while !s.is_char_boundary(k) {
        k -= 1;
    }
    log.note("long", line, format!("{what} of {} bytes: cut to {k} (an FST's readers take no more)", s.len()));
    s[..k].as_bytes().to_vec()
}

/// The leaf of a variable's path for the types file, as dumpscan.py's parse_ref and the page read a $var's reference: a
/// range glued to the name (`state[1:0]`) or apart (`state [1:0]`) is the vector's, not part of its path; an element of
/// an array (`mem[3]`, `mem[3] [7:0]`) is `mem.[3]`; an escaped name (`\a.b[0]`) is a name as it is.
fn ref_path(words: &[Vec<u8>]) -> String {
    let r = String::from_utf8_lossy(&words[0]).into_owned();
    if r.starts_with('\\') {
        return r;
    }
    let apart = words.get(1).is_some_and(|w| w.starts_with(b"["));
    let mut r = r;
    if !apart && r.ends_with(']') {
        if let Some(i) = r.rfind('[') {
            let range = &r[i + 1..r.len() - 1];
            let glued = i > 0 && range.split_once(':').is_some_and(|(a, b)| {
                !a.is_empty() && !b.is_empty() && a.bytes().chain(b.bytes()).all(|c| c.is_ascii_digit())
            });
            if glued {
                r.truncate(i);
            }
        }
    }
    match r.find('[') {
        Some(i) if i > 0 => format!("{}.{}", &r[..i], &r[i..]),
        _ => r,
    }
}

fn header<R: Read>(w: &mut Words<R>, log: &mut Log) -> Result<Header, String> {
    let io = |e: std::io::Error| e.to_string();
    let cut = || "no $enddefinitions: not a VCD, or its header is cut off".to_string();
    // no $timescale: 1 ps, as WaveLens reads a VCD (dumpscan.py, the page; vcd2fst takes 1 ns)
    let mut h = Header { exponent: -12, ..Default::default() };
    let mut timescale = false;
    let mut scope: Vec<String> = Vec::new();
    loop {
        if !w.next().map_err(io)? {
            return Err(cut());
        }
        let line = w.line;
        let cmd = w.tok.clone();
        match cmd.as_slice() {
            b"$enddefinitions" => {
                w.upto_end().map_err(io)?.ok_or_else(cut)?;
                break;
            }
            b"$scope" => {
                let a = w.upto_end().map_err(io)?.ok_or_else(cut)?;
                let (t, name) = match a.as_slice() {
                    [t, n, ..] => (scope_type(t), clip(n, NAME_MAX, log, line, "a $scope name")),
                    [n] => (0, clip(n, NAME_MAX, log, line, "a $scope name")),
                    [] => (0, Vec::new()),
                };
                scope.push(String::from_utf8_lossy(&name).into_owned());
                h.entries.push(Entry::Scope(t, name));
                h.scopes += 1;
            }
            b"$upscope" => {
                w.upto_end().map_err(io)?.ok_or_else(cut)?;
                if scope.pop().is_none() {
                    log.note("upscope", line, "$upscope without its $scope: left out".into());
                } else {
                    h.entries.push(Entry::Up);
                }
            }
            b"$var" => {
                let a = w.upto_end().map_err(io)?.ok_or_else(cut)?;
                if a.len() < 4 {
                    log.note("var", line, "a $var without its type, size, code or name: left out".into());
                    continue;
                }
                let mut tpe = var_type(&a[0]);
                if tpe == VT_PORT {
                    // an extended VCD's port: its own values (p… with two strengths) are not read, as WaveLens reads
                    // the VCD; the FST holds it as the wire of its width (fstapi's port is 3n+2 bits of EVCD)
                    log.note("port", line, format!("$var port {}: written as a wire; its EVCD values (p…) are not read",
                                                   text(&a[3..])));
                    tpe = VT_WIRE;
                }
                let size: u32 = std::str::from_utf8(&a[1]).ok().and_then(|s| s.parse().ok()).unwrap_or(1);
                let kind = if is_real(tpe) {
                    Kind::Real
                } else if tpe == VT_STRING {
                    Kind::Str
                } else {
                    Kind::Bits(size.max(1))
                };
                // the name as the VCD has it, a range apart included (`data [7:0]`), as vcd2fst keeps it
                let name = clip(&a[3..].join(&b' '), NAME_MAX, log, line, "a $var name");
                let len = match kind {
                    Kind::Real => 8,
                    Kind::Str => 0,
                    Kind::Bits(n) => n,
                };
                // the code of an earlier variable of the same kind: an alias of it; of another width: a signal of its own
                let handles = h.codes.entry(a[2].clone()).or_default();
                let (handle, alias) = match handles.iter().find(|&&x| h.kinds[x as usize - 1] == kind) {
                    Some(&x) => (x, true),
                    None => {
                        h.kinds.push(kind);
                        let x = h.kinds.len() as u32;
                        handles.push(x);
                        (x, false)
                    }
                };
                let path = scope.iter().cloned().chain([ref_path(&a[3..])]).collect::<Vec<_>>().join(".");
                h.entries.push(Entry::Var { tpe, name, len, handle, alias, path });
                h.vars += 1;
            }
            b"$attrbegin" => {
                let a = w.upto_end().map_err(io)?.ok_or_else(cut)?;
                let max = if a.first().is_some_and(|t| t == b"misc") { ATTR_MAX } else { NAME_MAX };
                let parsed = (a.len() >= 4 && a[2..a.len() - 1].iter().map(|x| x.len() + 1).sum::<usize>() <= max + 1).then(|| {
                    let tpe = attr_type(&a[0])?;
                    let sub = u8::from_str_radix(std::str::from_utf8(&a[1]).ok()?, 16).ok()?;
                    let arg: u64 = std::str::from_utf8(&a[a.len() - 1]).ok()?.parse().ok()?;
                    let name = String::from_utf8_lossy(&a[2..a.len() - 1].join(&b' ')).into_owned().into_bytes();
                    Some(Entry::Attr { tpe, sub, name: if name == b"\"\"" { Vec::new() } else { name }, arg })
                }).flatten();
                match parsed {
                    Some(e) => h.entries.push(e),
                    None => {
                        let t = text(&a);
                        let t = if t.chars().count() > 80 { format!("{}…", t.chars().take(80).collect::<String>()) } else { t };
                        log.note("attr", line, format!("$attrbegin {t} not read (or longer than an FST takes): left out"))
                    }
                }
            }
            b"$attrend" => {
                w.upto_end().map_err(io)?.ok_or_else(cut)?;
                h.entries.push(Entry::AttrEnd);
            }
            b"$comment" => {
                let a = w.upto_end().map_err(io)?.ok_or_else(cut)?;
                h.entries.push(Entry::Comment(clip(text(&a).as_bytes(), ATTR_MAX, log, line, "a $comment")));
            }
            b"$date" => h.date = text(&w.upto_end().map_err(io)?.ok_or_else(cut)?),
            b"$version" => h.version = text(&w.upto_end().map_err(io)?.ok_or_else(cut)?),
            b"$timescale" => {
                let t = text(&w.upto_end().map_err(io)?.ok_or_else(cut)?);
                match exponent(&t) {
                    Some(e) => h.exponent = e,
                    None => log.note("timescale", line, format!("$timescale \"{t}\" not understood: 1ps taken")),
                }
                timescale = true;
            }
            b"$timezero" => {
                let t = text(&w.upto_end().map_err(io)?.ok_or_else(cut)?);
                match t.trim().parse() {
                    Ok(z) => h.timezero = z,
                    Err(_) => log.note("timezero", line, format!("$timezero \"{t}\" not a number: left out")),
                }
            }
            // another command, or words outside one (`$comment a $end b $end`: "b"), up to its $end, as dumpscan.py
            _ => {
                w.upto_end().map_err(io)?.ok_or_else(cut)?;
            }
        }
    }
    if !timescale {
        log.note("timescale", 0, "no $timescale: 1ps taken (as WaveLens reads the VCD)".into());
    }
    Ok(h)
}

// ----------------------------------------------------------------------------------------- FSM states by path

/// An enum table: (width, {value: label}) of the types file.
type Table = (u32, Vec<(u64, String)>);

/// Questa's describe of an enum, `Verilog enum: (2 downto 0) [5 enumeration values]` and `(IDLE=0,START=1,…)` on the
/// lines after it -> its table on its width; anything else (a struct, a vector, a value it does not read) None.
/// svtypes.py parse_describe and table, for the enums of whole signals.
fn describe_enum(text: &str) -> Option<Table> {
    let lines: Vec<&str> = text.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
    let head = lines.first()?.strip_prefix("Verilog enum: (")?;
    let (range, rest) = head.split_once(") [")?;
    let (a, b) = range.split_once(" downto ").or_else(|| range.split_once(" to "))?;
    let (a, b): (i64, i64) = (a.parse().ok()?, b.parse().ok()?);
    let count: usize = rest.strip_suffix(" enumeration values]").or_else(|| rest.strip_suffix(" enumeration value]"))?.parse().ok()?;
    let width = (a - b).unsigned_abs() + 1;
    if width > 32 {
        return None;   // Questa's describe keeps 32 bits of each value
    }
    let mut body = String::new();
    for l in &lines[1..] {
        body.push_str(l);
        if body.contains('(') && body.matches('(').count() <= body.matches(')').count() {
            break;
        }
    }
    let inner = body.trim().strip_prefix('(').unwrap_or(&body).strip_suffix(')').unwrap_or(&body);
    let mask = (1u64 << width) - 1;
    let mut items = Vec::new();
    for x in inner.split(',') {
        let (n, v) = x.trim().split_once('=')?;
        let ok = n.chars().next().is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
            && n.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$');
        if !ok {
            return None;
        }
        let v: i64 = v.parse().ok()?;
        items.push(((v as u64) & mask, n.to_string()));
    }
    if items.len() != count {
        return None;
    }
    items.sort_by_key(|x| x.0);
    Some((width as u32, items))
}

/// The enums of a types file by path, every path it has a type of (its roots are the design's: svtypes.py
/// added_tops), and the dump's scopes as it names them (its "map", then --map).
struct Types {
    enums: HashMap<String, Table>,
    paths: HashSet<String>,
    map: Vec<(String, String)>,
}

/// The enums of a types file by path ("signals" with an "enum", and Questa's "describe" of an enum) and its "map".
fn types_enums(path: &Path) -> Result<Types, String> {
    let s = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let d: serde_json::Value = serde_json::from_str(&s).map_err(|e| format!("not a types file ({e})"))?;
    if d.get("wavelens").and_then(|x| x.as_str()) != Some("types") {
        return Err("not a WaveLens types file (no \"wavelens\": \"types\")".into());
    }
    let mut out = HashMap::new();
    let mut paths = HashSet::new();
    if let Some(sigs) = d.get("signals").and_then(|x| x.as_object()) {
        for (p, e) in sigs {
            paths.insert(p.clone());
            let (Some(w), Some(en)) = (e.get("width").and_then(|x| x.as_u64()), e.get("enum").and_then(|x| x.as_object())) else { continue };
            // a table whose values do not all fit the width is not this signal's (svtypes.py apply)
            let mut items = Vec::new();
            for (k, v) in en {
                let n = k.parse::<u64>().ok().filter(|&n| w >= 64 || n < 1u64 << w);
                match (n, v.as_str()) {
                    (Some(n), Some(l)) if k.bytes().all(|c| c.is_ascii_digit()) => items.push((n, l.to_string())),
                    _ => {
                        items.clear();
                        break;
                    }
                }
            }
            if !items.is_empty() && w <= 64 {
                items.sort_by_key(|x| x.0);
                out.insert(p.clone(), (w as u32, items));
            }
        }
    }
    if let Some(desc) = d.get("describe").and_then(|x| x.as_object()) {
        for (p, t) in desc {
            if t.as_str().is_some_and(|t| !t.starts_with("describe failed")) {
                paths.insert(p.clone());
            }
            if let Some(t) = t.as_str().and_then(describe_enum) {
                out.insert(p.clone(), t);
            }
        }
    }
    // none or null: no map; anything but {"dump.prefix": "types.prefix"} an error, as svtypes.py and the page say
    let map = match d.get("map") {
        None | Some(serde_json::Value::Null) => Vec::new(),
        Some(serde_json::Value::Object(m)) if m.values().all(|v| v.is_string()) => {
            m.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_string())).collect()
        }
        Some(_) => return Err("\"map\" is {\"dump.prefix\": \"types.prefix\"}, the dump's scopes as the types name them".into()),
    };
    Ok(Types { enums: out, paths, map })
}

/// A dump's path as the types name it, by the longest prefix of the map (svtypes.py remap).
fn remap(path: &str, map: &[(String, String)]) -> String {
    let best = map.iter().filter(|(k, _)| path == k || path.starts_with(&format!("{k}."))).max_by_key(|(k, _)| k.len());
    match best {
        Some((k, v)) => format!("{v}{}", &path[k.len()..]),
        None => path.to_string(),
    }
}

/// The entry of a path: its own; else without a top scope the dump adds; an element of an unpacked array (x[3],
/// x.[3]) the array's (svtypes.py lookup).
fn lookup<'a>(sigs: &'a HashMap<String, Table>, path: &str, tops: &HashSet<String>) -> Option<&'a Table> {
    if let Some(t) = sigs.get(path) {
        return Some(t);
    }
    if let Some((top, rest)) = path.split_once('.') {
        if tops.contains(top) {
            if let Some(t) = sigs.get(rest) {
                return Some(t);
            }
        }
    }
    let mut base = path;
    while let Some(i) = base.rfind('[') {
        if !base.ends_with(']') || !base[i + 1..base.len() - 1].trim_start_matches('-').bytes().all(|c| c.is_ascii_digit()) {
            break;
        }
        base = base[..i].strip_suffix('.').unwrap_or(&base[..i]);
    }
    if base != path { lookup(sigs, base, tops) } else { None }
}

/// The top scopes a dump adds above the design's (TOP of Verilator): the dump's roots that are none of the types'
/// but have one of them as a child; none when a root of the dump is one of the types' (svtypes.py added_tops).
fn added_tops(types: &HashSet<String>, paths: &[String]) -> HashSet<String> {
    let mine: HashSet<&str> = types.iter().map(|p| p.split('.').next().unwrap_or("")).collect();
    let roots: HashSet<&str> = paths.iter().map(|p| p.split('.').next().unwrap_or("")).collect();
    if roots.iter().any(|r| mine.contains(r)) {
        return HashSet::new();
    }
    paths.iter().filter_map(|p| {
        let mut q = p.splitn(3, '.');
        let (a, b) = (q.next()?, q.next()?);
        mine.contains(b).then(|| a.to_string())
    }).collect()
}

/// The enum table of an FST: NAME COUNT LABEL… VALUE… (the values in bits on the width), as fstWriterCreateEnumTable
/// writes it.
fn table_text(name: &str, t: &Table) -> Vec<u8> {
    let (w, items) = t;
    let mut s = format!("{name} {}", items.len());
    for (_, l) in items {
        s.push(' ');
        s.push_str(l);
    }
    for (v, _) in items {
        s.push_str(&format!(" {v:0w$b}", w = *w as usize));
    }
    s.into_bytes()
}

/// The FSM states of a types file on the variables of the header: an enum table before the first variable of each
/// one, a reference before every variable, where the VCD gives it none -> (tables, variables labelled).
fn add_types(h: &mut Header, types: &Types) -> (usize, usize) {
    let map = &types.map;
    let paths: Vec<String> = h.entries.iter().filter_map(|e| match e {
        Entry::Var { path, .. } => Some(remap(path, map)),
        _ => None,
    }).collect();
    let tops = added_tops(&types.paths, &paths);
    let mut next = 1 + h.entries.iter().filter_map(|e| match e {
        Entry::Attr { tpe: 0, sub: MT_ENUMTABLE, arg, .. } => Some(*arg),
        _ => None,
    }).max().unwrap_or(0);
    let mut handles: HashMap<String, u64> = HashMap::new();
    let mut out = Vec::with_capacity(h.entries.len());
    let mut labelled = 0;
    let mut referenced = false;   // the VCD's own reference before this variable (after the one before)
    for e in std::mem::take(&mut h.entries) {
        if let Entry::Var { len, path, tpe, .. } = &e {
            // its width's table; an enum on a wider integer its codes on the integer's width (svtypes.py on_integer)
            let t = (!referenced && !is_real(*tpe) && *tpe != VT_STRING)
                .then(|| lookup(&types.enums, &remap(path, map), &tops)).flatten()
                .and_then(|t| (t.0 == *len || (is_int(*tpe) && t.0 < *len)).then(|| (*len, t.1.clone())));
            if let Some(t) = t {
                let leaf = path.rsplit('.').find(|c| !c.starts_with('[')).unwrap_or("state");   // an array's element: the array's
                let text = table_text(&format!("{leaf}_t"), &t);
                let key = String::from_utf8_lossy(&text[text.iter().position(|&c| c == b' ').unwrap_or(0)..]).into_owned();
                let handle = *handles.entry(key).or_insert_with(|| {
                    out.push(Entry::Attr { tpe: 0, sub: MT_ENUMTABLE, name: text, arg: next });
                    next += 1;
                    next - 1
                });
                out.push(Entry::Attr { tpe: 0, sub: MT_ENUMTABLE, name: Vec::new(), arg: handle });
                labelled += 1;
            }
        }
        match &e {
            Entry::Attr { tpe: 0, sub: MT_ENUMTABLE, name, .. } if name.is_empty() => referenced = true,
            Entry::Var { .. } => referenced = false,
            _ => {}
        }
        out.push(e);
    }
    h.entries = out;
    (handles.len(), labelled)
}

// ------------------------------------------------------------------------------------------------ the writer

/// The blocks of value changes: each signal's changes since the block began, as fstapi packs them (the time as the
/// index into the block's table of times, from the signal's change before).
struct Blocks {
    kinds: Vec<Kind>,
    at: Vec<usize>,     // where each signal's value starts in `cur`
    cur: Vec<u8>,       // the values now: '0' '1' 'x' … of a vector, the 8 bytes of a real, nothing of a string
    frame: Vec<u8>,     // the values when the block began
    data: Vec<Vec<u8>>, // this block's changes of each signal
    last: Vec<u32>,     // the index of each signal's last change in this block
    times: Vec<u64>,
    start: u64,
    size: usize,
    count: u64,         // blocks written
    first: Option<u64>, // the start of the first block
    blackouts: Vec<(bool, u64)>,
    changes: u64,
    limit: usize,
}

impl Blocks {
    fn new(kinds: Vec<Kind>, limit: usize) -> Self {
        let mut at = Vec::with_capacity(kinds.len());
        let mut cur = Vec::new();
        for k in &kinds {
            at.push(cur.len());
            match k {
                Kind::Bits(n) => cur.resize(cur.len() + *n as usize, b'x'),
                Kind::Real => cur.extend_from_slice(&f64::NAN.to_le_bytes()),   // as fstapi starts a double
                Kind::Str => {}
            }
        }
        let n = kinds.len();
        Blocks { kinds, at, frame: cur.clone(), cur, data: vec![Vec::new(); n], last: vec![0; n], times: Vec::new(), start: 0,
                 size: 0, count: 0, first: None, blackouts: Vec::new(), changes: 0, limit }
    }

    fn now(&self) -> Option<u64> {
        self.times.last().copied()
    }

    /// Time `t` from now on; a full block is written first, the new one beginning at the time before (as fstapi does).
    fn time(&mut self, t: u64, o: &mut impl Write) -> std::io::Result<()> {
        match self.now() {
            None => {
                self.start = t;
                self.first = Some(t);
                self.times.push(t);
                self.size += 8;
            }
            Some(n) if t > n => {
                if self.size >= self.limit {
                    self.flush(o)?;
                    self.start = n;
                    self.frame.clone_from(&self.cur);
                    self.times.push(n);
                }
                self.times.push(t);
                self.size += 8;   // the table of times is the block's too: a dump of times without changes
            }
            _ => {}
        }
        Ok(())
    }

    /// A change of signal `h` (from 0) now: bits on its width, the 8 bytes of a real, a string's bytes.
    fn change(&mut self, h: usize, v: &[u8]) {
        let idx = self.times.len() as u32 - 1;
        let d = (idx - self.last[h]) as u64;
        self.last[h] = idx;
        let o = &mut self.data[h];
        let before = o.len();
        match self.kinds[h] {
            Kind::Bits(1) => {
                let c = v[0];
                let rcv = match c {
                    b'0' | b'1' => (d << 2) | (((c & 1) as u64) << 1),
                    _ => {
                        let code = match c.to_ascii_lowercase() {
                            b'x' => 0,
                            b'z' => 1,
                            b'h' => 2,
                            b'u' => 3,
                            b'w' => 4,
                            b'l' => 5,
                            b'?' => 7,
                            _ => 6,   // '-' and what else: don't care
                        };
                        (d << 4) | (code << 1) | 1
                    }
                };
                varint(o, rcv);
            }
            Kind::Bits(_) => {
                if v.iter().all(|&c| c == b'0' || c == b'1') {
                    varint(o, d << 1);
                    for chunk in v.chunks(8) {
                        let mut b = 0u8;
                        for (i, &c) in chunk.iter().enumerate() {
                            b |= (c & 1) << (7 - i);
                        }
                        o.push(b);
                    }
                } else {
                    varint(o, (d << 1) | 1);
                    o.extend_from_slice(v);
                }
            }
            Kind::Real => {
                varint(o, (d << 1) | 1);   // the 8 bytes as they are
                o.extend_from_slice(v);
            }
            Kind::Str => {
                varint(o, d << 1);
                varint(o, v.len() as u64);
                o.extend_from_slice(v);
            }
        }
        self.size += o.len() - before;
        if self.kinds[h] != Kind::Str {
            let a = self.at[h];
            self.cur[a..a + v.len()].copy_from_slice(v);
        }
        self.changes += 1;
    }

    /// The block as fstapi writes an FST_BL_VCDATA_DYN_ALIAS2: its times, the frame, each signal's changes (LZ4 when
    /// that is shorter), the offsets of the signals, the table of times.
    fn flush(&mut self, out: &mut impl Write) -> std::io::Result<()> {
        let end = self.now().unwrap_or(self.start);
        let mut s = Vec::with_capacity(self.size + self.frame.len() / 4 + 1024);
        u64be(&mut s, self.start);
        u64be(&mut s, end);
        u64be(&mut s, 0);   // the memory a reader needs, below
        let frame = zlib(&self.frame, 4);
        varint(&mut s, self.frame.len() as u64);
        varint(&mut s, frame.len() as u64);
        varint(&mut s, self.kinds.len() as u64);
        s.extend_from_slice(&frame);
        varint(&mut s, self.kinds.len() as u64);
        let vc = s.len();
        s.push(b'4');
        // where each signal's changes are (0: none in this block), or the earlier signal whose changes are the same
        // bytes (as fstapi's dynamic aliases: a clock and its copies written once)
        let mut pos = vec![0usize; self.kinds.len()];
        let mut same: Vec<Option<usize>> = vec![None; self.kinds.len()];
        let mut seen: HashMap<&[u8], usize> = HashMap::new();
        let mut mem = 0u64;
        for (h, d) in self.data.iter().enumerate() {
            if d.is_empty() {
                continue;
            }
            mem += d.len() as u64;   // an alias too: fstapi's reader unpacks each signal into a buffer of this size
            if let Some(&first) = seen.get(d.as_slice()) {
                same[h] = Some(first);
                continue;
            }
            seen.insert(d, h);
            pos[h] = s.len() - vc;
            let z = if d.len() > 32 { lz4_flex::block::compress(d) } else { Vec::new() };
            if d.len() > 32 && z.len() < d.len() {
                varint(&mut s, d.len() as u64);
                s.extend_from_slice(&z);
            } else {
                varint(&mut s, 0);
                s.extend_from_slice(d);
            }
        }
        drop(seen);
        self.data.iter_mut().for_each(Vec::clear);
        let chain = s.len();
        let (mut prev, mut zeros, mut alias) = (0usize, 0u64, None);
        for (&p, &a) in pos.iter().zip(&same) {
            if p == 0 && a.is_none() {
                zeros += 1;
                continue;
            }
            if zeros > 0 {
                varint(&mut s, zeros << 1);
                zeros = 0;
            }
            match a {
                // an alias: -(its handle), once for a run of the same one
                Some(a) if alias == Some(a) => svarint(&mut s, 1),
                Some(a) => {
                    svarint(&mut s, (-(a as i64 + 1) << 1) | 1);
                    alias = Some(a);
                }
                None => {
                    svarint(&mut s, (((p - prev) as i64) << 1) | 1);
                    prev = p;
                }
            }
        }
        if zeros > 0 {
            varint(&mut s, zeros << 1);
        }
        let n = (s.len() - chain) as u64;
        u64be(&mut s, n);
        let mut tt = Vec::with_capacity(self.times.len() * 2);
        let mut t0 = 0;
        for &t in &self.times {
            varint(&mut tt, t - t0);
            t0 = t;
        }
        let z = zlib(&tt, 9);
        s.extend_from_slice(&z);
        u64be(&mut s, tt.len() as u64);
        u64be(&mut s, z.len() as u64);
        u64be(&mut s, self.times.len() as u64);
        s[16..24].copy_from_slice(&mem.to_be_bytes());
        out.write_all(&[8])?;
        out.write_all(&(8 + s.len() as u64).to_be_bytes())?;
        out.write_all(&s)?;
        self.count += 1;
        self.times.clear();
        self.last.iter_mut().for_each(|x| *x = 0);
        self.size = 0;
        Ok(())
    }
}

/// The hierarchy as fstapi writes it (FST_ST_* scopes, FST_VT_* variables, attributes).
fn hierarchy(h: &Header) -> Vec<u8> {
    let mut o = Vec::new();
    for e in &h.entries {
        match e {
            Entry::Scope(t, name) => {
                o.push(254);
                o.push(*t);
                o.extend_from_slice(name);
                o.extend_from_slice(&[0, 0]);   // the name, an empty component
            }
            Entry::Up => o.push(255),
            Entry::Var { tpe, name, len, handle, alias, .. } => {
                o.push(*tpe);
                o.push(0);   // a VCD has no direction
                o.extend_from_slice(name);
                o.push(0);
                varint(&mut o, *len as u64);
                varint(&mut o, if *alias { *handle as u64 } else { 0 });
            }
            Entry::Attr { tpe, sub, name, arg } => {
                o.extend_from_slice(&[252, *tpe, *sub]);
                if *tpe == 0 && (*sub == 4 || *sub == 5) {
                    // a source stem: the path's id as a varint in the place of the name
                    let id = std::str::from_utf8(name).ok().and_then(|s| s.parse().ok()).unwrap_or(0);
                    varint(&mut o, id);
                } else {
                    o.extend_from_slice(name);
                }
                o.push(0);
                varint(&mut o, *arg);
            }
            Entry::AttrEnd => o.push(253),
            Entry::Comment(t) => {
                o.extend_from_slice(&[252, 0, MT_COMMENT]);
                o.extend_from_slice(t);
                o.extend_from_slice(&[0, 0]);   // the text, arg 0
            }
        }
    }
    o
}

fn fixed(o: &mut Vec<u8>, s: &str, n: usize) {
    let b = s.as_bytes();
    let mut k = b.len().min(n - 1);
    while !s.is_char_boundary(k) {
        k -= 1;
    }
    o.extend_from_slice(&b[..k]);
    o.resize(o.len() + n - k, 0);
}

/// The header block (FST_BL_HDR): 329 bytes after its type.
fn header_block(h: &Header, b: &Blocks, end: u64) -> Vec<u8> {
    let mut o = vec![0u8];
    u64be(&mut o, 329);
    u64be(&mut o, b.first.unwrap_or(0));
    u64be(&mut o, end);
    o.extend_from_slice(&std::f64::consts::E.to_le_bytes());
    u64be(&mut o, 0);
    u64be(&mut o, h.scopes);
    u64be(&mut o, h.vars);
    u64be(&mut o, b.kinds.len() as u64);
    u64be(&mut o, b.count);
    o.push(h.exponent as u8);
    fixed(&mut o, if h.version.is_empty() { concat!("WaveLens sva fst ", env!("CARGO_PKG_VERSION")) } else { &h.version }, 128);
    fixed(&mut o, &h.date, 119);
    o.push(0);   // Verilog
    u64be(&mut o, h.timezero as u64);
    o
}

/// A VCD value (`b`: bits or a scalar, `r` a real, `s` a string) as the FST keeps it for a signal of `kind`, into
/// `out`: bits on the width, the 8 bytes of a real, a string's bytes; false when a real is not a number (NaN taken).
fn value(kind: Kind, k: u8, v: &[u8], out: &mut Vec<u8>) -> bool {
    out.clear();
    let num = |v: &[u8]| std::str::from_utf8(v).ok().and_then(|s| s.parse::<f64>().ok());
    match kind {
        Kind::Str if k == b's' => out.extend_from_slice(&unescape(v)),
        Kind::Str => out.extend_from_slice(v),
        Kind::Real => {
            let x = if k == b'r' { num(v) } else { std::str::from_utf8(v).ok().and_then(|s| u64::from_str_radix(s, 2).ok()).map(|n| n as f64) };
            out.extend_from_slice(&x.unwrap_or(f64::NAN).to_le_bytes());
            return x.is_some();
        }
        Kind::Bits(n) => {
            let n = n as usize;
            let int: Vec<u8>;
            let v: &[u8] = if k == b'r' {
                // a real on a vector: its integer, in two's complement
                let x = num(v).unwrap_or(0.0).round() as i64;
                int = (0..64).rev().map(|j| b'0' + ((x >> j) & 1) as u8).collect();
                &int
            } else {
                v
            };
            if v.len() >= n {
                out.extend_from_slice(&v[v.len() - n..]);
            } else {
                // a shorter value extends on the left: with 0 before a 0 or 1, else with its first bit (x, z)
                let pad = match v.first() {
                    Some(b'0') | Some(b'1') | None => b'0',
                    Some(&p) => p,
                };
                out.resize(n - v.len(), pad);
                out.extend_from_slice(v);
            }
        }
    }
    true
}

/// What `convert` wrote.
struct Done {
    vars: u64,
    signals: usize,
    changes: u64,
    tables: usize,
    from_types: (usize, usize),
}

/// The VCD `vcd` as the FST `out`; `types`: the FSM states by path.
fn convert(vcd: &str, out: &mut (impl Write + Seek), types: Option<&Types>, limit: usize, log: &mut Log) -> Result<Done, String> {
    let file = vcd;
    let f = std::fs::File::open(vcd).map_err(|e| format!("{file}: {e}"))?;
    let mut w = Words::new(f);
    let mut h = header(&mut w, log).map_err(|e| format!("{file}:{}: {e}", w.line))?;
    let from_types = types.map_or((0, 0), |t| add_types(&mut h, t));
    let tables = h.entries.iter().filter(|e| matches!(e, Entry::Attr { tpe: 0, sub: MT_ENUMTABLE, name, .. } if !name.is_empty())).count();
    if log.large() {
        eprintln!("sva: {file}: progress: {} variables ({} signals) in {} scopes, {tables} enum tables; the values next ({} MB)", h.vars,
                  h.kinds.len(), h.scopes, log.size >> 20);
    }
    let io = |e: std::io::Error| format!("{file}: {e}");
    let mut b = Blocks::new(h.kinds.clone(), limit);
    let placeholder = header_block(&h, &b, 0);
    out.write_all(&placeholder).map_err(io)?;
    let (mut unknown, mut skipped): (HashSet<Vec<u8>>, u64) = (HashSet::new(), 0);
    let (mut val, mut code, mut fit) = (Vec::new(), Vec::new(), Vec::new());
    while w.next().map_err(io)? {
        let line = w.line;
        if w.read >= log.next {
            log.progress(w.read, line, b.now());
        }
        let t = &w.tok;
        let c = t[0];
        if c == b'#' {
            let s = std::str::from_utf8(&t[1..]).ok().and_then(|s| s.parse::<u64>().ok());
            let Some(s) = s else { return Err(format!("{file}:{line}: \"{}\" is not a time", String::from_utf8_lossy(t))) };
            if let Some(n) = b.now() {
                if s < n {
                    return Err(format!("{file}:{line}: #{s} after #{n}: the time goes back (a dump of several runs?)"));
                }
            }
            b.time(s, out).map_err(io)?;
            continue;
        }
        if c == b'$' {
            match t.as_slice() {
                b"$dumpoff" | b"$dumpon" => {
                    let on = t.as_slice() == b"$dumpon";
                    let now = b.now().unwrap_or(0);
                    if b.blackouts.last().is_none_or(|x| x.0 != on) {
                        b.blackouts.push((on, now));
                    }
                }
                b"$comment" => {
                    w.upto_end().map_err(io)?;
                }
                _ => {}   // $dumpvars, $dumpall, $end
            }
            continue;
        }
        if c == b'p' || c == b'P' {
            // an extended VCD's port value, `pD 6 0 <code>`: not read (its $var is a wire), its words skipped
            let said = format!("\"{}\": a port value of an extended VCD, not read: left out", String::from_utf8_lossy(t));
            for _ in 0..3 {
                if !w.next().map_err(io)? {
                    break;
                }
            }
            log.note("evcd", line, said);
            continue;
        }
        // a value: 0! x# b0101 % r1.5 & sText '
        let (kind, v) = match c {
            b'b' | b'B' | b'r' | b'R' | b's' | b'S' => {
                val.clear();
                val.extend_from_slice(&t[1..]);
                let k = c.to_ascii_lowercase();
                if !w.next().map_err(io)? {
                    return Err(format!("{file}:{line}: a value without its code at the end of the file"));
                }
                code.clear();
                code.extend_from_slice(&w.tok);
                (k, &val)
            }
            _ => {
                if t.len() < 2 {
                    log.note("value", line, format!("\"{}\" not a value: left out", String::from_utf8_lossy(t)));
                    continue;
                }
                val.clear();
                val.push(c);
                code.clear();
                code.extend_from_slice(&t[1..]);
                (b'b', &val)
            }
        };
        let Some(handles) = h.codes.get(&code) else {
            skipped += 1;
            if unknown.insert(code.clone()) {
                log.note("code", line, format!("a value of \"{}\", which no $var declares: left out", String::from_utf8_lossy(&code)));
            }
            continue;
        };
        if b.now().is_none() {
            b.time(0, out).map_err(io)?;   // values before the first time are at 0
        }
        for &handle in handles {
            let i = handle as usize - 1;
            if !value(b.kinds[i], kind, v, &mut fit) {
                log.note("real", line, format!("\"{}\" is not a number: NaN taken", String::from_utf8_lossy(v)));
            }
            b.change(i, &fit);
        }
    }
    if b.now().is_none() {
        b.time(0, out).map_err(io)?;
    }
    if !unknown.is_empty() {
        log.note("codes", 0, format!("{skipped} value{} left out in all, of {} code{} which no $var declares", if skipped == 1 { "" } else { "s" },
                                     unknown.len(), if unknown.len() == 1 { "" } else { "s" }));
    }
    let end = b.now().unwrap_or(0);
    b.flush(out).map_err(io)?;
    if !b.blackouts.is_empty() {
        let mut s = Vec::new();
        varint(&mut s, b.blackouts.len() as u64);
        let mut t0 = 0;
        for &(on, t) in &b.blackouts {
            s.push(on as u8);
            varint(&mut s, t - t0);
            t0 = t;
        }
        out.write_all(&[2]).and_then(|_| out.write_all(&(8 + s.len() as u64).to_be_bytes())).and_then(|_| out.write_all(&s)).map_err(io)?;
    }
    let mut geom = Vec::new();
    for k in &b.kinds {
        varint(&mut geom, match k {
            Kind::Bits(n) => *n as u64,
            Kind::Real => 0,
            Kind::Str => 0xFFFF_FFFF,
        });
    }
    let z = zlib(&geom, 9);
    let mut g = vec![3u8];
    u64be(&mut g, 24 + z.len() as u64);
    u64be(&mut g, geom.len() as u64);
    u64be(&mut g, b.kinds.len() as u64);
    g.extend_from_slice(&z);
    out.write_all(&g).map_err(io)?;
    let hier = hierarchy(&h);
    let z = lz4_flex::block::compress(&hier);
    let mut g = vec![6u8];
    u64be(&mut g, 16 + z.len() as u64);
    u64be(&mut g, hier.len() as u64);
    g.extend_from_slice(&z);
    out.write_all(&g).map_err(io)?;
    out.seek(SeekFrom::Start(0)).map_err(io)?;
    out.write_all(&header_block(&h, &b, end)).map_err(io)?;
    out.flush().map_err(io)?;
    Ok(Done { vars: h.vars, signals: b.kinds.len(), changes: b.changes, tables, from_types })
}

/// The FST of a dump by default: its name with .fst (tb.vcd -> tb.fst, tb -> tb.fst).
fn fst_name(vcd: &str) -> PathBuf {
    Path::new(vcd).with_extension("fst")
}

/// The types file of a dump: its name with .types.json (tb.vcd -> tb.types.json), when there is one.
fn types_beside(vcd: &str) -> Option<PathBuf> {
    let p = Path::new(vcd).with_extension("types.json");
    p.exists().then_some(p)
}

pub fn fst_cmd(args: &[String]) -> ExitCode {
    let (mut waves, mut out, mut types, mut no_types, mut quiet) = (None::<String>, None::<String>, None::<String>, false, false);
    let mut map: Vec<(String, String)> = Vec::new();
    let (mut limit, mut large) = (BLOCK, LARGE);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--waves" => waves = it.next().cloned(),
            "--out" | "-o" => out = it.next().cloned(),
            "--types" => types = it.next().cloned(),
            "--no-types" => no_types = true,
            "--quiet" | "-q" => quiet = true,
            "--block-bytes" | "--large-bytes" => match it.next().and_then(|n| n.parse::<u64>().ok()) {
                Some(n) if a == "--block-bytes" => limit = n as usize,
                Some(n) => large = n,
                None => {
                    eprintln!("sva: {a} N, a number of bytes");
                    return ExitCode::from(2);
                }
            },
            "--map" => match it.next().and_then(|m| m.split_once('=')) {
                Some((a, b)) if !a.is_empty() && !b.is_empty() => map.push((a.into(), b.into())),
                _ => {
                    eprintln!("sva: --map DUMP=TYPES, a scope of the dump and the one of the types file (top.dut_i=dut)");
                    return ExitCode::from(2);
                }
            },
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
    let fail = |e: String| {
        eprintln!("sva: {e}");
        ExitCode::from(2)
    };
    {
        let mut f = match std::fs::File::open(&waves) {
            Ok(f) => std::io::BufReader::new(f),
            Err(e) => return fail(format!("{waves}: {e}")),
        };
        if fst_reader::is_fst_file(&mut f) {
            return fail(format!("{waves}: already an FST (sva vcd writes it as VCD text)"));
        }
    }
    let target = out.map_or_else(|| fst_name(&waves), PathBuf::from);
    if target.canonicalize().ok().is_some_and(|t| Path::new(&waves).canonicalize().ok() == Some(t)) {
        return fail(format!("{waves}: the FST would replace the dump: --out another file"));
    }
    let tfile = if no_types { None } else { types.map(PathBuf::from).or_else(|| types_beside(&waves)) };
    if !map.is_empty() && tfile.is_none() {
        eprintln!("sva: {waves}: --map given, but no types file ({} beside the dump, or --types){}",
                  Path::new(&waves).with_extension("types.json").file_name().unwrap_or_default().to_string_lossy(),
                  if no_types { ": --no-types" } else { "" });
    }
    let loaded = match &tfile {
        Some(p) => match types_enums(p) {
            Ok(mut t) => {
                t.map.extend(map);
                Some(t)
            }
            Err(e) => return fail(format!("{}: {e}", p.display())),
        },
        None => None,
    };
    // written beside the target, renamed over it when complete: a reader never sees half an FST. The part is this
    // run's (tb.fst.<pid>.part, made new: never another run's file, nor the dump): two runs at once each write their
    // own, the last one renamed stays; a run killed leaves its part, which no other run takes
    let part = target.with_file_name(format!("{}.{}.part", target.file_name().unwrap_or_default().to_string_lossy(), std::process::id()));
    let file = match std::fs::OpenOptions::new().write(true).create_new(true).open(&part) {
        Ok(f) => f,
        Err(e) => return fail(format!("{}: {e}", part.display())),
    };
    let mut o = std::io::BufWriter::with_capacity(1 << 20, file);
    let mut log = Log::new(&waves, quiet, large);
    let r = convert(&waves, &mut o, loaded.as_ref(), limit, &mut log);
    log.finish();
    let r = r.and_then(|d| {
        o.into_inner().map_err(|e| format!("{}: {e}", part.display()))?.sync_all().map_err(|e| format!("{}: {e}", part.display()))?;
        std::fs::rename(&part, &target).map_err(|e| format!("{}: {e}", target.display()))?;
        Ok(d)
    });
    match r {
        Ok(d) => {
            if !quiet {
                let types = match (&tfile, d.from_types) {
                    (Some(p), (t, n)) if n > 0 => format!(", {t} of them from {} ({n} variable{})",
                                                          p.file_name().unwrap_or_default().to_string_lossy(), if n == 1 { "" } else { "s" }),
                    (Some(p), _) => format!(", none from {}", p.file_name().unwrap_or_default().to_string_lossy()),
                    _ => String::new(),
                };
                println!("{}: {} variables ({} signals), {} value changes, {} enum table{}{types}", target.display(), d.vars,
                         d.signals, d.changes, d.tables, if d.tables == 1 { "" } else { "s" });
            }
            ExitCode::SUCCESS
        }
        Err(e) => {
            let _ = std::fs::remove_file(&part);
            fail(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn varints_as_fstapi_writes_them() {
        let mut o = Vec::new();
        varint(&mut o, 300);
        assert_eq!(o, [0xac, 0x02]);
        for (v, b) in [(1i64, vec![1u8]), (63, vec![63]), (64, vec![0xc0, 0]), (-1, vec![0x7f]), (-65, vec![0xbf, 0x7f])] {
            let mut o = Vec::new();
            svarint(&mut o, v);
            assert_eq!(o, b, "{v}");
        }
    }

    #[test]
    fn timescales_as_exponents() {
        assert_eq!(exponent("1ns"), Some(-9));
        assert_eq!(exponent("10 ps"), Some(-11));
        assert_eq!(exponent("100fs"), Some(-13));
        assert_eq!(exponent("1 s"), Some(0));
        assert_eq!(exponent("3ns"), None);
    }

    #[test]
    fn strings_unescape_as_fstapi_reads_them() {
        assert_eq!(unescape(b"a\\040b"), b"a b");
        assert_eq!(unescape(b"q\\\"\\'\\?\\\\"), b"q\"'?\\");
        assert_eq!(unescape(b"\\t\\n\\x41\\303\\251"), b"\t\nA\xc3\xa9");
        assert_eq!(unescape(b"end\\"), b"end\\");
    }

    #[test]
    fn questa_enums_from_describe() {
        let t = describe_enum("Verilog enum: (2 downto 0) [5 enumeration values]\n  (IDLE=0,START=1,DATA=2,STOP=3,ERROR=4)").unwrap();
        assert_eq!(t.0, 3);
        assert_eq!(t.1[4], (4, "ERROR".into()));
        let t = describe_enum("Verilog enum: (1 downto 0) [2 enumeration values]\n  (NEG=-1,\n ZERO=0)").unwrap();
        assert_eq!(t.1, vec![(0, "ZERO".into()), (3, "NEG".into())]);
        assert!(describe_enum("Register [7:0]").is_none());
        assert!(describe_enum("Verilog enum: (1 downto 0) [3 enumeration values]\n  (A=0,B=1)").is_none(), "a value it does not read");
    }

    #[test]
    fn paths_as_svtypes_finds_them() {
        let t: HashMap<String, Table> = [("tb.u.state".to_string(), (2, vec![(0, "A".to_string())])), ("tb.arr".to_string(), (2, vec![]))].into();
        let none = HashSet::new();
        assert!(lookup(&t, "tb.u.state", &none).is_some());
        assert!(lookup(&t, "tb.arr[3]", &none).is_some());
        assert!(lookup(&t, "tb.arr.[3][1]", &none).is_some());
        assert!(lookup(&t, "TOP.tb.u.state", &none).is_none());
        let tops = added_tops(&t.keys().cloned().collect(), &["TOP.tb.u.state".to_string()]);
        assert!(lookup(&t, "TOP.tb.u.state", &tops).is_some());
        assert_eq!(remap("top.dut_i.state", &[("top.dut_i".into(), "dut".into()), ("top".into(), "x".into())]), "dut.state");
        assert_eq!(table_text("s_t", &(2, vec![(0, "A".into()), (3, "D".into())])), b"s_t 2 A D 00 11");
        let p = |r: &str| ref_path(&r.split(' ').map(|w| w.as_bytes().to_vec()).collect::<Vec<_>>());
        assert_eq!([p("state[1:0]"), p("state [1:0]"), p("mem[3]"), p("mem[3] [7:0]"), p("x[3][1]"), p("\\a.b[0]"), p("[3:0]")],
                   ["state", "state", "mem.[3]", "mem.[3]", "x.[3][1]", "\\a.b[0]", "[3:0]"]);
    }
}
