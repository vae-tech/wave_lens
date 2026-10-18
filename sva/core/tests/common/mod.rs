//! The corpus tests/sva/*.sv, shared by the integration tests.

use std::path::{Path, PathBuf};

pub fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/sva")
}

/// (file name, text) of every corpus file, sorted.
pub fn corpus() -> Vec<(String, String)> {
    let mut files: Vec<_> = std::fs::read_dir(corpus_dir()).unwrap().map(|e| e.unwrap().path()).filter(|p| p.extension().is_some_and(|e| e == "sv")).collect();
    files.sort();
    files.into_iter().map(|p| (p.file_name().unwrap().to_string_lossy().into_owned(), std::fs::read_to_string(&p).unwrap())).collect()
}
