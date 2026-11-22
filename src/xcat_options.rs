// SPDX-License-Identifier: Apache-2.0
//! Shared xcat argument parser used by native and WASI host.
use std::path::PathBuf;

#[derive(Debug, PartialEq, Eq)]
pub struct Options {
    pub dir: PathBuf,
    pub execute: Option<PathBuf>,
    pub file: Option<PathBuf>,
    pub standalone: bool,
    pub config: Option<PathBuf>,
    pub forwarded: Vec<String>,
    pub help: bool,
}

pub fn parse(args: impl IntoIterator<Item = String>) -> Result<Options, String> {
    let mut opts = Options {
        dir: PathBuf::from("."),
        execute: None,
        file: None,
        standalone: false,
        config: None,
        forwarded: Vec::new(),
        help: false,
    };
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => {
                opts.help = true;
                return Ok(opts);
            }
            "-d" | "--dir" => {
                opts.dir = PathBuf::from(args.next().ok_or("-d requires a directory")?)
            }
            "-f" | "--file" => {
                if opts.file.is_some() {
                    return Err("Only one -f file may be supplied".into());
                }
                opts.file = Some(PathBuf::from(args.next().ok_or("-f requires a file")?));
            }
            "-e" | "--execute" => {
                if opts.execute.is_some() {
                    return Err("Only one of -e and -r may be supplied".into());
                }
                opts.execute = Some(PathBuf::from(args.next().ok_or("-e requires a file")?));
            }
            "-r" | "--run" => {
                if opts.execute.is_some() {
                    return Err("Only one of -e and -r may be supplied".into());
                }
                opts.execute = Some(PathBuf::from(args.next().ok_or("-r requires a file")?));
                opts.standalone = true;
            }
            "-c" | "--config" => {
                opts.config = Some(PathBuf::from(args.next().ok_or("-c requires a file")?))
            }
            "--" => {
                opts.forwarded.extend(args);
                break;
            }
            _ => return Err(format!("Unknown argument: {arg}. Run xcat --help.")),
        }
    }
    if opts.file.is_some() && opts.execute.is_some() {
        return Err("-f cannot be combined with -e or -r".into());
    }
    if opts.execute.is_none() && !opts.forwarded.is_empty() {
        return Err("-- arguments require -e".into());
    }
    Ok(opts)
}
