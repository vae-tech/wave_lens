//! The evaluator's inputs and outputs: the sampled values (`Column`, `Trace` and its JSON), the options, and the results
//! (`Results`, `Outcome`, `Attempt`, …) with the JSON of docs/sva/results.schema.json.

use crate::ast::Kind;
use crate::value::V;
use serde::ser::SerializeSeq;
use serde::{Deserialize, Serialize, Serializer};
use std::collections::BTreeMap;

// ---------------------------------------------------------------- input

/// The sampled values of one signal: `v[cycle]` / `x[cycle]` (`x` empty when every value is known). Cycles before the
/// first read the initial value of the type: x for 4-state signals, 0 for 2-state ones (`bit`, `int`, ...).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Column {
    pub width: u32,
    pub v: Vec<u64>,
    pub x: Vec<u64>,
    pub two_state: bool,
}

impl Column {
    pub fn new(width: u32, vals: &[V]) -> Column {
        let x: Vec<u64> = if vals.iter().any(|v| v.x != 0) { vals.iter().map(|v| v.x).collect() } else { Vec::new() };
        Column { width: width.clamp(1, 64), v: vals.iter().map(|v| v.v).collect(), x, two_state: false }
    }
    pub fn known(width: u32, vals: &[u64]) -> Column {
        Column { width: width.clamp(1, 64), v: vals.to_vec(), x: Vec::new(), two_state: false }
    }
    pub fn len(&self) -> usize {
        self.v.len()
    }
    pub fn is_empty(&self) -> bool {
        self.v.is_empty()
    }
    pub fn at(&self, c: i64) -> V {
        if c < 0 || c as usize >= self.v.len() {
            return if self.two_state { V::known(0) } else { V::unknown(self.width) };
        }
        V::new(self.v[c as usize], self.x.get(c as usize).copied().unwrap_or(0))
    }
}

/// Signal values at the sampling points of one clock: `signals[name]` has one value per cycle, `times[cycle]` is the
/// time of the clock edge (in `unit`, default ps) and goes into the results unchanged.
#[derive(Clone, Debug, Default)]
pub struct Trace {
    pub cycles: usize,
    pub times: Vec<u64>,
    pub unit: Option<String>,
    pub signals: BTreeMap<String, Column>,
    /// What reading the JSON trace changed, per signal (values cut to 64 bits); the outcomes that read it say so.
    pub warnings: BTreeMap<String, String>,
}

impl Trace {
    pub fn add(&mut self, name: &str, col: Column) {
        self.cycles = self.cycles.max(col.len());
        self.signals.insert(name.to_string(), col);
    }
}

/// JSON: `{"cycles"?: n, "times"?: [..], "unit"?: "ps", "signals": {"name": [values]}, "widths"?: {"name": w},
/// "two_state"?: ["name"]}`; a value is a number, `null` (x), or a string of binary digits (`"10x1"`) or of hex
/// digits after `h` (`"h1f"`).
impl<'de> Deserialize<'de> for Trace {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Trace, D::Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Raw {
            #[serde(default)]
            cycles: Option<usize>,
            #[serde(default)]
            times: Vec<u64>,
            #[serde(default)]
            unit: Option<String>,
            signals: BTreeMap<String, Vec<serde_json::Value>>,
            #[serde(default)]
            widths: BTreeMap<String, u32>,
            #[serde(default)]
            two_state: Vec<String>,
        }
        let r = Raw::deserialize(d)?;
        if let Some((name, _)) = r.widths.iter().find(|(_, w)| **w == 0) {
            return Err(serde::de::Error::custom(format!("widths: {name}: a width is 1 or more")));
        }
        let mut t = Trace { cycles: 0, times: r.times, unit: r.unit, signals: BTreeMap::new(), warnings: BTreeMap::new() };
        for (name, vals) in r.signals {
            let mut out = Vec::with_capacity(vals.len());
            let mut w = 1u32;
            for (k, v) in vals.iter().enumerate() {
                let (val, vw) = match v {
                    serde_json::Value::Null => (V::unknown(64), 0),
                    serde_json::Value::Number(n) => match n.as_u64() {
                        Some(n) => (V::known(n), (64 - n.leading_zeros()).max(1)),
                        None => return Err(serde::de::Error::custom(format!("signal {name}, cycle {k}: {n} is not a value"))),
                    },
                    serde_json::Value::String(s) => match V::parse(s) {
                        Some(x) => {
                            let digits = s.trim().trim_start_matches(['h', 'H']).chars().filter(|c| *c != '_').count();
                            let bits = if s.trim().starts_with(['h', 'H']) { 4 * digits } else { digits };
                            if bits > 64 {
                                t.warnings.insert(name.clone(), format!("{name}: values wider than 64 bits keep their low 64 bits (cycle {k})"));
                            }
                            x
                        }
                        None => return Err(serde::de::Error::custom(format!("signal {name}, cycle {k}: '{s}' is not a value"))),
                    },
                    other => return Err(serde::de::Error::custom(format!("signal {name}, cycle {k}: {other} is not a value"))),
                };
                w = w.max(vw);
                out.push((val, vw));
            }
            let w = r.widths.get(&name).copied().unwrap_or(w).clamp(1, 64);
            let m = crate::value::mask(w);
            // a value written with fewer digits than the width: an unknown top digit fills the rest (like 'hx)
            let fit = |(v, vw): &(V, u32)| {
                let fill = if *vw == 0 || (*vw < w && v.x >> (vw - 1) & 1 == 1) { m & !crate::value::mask(*vw) } else { 0 };
                V::new(v.v & m, (v.x | fill) & m)
            };
            let mut col = Column::new(w, &out.iter().map(fit).collect::<Vec<_>>());
            col.two_state = r.two_state.contains(&name);
            t.add(&name, col);
        }
        t.cycles = r.cycles.unwrap_or(t.cycles);
        if !t.times.is_empty() && t.times.len() < t.cycles {
            return Err(serde::de::Error::custom(format!("times: {} for {} cycles (a time per cycle, or none)", t.times.len(), t.cycles)));
        }
        Ok(t)
    }
}

