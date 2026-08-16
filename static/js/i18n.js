/* ═══════════════════════════════════════════════════════════
   CMS — i18n.js
   Small shared helpers for dark mode + language persistence,
   matching the logic already inlined in each dashboard page.
   Safe to include on any additional page you build.
   ═══════════════════════════════════════════════════════════ */

(function () {
  // Apply saved theme/lang immediately (before paint) if this
  // script is placed in <head>.
  const theme = localStorage.getItem("cms_theme") || "light";
  const lang = localStorage.getItem("cms_lang") || "en";
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.setAttribute("data-lang", lang);
})();

const CMSTheme = {
  get() {
    return document.documentElement.getAttribute("data-theme") || "light";
  },
  toggle() {
    const next = this.get() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("cms_theme", next);
    document.querySelectorAll(".theme-pill-thumb").forEach((el) => {
      el.textContent = next === "dark" ? "🌙" : "☀️";
    });
    return next;
  },
};

const CMSLang = {
  labels: { en: "EN", ta: "தமிழ்", hi: "हिंदी", fr: "FR", de: "DE" },
  get() {
    return document.documentElement.getAttribute("data-lang") || "en";
  },
  set(lang) {
    document.documentElement.setAttribute("data-lang", lang);
    localStorage.setItem("cms_lang", lang);
    document.querySelectorAll(".lang-item[data-lang]").forEach((el) => {
      el.classList.toggle("active", el.dataset.lang === lang);
    });
    return lang;
  },
};
