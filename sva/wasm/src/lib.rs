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
