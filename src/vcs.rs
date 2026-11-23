// SPDX-License-Identifier: Apache-2.0
//! Native adapter for the shared core-only VCS policy.
#[path = "vcs_policy.rs"]
mod policy;
use std::{error::Error, process::Command};
struct Native;
impl policy::Executor for Native {
    fn run(&mut self, args: &[&str], out: &mut [u8]) -> Result<usize, ()> {
        let (program, arguments) = args.split_first().ok_or(())?;
        let result = Command::new(program).args(arguments).output().map_err(|_| ())?;
        if !result.status.success() || result.stdout.len() > out.len() { return Err(()); }
        out[..result.stdout.len()].copy_from_slice(&result.stdout);
        Ok(result.stdout.len())
    }
}
pub fn remote_url(remote: &str) -> Result<String, Box<dyn Error>> {
    let mut out = [0u8; 8192];
    let len = policy::remote_url(remote, &mut Native, &mut out)?;
    Ok(String::from_utf8(out[..len].to_vec())?)
}
