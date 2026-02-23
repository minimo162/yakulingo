(function () {
  "use strict";

  const chatForm = document.getElementById("chat-form");
  const promptInput = document.getElementById("prompt");
  const chatLog = document.getElementById("chat-log");

  function scrollBottom() {
    if (!chatLog) return;
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (!event.target) return;
    if (event.target.id === "chat-log") {
      scrollBottom();
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
  });

  document.body.addEventListener("htmx:responseError", function (event) {
    if (!chatLog) return;
    const xhr = event?.detail?.xhr;
    const status = xhr?.status || 0;
    const text = xhr?.responseText || "Request failed.";
    const article = document.createElement("article");
    article.className = "turn turn-error";
    article.innerHTML = [
      '<header class="turn-header">Error</header>',
      `<pre class="turn-body">HTTP ${status}\n${String(text).slice(0, 1200)}</pre>`,
    ].join("");
    chatLog.appendChild(article);
    scrollBottom();
  });

  if (promptInput) {
    promptInput.focus();
  }
})();
