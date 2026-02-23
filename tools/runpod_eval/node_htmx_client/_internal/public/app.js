(function () {
  "use strict";

  const chatForm = document.getElementById("chat-form");
  const promptInput = document.getElementById("prompt");
  const chatLog = document.getElementById("chat-log");
  const toolLog = document.getElementById("tool-log");
  const toolReadForm = document.getElementById("tool-read-form");
  const toolSearchForm = document.getElementById("tool-search-form");
  const toolShellForm = document.getElementById("tool-shell-form");
  const toolWriteForm = document.getElementById("tool-write-form");
  const autoloopForm = document.getElementById("autoloop-form");
  const modelSelect = document.getElementById("model");

  function scrollBottom(target) {
    if (!target) return;
    target.scrollTop = target.scrollHeight;
  }

  function clearIfFound(id, value = "") {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = value;
  }

  function uncheckIfFound(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = false;
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (!event.target) return;
    if (event.target.id === "chat-log") {
      scrollBottom(chatLog);
    }
    if (event.target.id === "tool-log") {
      scrollBottom(toolLog);
    }
  });

  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (!event.detail || !event.detail.elt) return;
    const elt = event.detail.elt;
    if (chatForm && elt === chatForm && event.detail.successful) {
      if (promptInput) {
        promptInput.value = "";
        promptInput.focus();
      }
    }

    if (toolReadForm && elt === toolReadForm && event.detail.successful) {
      clearIfFound("tool-read-path");
    }
    if (toolSearchForm && elt === toolSearchForm && event.detail.successful) {
      clearIfFound("tool-search-pattern");
      clearIfFound("tool-search-glob");
    }
    if (toolShellForm && elt === toolShellForm && event.detail.successful) {
      clearIfFound("tool-shell-command");
      uncheckIfFound("tool-shell-approved");
    }
    if (toolWriteForm && elt === toolWriteForm && event.detail.successful) {
      clearIfFound("tool-write-path");
      clearIfFound("tool-write-content");
      uncheckIfFound("tool-write-approved");
    }
    if (autoloopForm && elt === autoloopForm && event.detail.successful) {
      uncheckIfFound("autoloop-approve");
    }
  });

  document.body.addEventListener("htmx:responseError", function (event) {
    if (!chatLog && !toolLog) return;
    const xhr = event?.detail?.xhr;
    const status = xhr?.status || 0;
    const text = xhr?.responseText || "Request failed.";
    const target = event?.detail?.elt?.closest?.("#tool-read-form, #tool-search-form, #tool-shell-form, #tool-write-form")
      ? toolLog
      : chatLog;
    if (!target) return;
    const article = document.createElement("article");
    article.className = "turn turn-error";
    article.innerHTML = [
      '<header class="turn-header">Error</header>',
      `<pre class="turn-body">HTTP ${status}\n${String(text).slice(0, 1200)}</pre>`,
    ].join("");
    target.appendChild(article);
    scrollBottom(target);
  });

  if (promptInput) {
    promptInput.focus();
  }

  if (autoloopForm) {
    autoloopForm.addEventListener("submit", function () {
      const autoModel = document.getElementById("autoloop-model");
      if (!autoModel) return;
      if (!String(autoModel.value || "").trim() && modelSelect && modelSelect.value) {
        autoModel.value = modelSelect.value;
      }
    });
  }
})();
