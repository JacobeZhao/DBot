import { LOCAL_KEYS } from "./constants.js";
import { safeText } from "./utils.js";

export function loadLocalSessions() {
  try {
    const raw = localStorage.getItem(LOCAL_KEYS.sessions);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && item.id && item.title !== undefined);
  } catch {
    return [];
  }
}

export function saveLocalSession(session, limit) {
  const list = loadLocalSessions();
  const dedup = [session, ...list.filter((s) => s.id !== session.id)];
  const finalLimit = Math.max(5, Number(limit) || 20);
  localStorage.setItem(LOCAL_KEYS.sessions, JSON.stringify(dedup.slice(0, finalLimit)));
}

export function buildSessionTitle(sessionId) {
  return `会话 ${safeText(sessionId).slice(-4)}`;
}
