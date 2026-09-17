/* Values live only in this form's closure. No storage, analytics, interpolation or eval. */
(() => {
  "use strict";
  function parseEnv(text) {
    if (new TextEncoder().encode(text).length > 128000) throw Error("Choose a file under 128 KB.");
    const entries = [];
    const names = new Set();
    for (let line of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
      line = line.trim();
      if (!line || line.startsWith("#")) continue;
      const match = /^(?:export\s+)?([A-Z][A-Z0-9_]{0,63})\s*=\s*(.*)$/.exec(line);
      if (!match || names.has(match[1])) throw Error("Use unique uppercase NAME=value entries, one per line.");
      let value = match[2];
      if (value.startsWith('"') || value.startsWith("'")) {
        const quote = value[0];
        const end = value.lastIndexOf(quote);
        if (end === 0 || !/^\s*(?:#.*)?$/.test(value.slice(end + 1))) throw Error("Multiline or invalid quoted values are not supported.");
        value = value.slice(1, end); // Literal text; even $() and ${...} are never evaluated.
      } else value = value.replace(/\s+#.*$/, "").trim();
      if (!value || /[\x00-\x1f\x7f]/.test(value) || new TextEncoder().encode(value).length > 8000) throw Error("Values must be single-line text under 8 KB.");
      names.add(match[1]);
      entries.push({ name: match[1], value });
    }
    return entries;
  }

  async function open({ api, projectId, connection = null, done }) {
    const base = `/api/projects/${encodeURIComponent(projectId)}/connections`;
    const metadata = await api(`${base}/secrets`);
    const revisions = new Map(metadata.map(item => [item.name, item.revision]));
    let imported = [];
    const dialog = document.createElement("dialog");
    dialog.className = "integration-project-dialog custom-api-dialog ph-no-capture";
    dialog.setAttribute("aria-labelledby", "custom-api-title");
    const row = (label, control, attrs = "") => `<label class="custom-api-row" ${attrs}><span class="custom-api-label">${label}</span><span class="custom-api-control">${control}</span></label>`;
    const method = (m, note, checked) => `<label class="custom-api-check"><input name="method" type="checkbox" value="${m}"${checked ? " checked" : ""} /><code>${m}</code><small>${note}</small></label>`;
    dialog.innerHTML = `<form>
      <header>
        <h2 id="custom-api-title">Custom API</h2>
        <p>Connect one HTTPS service to this project. Keys stay in Tin. Saving does not make an API request.</p>
      </header>
      ${row("Connection name", '<input name="name" pattern="[a-z][a-z0-9_]{0,47}" required placeholder="crm" autocomplete="off" spellcheck="false" /><small class="custom-api-hint">Workflows call it as custom.api.name</small>')}
      ${row("HTTPS origin", '<input name="origin" type="url" required placeholder="https://api.example.com" autocomplete="off" spellcheck="false" />')}
      ${row("Authentication", '<select name="auth"><option value="bearer">Bearer token</option><option value="header">API-key header</option></select>')}
      ${row("Header name", '<input name="header" placeholder="X-API-Key" autocomplete="off" spellcheck="false" />', "data-header hidden")}
      ${row("Project secret name", '<input name="secret_name" pattern="[A-Z][A-Z0-9_]{0,63}" required placeholder="CRM_API_KEY" list="project-secret-names" autocomplete="off" spellcheck="false" /><datalist id="project-secret-names"></datalist><small class="custom-api-hint">Pick a saved secret or name a new one</small>')}
      ${row("Paste key", '<input name="secret" type="password" autocomplete="new-password" /><small class="custom-api-hint">Leave empty to use the saved secret</small>')}
      <div class="custom-api-row">
        <label class="custom-api-label" for="custom-api-env-file">Import from .env</label>
        <span class="custom-api-control"><input id="custom-api-env-file" name="env_file" type="file" /><small class="custom-api-hint">Only the names you select are saved. Values are never shown.</small><div data-import></div></span>
      </div>
      ${row("Confirm", '<span class="custom-api-check"><input name="replace" type="checkbox" /><span>Replace the selected existing secrets</span></span>', "data-replace hidden")}
      <div class="custom-api-row" role="group" aria-labelledby="custom-api-methods">
        <span class="custom-api-label" id="custom-api-methods">Allowed methods</span>
        <span class="custom-api-control custom-api-options">${method("GET", "read", true)}${["POST", "PUT", "PATCH", "DELETE"].map(m => method(m, "write", false)).join("")}</span>
      </div>
      ${row("Idempotency header", '<select name="idempotency"><option value="">None</option><option>Idempotency-Key</option><option>X-Idempotency-Key</option></select><small class="custom-api-hint">Added to write requests so retries stay safe</small>')}
      <p class="custom-api-note">Requests use the connected provider\u2019s account and may incur its charges. Tin model credits are separate. A workflow must also declare write permission to use write methods.</p>
      <footer class="custom-api-footer">
        <p data-error role="status"></p>
        <div class="custom-api-actions">${connection ? '<button class="integration-disconnect" type="button" data-disconnect>Disconnect</button>' : ""}<button class="button-quiet" type="button" data-close>Cancel</button><button class="button" type="submit">Save connection</button></div>
      </footer>
    </form>`;
    const form = dialog.querySelector("form");
    const field = name => form.elements.namedItem(name);
    const status = (message, tone = "error") => { const line = dialog.querySelector("[data-error]"); line.textContent = message; line.dataset.tone = tone; };
    for (const name of revisions.keys()) {
      const option = document.createElement("option");
      option.value = name;
      dialog.querySelector("datalist").append(option);
    }
    const config = connection?.configuration;
    if (config) {
      field("name").value = connection.key.replace("custom.api.", "");
      field("name").readOnly = true;
      for (const key of ["origin", "auth", "header", "secret_name"]) field(key).value = config[key];
      field("idempotency").value = config.idempotency_header || "";
      form.querySelectorAll('[name="method"]').forEach(input => { input.checked = config.methods.includes(input.value); });
    }
    const sync = () => {
      dialog.querySelector("[data-header]").hidden = field("auth").value !== "header";
      const selected = imported.filter((_, i) => form.querySelector(`[data-import-index="${i}"]`)?.checked);
      const replacing = selected.some(item => revisions.has(item.name)) || (field("secret").value && revisions.has(field("secret_name").value));
      dialog.querySelector("[data-replace]").hidden = !replacing;
      return { selected, replacing };
    };
    form.addEventListener("input", sync);
    field("env_file").addEventListener("change", async () => {
      try {
        const file = field("env_file").files[0];
        if (!file || file.size > 128000) throw Error("Choose a file under 128 KB.");
        imported = parseEnv(await file.text());
        const list = dialog.querySelector("[data-import]");
        list.replaceChildren();
        imported.forEach((item, i) => {
          const label = document.createElement("label");
          label.className = "custom-api-check custom-api-import";
          const input = document.createElement("input");
          input.type = "checkbox";
          input.dataset.importIndex = String(i);
          const name = document.createElement("code");
          name.textContent = item.name;
          const note = document.createElement("small");
          note.textContent = `•••••••• · ${revisions.has(item.name) ? "replaces saved secret" : "new"}`;
          label.append(input, name, note);
          list.append(label);
        });
        status("Select only the names this project needs.", "note");
      } catch (error) {
        imported = [];
        dialog.querySelector("[data-import]").replaceChildren();
        status(error.message);
      }
      field("env_file").value = "";
      sync();
    });
    const close = () => dialog.close();
    dialog.addEventListener("close", () => { imported = []; form.reset(); dialog.remove(); }, { once: true });
    dialog.querySelector("[data-close]").onclick = close;
    dialog.querySelector("[data-disconnect]")?.addEventListener("click", async () => {
      try {
        await api(`/api/projects/${encodeURIComponent(projectId)}/integrations/${encodeURIComponent(connection.key)}`, { method: "DELETE" });
        close(); await done();
      } catch (error) { status(error.message); }
    });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      try {
        const { selected, replacing } = sync();
        if (replacing && !field("replace").checked) throw Error("Confirm the listed secret replacements.");
        const entries = [...selected];
        if (field("secret").value) entries.push({ name: field("secret_name").value, value: field("secret").value });
        if (entries.length) {
          const updated = await api(`${base}/secrets`, { method: "PUT", body: JSON.stringify({ entries: entries.map(item => ({ ...item, expected_revision: revisions.get(item.name) || null })) }) });
          for (const item of updated) revisions.set(item.name, item.revision);
          // Do not retain key values if a later configuration save conflicts.
          field("secret").value = ""; imported = []; dialog.querySelector("[data-import]").replaceChildren();
        }
        await api(`${base}/custom.api.${field("name").value}`, { method: "PUT", body: JSON.stringify({ expected_revision: config?.revision || null, configuration: {
          origin: field("origin").value, auth: field("auth").value,
          header: field("auth").value === "bearer" ? "Authorization" : field("header").value,
          secret_name: field("secret_name").value,
          methods: [...form.querySelectorAll('[name="method"]:checked')].map(input => input.value),
          idempotency_header: field("idempotency").value || null,
        } }) });
        close(); await done();
      } catch (error) { status(error.message); }
      finally { button.disabled = false; }
    });
    sync(); document.body.append(dialog); dialog.showModal();
    // The scrolling form would otherwise take initial focus; start in the first editable field.
    form.querySelector("input:not([readonly]):not([type=\"file\"])").focus();
  }
  window.TinProjectConnections = { parseEnv, open };
})();
