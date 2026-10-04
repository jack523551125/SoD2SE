pub mod diagnostics;
pub mod events;
pub mod install;
pub mod legacy;
pub mod native_settings;
pub mod overlay;
pub mod plugin;
pub mod settings;
pub mod state;
pub mod translation;
pub mod transport;
pub mod ui;

pub fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id.as_bytes()[0].is_ascii_alphanumeric()
        && id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
}
