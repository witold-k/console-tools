// SPDX-License-Identifier: Apache-2.0
//! Shared core-only CLI contract for native and no_std WASI cptx.
pub const HELP: &str = "cptx — copy text to the desktop clipboard

Usage: cptx [OPTION] [REMOTE]

Options:
  -b, --buffer           Copy the current tmux pane and scrollback (default)
  -p, --path             Copy the absolute current working directory
  -v, --version [REMOTE] Copy the version-control remote URL (default: origin)
  -h, --help             Show this help

Supported version-control systems: Git, Subversion (SVN), Mercurial (hg), Pijul.
Requires a supported clipboard backend (xclip, xsel, or wl-copy).
Buffer mode also requires tmux.
";

pub const USAGE: &str = "Usage: cptx [-b|--buffer|-p|--path|-v|--version [REMOTE]|-h|--help]";

#[derive(Debug, PartialEq, Eq)]
pub enum Mode<'a> {
    Help,
    Buffer,
    Path,
    Version(&'a str),
}

pub fn parse_args<'a>(args: &[&'a str]) -> Result<Mode<'a>, &'static str> {
    match args {
        [] | ["-b" | "--buffer"] => Ok(Mode::Buffer),
        ["-h" | "--help"] => Ok(Mode::Help),
        ["-p" | "--path"] => Ok(Mode::Path),
        ["-v" | "--version"] => Ok(Mode::Version("origin")),
        ["-v" | "--version", remote] if !remote.is_empty() && !remote.starts_with('-') => Ok(Mode::Version(remote)),
        _ => Err(USAGE),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn modes() {
        assert_eq!(parse_args(&[]), Ok(Mode::Buffer));
        assert_eq!(parse_args(&["-b"]), Ok(Mode::Buffer));
        assert_eq!(parse_args(&["--buffer"]), Ok(Mode::Buffer));
        assert_eq!(parse_args(&["-p"]), Ok(Mode::Path));
        assert_eq!(parse_args(&["--path"]), Ok(Mode::Path));
        assert_eq!(parse_args(&["-v"]), Ok(Mode::Version("origin")));
        assert_eq!(parse_args(&["--version", "upstream"]), Ok(Mode::Version("upstream")));
        assert_eq!(parse_args(&["--help"]), Ok(Mode::Help));
        assert!(parse_args(&["-p", "extra"]).is_err());
        assert!(parse_args(&["--help", "extra"]).is_err());
        assert!(parse_args(&["--version", "--help"]).is_err());
        assert!(parse_args(&["--unknown"]).is_err());
    }
}
