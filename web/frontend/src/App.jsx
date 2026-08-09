import React, { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "coding_agent_tabs";
const LEGACY_SESSION_KEY = "coding_agent_session_id";

function makeTab(id = crypto.randomUUID(), title = "New session") {
  return {
    id,
    title,
    input: "",
    messages: [],
    pending: null,
    busy: false,
    tree: null,
    selected: "",
    fileContent: "",
    dirty: false,
    saving: false,
    running: false,
    runResult: "",
    openFolders: [],
  };
}

function loadTabs() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.map((t) => ({ ...makeTab(t.id), ...t }));
      }
    } catch {
      // fall through to a fresh tab
    }
  }
  const legacyId = localStorage.getItem(LEGACY_SESSION_KEY);
  if (legacyId) {
    return [makeTab(legacyId, "New session")];
  }
  return [makeTab()];
}

function parseConfirmation(text) {
  const actionMatch = text.match(/Action:\s*(.+)/);
  const targetMatch = text.match(/Target:\s*(.+)/);
  return {
    action: actionMatch ? actionMatch[1].trim() : "",
    target: targetMatch ? targetMatch[1].trim() : "",
  };
}

const FILE_TYPES = {
  py: { icon: "\u{1F40D}", color: "#3572A5" }, // snake -> python
  js: { icon: "\u{1F381}", color: "#f1e05a" },
  jsx: { icon: "\u26A1", color: "#61dafb" },
  ts: { icon: "\u{1F5C4}\uFE0F", color: "#3178c6" },
  tsx: { icon: "\u26A1", color: "#61dafb" },
  json: { icon: "\u{1F4CB}", color: "#cbcb41" },
  html: { icon: "\u{1F4F1}", color: "#e34c26" },
  css: { icon: "\u{1F3A8}", color: "#563d7c" },
  md: { icon: "\u{1F4DD}", color: "#519aba" },
  txt: { icon: "\u{1F4C4}", color: "#9ca3af" },
  yml: { icon: "\u2699\uFE0F", color: "#e34c26" },
  yaml: { icon: "\u2699\uFE0F", color: "#e34c26" },
  sh: { icon: "\u{1F4F4}", color: "#89e051" },
  bash: { icon: "\u{1F4F4}", color: "#89e051" },
  Dockerfile: { icon: "\u{1F6E2}\uFE0F", color: "#2496ed" },
  env: { icon: "\u{1F512}", color: "#9ca3af" },
  lock: { icon: "\u{1F512}", color: "#9ca3af" },
  toml: { icon: "\u2699\uFE0F", color: "#9ca3af" },
  cfg: { icon: "\u2699\uFE0F", color: "#9ca3af" },
  ini: { icon: "\u2699\uFE0F", color: "#9ca3af" },
  gitignore: { icon: "\u{1F511}", color: "#f05033" },
  csv: { icon: "\u{1F4CA}", color: "#2ea44f" },
  sql: { icon: "\u{1F4BE}", color: "#e38c00" },
  zip: { icon: "\u{1F4E6}", color: "#9ca3af" },
};

const FOLDER_ICON = "\u{1F4C1}";
const FOLDER_OPEN_ICON = "\u{1F4C2}";
const FILE_ICON = "\u{1F4C4}";

function fileTypeFor(name) {
  const lower = name.toLowerCase();
  if (lower in FILE_TYPES) return lower;
  const dot = lower.lastIndexOf(".");
  if (dot > 0 && lower.slice(dot + 1) in FILE_TYPES) {
    return lower.slice(dot + 1);
  }
  return null;
}

