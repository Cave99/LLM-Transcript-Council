function detailsStorageKey() {
  return `details:${location.pathname}`;
}

function detailsKey(details) {
  if (details.dataset.detailsKey) return details.dataset.detailsKey;
  const summary = details.querySelector("summary");
  return summary ? summary.textContent.trim() : "";
}

function restoreDetailsState() {
  const saved = JSON.parse(localStorage.getItem(detailsStorageKey()) || "{}");
  document.querySelectorAll("details").forEach((details) => {
    const key = detailsKey(details);
    if (!key) return;
    if (Object.prototype.hasOwnProperty.call(saved, key)) details.open = saved[key];
    details.addEventListener("toggle", () => {
      const current = JSON.parse(localStorage.getItem(detailsStorageKey()) || "{}");
      current[key] = details.open;
      localStorage.setItem(detailsStorageKey(), JSON.stringify(current));
    });
  });
}

function bindConfirmForms() {
  document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const message = form.dataset.confirmMessage || "Are you sure?";
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });
}

function bindProjectRename() {
  document.querySelectorAll("[data-project-rename-form='true']").forEach((form) => {
    const container = form.closest(".hero-copy");
    const toggle = container ? container.querySelector("[data-rename-toggle='true']") : null;
    const cancel = form.querySelector("[data-rename-cancel='true']");
    const input = form.querySelector("[data-rename-input='true']");
    if (!container || !toggle || !cancel || !input) return;

    const setEditing = (editing) => {
      form.hidden = !editing;
      container.classList.toggle("is-editing", editing);
      if (editing) {
        input.focus();
        input.select();
      } else {
        toggle.focus();
      }
    };

    toggle.addEventListener("click", () => setEditing(true));
    cancel.addEventListener("click", () => setEditing(false));
  });
}

function saveDetailsState() {
  const current = JSON.parse(localStorage.getItem(detailsStorageKey()) || "{}");
  document.querySelectorAll("details").forEach((details) => {
    const key = detailsKey(details);
    if (key) current[key] = details.open;
  });
  localStorage.setItem(detailsStorageKey(), JSON.stringify(current));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    restoreDetailsState();
    bindConfirmForms();
    bindProjectRename();
    bindAnalysisForms();
  });
} else {
  restoreDetailsState();
  bindConfirmForms();
  bindProjectRename();
  bindAnalysisForms();
}

setInterval(() => {
  const pill = document.querySelector(".pill-running");
  if (pill && !document.hidden) {
    saveDetailsState();
    window.location.reload();
  }
}, 5000);

function bindAnalysisForms() {
  document.querySelectorAll("[data-analysis-form='true']").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      saveDetailsState();

      const button = form.querySelector("button");
      const progress = form.querySelector(".analysis-progress");
      const messages = [
        "Sampling judge reasoning traces...",
        "Asking analyzer model for patterns...",
        "Waiting for response...",
        "Saving trend summary...",
      ];
      let index = 0;

      button.disabled = true;
      button.dataset.originalText = button.textContent;
      button.textContent = "Analyzing...";
      progress.textContent = messages[index];

      const timer = setInterval(() => {
        index = Math.min(index + 1, messages.length - 1);
        progress.textContent = messages[index];
      }, 2500);

      try {
        const response = await fetch(form.action, { method: "POST" });
        clearInterval(timer);
        progress.textContent = "Analysis saved. Refreshing...";
        window.location.href = response.url || window.location.href;
      } catch (error) {
        clearInterval(timer);
        button.disabled = false;
        button.textContent = button.dataset.originalText || "Judge Pattern Analysis";
        progress.textContent = "Analysis request failed. Try again.";
      }
    });
  });
}
