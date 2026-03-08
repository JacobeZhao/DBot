export function safeText(value) {
  if (value === null || value === undefined) return "";
  return String(value);
}

export function escapeHtml(value) {
  const text = safeText(value);
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function validateIdentifier(value) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(safeText(value).trim());
}

export function validateWhereClause(value) {
  const clause = safeText(value).trim();
  if (!clause) return false;
  return !/(;|--|\/\*|\*\/|\b(drop|alter|attach|detach|pragma|vacuum|reindex|create|replace)\b)/i.test(clause);
}

export function sanitizeIntent(value) {
  const intent = safeText(value).trim();
  return /^[a-z_]{1,32}$/.test(intent) ? intent : "";
}

export function normalizeErrorMessage(message) {
  if (!message) return "请求失败，请稍后重试。";
  if (typeof message === "string") return message;
  return "请求失败，请检查网络或配置。";
}

export function parseHttpErrorPayload(payload) {
  if (!payload) return "请求失败";
  if (typeof payload === "string") return payload;
  if (payload.detail) return payload.detail;
  if (payload.message) return payload.message;
  return "请求失败";
}

export function parseConfirmPreview(previewText) {
  const text = safeText(previewText);
  const parsed = { table: "", whereClause: "", sqls: [] };

  const tableMatch = text.match(/表[「\"]([^」\"\n]+)[」\"]/);
  if (tableMatch) parsed.table = tableMatch[1].trim();

  const whereMatch = text.match(/条件：([^\n]+)/);
  if (whereMatch) parsed.whereClause = whereMatch[1].trim();

  const sqlBlockMatch = text.match(/SQL：\n([\s\S]*?)(?:\n\n|$)/);
  if (sqlBlockMatch) {
    parsed.sqls = sqlBlockMatch[1]
      .split("\n")
      .map((line) => line.replace(/^\s*[·•]\s*/, "").trim())
      .filter(Boolean);
  }

  return parsed;
}

export function validateConfirmPreview(intent, previewText) {
  const parsed = parseConfirmPreview(previewText);
  const normalizedIntent = sanitizeIntent(intent);

  if (["drop_table", "delete_data"].includes(normalizedIntent)) {
    if (!validateIdentifier(parsed.table)) {
      return { ok: false, reason: "预览中的表名不合法，已拦截执行。" };
    }
  }

  if (normalizedIntent === "delete_data") {
    if (!validateWhereClause(parsed.whereClause)) {
      return { ok: false, reason: "预览中的删除条件不安全，已拦截执行。" };
    }
  }

  if (normalizedIntent === "alter_table") {
    if (!parsed.sqls.length) {
      return { ok: false, reason: "未识别到结构修改 SQL，已拦截执行。" };
    }

    const hasUnsafeSql = parsed.sqls.some((sql) =>
      /(;|--|\/\*|\*\/|\b(attach|detach|pragma|vacuum|reindex|create|replace)\b)/i.test(sql)
    );
    if (hasUnsafeSql) {
      return { ok: false, reason: "预览中的 SQL 包含危险语句，已拦截执行。" };
    }

    const hasNonAlter = parsed.sqls.some((sql) => !/^ALTER\s+TABLE\s+/i.test(sql.trim()));
    if (hasNonAlter) {
      return { ok: false, reason: "仅允许 ALTER TABLE 语句，已拦截执行。" };
    }
  }

  return { ok: true, reason: "" };
}
