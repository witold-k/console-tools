// SPDX-License-Identifier: Apache-2.0
//! Shared task-output format for native and WASI xcat.
use std::path::Path;

pub fn format_task_output(
    file: &Path,
    stdout: &[u8],
    stderr: &[u8],
    status: &str,
) -> String {
    let mut content = format!("\n===== EXECUTABLE OUTPUT: {} =====\n", file.display());
    content.push_str("===== STDOUT =====\n");
    content.push_str(&String::from_utf8_lossy(stdout));
    if !content.ends_with('\n') { content.push('\n'); }
    content.push_str("===== STDERR =====\n");
    content.push_str(&String::from_utf8_lossy(stderr));
    if !content.ends_with('\n') { content.push('\n'); }
    content.push_str(&format!("===== EXIT STATUS: {status} =====\n"));
    content
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn output_sections_and_newlines() {
        assert_eq!(
            format_task_output(Path::new("example.sh"), b"ok", b"", "0"),
            "\n===== EXECUTABLE OUTPUT: example.sh =====\n===== STDOUT =====\nok\n===== STDERR =====\n===== EXIT STATUS: 0 =====\n"
        );
    }
}
