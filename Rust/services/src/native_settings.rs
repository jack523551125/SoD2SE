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

#[cfg(test)]
mod consent_expiry {
    use super::*;
    #[test]
    fn expired_consent_cannot_enqueue_a_write() {
        let mut session=Session::default();
        session.token=1;session.presentation_v2=true;
        session.consent=Some((1,0,5,0,std::time::Instant::now()-std::time::Duration::from_secs(31)));
        assert!(matches!(session.query_v2(26,1,1,0,0),Reply::Number(-7)));
        assert!(session.pending.is_none());
        assert!(session.consent.is_none());
    }
    #[test]
    fn native_menu_handoff_is_single_use_and_expires() {
        let mut session=Session::default();
        assert_eq!(session.take_native_open(),0);
        assert_eq!(session.request_native_open(),1);
        assert_eq!(session.take_native_open(),1);
        assert_eq!(session.take_native_open(),0);
        session.native_open=Some(std::time::Instant::now()-std::time::Duration::from_secs(11));
        assert_eq!(session.take_native_open(),0);
        session.pending=Some((0,0));
        assert_eq!(session.request_native_open(),-3);
    }
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
    chrome: Vec<String>,
    stale: bool,
    presentation_v2: bool,
    consent: Option<(i32, usize, i32, u64, std::time::Instant)>,
    nonce: i32,
    native_open: Option<std::time::Instant>,
}
impl Session {
    /// One-shot handoff from a menu button to the native settings host.
    pub fn request_native_open(&mut self) -> i32 {
        if self.pending.is_some() { return -3; }
        self.native_open=Some(std::time::Instant::now());1
    }
    pub fn take_native_open(&mut self) -> i32 {
        self.native_open.take().is_some_and(|issued| issued.elapsed().as_secs()<10) as i32
    }
    pub fn pending_extension(&self) -> Option<&str> {
        self.pending
            .and_then(|(index, _)| self.options.get(index).map(|row| row.0.as_str()))
    }
    /// Advance view revisions only when the republished model exactly matches
    /// the acknowledged snapshot. External edits and structural changes stay stale.
    pub fn refresh(&mut self, models: Vec<(String, Model)>) {
        if self.pending.is_some() || self.token == 0 {
            return;
        }
        let mut candidate = Session::default();
        if candidate.open(models) == 0
            || candidate.pages != self.pages
            || candidate.language != self.language
            || candidate.options.len() != self.options.len()
        {
            self.stale = self.presentation_v2; self.consent = None; return;
        }
        if candidate
            .options
            .iter()
            .zip(&self.options)
            .any(|(next, old)| next.0 != old.0 || next.3 != old.3 || next.2 < old.2)
        {
            self.stale = self.presentation_v2; self.consent = None; return;
        }
        self.options = candidate.options;
    }
    pub fn open_v2(&mut self, models:Vec<(String,Model)>) -> i32 {
        if !models.iter().any(|(_,m)|m.presentation==2 && !m.chrome.is_empty()) {return -2;}
        let token=self.open(models);if token>0 {self.presentation_v2=true;}token
    }
    pub fn open(&mut self, models: Vec<(String, Model)>) -> i32 {
        if self.pending.is_some() || self.token == i32::MAX {
            return 0;
        }
        let mut pages = Vec::new();
        let mut options = Vec::new();
        let mut language = "en-US".to_owned();
        let mut chrome = Vec::new();
        for (id, model) in models {
            let offset = pages.len();
            if model.presentation == 2 && !model.chrome.is_empty() { language=model.language; chrome=model.chrome; }
            else if chrome.is_empty() { language=model.language; }
            pages.extend(model.pages);
            for mut row in model.options {
                row.page += offset;
                options.push((id.clone(), model.revision, model.settings_revision, row));
            }
        }
        if pages.len() > crate::ui::MAX_PAGES || options.len() > crate::ui::MAX_OPTIONS {
            return 0;
        }
        self.presentation_v2=false;
        self.chrome = chrome; self.stale = false; self.consent = None;
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
                if self.stale { return Reply::Number(sod2se_abi::STALE); }
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
        let Some((_, _, _, row)) = usize::try_from(index)
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
            15 => self.edit(index, value, false),
            _ => Reply::Number(-3),
        }
    }
    fn edit(&mut self, index: i32, value: i32, risk_ack: bool) -> Reply {
        if self.stale { return Reply::Number(sod2se_abi::STALE); }
        let Some((extension, revision, settings_revision, row)) = usize::try_from(index).ok().and_then(|i| self.options.get_mut(i)) else { return Reply::Number(-3); };
        if self.pending.is_some() || value < row.minimum || value > row.maximum
            || (row.kind == 0 && ![0,1].contains(&value)) || (row.risk == "dangerous" && !risk_ack) {
            return Reply::Number(-3);
        }
        if value == row.value { return Reply::Number(0); }
        self.consent = None;
        self.pending = Some((index as usize, row.value)); row.value = value;
        Reply::Edit { extension: extension.clone(), revision:*revision, token:self.token,
            value:json!({"module":row.module,"id":row.id,"value":if row.kind==0{json!(value!=0)}else{json!(value)},"settings_revision":settings_revision,"risk_ack":risk_ack,"token":self.token}) }
    }
    /// Presentation v2 adds metadata and revision-bound, single-use consent.
    /// The legacy query never accepts a dangerous edit.
    pub fn query_v2(&mut self, op:i32, token:i32, index:i32, value:i32, current_revision:u64) -> Reply {
        if token == 0 || token != self.token || !self.presentation_v2 { return Reply::Number(-2); }
        if op == 8 { return self.options.get(index as usize).map(|r|Reply::Text(r.3.description.clone())).unwrap_or(Reply::Number(-3)); }
        if op == 20 { return self.chrome.get(index as usize).cloned().map(Reply::Text).unwrap_or(Reply::Number(-2)); }
        if op == 21 { return self.pages.get(index as usize).map(|p|Reply::Text(p.id.clone())).unwrap_or(Reply::Number(-3)); }
        if op == 22 { return self.pages.get(index as usize).map(|p|Reply::Text(p.version.clone().unwrap_or_default())).unwrap_or(Reply::Number(-3)); }
        if matches!(op,10..=12) { return self.options.get(index as usize).map(|r| Reply::Text(match op {10=>r.3.value,11=>r.3.minimum,_=>r.3.maximum}.to_string())).unwrap_or(Reply::Number(-3)); }
        if op == 27 { self.consent = None; return Reply::Number(0); }
        if op == 26 {
            let Some((nonce, row, desired, revision, issued)) = self.consent.take() else { return Reply::Number(-7); };
            if nonce != index || revision != current_revision || issued.elapsed().as_secs() >= 30 || self.stale
                || self.options.get(row).is_none_or(|r|r.2!=revision) { return Reply::Number(-7); }
            return self.edit(row as i32, desired, true);
        }
        if matches!(op,23..=25|28) {
            let Some((_,_,revision,row)) = self.options.get(index as usize) else { return Reply::Number(-3); };
            if op == 23 { return Reply::Text(row.default_value.map(|v|v.to_string()).unwrap_or_default()); }
            if op == 24 { return Reply::Number(match row.risk.as_str(){"experimental"=>1,"dangerous"=>2,_=>0}); }
            if op == 28 { return Reply::Number(row.default_value.is_some() as i32); }
            if self.pending.is_some() || self.stale || *revision != current_revision || row.risk!="dangerous"
                || value<row.minimum || value>row.maximum { return Reply::Number(-7); }
            let Some(nonce)=self.nonce.checked_add(1) else { return Reply::Number(-7); };
            self.nonce=nonce;self.consent=Some((nonce,index as usize,value,*revision,std::time::Instant::now()));
            return Reply::Number(nonce);
        }
        if op==15 && self.options.get(index as usize).is_some_and(|r|r.2!=current_revision) { return Reply::Number(-7); }
        self.query(op,token,index,value)
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
