// SPDX-License-Identifier: Apache-2.0
//! Dependency-free JSON config for native and WASI builds.
#[path = "cli/xcat_filter.rs"]
mod xcat_filter;

use std::{
    env, fs, io,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug)]
pub struct Config {
    pub scanendfilter: Vec<String>,
    pub scanfullfilter: Vec<String>,
    pub excludedirs: Vec<String>,
    pub max_file_bytes: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            scanendfilter: [
                ".bb", ".bbclass", ".c", ".cc", ".cmake", ".cpp", ".cxx", ".go", ".h", ".hh",
                ".hpp", ".hxx", ".in", ".ini", ".java", ".jl", ".json", ".lua", ".md", ".py",
                ".rc", ".rs", ".sh", ".ps1", ".sv", ".tcl", ".tex", ".toml", ".txt", ".xml",
                ".log", ".yaml", ".yml",
            ]
            .into_iter()
            .map(str::to_string)
            .collect(),
            scanfullfilter: [
                "CMakeLists.txt",
                "Cargo.toml",
                "meson.build",
                "pom.xml",
                "Makefile",
                "makefile",
                "Justfile",
            ]
            .into_iter()
            .map(str::to_string)
            .collect(),
            excludedirs: [
                ".git",
                ".svn",
                ".hg",
                "target",
                "build",
                "node_modules",
                ".venv",
                "venv",
            ]
            .into_iter()
            .map(str::to_string)
            .collect(),
            max_file_bytes: 2_000_000,
        }
    }
}

impl Config {
    pub fn default_path() -> io::Result<PathBuf> {
        #[cfg(windows)]
        if let Some(dir) = env::var_os("APPDATA").filter(|s| !s.is_empty()) {
            return Ok(PathBuf::from(dir).join("xcat").join("config.json"));
        }
        if let Some(dir) = env::var_os("XDG_CONFIG_HOME").filter(|s| !s.is_empty()) {
            return Ok(PathBuf::from(dir).join("xcat").join("config.json"));
        }
        let home = env::var_os("HOME")
            .or_else(|| env::var_os("USERPROFILE"))
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::NotFound, "HOME/USERPROFILE is not set")
            })?;
        Ok(PathBuf::from(home)
            .join(".config")
            .join("xcat")
            .join("config.json"))
    }

    pub fn load_or_create(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        if !path.exists() {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            let text = Self::default().to_json();
            match fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
            {
                Ok(mut f) => {
                    use std::io::Write;
                    f.write_all(text.as_bytes())?;
                    eprintln!("Created config: {}", path.display());
                }
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
                Err(e) => return Err(Box::new(e)),
            }
        }
        let data = fs::read_to_string(path)?;
        let config =
            Self::from_json(&data).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
        if config
            .scanendfilter
            .iter()
            .any(|s| s.is_empty() || !s.starts_with('.'))
        {
            return Err("scanendfilter entries must start with a dot".into());
        }
        if config.max_file_bytes == 0 {
            return Err("max_file_bytes must be positive".into());
        }
        Ok(config)
    }

    fn to_json(&self) -> String {
        fn esc(s: &str) -> String {
            let mut out = String::from("\"");
            for c in s.chars() {
                match c {
                    '"' => out.push_str("\\\""),
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
                    c => out.push(c),
                }
            }
            out.push('"');
            out
        }
        fn arr(v: &[String]) -> String {
            v.iter().map(|s| esc(s)).collect::<Vec<_>>().join(", ")
        }
        format!(
            "{{\n  \"scanendfilter\": [{}],\n  \"scanfullfilter\": [{}],\n  \"excludedirs\": [{}],\n  \"max_file_bytes\": {}\n}}\n",
            arr(&self.scanendfilter),
            arr(&self.scanfullfilter),
            arr(&self.excludedirs),
            self.max_file_bytes
        )
    }

    pub fn from_json(text: &str) -> Result<Self, String> {
        let mut j = Json { text, pos: 0 };
        let mut result = Self::default();
        j.expect('{')?;
        if !j.consume('}') {
            loop {
                let key = j.string()?;
                j.expect(':')?;
                match key.as_str() {
                    "scanendfilter" => result.scanendfilter = j.string_array()?,
                    "scanfullfilter" => result.scanfullfilter = j.string_array()?,
                    "excludedirs" => result.excludedirs = j.string_array()?,
                    "max_file_bytes" => result.max_file_bytes = j.integer()?,
                    _ => j.skip_value(0)?,
                }
                if j.consume('}') {
                    break;
                }
                j.expect(',')?;
            }
        }
        j.space();
        if j.pos != j.text.len() {
            return Err("trailing JSON data".into());
        }
        Ok(result)
    }

    pub fn accepts(&self, path: &Path) -> bool {
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            return false;
        };
        // Keep Unicode case folding for non-ASCII filenames, while sharing
        // the ASCII matching policy with the no_std JVM implementation.
        if name.is_ascii()
            && self.scanfullfilter.iter().all(|s| s.is_ascii())
            && self.scanendfilter.iter().all(|s| s.is_ascii())
        {
            return xcat_filter::accepts(
                name.as_bytes(),
                self.scanfullfilter.iter().map(|s| s.as_bytes()),
                self.scanendfilter.iter().map(|s| s.as_bytes()),
            );
        }
        let name = name.to_lowercase();
        self.scanfullfilter
            .iter()
            .any(|full| name == full.to_lowercase())
            || self
                .scanendfilter
                .iter()
                .any(|ending| name.ends_with(&ending.to_lowercase()))
    }

    pub fn is_excluded(&self, relative: &Path) -> bool {
        relative.components().any(|c| {
            let part = c.as_os_str().to_string_lossy();
            self.excludedirs
                .iter()
                .any(|excluded| part.eq_ignore_ascii_case(excluded))
        })
    }
}

