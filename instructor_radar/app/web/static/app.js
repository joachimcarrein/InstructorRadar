// Instructor Radar UI. No inline scripts or styles (CSP); every URL is relative to the ingress base.
(function () {
  "use strict";
  const base = document.body.dataset.base || "/";

  // Position cards in the time grid (CSSOM changes are allowed by the CSP, style attributes in HTML are not).
  document.querySelectorAll(".card[data-top]").forEach((card) => {
    card.style.setProperty("--top", card.dataset.top + "%");
    card.style.setProperty("--height", card.dataset.height + "%");
  });
  document.querySelectorAll(".hour[data-h]").forEach((el, i, all) => {
    el.style.setProperty("--top", (i / (all.length - 1)) * 100 + "%");
  });

  // Phone (list layout): start at today instead of Monday.
  const today = document.querySelector(".day.is-today");
  if (today && window.matchMedia("(max-width: 760px)").matches) today.scrollIntoView({ block: "start" });

  const toast = document.getElementById("toast");
  function showToast(text) {
    if (!toast) return;
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => (toast.hidden = true), 5000);
  }

  // Lesson detail in a dialog.
  const dialog = document.getElementById("detail");
  const body = document.getElementById("detail-body");
  document.addEventListener("click", async (ev) => {
    const card = ev.target.closest(".card[data-id]");
    if (card && dialog) {
      const res = await fetch(base + "lesson/" + encodeURIComponent(card.dataset.id), { credentials: "same-origin" });
      if (!res.ok) return;
      body.innerHTML = await res.text(); // server-rendered, autoescaped template
      dialog.showModal();
      // Focus the dialog itself, not the close button (iOS draws a focus ring around it otherwise).
      dialog.setAttribute("tabindex", "-1");
      dialog.focus({ preventScroll: true });
      return;
    }
    if (ev.target.closest("[data-close]") || ev.target === dialog) dialog.close();
  });

  // Language (per Home Assistant user).
  const language = document.getElementById("language");
  if (language) {
    language.addEventListener("change", async () => {
      const res = await fetch(base + "language", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        body: new URLSearchParams({ language: language.value }),
      });
      if (res.ok) location.reload();
    });
  }

  // Fetch now, then poll the status until the run is done.
  const button = document.getElementById("fetch-now");
  if (button) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      const res = await fetch(base + "fetch", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
      });
      const data = await res.json();
      showToast(data.message);
      if (data.result !== "started" && data.result !== "running") {
        button.disabled = false;
        return;
      }
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const s = await (await fetch(base + "status", { credentials: "same-origin" })).json();
        if (!s.running) {
          location.reload();
          return;
        }
      }
      button.disabled = false;
    });
  }
})();
