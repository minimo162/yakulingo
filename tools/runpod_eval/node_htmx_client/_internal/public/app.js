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

  if (promptInput) {
    promptInput.focus();
  }
})();
