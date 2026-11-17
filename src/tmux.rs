// SPDX-License-Identifier: Apache-2.0
//! Single tmux capture implementation for native cptx and WASI host.
use std::{error::Error, io};
#[cfg(not(target_os = "wasi"))]
use std::process::Command;

#[cfg(not(target_os = "wasi"))]
pub fn capture() -> Result<String, Box<dyn Error>> {
    let output = Command::new("tmux")
        .args(["capture-pane", "-p", "-S", "-"])
        .output()?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr);
        return Err(io::Error::other(format!(
            "tmux capture-pane failed ({}): {}", output.status, detail.trim()
        )).into());
    }
    Ok(String::from_utf8(output.stdout)?)
}

 
// The host captures tmux output and pipes it to the same Rust application
// when it runs as WASI. No duplicate Java/Python program logic is needed.
#[cfg(target_os = "wasi")]
pub fn capture() -> Result<String, Box<dyn Error>> {
    use std::io::Read;
    let mut bytes = Vec::new();
    io::stdin().read_to_end(&mut bytes)?;
    Ok(String::from_utf8(bytes)?)
}