function FileTree({ node, depth = 0, onSelect, selected, open, onToggle, onDelete }) {
  const indent = { paddingLeft: `${depth * 14 + 8}px` };
  if (node.type === "file") {
    const isSel = selected === node.path;
    const info = fileTypeFor(node.name);
    const style = info ? { color: FILE_TYPES[info].color } : null;
    const icon = info ? FILE_TYPES[info].icon : FILE_ICON;
    return (
      <div
        className={`file-entry file ${isSel ? "selected" : ""}`}
        style={indent}
        onClick={() => onSelect(node.path)}
        title={`${node.path} (${node.size} bytes)`}
      >
        <span className="file-icon" style={style}>
          {icon}
        </span>
        <span className="file-name">{node.name}</span>
        <span
          className="file-del"
          title="Delete file"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(node.path);
          }}
        >
          ✕
        </span>
      </div>
    );
  }
  const isOpen = open.has(node.path);
  return (
    <div>
      <div
        className="file-entry dir"
        style={indent}
        onClick={() => onToggle(node.path)}
      >
        <span className="file-icon">
          {isOpen ? FOLDER_OPEN_ICON : FOLDER_ICON}
        </span>
        <span className="file-name">{node.name}</span>
      </div>
      {isOpen &&
        node.children.map((child, i) => (
          <FileTree
            key={`${child.name}-${i}`}
            node={{ ...child, path: `${node.path}/${child.name}` }}
            depth={depth + 1}
            onSelect={onSelect}
            selected={selected}
            open={open}
            onToggle={onToggle}
            onDelete={onDelete}
          />
        ))}
    </div>
  );
}

