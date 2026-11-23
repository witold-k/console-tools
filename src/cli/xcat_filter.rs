// SPDX-License-Identifier: Apache-2.0
//! Allocation-free filename matching shared by native xcat and no_std WASI.
pub fn eq_ignore_ascii_case(a: &[u8], b: &[u8]) -> bool {
    a.eq_ignore_ascii_case(b)
}

pub fn ends_ignore_ascii_case(name: &[u8], suffix: &[u8]) -> bool {
    name.len() >= suffix.len()
        && eq_ignore_ascii_case(&name[name.len() - suffix.len()..], suffix)
}

pub fn accepts<'a>(
    name: &[u8],
    full: impl IntoIterator<Item = &'a [u8]>,
    suffixes: impl IntoIterator<Item = &'a [u8]>,
) -> bool {
    full.into_iter().any(|entry| eq_ignore_ascii_case(name, entry))
        || suffixes.into_iter().any(|entry| ends_ignore_ascii_case(name, entry))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn suffixes_and_full_names_are_ascii_case_insensitive() {
        assert!(accepts(b"README.MD", [b"Cargo.toml".as_slice()], [b".md".as_slice()]));
        assert!(accepts(b"cargo.TOML", [b"Cargo.toml".as_slice()], [b".rs".as_slice()]));
        assert!(!accepts(b"notes.tmp", [b"Cargo.toml".as_slice()], [b".rs".as_slice()]));
        assert!(!ends_ignore_ascii_case(b"a", b".md"));
    }

    #[test]
    fn empty_suffix_matches_everything_but_is_not_a_valid_config() {
        // Validation of configuration entries belongs to the config parser.
        assert!(ends_ignore_ascii_case(b"file", b""));
    }
}
