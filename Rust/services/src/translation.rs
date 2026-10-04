use sod2se_abi::INVALID;
use std::collections::{BTreeMap, BTreeSet};
#[derive(Default)]
pub struct Catalog {
    pub locale: String,
    entries: BTreeMap<String, BTreeMap<String, String>>,
    owners: BTreeMap<String, u64>,
}
fn placeholders(text: &str) -> Result<BTreeSet<String>, i32> {
    let mut names = BTreeSet::new();
    let mut rest = text;
    while let Some((_, tail)) = rest.split_once('{') {
        let (name, next) = tail.split_once('}').ok_or(INVALID)?;
        if !super::valid_id(name) {
            return Err(INVALID);
        }
        names.insert(name.into());
        rest = next;
    }
    if rest.contains('}') {
        return Err(INVALID);
    }
    Ok(names)
}
impl Catalog {
    pub fn new(locale: String) -> Self {
        Self {
            locale,
            ..Self::default()
        }
    }
    pub fn register(
        &mut self,
        owner: u64,
        module: &str,
        entries: BTreeMap<String, BTreeMap<String, String>>,
    ) -> Result<(), i32> {
        let english = entries.get("en-US").ok_or(INVALID)?;
        if owner == 0 || english.is_empty() {
            return Err(INVALID);
        }
        for (key, text) in english {
            if !key.starts_with(&format!("{module}."))
                || self.owners.contains_key(key)
                || text.is_empty()
            {
                return Err(INVALID);
            }
            placeholders(text)?;
        }
        for catalog in entries.values() {
            if catalog.keys().ne(english.keys()) {
                return Err(INVALID);
            }
            for (key, text) in catalog {
                if text.is_empty() || placeholders(text)? != placeholders(&english[key])? {
                    return Err(INVALID);
                }
            }
        }
        for key in english.keys() {
            self.owners.insert(key.clone(), owner);
        }
        for (locale, values) in entries {
            self.entries.entry(locale).or_default().extend(values);
        }
        Ok(())
    }
    pub fn get(&self, key: &str) -> String {
        self.entries
            .get(&self.locale)
            .and_then(|c| c.get(key))
            .or_else(|| {
                self.entries
                    .get(self.locale.split('-').next().unwrap_or(""))
                    .and_then(|c| c.get(key))
            })
            .or_else(|| {
                if self.locale.starts_with("zh") {
                    self.entries.get("zh-CN").and_then(|c| c.get(key))
                } else {
                    None
                }
            })
            .or_else(|| self.entries.get("en-US").and_then(|c| c.get(key)))
            .cloned()
            .unwrap_or_else(|| key.into())
    }
    pub fn unregister(&mut self, owner: u64) {
        let keys: Vec<_> = self
            .owners
            .iter()
            .filter(|(_, o)| **o == owner)
            .map(|(k, _)| k.clone())
            .collect();
        for key in keys {
            self.owners.remove(&key);
            for catalog in self.entries.values_mut() {
                catalog.remove(&key);
            }
        }
    }
}
