use serde::{Deserialize, Serialize};
use sod2se_abi::{INVALID, STALE, UNSUPPORTED};
pub const MAX_PAGES: usize = 32;
pub const MAX_OPTIONS: usize = 128;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Extension {
    pub id: String,
    pub target: String,
    pub title: String,
    pub description: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Page {
    pub id: String,
    pub name: String,
    pub description: String,
    pub loaded: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct OptionRow {
    pub module: String,
    pub id: String,
    pub page: usize,
    pub label: String,
    pub description: String,
    pub kind: i32,
    pub value: i32,
    pub minimum: i32,
    pub maximum: i32,
    pub restart: bool,
    pub risk: String,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Model {
    pub revision: u64,
    pub settings_revision: u64,
    pub language: String,
    pub pages: Vec<Page>,
    pub options: Vec<OptionRow>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Action {
    pub sequence: u64,
    pub extension: String,
    pub revision: u64,
    pub action: String,
    pub value: serde_json::Value,
}
#[derive(Default)]
pub struct UiRegistry {
    extensions: BTreeMap<String, (u64, Extension)>,
    models: BTreeMap<String, Model>,
    actions: Vec<Action>,
    sequence: u64,
}
impl UiRegistry {
    pub fn owns(&self, owner: u64, id: &str) -> bool {
        self.extensions
            .get(id)
            .is_some_and(|entry| entry.0 == owner)
    }
    pub fn register(&mut self, owner: u64, extension: Extension) -> Result<(), i32> {
        if extension.target != "settings" {
            return Err(UNSUPPORTED);
        }
        if owner == 0
            || !super::valid_id(&extension.id)
            || extension.title.is_empty()
            || self.extensions.contains_key(&extension.id)
        {
            return Err(INVALID);
        }
        self.extensions
            .insert(extension.id.clone(), (owner, extension));
        Ok(())
    }
    pub fn publish(&mut self, owner: u64, id: &str, model: Model) -> Result<(), i32> {
        if self.extensions.get(id).map(|e| e.0) != Some(owner)
            || model.pages.len()
                + self
                    .models
                    .iter()
                    .filter(|(key, _)| key.as_str() != id)
                    .map(|(_, m)| m.pages.len())
                    .sum::<usize>()
                > MAX_PAGES
            || model.options.len()
                + self
                    .models
                    .iter()
                    .filter(|(key, _)| key.as_str() != id)
                    .map(|(_, m)| m.options.len())
                    .sum::<usize>()
                > MAX_OPTIONS
        {
            return Err(INVALID);
        }
        for row in &model.options {
            if row.page >= model.pages.len()
                || row.minimum > row.maximum
                || row.value < row.minimum
                || row.value > row.maximum
                || ![0, 1, 2].contains(&row.kind)
                || (row.kind == 0
                    && (row.minimum != 0 || row.maximum != 1 || ![0, 1].contains(&row.value)))
            {
                return Err(INVALID);
            }
        }
        if let Some(current) = self.models.get(id) {
            let mut comparison = model.clone();
            comparison.revision = current.revision;
            if comparison == *current {
                return Ok(());
            }
            if model.revision <= current.revision {
                return Err(STALE);
            }
        }
        self.models.insert(id.into(), model);
        Ok(())
    }
    pub fn unregister(&mut self, owner: u64) {
        let ids: Vec<_> = self
            .extensions
            .iter()
            .filter(|(_, e)| e.0 == owner)
            .map(|(id, _)| id.clone())
            .collect();
        for id in ids {
            self.extensions.remove(&id);
            self.models.remove(&id);
            self.actions.retain(|a| a.extension != id);
        }
    }
    pub fn extensions(&self) -> Vec<Extension> {
        self.extensions.values().map(|e| e.1.clone()).collect()
    }
    pub fn model(&self, id: &str) -> Option<&Model> {
        self.models.get(id)
    }
    pub fn models(&self) -> Vec<(String, Model)> {
        self.models
            .iter()
            .map(|(id, m)| (id.clone(), m.clone()))
            .collect()
    }
    pub fn action(
        &mut self,
        id: &str,
        revision: u64,
        action: &str,
        value: serde_json::Value,
    ) -> Result<(), i32> {
        if self.models.get(id).map(|m| m.revision) != Some(revision) {
            return Err(STALE);
        }
        if !["confirm", "back", "close", "set"].contains(&action) || self.actions.len() >= 256 {
            return Err(INVALID);
        }
        self.sequence = self.sequence.checked_add(1).ok_or(STALE)?;
        self.actions.push(Action {
            sequence: self.sequence,
            extension: id.into(),
            revision,
            action: action.into(),
            value,
        });
        Ok(())
    }
    pub fn drain(&mut self, owner: u64, id: &str) -> Result<Vec<Action>, i32> {
        if self.extensions.get(id).map(|e| e.0) != Some(owner) {
            return Err(INVALID);
        }
        let result = self
            .actions
            .iter()
            .filter(|a| a.extension == id)
            .cloned()
            .collect();
        self.actions.retain(|a| a.extension != id);
        Ok(result)
    }
}
