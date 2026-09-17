"use strict";

const viewer = document.querySelector("#viewer");

async function loadStandaloneDocument() {
  const match = window.location.pathname.match(/^\/documents\/runs\/([^/]+)\/?$/);
  if (!match) {
    showViewerError("This document address is not valid.");
    return;
  }
  try {
    if (!window.Clerk) throw new Error("The identity service did not load.");
    await window.Clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
    if (!window.Clerk.isSignedIn) {
      const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
      viewer.innerHTML = `<div class="viewer-error">
        <strong>Sign in to open this document.</strong>
        <a class="button-secondary" href="/?next=${next}">Sign in</a>
      </div>`;
      return;
    }
    const token = await window.Clerk.session.getToken();
    if (!token) throw new Error("Your Tin session has ended.");
    const source = new URLSearchParams(window.location.search).get("source") === "retained" ? "?source=retained" : "";
    const response = await fetch(
      `/api/workflows/runs/${encodeURIComponent(match[1])}/artifact/document${source}`,
      { headers: { Accept: "application/json", Authorization: `Bearer ${token}` } },
    );
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string") message = payload.detail;
      } catch (_error) {
        // Preserve the HTTP status when the response is not JSON.
      }
      throw new Error(message);
    }
    const documentData = await response.json();
    window.TinMarkdownViewer.mount(viewer, documentData, { mode: "standalone" });
    window.document.title = `${documentData.filename} · Tin`;
  } catch (error) {
    showViewerError(error.message);
  }
}

function showViewerError(message) {
  const state = document.createElement("div");
  state.className = "viewer-error";
  const heading = document.createElement("strong");
  heading.textContent = "Tin could not open this document.";
  const detail = document.createElement("span");
  detail.textContent = message;
  state.append(heading, detail);
  viewer.replaceChildren(state);
}

loadStandaloneDocument();
