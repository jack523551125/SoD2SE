//! Pure model for the existing fixed-build four-integer settings resource protocol.
use crate::ui::{Model, OptionRow, Page};
use serde_json::json;
#[derive(Debug)]
pub enum Reply {
    Number(i32),
    Text(String),
    Edit {
        extension: String,
        revision: u64,
        token: i32,
        value: serde_json::Value,
    },
}
#[derive(Default)]
pub struct Session {
    token: i32,
    pages: Vec<Page>,
    options: Vec<(String, u64, u64, OptionRow)>,
    language: String,
    pending: Option<(usize, i32)>,
    status: i32,
    message: String,
}
impl Session {
    pub fn open(&mut self, models: Vec<(String, Model)>) -> i32 {
        if self.pending.is_some() || self.token == i32::MAX {
            return 0;
        }
        let mut pages = Vec::new();
        let mut options = Vec::new();
        let mut language = "en-US".to_owned();
        for (id, model) in models {
            let offset = pages.len();
            language = model.language;
            pages.extend(model.pages);
            for mut row in model.options {
                row.page += offset;
                options.push((id.clone(), model.revision, model.settings_revision, row));
            }
        }
        if pages.len() > crate::ui::MAX_PAGES || options.len() > crate::ui::MAX_OPTIONS {
            return 0;
        }
        self.pages = pages;
        self.options = options;
        self.language = language;
        self.status = 0;
        self.message.clear();
        self.token += 1;
        self.token
    }
    pub fn query(&mut self, op: i32, token: i32, index: i32, value: i32) -> Reply {
        if token == 0 || token != self.token {
            return Reply::Number(-2);
        }
        match op {
            1 => return Reply::Number(self.pages.len() as i32),
            2 => return Reply::Number(self.options.len() as i32),
            14 => {
                return Reply::Number(if self.language.starts_with("zh") {
                    1
                } else {
                    2
                });
            }
            17 => {
                return Reply::Text(if self.pending.is_some() {
                    if self.language.starts_with("zh") {
                        "正在保存……"
                    } else {
                        "Saving..."
                    }
                    .into()
                } else {
                    self.message.clone()
                });
            }
            18 => {
                return Reply::Number(if self.pending.is_some() {
                    1
                } else {
                    self.status
                });
            }
            _ => {}
        }
        if (3..=5).contains(&op) {
            let Some(page) = usize::try_from(index).ok().and_then(|i| self.pages.get(i)) else {
                return Reply::Number(-3);
            };
            return match op {
                3 => Reply::Text(page.name.clone()),
                4 => Reply::Text(page.description.clone()),
                _ => Reply::Number(page.loaded as i32),
            };
        }
        let Some((extension, revision, settings_revision, row)) = usize::try_from(index)
            .ok()
            .and_then(|i| self.options.get_mut(i))
        else {
            return Reply::Number(-3);
        };
        match op {
            6 => Reply::Number(row.page as i32),
            7 => Reply::Text(row.label.clone()),
            8 => Reply::Text(format!(
                "{}{}",
                row.description,
                match row.risk.as_str() {
                    "experimental" => " [Experimental / 实验性]",
                    "dangerous" => " [Dangerous / 危险；需明确确认]",
                    _ => "",
                }
            )),
            9 => Reply::Number(row.kind),
            10 => Reply::Number(row.value),
            11 => Reply::Number(row.minimum),
            12 => Reply::Number(row.maximum),
            13 => Reply::Number(row.restart as i32),
            15 => {
                // The old resource protocol has no explicit risk-ack field. Never synthesize consent.
                if self.pending.is_some()
                    || value < row.minimum
                    || value > row.maximum
                    || (row.kind == 0 && ![0, 1].contains(&value))
                    || row.risk == "dangerous"
                {
                    return Reply::Number(-3);
                }
                if value == row.value {
                    return Reply::Number(0);
                }
                self.pending = Some((index as usize, row.value));
                row.value = value;
                Reply::Edit {
                    extension: extension.clone(),
                    revision: *revision,
                    token,
                    value: json!({"module":row.module,"id":row.id,"value":if row.kind==0{json!(value!=0)}else{json!(value)},"settings_revision":settings_revision,"risk_ack":false,"token":token}),
                }
            }
            _ => Reply::Number(-3),
        }
    }
    pub fn complete(
        &mut self,
        token: i32,
        status: i32,
        message: String,
        settings_revision: u64,
    ) -> Result<(), i32> {
        if token != self.token {
            return Err(sod2se_abi::STALE);
        }
        let (index, old) = self.pending.take().ok_or(sod2se_abi::INVALID)?;
        self.status = status;
        self.message = message;
        if status != 0 {
            self.options[index].3.value = old;
        } else {
            for item in &mut self.options {
                item.2 = settings_revision;
            }
        }
        Ok(())
    }
}
