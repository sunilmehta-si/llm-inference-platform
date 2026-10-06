"use strict";
const $ = (id) => document.getElementById(id);
let config, controller, running = false;
const history = [];
const messages = $("messages");
function showError(text) { $("error").textContent = text; $("error").hidden = !text; }
async function checkKey() {
  const key = $("api-key").value.trim().replace(/^Bearer\s+/i, "");
  if (!key) {
    showError("Open this project's .env file and paste the GATEWAY_API_KEY value, then check it here.");
    $("api-key").focus(); return false;
  }
  $("api-key").value = key;
  try {
    const response = await fetch("/v1/models", {headers: {Authorization: `Bearer ${key}`}, signal: AbortSignal.timeout(7000)});
    if (response.status === 401) {
      showError("This is not the local gateway key. Use GATEWAY_API_KEY from this project's .env file. External provider keys will not work.");
      $("key-status").textContent = "Key not accepted by this gateway."; return false;
    }
    if (!response.ok) throw new Error(`Key check failed (${response.status}).`);
    $("key-status").textContent = "Local key verified. You can send a question."; showError(""); return true;
  } catch (error) { showError(error.message); return false; }
}
$("check-key").addEventListener("click", checkKey);
$("api-key").addEventListener("input", () => { $("key-status").textContent = "Key changed. Click Check local key to verify it."; });
function addMessage(role, text) {
  $("empty-state")?.remove();
  const block = document.createElement("div"); block.className = `message ${role}`;
  const label = document.createElement("div"); label.className = "message-label";
  label.textContent = role === "user" ? "YOU" : "MODEL";
  const content = document.createElement("div"); content.className = "message-text";
  content.textContent = text; block.append(label, content); messages.append(block);
  messages.scrollTop = messages.scrollHeight; return content;
}
async function readiness() {
  try {
    const response = await fetch("/readyz", {signal: AbortSignal.timeout(7000)});
    $("status-text").textContent = response.ok ? "Model ready" : "Model unavailable";
    $("status").classList.toggle("ready", response.ok);
  } catch { $("status-text").textContent = "Gateway unavailable"; $("status").classList.remove("ready"); }
}
function busy(value) {
  running = value; $("send").disabled = value; $("clear").disabled = value;
  $("stop").hidden = !value; $("prompt").disabled = value;
  $("check-key").disabled = value;
}
$("max-tokens").addEventListener("input", (e) => { $("tokens-value").textContent = e.target.value; });
$("temperature").addEventListener("input", (e) => { $("temp-value").textContent = e.target.value; });
$("settings-form").addEventListener("submit", (e) => e.preventDefault());
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
  $("prompt").value = button.dataset.prompt; $("prompt").focus();
}));
$("clear").addEventListener("click", () => {
  history.length = 0; messages.replaceChildren(); showError("");
  $("request-stats").textContent = "New conversation · Streaming enabled"; $("prompt").focus();
});
$("stop").addEventListener("click", () => controller?.abort());
$("prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); if (!running) $("chat-form").requestSubmit();
  }
});
$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (running || !config) return;
  const prompt = $("prompt").value.trim(), key = $("api-key").value.trim();
  if (!prompt) return;
  if (!key) { showError("Paste the gateway API key from your local .env file first."); $("api-key").focus(); return; }
  if (history.length >= 62) { showError("Clear this conversation before sending more messages."); return; }
  showError(""); busy(true);
  if (!(await checkKey())) { busy(false); return; }
  addMessage("user", prompt); $("prompt").value = "";
  const answer = addMessage("assistant", "Waiting for the model…");
  const start = performance.now(); let first = null, text = "", usage = null, done = false;
  controller = new AbortController();
  let reader;
  try {
    const response = await fetch("/v1/chat/completions", {
      method: "POST", signal: controller.signal,
      headers: {"Content-Type": "application/json", "Authorization": `Bearer ${$("api-key").value}`},
      body: JSON.stringify({model: config.model, messages: [...history, {role: "user", content: prompt}],
        max_tokens: Number($("max-tokens").value), temperature: Number($("temperature").value), stream: true,
        stream_options: {include_usage: true}}),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === "string" ? error.detail : `Request failed (${response.status}).`);
    }
    reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const result = await reader.read();
      buffer += decoder.decode(result.value || new Uint8Array(), {stream: !result.done});
      const lines = buffer.split("\n"); buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim(); if (!payload) continue;
        if (payload === "[DONE]") { done = true; continue; }
        const chunk = JSON.parse(payload);
        if (chunk.error) throw new Error(chunk.error.message || "The model stream failed.");
        if (chunk.usage) usage = chunk.usage;
        const delta = chunk.choices?.[0]?.delta;
        const content = delta?.content || delta?.reasoning_content || "";
        if (content) {
          first ??= (performance.now() - start) / 1000; text += content;
          answer.textContent = text; messages.scrollTop = messages.scrollHeight;
          $("request-stats").textContent = `Streaming · First token ${first.toFixed(2)}s`;
        }
      }
      if (result.done) break;
    }
    if (!done || !text) throw new Error("The model stream ended without a complete answer.");
    history.push({role: "user", content: prompt}, {role: "assistant", content: text});
    const duration = (performance.now() - start) / 1000;
    const tokenInfo = Number.isInteger(usage?.completion_tokens) ? `${usage.completion_tokens} output tokens` : "Token usage unavailable";
    $("request-stats").textContent = `First token ${first.toFixed(2)}s · Total ${duration.toFixed(2)}s · ${tokenInfo}`;
  } catch (error) {
    const stopped = error.name === "AbortError";
    if (!text) answer.textContent = stopped ? "Generation stopped." : "The request did not complete.";
    showError(stopped ? "Generation stopped. The partial answer was not added to conversation history." : error.message);
    $("request-stats").textContent = stopped ? "Stopped" : "Request failed";
  } finally {
    await reader?.cancel().catch(() => {}); busy(false); controller = null; $("prompt").focus();
  }
});
async function init() {
  try {
    const response = await fetch("/ui/config"); if (!response.ok) throw new Error("UI configuration unavailable");
    config = await response.json(); $("model-name").textContent = config.model;
    $("max-tokens").max = config.max_output_tokens;
    $("max-tokens").value = Math.min(128, config.max_output_tokens);
    $("tokens-value").textContent = $("max-tokens").value;
  } catch (error) { showError(error.message); }
  await readiness(); setInterval(readiness, 15000);
}
init();
