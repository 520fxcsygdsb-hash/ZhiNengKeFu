import { useState } from "react";
import { applyAdminFonts, t } from "../i18n";

// 支持的语言（与聊天前台 i18n.js 保持一致）
const LANG_OPTIONS = [
  { code: "zh", label: "中文", name: "简体中文" },
  { code: "en", label: "English", name: "English" },
  { code: "ar", label: "العربية", name: "العربية" },
  { code: "ja", label: "日本語", name: "日本語" },
  { code: "ko", label: "한국어", name: "한국어" },
  { code: "fr", label: "Français", name: "Français" },
  { code: "de", label: "Deutsch", name: "Deutsch" },
  { code: "es", label: "Español", name: "Español" },
  { code: "ru", label: "Русский", name: "Русский" },
  { code: "pt", label: "Português", name: "Português" },
  { code: "it", label: "Italiano", name: "Italiano" },
];

const FONT_OPTIONS = [
  { value: "system", label: "fontSystem" },
  { value: "serif", label: "fontSerif" },
  { value: "sans", label: "fontSans" },
  { value: "mono", label: "fontMono" },
];

const LANG_NAMES = Object.fromEntries(
  LANG_OPTIONS.map((l) => [l.code, l.name])
);

export default function PersonalizePage() {
  const [lang, setLang] = useState(
    () => localStorage.getItem("kefu-lang") || "zh"
  );
  const [fontFamily, setFontFamily] = useState(
    () => localStorage.getItem("kefu-font-family") || "system"
  );

  function selectLang(code) {
    setLang(code);
    localStorage.setItem("kefu-lang", code);
    window.dispatchEvent(new Event("kefu-lang-changed"));
  }

  function selectFont(value) {
    setFontFamily(value);
    localStorage.setItem("kefu-font-family", value);
    applyAdminFonts();
    window.dispatchEvent(new Event("kefu-font-changed"));
  }

  return (
    <div>
      <header className="page-header">
        <h2>{t("personalizeTitle", lang)}</h2>
      </header>

      <section className="card">
        <h3>{t("uiLanguage", lang)}</h3>
        <p className="muted">
          {t("currentLang", lang)}：{LANG_NAMES[lang] || LANG_NAMES.zh}
        </p>
        <div className="lang-switcher">
          {LANG_OPTIONS.map((opt) => (
            <button
              key={opt.code}
              type="button"
              className={`lang-btn${lang === opt.code ? " active" : ""}`}
              onClick={() => selectLang(opt.code)}
              title={opt.name}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <p className="hint">{t("langSyncHint", lang)}</p>
      </section>

      <section className="card">
        <h3>{t("fontType", lang)}</h3>
        <div className="opt-group">
          {FONT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`lang-btn${fontFamily === opt.value ? " active" : ""}`}
              onClick={() => selectFont(opt.value)}
            >
              {t(opt.label, lang)}
            </button>
          ))}
        </div>
        <p className="hint">{t("fontTypeHint", lang)}</p>
      </section>
    </div>
  );
}