export default function App() {
  const [tabs, setTabs] = useState(loadTabs);
  const [activeTab, setActiveTab] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const endRef = useRef(null);
  const activeIdRef = useRef(null);

  const safeIndex = Math.min(activeTab, Math.max(tabs.length - 1, 0));
  const tab = tabs[safeIndex] || makeTab();
  activeIdRef.current = tab.id;

  useEffect(() => {
    const saved = tabs.map((t) => ({
      ...t,
      messages: (t.messages || []).slice(-200),
      openFolders: [...(t.openFolders || [])],
    }));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    } catch {
      // ignore quota errors
    }
  }, [tabs]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [tab.messages, tab.pending]);

  useEffect(() => {
    refreshFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  function patchTab(id, patch) {
    setTabs((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch } : t))
    );
  }

  async function ensureSession(id) {
    try {
      await fetch(`/api/sessions/${id}`, { method: "POST" });
    } catch {
      // workspace is created lazily on first chat anyway
    }
  }

  async function refreshFiles() {
    const id = activeIdRef.current;
    try {
      const res = await fetch(`/api/sessions/${id}/files`);
      if (!res.ok) return;
      const data = await res.json();
      patchTab(id, { tree: data.tree });
      if (tab.selected) {
        loadFile(tab.selected);
      }
    } catch {
      // ignore transient refresh errors
    }
  }

  function toggleFolder(path) {
    const id = tab.id;
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        const next = new Set(t.openFolders || []);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return { ...t, openFolders: [...next] };
      })
    );
  }

  function revealPath(path) {
    const id = tab.id;
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        const next = new Set(t.openFolders || []);
        const parts = path.split("/");
        parts.pop();
        let acc = "";
        for (const part of parts) {
          acc = acc ? `${acc}/${part}` : part;
          next.add(acc);
        }
        return { ...t, openFolders: [...next] };
      })
    );
  }

  async function loadFile(path) {
    const id = activeIdRef.current;
    patchTab(id, {
      selected: path,
      fileContent: "",
      dirty: false,
      runResult: "",
    });
    revealPath(path);
    try {
      const res = await fetch(`/api/sessions/${id}/files/${path}`);
      if (!res.ok) {
        patchTab(id, { fileContent: "(unable to read file)" });
        return;
      }
      const data = await res.json();
      patchTab(id, { fileContent: data.content });
    } catch {
      patchTab(id, { fileContent: "(unable to read file)" });
    }
  }

  async function saveFile() {
    const id = activeIdRef.current;
    const content = tab.fileContent;
    const selected = tab.selected;
    if (!selected || !tab.dirty) return;
    patchTab(id, { saving: true });
    try {
      const res = await fetch(`/api/sessions/${id}/files/${selected}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Save failed");
      }
      patchTab(id, { dirty: false });
      refreshFiles();
    } catch (error) {
      patchTab(id, {
        messages: [
          ...(tab.messages || []),
          { role: "agent", text: `Error saving: ${error.message}` },
        ],
      });
    } finally {
      patchTab(id, { saving: false });
    }
  }

  async function deleteFile(path) {
    const id = activeIdRef.current;
    if (!window.confirm(`Delete ${path}?`)) return;
    try {
      const res = await fetch(`/api/sessions/${id}/files/${path}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Delete failed");
      }
      if (tab.selected === path) {
        patchTab(id, { selected: "", fileContent: "", dirty: false, runResult: "" });
      }
      refreshFiles();
    } catch (error) {
      patchTab(id, {
        messages: [
          ...(tab.messages || []),
          { role: "agent", text: `Error deleting: ${error.message}` },
        ],
      });
    }
  }

  async function runFile() {
    const id = activeIdRef.current;
    const selected = tab.selected;
    if (!selected) return;
    patchTab(id, { running: true, runResult: "" });
    try {
      const res = await fetch(`/api/sessions/${id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: selected }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Run failed");
      }
      patchTab(id, { runResult: data.result });
    } catch (error) {
      patchTab(id, { runResult: `Error: ${error.message}` });
    } finally {
      patchTab(id, { running: false });
    }
  }

  async function downloadWorkspace() {
    const id = activeIdRef.current;
    setDownloading(true);
    try {
      const res = await fetch(`/api/sessions/${id}/download`, {
        headers: { Accept: "application/zip" },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Download failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      patchTab(id, {
        messages: [
          ...(tab.messages || []),
          { role: "agent", text: `Error: ${error.message}` },
        ],
      });
    } finally {
      setDownloading(false);
    }
  }

  function newTab() {
    const fresh = makeTab();
    setTabs((prev) => [...prev, fresh]);
    setActiveTab(tabs.length);
    ensureSession(fresh.id);
  }

  function closeTab(index) {
    const target = tabs[index];
    if (target.messages.length > 0 && !window.confirm(`Close tab "${target.title}"?`)) {
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
  }

  async function send(text, confirmed = false) {
    const id = activeIdRef.current;
    const currentMessages = tab.messages || [];
    patchTab(id, { busy: true, pending: null });

    if (!confirmed) {
      const newMessages = [...currentMessages, { role: "user", text }];
      patchTab(id, { messages: newMessages });
      if ((tab.title || "").startsWith("New session")) {
        patchTab(id, { title: text.slice(0, 24) || "New session" });
      }
    }

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: id,
          confirmed,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Request failed");
      }

      if (data.requires_confirmation) {
        const parsed = parseConfirmation(data.response);
        patchTab(id, {
          pending: {
            message: text,
            action: parsed.action,
            target: parsed.target,
            response: data.response,
          },
          busy: false,
        });
        return;
      }

      patchTab(id, {
        messages: [
          ...currentMessages,
          ...(confirmed ? [] : [{ role: "user", text }]),
          { role: "agent", text: data.response },
        ],
        busy: false,
      });
    } catch (error) {
      patchTab(id, {
        messages: [
          ...currentMessages,
          ...(confirmed ? [] : [{ role: "user", text }]),
          { role: "agent", text: `Error: ${error.message}` },
        ],
        busy: false,
      });
    } finally {
      patchTab(id, { busy: false });
      refreshFiles();
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = tab.input.trim();
    if (!trimmed || tab.busy) return;
    patchTab(tab.id, { input: "" });
    send(trimmed);
  }

  function decide(confirm) {
    const message = tab.pending.message;
    patchTab(tab.id, { pending: null });
    if (confirm) {
      send(message, true);
    } else {
      patchTab(tab.id, {
        messages: [...(tab.messages || []), { role: "agent", text: "Cancelled." }],
      });
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Coding Agent</h1>
        <button
          onClick={downloadWorkspace}
          className="btn download"
          disabled={downloading}
        >
          {downloading ? "Zipping…" : "Download workspace"}
        </button>
      </header>

      <div className="tab-bar">
        <div className="tabs">
          {tabs.map((t, i) => (
            <div
              key={t.id}
              className={`tab ${i === safeIndex ? "active" : ""}`}
              onClick={() => setActiveTab(i)}
              title={t.id}
            >
              <span className="tab-title">{t.title}</span>
              <span
                className="tab-close"
                title="Close tab"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(i);
                }}
              >
                ×
              </span>
            </div>
          ))}
        </div>
        <button className="tab-add" onClick={newTab} title="New tab">
          +
        </button>
      </div>

      <div className="workspace">
        <aside className="files-panel">
          <div className="files-header">Explorer</div>
          {!tab.tree && <div className="files-empty">No files yet.</div>}
          {tab.tree && tab.tree.length === 0 && (
            <div className="files-empty">Empty workspace.</div>
          )}
          {tab.tree && tab.tree.length > 0 && (
            <div className="files-tree">
              {tab.tree.map((node, i) => (
                <FileTree
                  key={`${node.name}-${i}`}
                  node={{ ...node, path: node.name }}
                  onSelect={loadFile}
                  selected={tab.selected}
                  open={new Set(tab.openFolders || [])}
                  onToggle={toggleFolder}
                  onDelete={deleteFile}
                />
              ))}
            </div>
          )}
        </aside>

        <main className="editor-panel">
          {!tab.selected && (
            <div className="editor-empty">
              Select a file from the explorer to view or edit it.
            </div>
          )}
          {tab.selected && (
            <div className="file-preview">
              <div className="editor-toolbar">
                <span className="file-preview-name">{tab.selected}</span>
                <div className="editor-actions">
                  {tab.selected.endsWith(".py") && (
                    <button
                      onClick={runFile}
                      className="btn run"
                      disabled={tab.running || tab.dirty}
                      title={
                        tab.dirty
                          ? "Save changes before running"
                          : "Run in sandbox (Python only)"
                      }
                    >
                      {tab.running ? "Running…" : "Run"}
                    </button>
                  )}
                  <button
                    onClick={saveFile}
                    className="btn save"
                    disabled={tab.saving || !tab.dirty}
                  >
                    {tab.saving ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={() => deleteFile(tab.selected)}
                    className="btn del"
                  >
                    Delete
                  </button>
                </div>
              </div>
              <textarea
                className="code-editor"
                value={tab.fileContent}
                onChange={(e) => {
                  patchTab(tab.id, { fileContent: e.target.value, dirty: true });
                }}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
              />
              {tab.runResult && (
                <div className="run-output">
                  <div className="run-output-title">Output</div>
                  <pre>{tab.runResult}</pre>
                </div>
              )}
            </div>
          )}
        </main>

        <main className="chat">
          <div className="messages">
          {tab.messages.length === 0 && (
            <div className="empty">
              Ask me to search, read, create, modify, or run code in this
              workspace.
            </div>
          )}
          {tab.messages.map((msg, i) => (
            <div key={i} className={`msg ${msg.role}`}>
              <pre>{msg.text}</pre>
            </div>
          ))}

          {tab.pending && (
            <div className="msg agent">
              <p>
                <strong>{tab.pending.action || "Action"}</strong>
                {tab.pending.target && <> on <code>{tab.pending.target}</code></>}
              </p>
              {tab.pending.response && (
                <pre className="confirm-preview">{tab.pending.response}</pre>
              )}
              <p className="muted">
                Proceed? This may modify files in the workspace.
              </p>
              <div className="actions">
                <button onClick={() => decide(true)} className="btn yes">
                  Yes, proceed
                </button>
                <button onClick={() => decide(false)} className="btn no">
                  Cancel
                </button>
              </div>
            </div>
          )}
          {tab.busy && !tab.pending && <div className="typing">Agent is thinking…</div>}
          <div ref={endRef} />
        </div>

        <form onSubmit={handleSubmit} className="input-row">
          <input
            value={tab.input}
            onChange={(e) => patchTab(tab.id, { input: e.target.value })}
            placeholder="Type your request…"
            disabled={tab.busy}
            autoFocus
          />
          <button type="submit" disabled={tab.busy || !tab.input.trim()}>
            Send
          </button>
        </form>
        </main>
      </div>
    </div>
  );
}
