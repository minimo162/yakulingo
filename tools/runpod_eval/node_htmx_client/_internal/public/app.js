(function () {
  "use strict";

  const chatForm = document.getElementById("chat-form");
  const promptInput = document.getElementById("prompt");
  const chatLog = document.getElementById("chat-log");
  const indicator = document.getElementById("req-indicator");
  const workspaceInfo = document.getElementById("workspace-root");
  const workspaceSelectButton = document.getElementById("workspace-select-btn");
  const submitButton = chatForm ? chatForm.querySelector('button[type="submit"]') : null;
  let isRunning = false;
  let workspaceBusy = false;
  let workspaceState = null;
  const clientIdStorageKey = "localingo_client_id";
  const clientHeartbeatIntervalMs = 15000;
  const workspaceSelectTimeoutMs = 120000;
  const streamConnectTimeoutMs = 20000;
  const chatFallbackTimeoutMs = 60000;
  let clientId = "";
  let clientHeartbeatTimer = null;
  let activeAssistantStream = null;

  function generateClientId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID().replace(/[^A-Za-z0-9_-]/g, "").slice(0, 80);
    }
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 80);
  }

  function getOrCreateClientId() {
    try {
      const existing = String(localStorage.getItem(clientIdStorageKey) || "").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 80);
      if (existing) return existing;
      const created = generateClientId();
      if (created) {
        localStorage.setItem(clientIdStorageKey, created);
      }
      return created;
    } catch {
      return generateClientId();
    }
  }

  function buildClientSignalBody() {
    return `clientId=${encodeURIComponent(clientId)}`;
  }

  async function sendClientSignal(path, keepalive) {
    if (!clientId) return;
    const body = buildClientSignalBody();
    if (keepalive && typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      try {
        const blob = new Blob([body], { type: "application/x-www-form-urlencoded; charset=UTF-8" });
        navigator.sendBeacon(path, blob);
        return;
      } catch {
        // fallback to fetch
      }
    }
    try {
      await fetch(path, {
        method: "POST",
        headers: {
          "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body,
        keepalive: !!keepalive,
      });
    } catch {
      // ignore heartbeat failures
    }
  }

  function startClientHeartbeat() {
    clientId = getOrCreateClientId();
    if (!clientId) return;
    void sendClientSignal("/api/client/ping", false);
    if (clientHeartbeatTimer) {
      clearInterval(clientHeartbeatTimer);
    }
    clientHeartbeatTimer = setInterval(() => {
      void sendClientSignal("/api/client/ping", false);
    }, clientHeartbeatIntervalMs);
  }

  function stopClientHeartbeat() {
    if (clientHeartbeatTimer) {
      clearInterval(clientHeartbeatTimer);
      clientHeartbeatTimer = null;
    }
    void sendClientSignal("/api/client/disconnect", true);
  }

  function scrollBottom(target) {
    if (!target) return;
    target.scrollTop = target.scrollHeight;
  }

  function appendHtml(target, html) {
    if (!target || !html) return;
    target.insertAdjacentHTML("beforeend", String(html));
    scrollBottom(target);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function appendError(message) {
    if (!chatLog) return;
    const article = document.createElement("article");
    article.className = "turn turn-error";
    article.innerHTML = [
      '<header class="turn-header">Error</header>',
      `<pre class="turn-body">${escapeHtml(String(message || "Request failed.").slice(0, 2000))}</pre>`,
    ].join("");
    chatLog.appendChild(article);
    scrollBottom(chatLog);
  }

  function resetAssistantStreamState() {
    activeAssistantStream = null;
  }

  function ensureAssistantStreamCard(modelName) {
    if (!chatLog) return null;
    if (activeAssistantStream && activeAssistantStream.article && activeAssistantStream.body) {
      return activeAssistantStream;
    }
    const article = document.createElement("article");
    article.className = "turn turn-assistant";

    const header = document.createElement("header");
    header.className = "turn-header";
    header.textContent = `LocaLingo (${String(modelName || "").trim() || "model"})`;

    const body = document.createElement("pre");
    body.className = "turn-body";
    body.textContent = "";

    const footer = document.createElement("footer");
    footer.className = "turn-footer";
    footer.textContent = "streaming...";

    article.appendChild(header);
    article.appendChild(body);
    article.appendChild(footer);
    chatLog.appendChild(article);
    scrollBottom(chatLog);

    activeAssistantStream = {
      article,
      header,
      body,
      footer,
      text: "",
      hasContent: false,
    };
    return activeAssistantStream;
  }

  function appendAssistantStreamDelta(deltaText) {
    const stream = ensureAssistantStreamCard("");
    if (!stream) return;
    const delta = String(deltaText || "");
    if (!delta) return;
    stream.text += delta;
    stream.hasContent = true;
    stream.body.textContent = stream.text;
    scrollBottom(chatLog);
  }

  function finishAssistantStream(elapsedMs) {
    if (!activeAssistantStream || !activeAssistantStream.footer) return;
    const elapsed = Number.isFinite(elapsedMs) ? `${elapsedMs} ms` : "Done";
    activeAssistantStream.footer.textContent = elapsed;
  }

  function replaceAssistantStreamText(finalText, modelName, elapsedMs) {
    if (!activeAssistantStream) return;
    const nextText = String(finalText || "");
    if (!nextText) return;
    if (activeAssistantStream.body) {
      activeAssistantStream.body.textContent = nextText;
    }
    if (activeAssistantStream.header && modelName) {
      activeAssistantStream.header.textContent = `LocaLingo (${String(modelName).trim() || "model"})`;
    }
    activeAssistantStream.text = nextText;
    activeAssistantStream.hasContent = true;
    finishAssistantStream(elapsedMs);
    scrollBottom(chatLog);
  }

  function setRunningState(active, text) {
    isRunning = !!active;
    if (submitButton) {
      submitButton.disabled = isRunning;
    }
    if (indicator) {
      indicator.textContent = text || (isRunning ? "Running..." : "Idle");
    }
  }

  function setWorkspaceButtonsDisabled(disabled) {
    if (workspaceSelectButton) workspaceSelectButton.disabled = disabled;
  }

  function renderWorkspaceRoot(pathValue) {
    if (!workspaceInfo) return;
    const text = String(pathValue || "-");
    workspaceInfo.textContent = text;
    workspaceInfo.title = text;
  }

  async function refreshWorkspaceState() {
    if (!workspaceInfo) return;
    try {
      const response = await fetch("/api/workspace/state", { method: "GET" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      workspaceState = payload && typeof payload === "object" ? payload : null;
      renderWorkspaceRoot(workspaceState?.workspaceRoot || "-");
    } catch (err) {
      renderWorkspaceRoot(`workspace load failed: ${err?.message || String(err)}`);
    }
  }

  async function setWorkspaceByPath(pathValue) {
    const body = new URLSearchParams();
    body.set("path", String(pathValue || "").trim());
    const response = await fetch("/api/workspace/set", {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
      },
      body: body.toString(),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    if (payload?.ok !== true) {
      throw new Error(payload?.error || "Workspace update failed.");
    }
    return payload;
  }

  async function postJsonWithTimeout(path, { method = "POST", timeoutMs = 0 } = {}) {
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    let timer = null;
    if (controller && Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timer = setTimeout(() => {
        try {
          controller.abort();
        } catch {
          // ignore
        }
      }, timeoutMs);
    }
    try {
      const response = await fetch(path, {
        method,
        signal: controller ? controller.signal : undefined,
      });
      return response;
    } finally {
      if (timer) {
        clearTimeout(timer);
      }
    }
  }

  async function fallbackPromptWorkspacePath(errorMessage) {
    const current = String(workspaceState?.workspaceRoot || "").trim();
    const message = errorMessage
      ? `Could not open native folder picker.\n\n${errorMessage}\n\nEnter workspace folder path:`
      : "Enter workspace folder path:";
    const input = window.prompt(message, current);
    if (input === null) {
      return { canceled: true };
    }
    const nextPath = String(input || "").trim();
    if (!nextPath) {
      return { canceled: true };
    }
    const payload = await setWorkspaceByPath(nextPath);
    return {
      ok: true,
      workspaceRoot: payload?.workspaceRoot || nextPath,
    };
  }

  async function runWorkspaceAction(path, options = {}) {
    const allowPromptFallback = options?.allowPromptFallback !== false;
    if (workspaceBusy) return;
    workspaceBusy = true;
    setWorkspaceButtonsDisabled(true);
    if (!isRunning && indicator) indicator.textContent = "Workspace...";
    try {
      let response = null;
      if (path === "/api/workspace/select") {
        response = await postJsonWithTimeout(path, { method: "POST", timeoutMs: workspaceSelectTimeoutMs });
      } else {
        response = await postJsonWithTimeout(path, { method: "POST" });
      }
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      let payload = await response.json();
      if (path === "/api/workspace/select" && payload?.ok !== true && allowPromptFallback) {
        payload = await fallbackPromptWorkspacePath(payload?.error || "");
      }
      if (payload?.ok !== true && payload?.canceled !== true) {
        throw new Error(payload?.error || "Workspace update failed.");
      }
      await refreshWorkspaceState();
      if (!isRunning && indicator) {
        indicator.textContent = payload?.canceled ? "Workspace unchanged" : "Workspace updated";
      }
    } catch (err) {
      const errMsg = err?.message || String(err);
      if (path === "/api/workspace/select" && allowPromptFallback && /aborted|aborterror|timeout/i.test(errMsg)) {
        try {
          const payload = await fallbackPromptWorkspacePath("Native folder picker timeout. Falling back to path input.");
          if (payload?.ok === true || payload?.canceled === true) {
            await refreshWorkspaceState();
            if (!isRunning && indicator) {
              indicator.textContent = payload?.canceled ? "Workspace unchanged" : "Workspace updated";
            }
          } else {
            throw new Error("Workspace update failed.");
          }
        } catch (fallbackErr) {
          appendError(fallbackErr?.message || String(fallbackErr));
          if (!isRunning && indicator) indicator.textContent = "Workspace error";
        }
      } else {
        appendError(errMsg);
        if (!isRunning && indicator) indicator.textContent = "Workspace error";
      }
    } finally {
      workspaceBusy = false;
      setWorkspaceButtonsDisabled(false);
      if (!isRunning && indicator) {
        setTimeout(() => {
          if (!isRunning && indicator) indicator.textContent = "Idle";
        }, 1200);
      }
    }
  }

  async function quickSelectWorkspace() {
    // Open native explorer-style folder picker immediately.
    await runWorkspaceAction("/api/workspace/select", { allowPromptFallback: false });
  }

  function handleStreamEvent(event) {
    if (!event || typeof event !== "object") return;
    if (event.type === "assistant_stream_start") {
      ensureAssistantStreamCard(event.model || "");
      return;
    }
    if (event.type === "assistant_stream_delta") {
      appendAssistantStreamDelta(event.delta || "");
      return;
    }
    if (event.type === "assistant_stream_done") {
      finishAssistantStream(event.elapsedMs);
      return;
    }
    if (
      event.type === "user_turn"
      || event.type === "assistant_turn"
      || event.type === "tool_card"
      || event.type === "context_compacted"
    ) {
      if (event.type === "assistant_turn" && activeAssistantStream && activeAssistantStream.hasContent) {
        if (event.text) {
          replaceAssistantStreamText(event.text, event.model || "", event.elapsedMs);
        } else {
          finishAssistantStream(event.elapsedMs);
        }
        return;
      }
      appendHtml(chatLog, event.html || "");
      return;
    }
    if (event.type === "status") {
      setRunningState(true, String(event.message || "Running..."));
      return;
    }
    if (event.type === "error") {
      appendError(event.message || "Stream request failed.");
      return;
    }
    if (event.type === "done") {
      const elapsed = Number.isFinite(event.elapsedMs) ? `${event.elapsedMs} ms` : "Done";
      setRunningState(true, `Done (${elapsed})`);
    }
  }

  async function submitChatFallback(originalBody) {
    const fallbackBody = new URLSearchParams(originalBody.toString());
    fallbackBody.set("omit_user_turn", "1");
    fallbackBody.set("omit_middle_html", "1");
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    let timer = null;
    if (controller) {
      timer = setTimeout(() => {
        try {
          controller.abort();
        } catch {
          // ignore
        }
      }, chatFallbackTimeoutMs);
    }
    try {
      const response = await fetch("/api/chat/form", {
        method: "POST",
        headers: {
          "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body: fallbackBody.toString(),
        signal: controller ? controller.signal : undefined,
      });
      const html = await response.text();
      if (!response.ok) {
        throw new Error(`fallback HTTP ${response.status}\n${String(html).slice(0, 1200)}`);
      }
      appendHtml(chatLog, html);
    } catch (err) {
      if (err?.name === "AbortError") {
        throw new Error(`Fallback request timed out (${chatFallbackTimeoutMs} ms).`);
      }
      throw err;
    } finally {
      if (timer) {
        clearTimeout(timer);
      }
    }
  }

  async function submitChatWithStream(event) {
    event.preventDefault();
    if (!chatForm || isRunning) return;

    const formData = new FormData(chatForm);
    const prompt = String(formData.get("prompt") || "").trim();
    if (!prompt) {
      if (promptInput) promptInput.focus();
      return;
    }

    const body = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      if (typeof value === "string") {
        body.append(key, value);
      }
    }

    setRunningState(true, "Connecting...");
    resetAssistantStreamState();
    let gotDoneEvent = false;
    let gotAssistantTurn = false;
    try {
      const streamController = typeof AbortController !== "undefined" ? new AbortController() : null;
      let streamTimer = null;
      if (streamController) {
        streamTimer = setTimeout(() => {
          try {
            streamController.abort();
          } catch {
            // ignore
          }
        }, streamConnectTimeoutMs);
      }
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: {
          "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body: body.toString(),
        signal: streamController ? streamController.signal : undefined,
      });
      if (streamTimer) {
        clearTimeout(streamTimer);
      }

      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}\n${String(text).slice(0, 1200)}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let splitIndex = buffer.indexOf("\n");
        while (splitIndex >= 0) {
          const line = buffer.slice(0, splitIndex).trim();
          buffer = buffer.slice(splitIndex + 1);
          if (line) {
            try {
              const eventPayload = JSON.parse(line);
              if (eventPayload && typeof eventPayload === "object") {
                if (eventPayload.type === "assistant_turn") {
                  gotAssistantTurn = true;
                } else if (
                  eventPayload.type === "assistant_stream_start"
                  || eventPayload.type === "assistant_stream_delta"
                  || eventPayload.type === "assistant_stream_done"
                ) {
                  gotAssistantTurn = true;
                } else if (eventPayload.type === "done") {
                  gotDoneEvent = true;
                }
              }
              handleStreamEvent(eventPayload);
            } catch {
              // ignore malformed event line
            }
          }
          splitIndex = buffer.indexOf("\n");
        }
      }

      const tail = decoder.decode();
      if (tail) {
        buffer += tail;
      }
      const lastLine = buffer.trim();
      if (lastLine) {
        try {
          const finalPayload = JSON.parse(lastLine);
          if (finalPayload && typeof finalPayload === "object") {
            if (finalPayload.type === "assistant_turn") {
              gotAssistantTurn = true;
            } else if (
              finalPayload.type === "assistant_stream_start"
              || finalPayload.type === "assistant_stream_delta"
              || finalPayload.type === "assistant_stream_done"
            ) {
              gotAssistantTurn = true;
            } else if (finalPayload.type === "done") {
              gotDoneEvent = true;
            }
          }
          handleStreamEvent(finalPayload);
        } catch {
          // ignore malformed final line
        }
      }
    } catch (err) {
      const normalizedErr = err?.name === "AbortError"
        ? new Error(`Stream connection timed out (${streamConnectTimeoutMs} ms).`)
        : err;
      const streamError = normalizedErr?.message || String(normalizedErr);
      if (!gotDoneEvent && !gotAssistantTurn) {
        try {
          setRunningState(true, "Reconnecting...");
          await submitChatFallback(body);
        } catch (fallbackErr) {
          appendError([streamError, fallbackErr?.message || String(fallbackErr)].filter(Boolean).join("\n\n"));
        }
      } else if (!gotDoneEvent && gotAssistantTurn) {
        finishAssistantStream(null);
        setRunningState(true, "Completed");
      } else {
        appendError(streamError);
      }
    } finally {
      setRunningState(false, "Idle");
      if (promptInput) {
        promptInput.value = "";
        promptInput.focus();
      }
    }
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (!event.target) return;
    if (event.target.id === "chat-log") {
      scrollBottom(chatLog);
    }
  });

  if (chatForm) {
    chatForm.addEventListener("submit", submitChatWithStream);
  }
  if (workspaceSelectButton) {
    workspaceSelectButton.addEventListener("click", () => {
      void quickSelectWorkspace();
    });
  }
  void refreshWorkspaceState();
  startClientHeartbeat();
  window.addEventListener("pagehide", stopClientHeartbeat);
  window.addEventListener("beforeunload", stopClientHeartbeat);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      void sendClientSignal("/api/client/ping", false);
    }
  });
  if (promptInput) {
    promptInput.focus();
  }
})();

