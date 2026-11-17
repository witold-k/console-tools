// SPDX-License-Identifier: Apache-2.0
//! Integration tests for the native WASI host, using fake OS executables.
//! Actual WebAssembly execution is separately covered by scripts/wasm.py test.
use std::process::Command;

#[test]
fn rejects_unknown_tool() {
    let result = Command::new(env!("CARGO_BIN_EXE_wasm-host"))
        .arg("not-a-tool").output().unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("Unknown tool"));
}

#[test]
fn reuses_xcat_argument_validation() {
    let result = Command::new(env!("CARGO_BIN_EXE_wasm-host"))
        .args(["xcat", "--does-not-exist"]).output().unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("Unknown argument"));
}

#[cfg(unix)]
mod unix {
    use std::{
        env, fs,
        os::unix::fs::PermissionsExt,
        path::PathBuf,
        process::Command,
        time::{SystemTime, UNIX_EPOCH},
    };

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let dir = env::temp_dir().join(format!("console-tools-host-test-{}-{n}", std::process::id()));
            fs::create_dir(&dir).unwrap();
            Self(dir)
        }
        fn file(&self, name: &str, data: &[u8]) -> PathBuf {
            let path = self.0.join(name);
            fs::write(&path, data).unwrap();
            path
        }
        fn script(&self, name: &str, contents: &str) {
            let file = self.file(name, contents.as_bytes());
            fs::set_permissions(file, fs::Permissions::from_mode(0o755)).unwrap();
        }
        fn command(&self, tool: &str) -> Command {
            let mut command = Command::new(env!("CARGO_BIN_EXE_wasm-host"));
            let path = format!("{}:{}", self.0.display(), env::var("PATH").unwrap_or_default());
            command.arg(tool).env("PATH", path)
                .env("CONSOLE_TOOLS_WASM_DIR", &self.0)
                .env("WAYLAND_DISPLAY", "test")
                .env_remove("DISPLAY")
                .env("MOCK_TMUX_CAPTURE", self.0.join("scrollback"))
                .env("CAPTURED_CLIPBOARD", self.0.join("clipboard"));
            command
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
    }

    #[test]
    fn cptx_large_scrollback_through_host_and_clipboard() {
        let f = Fixture::new();
        // More than a typical pipe buffer: verifies the reader/writer do not deadlock.
        let mut capture = vec![b'A'; 256 * 1024];
        capture.push(b'\n');
        f.file("scrollback", &capture);
        f.file("cptx.wasm", b"fake module");
        f.script("tmux", "#!/bin/sh\nexec /bin/cat \"$MOCK_TMUX_CAPTURE\"\n");
        f.script("wasmtime", "#!/bin/sh\nexec /bin/cat\n");
        f.script("wl-copy", "#!/bin/sh\nexec /bin/cat > \"$CAPTURED_CLIPBOARD\"\n");

        let output = f.command("cptx").output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        assert_eq!(fs::read(f.0.join("clipboard")).unwrap(), capture);
    }

    #[test]
    fn xcat_calls_wasm_scanner_and_uses_shared_clipboard() {
        let f = Fixture::new();
        f.file("xcat.wasm", b"fake module");
        f.script("wasmtime", "#!/bin/sh\nprintf '===== ./sample.rs =====\\nhello\\n'\n");
        f.script("wl-copy", "#!/bin/sh\nexec /bin/cat > \"$CAPTURED_CLIPBOARD\"\n");
        let root = f.0.join("source");
        fs::create_dir(&root).unwrap();
        let config = f.0.join("config.json");
        let output = f.command("xcat")
            .args(["-d", root.to_str().unwrap(), "-c", config.to_str().unwrap()])
            .output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        let clipboard = fs::read_to_string(f.0.join("clipboard")).unwrap();
        assert!(clipboard.contains("sample.rs"));
        assert!(clipboard.contains("hello"));
    }
}
