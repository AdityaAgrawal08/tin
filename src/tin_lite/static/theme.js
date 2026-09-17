"use strict";

(() => {
  const STORAGE_KEY = "tin-lite:theme";
  const PREFERENCES = new Set(["system", "light", "dark"]);
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  function storedPreference() {
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      return PREFERENCES.has(value) ? value : "system";
    } catch (_error) {
      return "system";
    }
  }

  function resolvedTheme(preference) {
    if (preference === "system") return systemDark.matches ? "dark" : "light";
    return preference;
  }

  function syncControls(root = document) {
    const preference = document.documentElement.dataset.themePreference || "system";
    root.querySelectorAll("[data-theme-preference]").forEach((button) => {
      const active = button.dataset.themePreference === preference;
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function apply(preference, { persist = true } = {}) {
    const selected = PREFERENCES.has(preference) ? preference : "system";
    const theme = resolvedTheme(selected);
    const root = document.documentElement;
    const previous = root.dataset.theme;
    root.dataset.themePreference = selected;
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      theme === "dark" ? "#141210" : "#f7f5ef",
    );
    if (persist) {
      try {
        window.localStorage.setItem(STORAGE_KEY, selected);
      } catch (_error) {
        // The active document still keeps the requested appearance.
      }
    }
    syncControls();
    if (previous !== theme) {
      window.dispatchEvent(new CustomEvent("tin:themechange", {
        detail: { preference: selected, theme },
      }));
    }
    return theme;
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-theme-preference]");
    if (button) apply(button.dataset.themePreference);
  });

  systemDark.addEventListener("change", () => {
    if (document.documentElement.dataset.themePreference === "system") {
      apply("system", { persist: false });
    }
  });

  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) apply(storedPreference(), { persist: false });
  });

  window.TinTheme = { apply, storedPreference, syncControls };
  syncControls();
})();
