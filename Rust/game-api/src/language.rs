//! Read-only language sources: explicit game culture, then this game's mounted Steam language.
use std::path::Path;
fn locale(value: &str) -> Option<String> {
    let value = value
        .trim()
        .trim_matches('"')
        .to_lowercase()
        .replace('_', "-");
    let mapped = match value.as_str() {
        "schinese" | "chinese" | "zh" => "zh-CN",
        "tchinese" => "zh-TW",
        "english" | "en" => "en-US",
        "french" => "fr-FR",
        "german" => "de-DE",
        "spanish" => "es-ES",
        "latam" => "es-419",
        "italian" => "it-IT",
        "japanese" => "ja-JP",
        "koreana" => "ko-KR",
        "russian" => "ru-RU",
        "polish" => "pl-PL",
        "portuguese" => "pt-PT",
        "brazilian" => "pt-BR",
        "turkish" => "tr-TR",
        _ => "",
    };
    if !mapped.is_empty() {
        return Some(mapped.into());
    }
    let parts: Vec<_> = value.split('-').collect();
    if parts.is_empty()
        || !(2..=3).contains(&parts[0].len())
        || !parts[0].bytes().all(|b| b.is_ascii_alphabetic())
        || parts
            .iter()
            .skip(1)
            .any(|p| p.is_empty() || p.len() > 8 || !p.bytes().all(|b| b.is_ascii_alphanumeric()))
    {
        return None;
    }
    Some(
        parts
            .iter()
            .enumerate()
            .map(|(i, p)| {
                if i > 0 && (p.len() == 2 || p.len() == 3) {
                    p.to_ascii_uppercase()
                } else {
                    p.to_string()
                }
            })
            .collect::<Vec<_>>()
            .join("-"),
    )
}
fn config(text: &str) -> Option<String> {
    text.trim_start_matches('\u{feff}')
        .lines()
        .filter_map(|line| line.split_once('='))
        .find_map(|(key, value)| {
            ["language", "locale", "culture"]
                .contains(&key.trim().to_ascii_lowercase().as_str())
                .then(|| locale(value))
                .flatten()
        })
}
fn manifest(text: &str) -> Option<String> {
    for section in ["MountedConfig", "UserConfig"] {
        let Some((_, tail)) = text.split_once(&format!(r#""{section}""#)) else {
            continue;
        };
        let block = tail.split('}').next().unwrap_or("");
        let fields: Vec<_> = block.split('"').collect();
        if let Some(l) = fields
            .windows(3)
            .filter(|p| p[0].eq_ignore_ascii_case("language"))
            .find_map(|p| locale(p[2]))
        {
            return Some(l);
        }
    }
    None
}
pub fn detect(game: &Path, local: &Path) -> String {
    let paths = [
        local.join("StateOfDecay2/Saved/Config/WindowsNoEditor/GameUserSettings.ini"),
        local.join("StateOfDecay2/Saved/Config/WindowsNoEditor/Game.ini"),
        game.join("Saved/Config/WindowsNoEditor/GameUserSettings.ini"),
        game.join("StateOfDecay2/Saved/Config/WindowsNoEditor/GameUserSettings.ini"),
    ];
    for path in paths {
        if let Some(locale) = std::fs::read_to_string(path).ok().and_then(|s| config(&s)) {
            return locale;
        }
    }
    for parent in game.ancestors().take(8) {
        if parent
            .file_name()
            .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("common"))
            && let Some(apps) = parent.parent()
            && let Some(locale) = std::fs::read_to_string(apps.join("appmanifest_495420.acf"))
                .ok()
                .and_then(|s| manifest(&s))
        {
            return locale;
        }
    }
    "en-US".into()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn languages() {
        assert_eq!(locale("schinese").as_deref(), Some("zh-CN"));
        assert_eq!(locale("en_US").as_deref(), Some("en-US"));
        assert_eq!(locale("fr-FR").as_deref(), Some("fr-FR"));
        assert_eq!(locale("bogus"), None);
    }
    #[test]
    fn mounted_language_precedence() {
        assert_eq!(
            manifest(
                r#""UserConfig" { "language" "english" } "MountedConfig" { "language" "schinese" }"#
            )
            .as_deref(),
            Some("zh-CN")
        );
    }
    #[test]
    fn explicit_culture() {
        assert_eq!(
            config("\u{feff}[Internationalization]\nCulture=zh-Hans-CN").as_deref(),
            Some("zh-hans-CN")
        );
        assert_eq!(config("NotCulture=schinese"), None);
    }
}
