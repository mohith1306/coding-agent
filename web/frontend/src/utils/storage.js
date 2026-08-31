export const STORAGE_KEY = "coding_agent_tabs";
export const LEGACY_SESSION_KEY = "coding_agent_session_id";

export function loadTabs(makeTab) {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.map((t) => ({
          ...makeTab(t.id),
          ...t,
          model: t.model || "openrouter/auto",
        }));
      }
    } catch {
      // fall through
    }
  }
  const legacyId = localStorage.getItem(LEGACY_SESSION_KEY);
  if (legacyId) {
    return [makeTab(legacyId, "New session")];
  }
  return [makeTab()];
}

export function saveTabs(tabs) {
  const saved = tabs.map((t) => ({
    ...t,
    status: "",
    messages: (t.messages || []).slice(-200),
    openFolders: [...(t.openFolders || [])],
  }));
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // ignore quota errors
  }
}