/// What an unknown boolean does: `fail` the attempt (with a note naming it), or read as `false` (IEEE 1800-2017).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum XMode {
    #[default]
    Fail,
    False,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Options {
    /// List vacuous attempts too (debugging; they are always counted).
    pub vacuous: bool,
    /// The per-cycle lane string of every assertion.
    pub lane: bool,
    pub x: XMode,
    /// Threads of one sequence of one attempt; more are dropped and the results say so.
    pub max_threads: usize,
    /// Matches of a cover listed with their traces (all are counted).
    pub cover_traces: usize,
    /// Attempts start at cycles `from .. to`; the evaluation ends at `to` (the end of the trace when absent).
    pub from: usize,
    pub to: Option<usize>,
    /// Attempts in the same state are stepped once (default); false steps each one (for tests).
    pub merge: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options { vacuous: false, lane: true, x: XMode::Fail, max_threads: 256, cover_traces: 100, from: 0, to: None, merge: true }
    }
}

// ---------------------------------------------------------------- output

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Pass,
    Fail,
    Vacuous,
    Active,
    Disabled,
    /// The thread limit dropped threads of this attempt: its result is not known.
    Capped,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Stats {
    pub attempts: usize,
    pub pass: usize,
    pub fail: usize,
    pub vacuous: usize,
    pub disabled: usize,
    pub active: usize,
    pub capped: usize,
    /// Covers: every match (a `cover sequence` can match several times in one attempt).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub matches: Option<usize>,
}

/// `[id, cycle]`, or `[id, cycle, value]` when the step compares a bus (the value of its left side).
#[derive(Clone, Debug, PartialEq)]
pub struct TraceStep {
    pub id: String,
    pub cycle: usize,
    pub value: Option<serde_json::Value>,
}

impl Serialize for TraceStep {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        let mut q = s.serialize_seq(Some(2 + self.value.is_some() as usize))?;
        q.serialize_element(&self.id)?;
        q.serialize_element(&self.cycle)?;
        if let Some(v) = &self.value {
            q.serialize_element(v)?;
        }
        q.end()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Attempt {
    pub start: usize,
    pub end: usize,
    pub result: Status,
    pub trace: Vec<TraceStep>,
    /// The trace keeps the first and the last steps of a long attempt; the ones between were dropped.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub truncated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub failed_at: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    /// Why it failed (or has no verdict), for grouping: `note` says the same in words.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<Reason>,
    /// Implications (the assertion's top property): the cycles at which the antecedent matched (of more than 64, the
    /// first 32 and the latest 32: the latency takes the latest before the consequent).
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub ante_end: Vec<usize>,
    /// `ante_end` left matches out between its first and its latest ones.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub ante_truncated: bool,
}

/// `kind`: `no_match` (no thread of a sequence left), `expected` (a boolean that had to hold did not), `range` (not
/// within a delay or `eventually` range), `unknown` (an x was read), `not_held` (the property under `not` held),
/// `strong_end` (a strong operator at the end of the dump), `capped` (the thread limit: no verdict). `step`: the element
/// it is about, `cycle`: where.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Reason {
    pub kind: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step: Option<String>,
    pub cycle: usize,
}

/// A sequence element: `role` is `ante` / `cons` (the antecedent / consequent of implication `group`, counted from 0 in
/// source order), `cond` (the condition of a `throughout`) or `seq` (a sequence property, a cover).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct StepInfo {
    pub id: String,
    pub label: String,
    pub role: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group: Option<u32>,
}

/// The results of one assertion. `file`, `scope`, `signals` (name -> path in the dump) and, for an assertion on
/// another clock than the document's, `clock` and `cycles` are filled in by the caller that knows the dump.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Outcome {
    pub name: String,
    pub kind: Kind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
    pub line: usize,
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scope: Option<String>,
    #[serde(skip_serializing_if = "BTreeMap::is_empty")]
    pub signals: BTreeMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub clock: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cycles: Option<Vec<u64>>,
    pub steps: Vec<StepInfo>,
    pub stats: Stats,
    pub attempts: Vec<Attempt>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lane: Option<String>,
    /// Signals the trace does not have: the assertion was not evaluated.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub missing: Vec<String>,
    /// Limits that were hit (thread caps).
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub notes: Vec<String>,
}

impl Outcome {
    /// The first failing attempt.
    pub fn first_fail(&self) -> Option<&Attempt> {
        self.attempts.iter().find(|a| a.result == Status::Fail)
    }
}

/// One evaluation: `cycles[k]` is the time of cycle k of `clock`; `unit` is the unit of the times.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Results {
    pub clock: String,
    pub unit: String,
    pub cycles: Vec<u64>,
    pub assertions: Vec<Outcome>,
}