struct Json<'a> {
    text: &'a str,
    pos: usize,
}
impl Json<'_> {
    fn space(&mut self) {
        while self
            .text
            .as_bytes()
            .get(self.pos)
            .is_some_and(u8::is_ascii_whitespace)
        {
            self.pos += 1;
        }
    }
    fn next(&mut self) -> Option<char> {
        let c = self.text[self.pos..].chars().next()?;
        self.pos += c.len_utf8();
        Some(c)
    }
    fn consume(&mut self, c: char) -> bool {
        self.space();
        if self.text[self.pos..].starts_with(c) {
            self.pos += c.len_utf8();
            true
        } else {
            false
        }
    }
    fn expect(&mut self, c: char) -> Result<(), String> {
        if self.consume(c) {
            Ok(())
        } else {
            Err(format!("expected '{c}' at byte {}", self.pos))
        }
    }
    fn hex4(&mut self) -> Result<u32, String> {
        let mut code = 0;
        for _ in 0..4 {
            code = (code << 4)
                + self
                    .next()
                    .and_then(|c| c.to_digit(16))
                    .ok_or("invalid JSON unicode escape")?;
        }
        Ok(code)
    }
    fn string(&mut self) -> Result<String, String> {
        self.expect('"')?;
        let mut out = String::new();
        loop {
            match self.next().ok_or("unterminated JSON string")? {
                '"' => return Ok(out),
                '\\' => match self.next().ok_or("incomplete JSON escape")? {
                    '"' => out.push('"'),
                    '\\' => out.push('\\'),
                    '/' => out.push('/'),
                    'b' => out.push('\u{0008}'),
                    'f' => out.push('\u{000c}'),
                    'n' => out.push('\n'),
                    'r' => out.push('\r'),
                    't' => out.push('\t'),
                    'u' => {
                        let mut n = self.hex4()?;
                        if (0xd800..=0xdbff).contains(&n) {
                            if self.next() != Some('\\') || self.next() != Some('u') {
                                return Err("expected JSON low surrogate".into());
                            }
                            let low = self.hex4()?;
                            if !(0xdc00..=0xdfff).contains(&low) {
                                return Err("invalid JSON low surrogate".into());
                            }
                            n = 0x10000 + ((n - 0xd800) << 10) + (low - 0xdc00);
                        }
                        out.push(char::from_u32(n).ok_or("invalid JSON unicode scalar")?);
                    }
                    _ => return Err("invalid JSON escape".into()),
                },
                c if c < '\u{0020}' => return Err("control character in JSON string".into()),
                c => out.push(c),
            }
        }
    }
    fn integer(&mut self) -> Result<u64, String> {
        self.space();
        let start = self.pos;
        while self
            .text
            .as_bytes()
            .get(self.pos)
            .is_some_and(u8::is_ascii_digit)
        {
            self.pos += 1;
        }
        let s = &self.text[start..self.pos];
        if s.is_empty() || (s.len() > 1 && s.starts_with('0')) {
            return Err("expected unsigned JSON integer".into());
        }
        s.parse::<u64>().map_err(|e| e.to_string())
    }
    fn string_array(&mut self) -> Result<Vec<String>, String> {
        self.expect('[')?;
        let mut items = Vec::new();
        if self.consume(']') {
            return Ok(items);
        }
        loop {
            items.push(self.string()?);
            if self.consume(']') {
                return Ok(items);
            }
            self.expect(',')?;
        }
    }
    fn skip_value(&mut self, depth: u32) -> Result<(), String> {
        if depth > 64 {
            return Err("JSON nesting exceeds limit".into());
        }
        self.space();
        match self.text.as_bytes().get(self.pos).copied() {
            Some(b'"') => {
                self.string()?;
            }
            Some(b'{') => {
                self.expect('{')?;
                if !self.consume('}') {
                    loop {
                        self.string()?;
                        self.expect(':')?;
                        self.skip_value(depth + 1)?;
                        if self.consume('}') {
                            break;
                        }
                        self.expect(',')?;
                    }
                }
            }
            Some(b'[') => {
                self.expect('[')?;
                if !self.consume(']') {
                    loop {
                        self.skip_value(depth + 1)?;
                        if self.consume(']') {
                            break;
                        }
                        self.expect(',')?;
                    }
                }
            }
            Some(b't') | Some(b'f') | Some(b'n') => {
                let word = if self.text[self.pos..].starts_with("true") {
                    "true"
                } else if self.text[self.pos..].starts_with("false") {
                    "false"
                } else {
                    "null"
                };
                if !self.text[self.pos..].starts_with(word) {
                    return Err("invalid JSON literal".into());
                }
                self.pos += word.len();
            }
            Some(b'-' | b'0'..=b'9') => {
                let start = self.pos;
                while self
                    .text
                    .as_bytes()
                    .get(self.pos)
                    .is_some_and(|b| matches!(*b, b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9'))
                {
                    self.pos += 1;
                }
                if self.text[start..self.pos].is_empty() {
                    return Err("invalid JSON number".into());
                }
            }
            _ => return Err("invalid JSON value".into()),
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::Config;
    #[test]
    fn roundtrip_defaults() {
        let original = Config::default();
        let decoded = Config::from_json(&original.to_json()).unwrap();
        assert_eq!(decoded.scanendfilter, original.scanendfilter);
        assert_eq!(decoded.max_file_bytes, original.max_file_bytes);
    }
    #[test]
    fn rejects_broken_strings_and_wrong_types() {
        assert!(Config::from_json(r#"{"scanendfilter":"no"}"#).is_err());
        assert!(Config::from_json(r#"{"scanendfilter":["\uD800"]}"#).is_err());
        assert!(Config::from_json(r#"{"max_file_bytes":-1}"#).is_err());
    }
    #[test]
    fn accepts_unicode_escapes_and_unknown_fields() {
        let c = Config::from_json(r#"{"scanendfilter":[".\u0072s"],"other":{"a":[false,null]}}"#)
            .unwrap();
        assert!(c.scanendfilter.contains(&".rs".to_string()));
    }
}
