// SPDX-License-Identifier: Apache-2.0
//! Shared runtime support for core-only WASI binaries.
use core::ffi::c_void;

// LLVM may lower slice comparisons to libc memcmp even in a no_std build.
// Provide the symbol locally so wasm2jar does not require an env.memcmp import.
// Volatile reads prevent LLVM from folding this implementation back into memcmp.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn memcmp(a:*const c_void,b:*const c_void,n:usize)->i32 {
    let a=a.cast::<u8>();
    let b=b.cast::<u8>();
    let mut i=0;
    while i<n {
        let x=unsafe{core::ptr::read_volatile(a.add(i))};
        let y=unsafe{core::ptr::read_volatile(b.add(i))};
        if x!=y{return x as i32-y as i32}
        i+=1;
    }
    0
}

