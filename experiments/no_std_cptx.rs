#![no_std]
#![no_main]
use core::panic::PanicInfo;
#[path = "../src/no_std_runtime.rs"]
mod no_std_runtime;
#[path = "../src/cli/cptx.rs"]
mod cptx_cli;
#[path = "../src/vcs_policy.rs"]
mod vcs_policy;
use cptx_cli::{parse_args, Mode, HELP, USAGE};
#[panic_handler] fn panic(_: &PanicInfo) -> ! { loop {} }
#[repr(C)] struct Iovec { buf: *mut u8, len: usize }
#[repr(C)] struct Ciovec { buf: *const u8, len: usize }
#[link(wasm_import_module = "wasi_snapshot_preview1")]
unsafe extern "C" {
    fn args_sizes_get(argc: *mut i32, size: *mut i32) -> i32;
    fn args_get(argv: *mut *mut u8, buf: *mut u8) -> i32;
    fn fd_read(fd: i32, iovs: *const Iovec, count: i32, nread: *mut i32) -> i32;
    fn fd_write(fd: i32, iovs: *const Ciovec, count: i32, nwritten: *mut i32) -> i32;
    fn proc_exit(code: i32) -> !;
    fn cptx_command(args: *const u8, args_len: i32, out: *mut u8, cap: i32) -> i32;
    fn cptx_cwd(out: *mut u8, cap: i32) -> i32;
}
fn fail() -> ! { unsafe { proc_exit(1) } }
fn usage_error() -> ! {
    write_all(2, b"cptx: ");
    write_all(2, USAGE.as_bytes());
    write_all(2, b"\n");
    fail()
}
fn write_all(fd: i32, bytes: &[u8]) {
    let mut pos = 0;
    while pos < bytes.len() {
        let vec = Ciovec { buf: unsafe { bytes.as_ptr().add(pos) },
                           len: bytes.len() - pos };
        let mut done = 0i32;
        if unsafe { fd_write(fd, &vec, 1, &mut done) } != 0
            || done <= 0 || done as usize > bytes.len() - pos { fail(); }
        pos += done as usize;
    }
}
struct WasiExecutor;
impl vcs_policy::Executor for WasiExecutor {
    fn run(&mut self, args: &[&str], out: &mut [u8]) -> Result<usize, ()> {
        let mut buf = [0u8; 512];
        let mut pos = 0usize;
        for arg in args {
            if pos + arg.len() + 1 > buf.len() { return Err(()); }
            buf[pos..pos + arg.len()].copy_from_slice(arg.as_bytes());
            pos += arg.len();
            buf[pos] = 0;
            pos += 1;
        }
        let n = unsafe { cptx_command(buf.as_ptr(), pos as i32, out.as_mut_ptr(), out.len() as i32) };
        if n < 0 || n as usize > out.len() { Err(()) } else { Ok(n as usize) }
    }
}
fn host_text(mode: Mode<'_>) {
    let mut out = [0u8; 8192];
    let n = match mode {
        Mode::Path => unsafe { cptx_cwd(out.as_mut_ptr(), out.len() as i32) },
        Mode::Version(remote) => match vcs_policy::remote_url(remote, &mut WasiExecutor, &mut out) {
            Ok(n) => n as i32,
            Err(msg) => { write_all(2, msg.as_bytes()); write_all(2, b"\n"); fail() }
        },
        _ => return,
    };
    if n < 0 || n as usize > out.len() { fail(); }
    write_all(1, &out[..n as usize]);
}
#[unsafe(no_mangle)]
pub extern "C" fn _start() {
    let mut argc = 0i32;
    let mut size = 0i32;
    if unsafe { args_sizes_get(&mut argc, &mut size) } != 0 { fail(); }
    if argc < 1 || argc > 3 || size < argc || size > 512 { usage_error(); }
    let mut argv = [core::ptr::null_mut::<u8>(); 3];
    let mut argbuf = [0u8; 512];
    if unsafe { args_get(argv.as_mut_ptr(), argbuf.as_mut_ptr()) } != 0 { fail(); }
    let mut arguments = [""; 2];
    for i in 1..argc as usize {
        let ptr = argv[i];
        let offset = unsafe { ptr.offset_from(argbuf.as_ptr()) };
        if offset < 0 || offset as usize >= argbuf.len() { usage_error(); }
        let tail = &argbuf[offset as usize..];
        let len = tail.iter().position(|&byte| byte == 0).unwrap_or(tail.len());
        arguments[i - 1] = match core::str::from_utf8(&tail[..len]) {
            Ok(arg) => arg,
            Err(_) => usage_error(),
        };
    }
    match parse_args(&arguments[..argc as usize - 1]) {
        Ok(Mode::Help) => { write_all(1, HELP.as_bytes()); return; }
        Ok(Mode::Buffer) => {}
        Ok(mode @ (Mode::Path | Mode::Version(_))) => { host_text(mode); return; }
        Err(_) => usage_error(),
    }
    let mut buf = [0u8; 16384];
    let mut continuation = 0u8;
    let mut next_min = 0x80u8;
    let mut next_max = 0xbfu8;
    loop {
        let vec = Iovec { buf: buf.as_mut_ptr(), len: buf.len() };
        let mut read = 0i32;
        if unsafe { fd_read(0, &vec, 1, &mut read) } != 0
            || read < 0 || read as usize > buf.len() { fail(); }
        if read == 0 {
            if continuation != 0 {
                write_all(2, b"cptx: invalid UTF-8\n"); fail();
            }
            return;
        }
        let chunk = &buf[..read as usize];
        for &byte in chunk {
            if continuation != 0 {
                if byte < next_min || byte > next_max {
                    write_all(2, b"cptx: invalid UTF-8\n"); fail();
                }
                continuation -= 1;
                next_min = 0x80;
                next_max = 0xbf;
            } else if byte < 0x80 {
                // ASCII
            } else if byte >= 0xc2 && byte <= 0xdf {
                continuation = 1;
            } else if byte == 0xe0 {
                continuation = 2; next_min = 0xa0;
            } else if byte >= 0xe1 && byte <= 0xec {
                continuation = 2;
            } else if byte == 0xed {
                continuation = 2; next_max = 0x9f;
            } else if byte >= 0xee && byte <= 0xef {
                continuation = 2;
            } else if byte == 0xf0 {
                continuation = 3; next_min = 0x90;
            } else if byte >= 0xf1 && byte <= 0xf3 {
                continuation = 3;
            } else if byte == 0xf4 {
                continuation = 3; next_max = 0x8f;
            } else {
                write_all(2, b"cptx: invalid UTF-8\n"); fail();
            }
        }
        write_all(1, chunk);
    }
}
