// SPDX-License-Identifier: Apache-2.0
//! JSON configuration compatible with aiagents' scanendfilter/scanfullfilter names.

use serde::{Deserialize, Serialize};
use std::{env, fs, io, path::{Path, PathBuf}};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Case-insensitive file suffixes, including the leading dot.
    pub scanendfilter: Vec<String>,
    /// Case-insensitive complete filenames (e.g. Cargo.toml, Justfile).
    pub scanfullfilter: Vec<String>,
    /// Directory basenames omitted anywhere in the scanned tree.
    pub excludedirs: Vec<String>,
    /// Maximum size of a single file included in the clipboard (bytes).
    pub max_file_bytes: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            scanendfilter: [".bb", ".bbclass", ".c", ".cc", ".cmake", ".cpp", ".cxx", ".go", ".h", ".hh", ".hpp", ".hxx", ".in", ".ini", ".java", ".jl", ".json", ".lua", ".md", ".py", ".rc", ".rs", ".sh", ".ps1", ".sv", ".tcl", ".tex", ".toml", ".txt", ".xml", ".log", ".yaml", ".yml"]
                .into_iter().map(str::to_string).collect(),
            scanfullfilter: ["CMakeLists.txt", "Cargo.toml", "meson.build", "pom.xml", "Makefile", "makefile", "Justfile"]
                .into_iter().map(str::to_string).collect(),
            excludedirs: [".git", ".svn", ".hg", "target", "build", "node_modules", ".venv", "venv"]
                .into_iter().map(str::to_string).collect(),
            max_file_bytes: 2_000_000,
        }
    }
}

impl Config {
    pub fn default_path() -> io::Result<PathBuf> {
        #[cfg(windows)]
        {
            if let Some(dir) = env::var_os("APPDATA").filter(|s| !s.is_empty()) {
                return Ok(PathBuf::from(dir).join("xcat").join("config.json"));
            }
        }
        if let Some(dir) = env::var_os("XDG_CONFIG_HOME").filter(|s| !s.is_empty()) {
            return Ok(PathBuf::from(dir).join("xcat").join("config.json"));
        }
        let home = env::var_os("HOME").or_else(|| env::var_os("USERPROFILE"))
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "HOME/USERPROFILE is not set"))?;
        Ok(PathBuf::from(home).join(".config").join("xcat").join("config.json"))
    }

    /// Creates only if missing; existing invalid configuration is an error.
    pub fn load_or_create(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        if !path.exists() {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            let text = serde_json::to_string_pretty(&Self::default())?;
            match fs::OpenOptions::new().write(true).create_new(true).open(path) {
                Ok(mut f) => { use std::io::Write; f.write_all(text.as_bytes())?; eprintln!("Created config: {}", path.display()); }
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {},
                Err(e) => return Err(Box::new(e)),
            }
        }
        let data = fs::read_to_string(path)?;
        let config: Self = serde_json::from_str(&data)?;
        if config.scanendfilter.iter().any(|s| s.is_empty() || !s.starts_with('.')) {
            return Err("scanendfilter entries must start with a dot".into());
        }
        if config.max_file_bytes == 0 {
            return Err("max_file_bytes must be positive".into());
        }
        Ok(config)
    }

    pub fn accepts(&self, path: &Path) -> bool {
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else { return false; };
        let name = name.to_lowercase();
        self.scanfullfilter.iter().any(|full| name == full.to_lowercase())
            || self.scanendfilter.iter().any(|ending| name.ends_with(&ending.to_lowercase()))
    }

    pub fn is_excluded(&self, relative: &Path) -> bool {
        relative.components().any(|c| {
            let part = c.as_os_str().to_string_lossy();
            self.excludedirs.iter().any(|excluded| part.eq_ignore_ascii_case(excluded))
        })
    }
}
