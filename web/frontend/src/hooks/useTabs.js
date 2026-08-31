import { useCallback, useRef, useState } from "react";
import { loadTabs, saveTabs } from "../utils/storage";
import { makeTab } from "../utils/events";

export function useTabs() {
  const [tabs, setTabs] = useState(() => loadTabs(makeTab));
  const [activeTab, setActiveTab] = useState(0);
  const activeIdRef = useRef(null);

  const safeIndex = Math.min(activeTab, Math.max(tabs.length - 1, 0));
  const tab = tabs[safeIndex] || makeTab();

  const patchTab = useCallback((id, patch) => {
    setTabs((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch } : t))
    );
  }, []);

  const newTab = useCallback(() => {
    const fresh = makeTab();
    setTabs((prev) => {
      const next = [...prev, fresh];
      setActiveTab(next.length - 1);
      return next;
    });
    activeIdRef.current = fresh.id;
    return fresh.id;
  }, []);

  const closeTab = useCallback(
    (index) => {
      const target = tabs[index];
      if (
        target.messages.length > 0 &&
        !window.confirm(`Close tab "${target.title}"?`)
      ) {
        return;
      }
      const wasActive = index === safeIndex;
      setTabs((prev) => {
        const next = prev.filter((_, i) => i !== index);
        return next.length ? next : [makeTab()];
      });
      if (wasActive) {
        setActiveTab(Math.max(0, index - 1));
      } else if (index < safeIndex) {
        setActiveTab(safeIndex - 1);
      }
      fetch(`/api/sessions/${target.id}`, { method: "DELETE" }).catch(() => {});
    },
    [tabs, safeIndex]
  );

  // Persist to localStorage on every change
  const persistRef = useRef(tabs);
  persistRef.current = tabs;
  useState(() => {
    // Save on mount
    saveTabs(persistRef.current);
  });

  // Save on tab changes
  const lastSavedRef = useRef(0);
  const saveTimeoutRef = useRef(null);
  if (tabs !== persistRef.current) {
    const now = Date.now();
    if (now - lastSavedRef.current > 100) {
      saveTabs(tabs);
      lastSavedRef.current = now;
    } else if (!saveTimeoutRef.current) {
      saveTimeoutRef.current = setTimeout(() => {
        saveTabs(persistRef.current);
        saveTimeoutRef.current = null;
      }, 200);
    }
  }

  return {
    tabs,
    setTabs,
    activeTab,
    setActiveTab,
    safeIndex,
    tab,
    activeIdRef,
    patchTab,
    newTab,
    closeTab,
  };
}
