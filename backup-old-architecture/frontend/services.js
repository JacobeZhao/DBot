import { API } from "./constants.js";
import { parseHttpErrorPayload } from "./utils.js";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function withRetry(fetcher, { retries = 3, baseDelay = 280 } = {}) {
  let lastError = null;
  for (let i = 0; i < retries; i += 1) {
    try {
      return await fetcher(i);
    } catch (err) {
      lastError = err;
      if (i === retries - 1) break;
      await sleep(baseDelay * (i + 1));
    }
  }
  throw lastError;
}

export async function consumeSSE(response, handlers) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      try {
        const payload = JSON.parse(line.slice(5).trim());
        const fn = handlers[payload.type];
        if (fn) fn(payload);
      } catch {
        // ignore malformed chunks
      }
    }
  }
}

async function requireJson(response, fallback = "请求失败") {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(parseHttpErrorPayload(data) || fallback);
  }
  return data;
}

export async function streamChat(sessionId, message, handlers) {
  const response = await withRetry(async () => {
    const res = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => null);
      throw new Error(parseHttpErrorPayload(payload));
    }
    return res;
  }, { retries: 3, baseDelay: 320 });

  await consumeSSE(response, handlers);
}

export async function streamConfirm(sessionId, handlers) {
  const response = await fetch(`${API}/confirm/${encodeURIComponent(sessionId)}`, {
    method: "POST",
  });
  await consumeSSE(response, handlers);
}

export async function cancelPending(sessionId) {
  await fetch(`${API}/cancel/${encodeURIComponent(sessionId)}`, { method: "POST" });
}

export async function getConfig() {
  const res = await fetch(`${API}/config`);
  if (!res.ok) return {};
  return await res.json();
}

export async function saveConfigBatch(settings) {
  const payload = [
    { key: "openai_base_url", value: settings.api_base_url },
    { key: "openai_api_key", value: settings.api_key },
    { key: "openai_model", value: settings.model_id },
    { key: "temperature", value: settings.temperature },
    { key: "max_history_length", value: settings.max_history_length },
  ];

  const res = await fetch(`${API}/config/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  await requireJson(res, "配置保存失败");
}

export async function testConfigConnection(settings) {
  const res = await fetch(`${API}/config/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      api_key: settings.api_key,
      base_url: settings.api_base_url,
      model: settings.model_id,
      temperature: settings.temperature,
    }),
  });

  return await requireJson(res, "连接测试失败");
}

export async function listTables() {
  const data = await withRetry(async () => {
    const res = await fetch(`${API}/tables`);
    return await requireJson(res, "无法加载表列表");
  }, { retries: 3 });

  return data.tables || [];
}

export async function getTableData(tableName) {
  return await withRetry(async () => {
    const res = await fetch(`${API}/tables/${encodeURIComponent(tableName)}`);
    return await requireJson(res, "表数据加载失败");
  }, { retries: 3 });
}

export async function deleteTable(tableName) {
  const res = await fetch(`${API}/tables/${encodeURIComponent(tableName)}`, { method: "DELETE" });
  return await requireJson(res, "删除失败");
}

export async function createTable(payload) {
  const res = await fetch(`${API}/tables`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await requireJson(res, "创建失败");
}
