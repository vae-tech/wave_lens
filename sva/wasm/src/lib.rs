//! sva-core for the page: JSON in, JSON out over a plain C ABI, so no wasm-bindgen and no generated glue.
//!
//! JS: `p = sva_alloc(n)`, copy the UTF-8 request into memory at p, `r = sva_run(p, n)`, read `sva_result_len()` bytes
//! at r (the response JSON, valid until the next call), `sva_free(p, n)`. Request and response: see `sva_core::run_json`.

use std::alloc::{alloc, dealloc, Layout};
use std::cell::RefCell;

thread_local! {
    static OUT: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
}

fn layout(len: usize) -> Layout {
    Layout::from_size_align(len.max(1), 1).unwrap()
}

#[no_mangle]
pub extern "C" fn sva_alloc(len: usize) -> *mut u8 {
    unsafe { alloc(layout(len)) }
}

/// # Safety
/// `ptr` must come from `sva_alloc(len)` and not be freed twice.
#[no_mangle]
pub unsafe extern "C" fn sva_free(ptr: *mut u8, len: usize) {
    dealloc(ptr, layout(len))
}

/// # Safety
/// `ptr .. ptr + len` must be a request written by the caller into memory from `sva_alloc`.
#[no_mangle]
pub unsafe extern "C" fn sva_run(ptr: *const u8, len: usize) -> *const u8 {
    let req = std::slice::from_raw_parts(ptr, len);
    let out = match std::str::from_utf8(req) {
        Ok(s) => sva_core::run_json(s),
        Err(_) => r#"{"errors":[{"line":0,"col":0,"msg":"request is not UTF-8"}]}"#.to_string(),
    };
    OUT.with(|o| {
        *o.borrow_mut() = out.into_bytes();
        o.borrow().as_ptr()
    })
}

#[no_mangle]
pub extern "C" fn sva_result_len() -> usize {
    OUT.with(|o| o.borrow().len())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// What wavelens/sva.js does: allocate, copy the request in, run, read the result, free. The answer as text (this
    /// crate has no JSON parser of its own: string checks do).
    fn call(req: &[u8]) -> String {
        let p = sva_alloc(req.len());
        unsafe {
            std::ptr::copy_nonoverlapping(req.as_ptr(), p, req.len());
            let r = sva_run(p, req.len());
            let out = std::slice::from_raw_parts(r, sva_result_len()).to_vec();
            sva_free(p, req.len());
            String::from_utf8(out).unwrap()
        }
    }

    #[test]
    fn parse_request_round_trip() {
        let v = call(br#"{"source": "a: assert property (@(posedge c) x |=> y);"}"#);
        assert!(v.contains(r#""label":"a""#) && v.contains(r#""errors":[]"#), "{v}");
    }

    #[test]
    fn eval_request_round_trip() {
        let v = call(br#"{"files": ["a: assert property (@(posedge c) x);"], "trace": {"signals": {"c": [0, 1], "x": [1, 0]}}}"#);
        assert!(v.contains(r#""pass":1"#) && v.contains(r#""fail":1"#), "{v}");
    }

    #[test]
    fn not_utf8_and_empty_requests() {
        assert!(call(&[0xff, 0xfe, b'{']).contains("request is not UTF-8"));
        assert!(call(b"").contains(r#""errors""#));
        let v = call(b"{}");
        assert_eq!(sva_result_len(), v.len(), "the result of the last call is what sva_result_len measures");
    }
}
