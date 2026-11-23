/* U - interface behaviour. Plain ES6+, no inline scripts (strict Content-Security-Policy). */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    initToasts();
    initPasswordToggles();
    initDeleteModal();
    initFormLoading();
    initBars();
    initCounters();
  });

  /* Flash messages are rendered as hidden toasts; show them. */
  function initToasts() {
    document.querySelectorAll(".u-toast").forEach(function (el) {
      new bootstrap.Toast(el).show();
    });
  }

  /* Password visibility toggle. */
  function initPasswordToggles() {
    document.querySelectorAll("[data-toggle-password]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var input = document.getElementById(btn.dataset.togglePassword);
        if (!input) return;
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.setAttribute("aria-pressed", String(show));
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        btn.querySelector("[data-icon-show]").hidden = show;
        btn.querySelector("[data-icon-hide]").hidden = !show;
      });
    });
  }

  /* One delete-confirmation modal shared by every row. Text is set with textContent (never innerHTML). */
  function initDeleteModal() {
    var modal = document.getElementById("deleteModal");
    if (!modal) return;
    var form = modal.querySelector("[data-delete-form]");
    var summary = modal.querySelector("[data-delete-summary]");
    modal.addEventListener("show.bs.modal", function (event) {
      var trigger = event.relatedTarget;
      if (!trigger) return;
      form.setAttribute("action", trigger.dataset.deleteUrl || "");
      summary.textContent = trigger.dataset.deleteSummary || "this expense";
    });
  }

  /* Loading feedback: label change + busy state after a valid submit starts. */
  function initFormLoading() {
    document.querySelectorAll("form").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented) return;
        var btn = event.submitter || form.querySelector('button[type="submit"]');
        if (!btn || !btn.dataset.loadingLabel) return;
        window.setTimeout(function () {
          btn.classList.add("is-loading");
          btn.setAttribute("aria-busy", "true");
          btn.disabled = true;
          var label = btn.dataset.loadingLabel;
          var text = document.createElement("span");
          text.textContent = label + "...";
          btn.replaceChildren(text);
        }, 0);
      });
    });
    /* Restore buttons if the page is shown again from the back/forward cache. */
    window.addEventListener("pageshow", function (event) {
      if (event.persisted) window.location.reload();
    });
  }

  /* Bars take their width from data-width (inline style attributes are blocked by the CSP). */
  function initBars() {
    document.querySelectorAll("[data-width]").forEach(function (el) {
      var value = parseFloat(el.dataset.width);
      if (!isNaN(value)) el.style.width = Math.max(0, Math.min(100, value)) + "%";
    });
  }

  /* Live character counter for the description field. */
  function initCounters() {
    document.querySelectorAll("[data-counter]").forEach(function (field) {
      var out = document.getElementById(field.dataset.counter);
      if (!out) return;
      var update = function () { out.textContent = String(field.value.length); };
      field.addEventListener("input", update);
      update();
    });
  }
})();
