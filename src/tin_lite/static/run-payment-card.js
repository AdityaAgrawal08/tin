"use strict";

window.TinRunPaymentCard = (() => {
  function collect() {
    return new Promise((resolve, reject) => {
      const dialog = document.createElement("dialog");
      dialog.className = "integration-project-dialog run-payment-dialog ph-no-capture";
      dialog.setAttribute("aria-label", "Start signup walkthrough");
      dialog.innerHTML = `<form autocomplete="off">
        <h2>Start signup walkthrough</h2>
        <p>A card is optional. Without one, the walkthrough records card-required trials as blockers.</p>
        <label><input type="checkbox" name="include_card"> Add a card for this run</label>
        <fieldset hidden disabled>
          <legend>One-run payment card</legend>
          <p>Use a card you authorize for this product’s free trial. The walkthrough may start a trial only when $0 is due now and must cancel before finishing. If cancellation fails, the report will tell you.</p>
          <label>Card number<input name="number" type="password" inputmode="numeric" maxlength="25" autocomplete="off" required></label>
          <label>Name on card<input name="name" maxlength="120" autocomplete="off" required></label>
          <label>Expiry (MM/YY)<input name="expiry" placeholder="MM/YY" pattern="(0[1-9]|1[0-2])/[0-9]{2}" maxlength="5" autocomplete="off" required></label>
          <label>Security code<input name="security_code" type="password" inputmode="numeric" pattern="[0-9]{3,4}" maxlength="4" autocomplete="off" required></label>
          <label>Billing address<input name="billing_address" maxlength="500" autocomplete="off" required></label>
          <p>Used only for this run. The stored card is encrypted and deleted when the run ends. It is never saved to this workflow’s configuration.</p>
        </fieldset>
        <div class="integration-dialog-actions"><button type="button" data-cancel>Cancel</button><button type="submit">Start walkthrough</button></div>
      </form>`;
      const form = dialog.querySelector("form");
      const checkbox = form.elements.include_card;
      const fields = form.querySelector("fieldset");
      checkbox.addEventListener("change", () => {
        fields.hidden = fields.disabled = !checkbox.checked;
        if (checkbox.checked) form.elements.number.focus();
      });
      const close = () => { form.reset(); dialog.close(); dialog.remove(); };
      const cancel = () => { close(); reject(new Error("Run cancelled.")); };
      dialog.addEventListener("cancel", event => { event.preventDefault(); cancel(); });
      dialog.querySelector("[data-cancel]").addEventListener("click", cancel);
      form.addEventListener("submit", event => {
        event.preventDefault();
        const card = checkbox.checked ? Object.fromEntries(
          ["number", "name", "expiry", "security_code", "billing_address"].map(name => [name, form.elements[name].value.trim()]),
        ) : null;
        close();
        resolve(card);
      });
      document.body.append(dialog);
      dialog.showModal();
    });
  }

  async function prepare(path, options, {workflows, projectWorkflows, assertContext}) {
    if (options.method !== "POST") return options;
    const direct = path.match(/^\/api\/workflows\/([^/]+)\/runs$/);
    const saved = path.match(/^\/api\/projects\/[^/]+\/workflows\/([^/]+)\/runs$/);
    const configured = saved && projectWorkflows.find(item => item.id === saved[1]);
    const workflow = workflows.find(item => item.id === (direct?.[1] || configured?.workflow_id));
    if (workflow?.key !== "qa.signup_walkthrough") return options;
    const card = await collect();
    assertContext();
    if (!card) return options;
    return {...options, body: JSON.stringify({...JSON.parse(options.body || "{}"), payment_card: card})};
  }
  return {prepare};
})();
