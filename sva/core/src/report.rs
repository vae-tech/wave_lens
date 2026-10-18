//! `sva parse` as text: the errors and warnings with the source line and a caret, then the scopes, declarations and
//! assertions of the file. The golden files of the corpus (tests/sva/golden/) are this text.

use crate::ast::*;
use crate::print::Printer;
use crate::{Parsed, SvaError};
use std::fmt::Write;

/// `file:line:col: error: msg`, the line, a caret under the offending token.
pub fn diagnostic(e: &SvaError, kind: &str, src: &str, file: &str) -> String {
    let mut s = format!("{file}:{}:{}: {kind}: {}\n", e.line, e.col, e.msg);
    if let Some(line) = src.lines().nth(e.line.saturating_sub(1)) {
        let line = line.trim_end();
        let width = if e.end > e.start && src.get(e.start..e.end).is_some_and(|t| !t.contains('\n')) { src[e.start..e.end].chars().count() } else { 1 };
        let pad: String = line.chars().take(e.col.saturating_sub(1)).map(|c| if c == '\t' { '\t' } else { ' ' }).collect();
        let _ = writeln!(s, "{:>5} | {line}", e.line);
        let _ = writeln!(s, "      | {pad}{}", "^".repeat(width.max(1)));
    }
    s
}

fn signal(s: &SignalRef) -> String {
    let mut t = s.name.clone();
    if let Some(w) = s.width {
        let _ = write!(t, "[>={w}]");
    }
    if let Some(d) = s.declared {
        let _ = write!(t, ":{d}");
    }
    t
}

fn ports(ports: &[Port]) -> String {
    if ports.is_empty() {
        return String::new();
    }
    let p: Vec<String> = ports
        .iter()
        .map(|p| {
            let mut s = if p.ty == "untyped" { p.name.clone() } else { format!("{} {}", p.ty, p.name) };
            if let Some(d) = &p.default {
                let _ = write!(s, " = {d}");
            }
            s
        })
        .collect();
    format!("({})", p.join(", "))
}

/// The whole description of a parsed file; `inline` prints the bodies of instances in the expressions.
pub fn describe(p: &Parsed, src: &str, file: &str, inline: bool) -> String {
    let pr = Printer { full: false, inline };
    let mut s = String::new();
    for e in &p.errors {
        s += &diagnostic(e, "error", src, file);
    }
    for w in &p.warnings {
        s += &diagnostic(w, "warning", src, file);
    }
    for sc in &p.scopes {
        let ports: Vec<String> = sc.ports.iter().map(|n| n.width.map_or(n.name.clone(), |w| format!("{}:{w}", n.name))).collect();
        let params: Vec<String> = sc.params.iter().map(|n| n.value.map_or(n.name.clone(), |v| format!("{}={v}", n.name))).collect();
        let _ = write!(s, "{} {}", sc.kind, sc.name);
        if !ports.is_empty() {
            let _ = write!(s, " ports {}", ports.join(" "));
        }
        if !params.is_empty() {
            let _ = write!(s, " params {}", params.join(" "));
        }
        s.push('\n');
    }
    for b in &p.binds {
        let conn: Vec<String> = b.ports.iter().map(|c| c.name.as_ref().map_or(c.expr.clone(), |n| format!(".{n}({})", c.expr))).collect();
        let inst = if b.instances.is_empty() { String::new() } else { format!(": {}", b.instances.join(", ")) };
        let _ = writeln!(s, "bind {}{inst} {} {} ({})", b.target, b.module, b.instance, conn.join(", "));
    }
    for d in &p.sequences {
        let clock = d.clock.as_ref().map_or(String::new(), |c| format!(" {c}"));
        let _ = writeln!(s, "sequence {}{}{clock}: {}", d.name, ports(&d.ports), pr.seq(&d.body));
    }
    for d in &p.properties {
        let clock = d.clock.as_ref().map_or(String::new(), |c| format!(" {c}"));
        let dis = d.disable.as_ref().map_or(String::new(), |e| format!(" disable iff ({e})"));
        let _ = writeln!(s, "property {}{}{clock}{dis}: {}", d.name, ports(&d.ports), pr.prop(&d.body));
    }
    for a in &p.assertions {
        let scope = a.scope.as_ref().map_or(String::new(), |n| format!(" in {n}"));
        let _ = writeln!(s, "{} {}{scope}, line {}", a.kind.word(), a.label, a.line);
        let dis = a.disable.as_ref().map_or(String::new(), |e| format!(" disable iff ({})", pr.expr(e)));
        let _ = writeln!(s, "  clock     {}{dis}", a.clock);
        if let Some(n) = &a.property {
            let _ = writeln!(s, "  property  {n}");
        }
        let _ = writeln!(s, "  expr      {}", pr.prop(&a.prop));
        for e in &a.elements {
            let _ = writeln!(s, "  {:<9} {}", e.id, e.label);
        }
        let _ = writeln!(s, "  signals   {}", a.signals.iter().map(signal).collect::<Vec<_>>().join(" "));
        if a.message.is_some() || a.severity.is_some() {
            let _ = writeln!(s, "  message   {} {:?}", a.severity.as_deref().unwrap_or("-"), a.message.as_deref().unwrap_or(""));
        }
        for f in &a.flags {
            let _ = writeln!(s, "  note      {f}");
        }
    }
    s
}
