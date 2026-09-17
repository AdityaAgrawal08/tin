/* Next planned article by default, through the ordinary shared run service. */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const setting = (label, html) => `<div class="system-setting"><strong>${label}</strong>${html}</div>`;
  const labels = {drafting: "Assessing / drafting", awaiting_review: "Awaiting review", drafted: "Draft saved", already_covered: "Already covered", needs_replanning: "Brief needs revision", insufficient_evidence: "Coverage needs checking", assessment_saved: "Saved assessment; recheck this brief", saved_result: "Saved result needs attention", failed: "Previous attempt failed", stopped: "Previous attempt stopped"};
  function fields(inputs = {}, schema = null) {
    return `<section data-content-draft data-program="${esc(inputs.program_id)}" data-item="${esc(inputs.item_id)}" data-rewrite="${Boolean(inputs.rewrite)}" data-automatic="${!schema?.required?.includes("item_id")}" data-rewrite-allowed="${schema ? Boolean(schema.properties?.rewrite) : true}">
      ${setting("Content program", '<div data-draft-program>Loading programs…</div>')}
      <p data-draft-progress class="system-config-note"></p>
      ${setting("Article to draft", '<div data-draft-items>Select a content program.</div>')}
      <input type="hidden" name="input:plan_revision" value="">
      <div data-draft-preview class="system-config-note"></div>
      <div data-draft-rewrite hidden></div>
      ${setting("Anything to add?", `<textarea class="workflow-inline-input workflow-inline-textarea" name="input:direction" rows="3" maxlength="2000" aria-label="Anything to add?">${esc(inputs.direction)}</textarea>`)}
      ${(!schema || schema.properties?.delivery) ? setting("After review", tinSelectControl("input:delivery", inputs.delivery || "program", [["program", "Use program delivery settings"], ["draft_only", "Keep this draft in Tin"]], "After review")) : ""}
      <p class="system-config-note">Check current coverage, then draft if useful. Otherwise, save an explanation without an article approval. Plan order is followed; nothing is published automatically. Earlier drafts and the roadmap stay unchanged.</p>
      <p data-draft-message class="system-config-note" role="status"></p>
    </section>`;
  }
  function mount(root, {api, projectId}) {
    for (const panel of root.querySelectorAll("[data-content-draft]")) {
      if (panel.dataset.bound) continue;
      panel.dataset.bound = "true";
      let generation = 0, data = null;
      const automatic = panel.dataset.automatic === "true";
      const rewriteAllowed = panel.dataset.rewriteAllowed === "true";
      const message = panel.querySelector("[data-draft-message]");
      const revision = panel.querySelector('[name="input:plan_revision"]');
      const rewrite = panel.querySelector("[data-draft-rewrite]");
      const current = token => panel.isConnected && token === generation;
      const selected = () => {
        const id = panel.querySelector('[name="input:item_id"]')?.value || "";
        const item = data?.items.find(row => row.id === (id || (automatic ? data.next?.item_id : null)));
        const writeAgain = panel.querySelector('[name="input:rewrite"]');
        const showRewrite = rewriteAllowed && Boolean(id && item?.can_rewrite);
        rewrite.hidden = !showRewrite;
        if (!showRewrite && writeAgain) writeAgain.value = "false";
        const ready = id ? Boolean(item?.available || (showRewrite && writeAgain?.value === "true")) : Boolean(automatic && data?.next?.available);
        panel.dataset.ready = String(ready);
        panel.dataset.valid = String(Boolean(data && (item || (!id && automatic))));
        // Saving the default must not freeze a future manual run to today's revision/item.
        revision.value = id ? (data?.plan_revision || "") : "";
        const prior = item?.draft;
        if (writeAgain) {
          const option = rewrite.querySelector('[data-tin-segment="true"]');
          if (option) option.textContent = prior?.assessment ? "Recheck this brief" : "Write new draft";
        }
        panel.querySelector("[data-draft-preview]").innerHTML = item
          ? `<p><strong>${esc(item.title)}</strong> · ${esc(item.due_date)} · ${esc(item.action === "update_page" ? "Update existing page" : "New page")}</p><p>${esc(item.brief)}</p><p>${esc(item.intent)}</p>${item.destination ? `<p>${esc(item.destination)}</p>` : ""}${prior ? `<p>${esc(labels[prior.stage] || prior.stage)}${prior.has_output || prior.assessment ? ` · <a class="system-action is-strong" href="/document/${encodeURIComponent(prior.run_id)}?project=${encodeURIComponent(projectId)}&return=workflows${prior.output_source === "retained" ? "&source=retained" : ""}">${prior.assessment ? "Read assessment" : "Read saved draft"} →</a>` : ""}</p>${prior.assessment ? `<p>${esc(prior.assessment.rationale)}</p>` : ""}` : ""}${item.brief_changed ? "<p>The plan changed since that result. A new run checks the amended brief; the earlier result stays available.</p>" : ""}<details><summary>Checks for this draft</summary><ul>${item.verification.map(v => `<li>${esc(v)}</li>`).join("")}</ul></details>`
          : "";
        message.textContent = !id ? (data?.next?.reason || "") :
          !item ? "This selected article is no longer in the plan. Choose another article." :
          item.held ? "Finish the pending revision for this batch before drafting." :
          item.readiness === "deferred" ? "This article is deferred. Update its plan before drafting." :
          prior?.stage === "drafting" ? "This article is already drafting. No duplicate will be started." :
          prior?.stage === "saved_result" ? "Resolve the saved result before drafting again." :
          prior?.assessment && !ready ? "Read the assessment, revise the brief, or explicitly recheck it." :
          item.can_rewrite && !ready ? "Read the saved draft, or explicitly choose to write a new one." :
          !ready ? "This article is not available for drafting. Check the content program." : "";
      };
      const resetRewrite = value => {
        if (!rewriteAllowed) return;
        rewrite.innerHTML = setting("Existing draft", tinSegmentedControl("input:rewrite", value, [["false", "Keep existing"], ["true", "Write new draft"]], "Existing draft"));
        bindTinControls(rewrite);
        rewrite.querySelector("input").addEventListener("change", selected);
      };
      const loadItems = async program => {
        const token = ++generation;
        data = null; panel.dataset.ready = "false"; panel.dataset.valid = "false"; revision.value = "";
        panel.querySelector("[data-draft-preview]").textContent = "";
        panel.querySelector("[data-draft-progress]").textContent = "";
        panel.querySelector("[data-draft-items]").textContent = program ? "Loading articles…" : "Select a content program.";
        rewrite.hidden = true; rewrite.innerHTML = ""; message.textContent = "";
        if (!program) return;
        try {
          const result = await api(`/api/projects/${projectId}/content-drafts/sources?program_id=${encodeURIComponent(program)}`);
          if (!current(token)) return;
          data = result;
          const prior = program === panel.dataset.program ? panel.dataset.item : "";
          const choices = data.items.filter(row => row.readiness !== "deferred" || row.id === prior).map(row => [row.id, `${row.title} · ${row.due_date}${row.held ? " · On hold" : row.draft ? ` · ${labels[row.draft.stage] || row.draft.stage}` : ""}`]);
          if (prior && !data.items.some(row => row.id === prior)) choices.unshift([prior, "Selected article no longer available"]);
          panel.querySelector("[data-draft-items]").innerHTML = tinSelectControl("input:item_id", prior,
            [["", automatic ? "Next article in plan" : "Choose an article…"], ...choices], "Article to draft");
          resetRewrite(program === panel.dataset.program && panel.dataset.rewrite === "true" ? "true" : "false");
          const progress = data.progress;
          if (progress) panel.querySelector("[data-draft-progress]").textContent = `${progress.drafted + progress.awaiting_review} of ${progress.total} articles drafted · ${progress.awaiting_review} awaiting review${progress.already_covered ? ` · ${progress.already_covered} already covered` : ""}${progress.needs_attention ? ` · ${progress.needs_attention} need attention` : ""}${progress.drafting ? ` · ${progress.drafting} assessing / drafting` : ""}${progress.deferred ? ` · ${progress.deferred} deferred` : ""}`;
          bindTinControls(panel);
          panel.querySelector('[name="input:item_id"]').addEventListener("change", () => {
            // A rewrite is consent for this article only, never carried to another choice.
            resetRewrite("false");
            selected();
          });
          selected();
        } catch (error) {if (current(token)) message.textContent = `${error.message} Reopen this card to retry.`;}
      };
      (async () => {
        try {
          const result = await api(`/api/projects/${projectId}/content-drafts/sources`);
          if (!panel.isConnected) return;
          const prior = result.programs.some(row => row.id === panel.dataset.program) ? panel.dataset.program : (result.programs.length === 1 && !panel.dataset.program ? result.programs[0].id : "");
          panel.querySelector("[data-draft-program]").innerHTML = tinSelectControl("input:program_id", prior,
            [["", "Choose a content program…"], ...result.programs.map(row => [row.id, row.name])], "Content program");
          bindTinControls(panel);
          panel.querySelector('[name="input:program_id"]').addEventListener("change", e => loadItems(e.target.value));
          if (!result.programs.length) message.textContent = "Create a content plan first. Its articles will appear here.";
          if (prior) await loadItems(prior);
        } catch (error) {if (panel.isConnected) message.textContent = `${error.message} Reopen this card to retry.`;}
      })();
    }
  }
  function prepare(form, {forRun = true} = {}) {
    const panel = form.querySelector("[data-content-draft]");
    if (panel?.dataset[forRun ? "ready" : "valid"] !== "true") throw new Error(panel?.querySelector("[data-draft-message]")?.textContent || "Choose an available content program first.");
  }
  function requestId(form, inputs) {
    const fingerprint = JSON.stringify(inputs);
    if (form.dataset.draftFingerprint !== fingerprint) {
      form.dataset.draftFingerprint = fingerprint;
      form.dataset.draftRequest = `ui:${crypto.randomUUID()}`;
    }
    return form.dataset.draftRequest;
  }
  window.TinContentDraft = {fields, mount, prepare, requestId};
})();
