"use strict";

async function loadTinConsent() {
  const status = document.querySelector("#consent-status");
  const mount = document.querySelector("#clerk-oauth-consent");
  try {
    const clerk = window.Clerk;
    if (!clerk) throw new Error("Identity service unavailable");
    await clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
    if (!clerk.isSignedIn) {
      status.hidden = true;
      document.querySelector("#consent-sign-in").hidden = false;
      return;
    }
    if (typeof clerk.mountOAuthConsent !== "function") {
      throw new Error("Consent component unavailable");
    }
    // Clerk reads and preserves the request, renders the client/scopes/redirect,
    // and owns both Allow and Deny. Tin does not intercept or submit a decision.
    const shared = window.TinAuth.appearance;
    const appearance = {variables: {...shared.variables}, elements: {}};
    // Reuse Tin's card and text styling, while keeping every consent identity,
    // scope, warning, destination and decision control visible.
    for (const name of ["rootBox", "cardBox", "card", "header", "main", "footer"]) {
      appearance.elements[name] = structuredClone(shared.elements[name]);
    }
    appearance.elements.headerTitle = {
      color: "var(--ink)", fontSize: "18px", fontWeight: 400, lineHeight: "24px",
    };
    appearance.elements.headerSubtitle = {
      color: "var(--ink-secondary)", fontSize: "13px", lineHeight: "19px", textAlign: "left",
    };
    clerk.mountOAuthConsent(mount, {appearance});
    status.hidden = true;
  } catch (_error) {
    mount.replaceChildren();
    status.textContent = "The connection request could not load. Try reloading this step. If it still fails, close this tab and connect again from your coding agent.";
    status.hidden = false;
  }
}

document.querySelector("#consent-retry").addEventListener("click", () => window.location.reload());
loadTinConsent();
