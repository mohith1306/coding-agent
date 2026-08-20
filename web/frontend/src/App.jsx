import React, { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "coding_agent_tabs";
const LEGACY_SESSION_KEY = "coding_agent_session_id";

function makeTab(id = crypto.randomUUID(), title = "New session") {
  return {
    id,
    title,
    project: null,
    input: "",
    messages: [],
    pending: null,
    busy: false,
    status: "",
    tree: null,
    selected: "",
    fileContent: "",
    dirty: false,
    saving: false,
    running: false,
    runResult: "",
    openFolders: [],
    model: "openrouter/auto",
  };
}

function loadTabs() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.map((t) => ({ ...makeTab(t.id), ...t, model: t.model || "openrouter/auto" }));
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

async function readSSE(res, onEvent) {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch {
            // ignore malformed frames
          }
        }
      }
    }
  }
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

function ProjectPicker({ onSelect, onClose, cwd }) {
  const [projects, setProjects] = useState(null);
  const [custom, setCustom] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("recent");
  const [browsePath, setBrowsePath] = useState("");
  const [browseParent, setBrowseParent] = useState(null);
  const [browseDirs, setBrowseDirs] = useState(null);
  const [browseLoading, setBrowseLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/projects")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Failed to list projects"))))
      .then((data) => {
        if (!alive) return;
        setProjects(data.projects || []);
        if (!browsePath && data.cwd) {
          setBrowsePath(data.cwd);
        }
      })
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, []);

  async function openPath(path) {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/projects/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: path }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Failed to open project");
      onSelect(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadBrowse(dirPath) {
    setBrowseLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/projects/browse?path=${encodeURIComponent(dirPath)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Failed to browse directory");
      setBrowsePath(data.path);
      setBrowseParent(data.parent);
      setBrowseDirs(data.dirs || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setBrowseLoading(false);
    }
  }

  function handleCustom(e) {
    e.preventDefault();
    const path = custom.trim();
    if (path) openPath(path);
  }

  function switchMode(next) {
    setMode(next);
    setError("");
    if (next === "browse" && !browseDirs && browsePath) {
      loadBrowse(browsePath);
    }
  }

  return (
    <div className="picker-overlay">
      <div className="picker">
        <div className="picker-header">
          <h2>Open a project</h2>
          {onClose && (
            <button className="picker-close" onClick={onClose} title="Close">
              ×
            </button>
          )}
        </div>
        <p className="picker-hint">
          Choose a project folder from your machine. The agent will read, create,
          modify, and run code inside it.
        </p>

        <div className="picker-tabs">
          <button
            className={`picker-tab ${mode === "recent" ? "active" : ""}`}
            onClick={() => switchMode("recent")}
          >
            Recent projects
          </button>
          <button
            className={`picker-tab ${mode === "browse" ? "active" : ""}`}
            onClick={() => switchMode("browse")}
          >
            Browse…
          </button>
        </div>

        {error && <div className="picker-error">{error}</div>}

        {mode === "browse" && (
          <div className="picker-browse">
            <form
              className="picker-custom"
              onSubmit={(e) => {
                e.preventDefault();
                if (browsePath.trim()) loadBrowse(browsePath.trim());
              }}
            >
              <input
                value={browsePath}
                onChange={(e) => setBrowsePath(e.target.value)}
                placeholder="Type a folder path to browse…"
                spellCheck={false}
              />
              <button type="submit" disabled={browseLoading}>
                {browseLoading ? "Loading…" : "Go"}
              </button>
            </form>
            {browseParent && (
              <button
                className="picker-up"
                onClick={() => loadBrowse(browseParent)}
                disabled={browseLoading}
              >
                ↑ Up one level
              </button>
            )}
            <div className="picker-list">
              {browseLoading && <div className="picker-loading">Loading folder…</div>}
              {!browseLoading && browseDirs && browseDirs.length === 0 && (
                <div className="picker-loading">No subfolders here.</div>
              )}
              {!browseLoading &&
                browseDirs &&
                browseDirs.map((d) => (
                  <div key={d.path} className="picker-browse-item">
                    <button
                      className="picker-item"
                      onClick={() => loadBrowse(d.path)}
                      title={d.path}
                    >
                      <span className="picker-item-icon">
                        {d.is_project ? "📦" : "📁"}
                      </span>
                      <span className="picker-item-name">{d.name}</span>
                      <span className="picker-item-path">
                        {d.is_project ? "project" : d.path}
                      </span>
                    </button>
                    {d.is_project && (
                      <button
                        className="picker-open"
                        onClick={() => openPath(d.path)}
                        disabled={loading}
                      >
                        Open
                      </button>
                    )}
                  </div>
                ))}
            </div>
          </div>
        )}

        {mode === "recent" && (
          <>
            <form className="picker-custom" onSubmit={handleCustom}>
              <input
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                placeholder={cwd ? `Type a path (e.g. ${cwd})` : "Type a full path…"}
                spellCheck={false}
              />
              <button type="submit" disabled={loading || !custom.trim()}>
                {loading ? "Opening…" : "Open"}
              </button>
            </form>

            <div className="picker-divider">
              <span>Recent projects</span>
            </div>

            <div className="picker-list">
              {!projects && !error && <div className="picker-loading">Scanning your directories…</div>}
              {projects && projects.length === 0 && (
                <div className="picker-loading">No projects found. Try the Browse tab or type a path.</div>
              )}
              {projects &&
                projects.map((p) => (
                  <button
                    key={p.path}
                    className="picker-item"
                    onClick={() => openPath(p.path)}
                    disabled={loading}
                    title={p.path}
                  >
                    <span className="picker-item-icon">📁</span>
                    <span className="picker-item-name">{p.name}</span>
                    <span className="picker-item-path">{p.path}</span>
                  </button>
                ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [tabs, setTabs] = useState(loadTabs);
  const [activeTab, setActiveTab] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [cwd, setCwd] = useState("");
  const endRef = useRef(null);
  const runOutputRef = useRef(null);
  const activeIdRef = useRef(null);

  const safeIndex = Math.min(activeTab, Math.max(tabs.length - 1, 0));
  const tab = tabs[safeIndex] || makeTab();
  activeIdRef.current = tab.id;

  useEffect(() => {
    fetch("/api/projects")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setCwd(data.cwd || ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab.id && !tab.project && !tab.busy) {
      setPickerOpen(true);
    }
  }, [tab.id, tab.project, tab.busy]);

  useEffect(() => {
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
  }, [tabs]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [tab.messages, tab.pending]);

  useEffect(() => {
    const el = runOutputRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [tab.runResult]);

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

  async function bindProject(project) {
    const id = activeIdRef.current;
    setPickerOpen(false);
    patchTab(id, {
      project,
      title: project.name || id.slice(0, 8),
      tree: null,
      selected: "",
      fileContent: "",
      dirty: false,
      runResult: "",
      openFolders: [],
    });
    try {
      const res = await fetch(`/api/sessions/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: project.path }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to open project");
      }
      patchTab(id, {
        messages: [
          ...(tab.messages || []),
          {
            role: "agent",
            text: `Opened project **${project.name}** at \`${project.path}\`. What would you like to work on?`,
          },
        ],
      });
    } catch (error) {
      patchTab(id, {
        messages: [
          ...(tab.messages || []),
          { role: "agent", text: `Error opening project: ${error.message}` },
        ],
      });
    }
    refreshFiles();
  }

  async function refreshFiles() {
    const id = activeIdRef.current;
    const target = tabs.find((t) => t.id === id);
    if (target && !target.project) return;
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
    const updateOutput = (text) =>
      setTabs((prev) =>
        prev.map((t) => (t.id === id ? { ...t, runResult: text } : t))
      );
    try {
      const res = await fetch(`/api/sessions/${id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: selected }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Run failed");
      }
      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("text/event-stream")) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.result || data.detail || "Unexpected run response");
      }
      let acc = "";
      await readSSE(res, (event) => {
        if (event.type === "output") {
          acc += event.text;
          updateOutput(acc);
        } else if (event.type === "exit") {
          const statusLine =
            event.code === 0
              ? "[exited successfully]"
              : `[process exited with code ${event.code}]`;
          acc = acc.trim().length
            ? `${acc.replace(/\s+$/, "")}\n\n${statusLine}`
            : `(no output)\n${statusLine}`;
          updateOutput(acc);
        } else if (event.type === "error") {
          acc += `\n[error] ${event.message}`;
          updateOutput(acc);
        }
      });
    } catch (error) {
      patchTab(id, { runResult: `Error: ${error.message}` });
    } finally {
      patchTab(id, { running: false });
    }
  }

  async function stopRun() {
    const id = activeIdRef.current;
    const prefix = tab.runResult ? `${tab.runResult}\n` : "";
    patchTab(id, { runResult: `${prefix}[stopping…]` });
    try {
      await fetch(`/api/sessions/${id}/stop`, { method: "POST" });
    } catch {
      // the stream may have already finished
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
    setPickerOpen(true);
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
    fetch(`/api/sessions/${target.id}`, { method: "DELETE" }).catch(() => {});
  }

  async function send(text, confirmed = false) {
    const id = activeIdRef.current;
    const currentMessages = tab.messages || [];
    patchTab(id, { busy: true, pending: null, status: "Connecting…" });

    if (!confirmed) {
      if ((tab.title || "").startsWith("New session") && tab.project) {
        patchTab(id, { title: text.slice(0, 24) || "New session" });
      }
    }

    const baseMessages = confirmed
      ? currentMessages
      : [...currentMessages, { role: "user", text }];
    const liveIndex = baseMessages.length;
    patchTab(id, {
      messages: [...baseMessages, { role: "agent", text: "", streaming: true }],
    });

    const updateLive = (updater) =>
      setTabs((prev) =>
        prev.map((t) =>
          t.id !== id
            ? t
            : {
                ...t,
                messages: t.messages.map((m, i) =>
                  i === liveIndex ? updater(m) : m
                ),
              }
        )
      );

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: id,
          confirmed,
          model: tab.model,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Request failed");
      }

      await readSSE(res, (event) => {
        if (event.type === "chunk") {
          updateLive((m) => ({ ...m, text: (m.text || "") + event.text }));
        } else if (event.type === "action") {
          updateLive((m) => ({
            ...m,
            action: event.action,
            actionTarget: event.target,
            bullets: Array.isArray(event.bullets) ? event.bullets : [],
          }));
        } else if (event.type === "phase") {
          patchTab(id, { status: event.message });
        } else if (event.type === "confirmation") {
          setTabs((prev) =>
            prev.map((t) =>
              t.id !== id
                ? t
                : {
                    ...t,
                    messages: t.messages.slice(0, liveIndex),
                    pending: {
                      message: text,
                      action: event.action,
                      target: event.target,
                      response: event.response,
                    },
                    status: "",
                  }
            )
          );
        } else if (event.type === "done") {
          updateLive((m) => ({ ...m, role: "agent", text: event.response, streaming: false }));
          patchTab(id, { status: "" });
        } else if (event.type === "error") {
          updateLive(() => ({ role: "agent", text: `Error: ${event.message}` }));
          patchTab(id, { status: "" });
        }
      });
    } catch (error) {
      updateLive(() => ({ role: "agent", text: `Error: ${error.message}` }));
    } finally {
      patchTab(id, { busy: false, status: "" });
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
        {tab.project ? (
          <button
            onClick={() => setPickerOpen(true)}
            className="btn project-switch"
            title={tab.project.path}
          >
            📁 {tab.project.name}
          </button>
        ) : (
          <button onClick={() => setPickerOpen(true)} className="btn project-switch">
            Open project…
          </button>
        )}
        <button
          onClick={downloadWorkspace}
          className="btn download"
          disabled={downloading}
        >
          {downloading ? "Zipping…" : "Download workspace"}
        </button>
      </header>

      <div className="workspace">
        <section className="code-pane">
          <aside className="file-browser">
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
              <div className="editor-empty">Select a file to preview it.</div>
            )}
            {tab.selected && (
              <div className="file-preview">
                <div className="editor-toolbar">
                  <span className="file-preview-name">{tab.selected}</span>
                </div>
                <textarea
                  className="code-editor"
                  value={tab.fileContent}
                  readOnly
                  spellCheck={false}
                  autoCapitalize="off"
                  autoCorrect="off"
                />
              </div>
            )}
          </main>
        </section>

        <main className="chat">
          <div className="messages">
          {tab.messages.length === 0 && (
            <div className="empty">
              {tab.project
                ? "Ask me to search, read, create, modify, or run code in this project."
                : "Open a project to start working with the coding agent."}
            </div>
          )}
          {tab.messages.map((msg, i) => (
            <div
              key={i}
              className={`msg ${msg.role}${msg.streaming ? " streaming" : ""}`}
            >
              {msg.bullets?.length > 0 && (
                <ul className="action-bullets">
                  {msg.bullets.map((bullet, bulletIndex) => (
                    <li key={`${bullet}-${bulletIndex}`}>{bullet}</li>
                  ))}
                </ul>
              )}
              <pre>
                {msg.text}
                {msg.streaming && <span className="caret" />}
              </pre>
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
          {tab.busy && !tab.pending && !tab.status && (
            <div className="typing">Agent is thinking…</div>
          )}
          {tab.status && <div className="status-bar">{tab.status}</div>}
          <div ref={endRef} />
        </div>

        <form onSubmit={handleSubmit} className="input-row">
          <div className="chat-composer">
            <textarea
              value={tab.input}
              onChange={(e) => patchTab(tab.id, { input: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder={
                tab.project
                  ? "Ask anything, / for commands, @ for context..."
                  : "Open a project first…"
              }
              disabled={tab.busy || !tab.project}
              rows={1}
              autoFocus
            />

            <div className="composer-footer">
              <button
                type="button"
                className="composer-icon"
                title="Add context"
                disabled={tab.busy || !tab.project}
                onClick={() => {}}
              >
                +
              </button>

              <div className="model-selector">
                <select
                  value={tab.model}
                  onChange={(e) => patchTab(tab.id, { model: e.target.value })}
                  disabled={tab.busy || !tab.project}
                  aria-label="Select model"
                >
                  <option value="openrouter/auto">Auto</option>
                  <option value="openrouter/deepseek-coder-v2">DeepSeek Coder V2</option>
                  <option value="openrouter/codellama-34b">CodeLlama 34B</option>
                  <option value="openrouter/mistral-7b">Mistral 7B</option>
                  <option value="openai/gpt-4o">GPT-4o</option>
                  <option value="gemini/gemini-1.5-flash">Gemini 1.5 Flash</option>
                  <option value="groq/llama-3.3-70b-versatile">Llama 3.3 70B</option>
                </select>
              </div>

              <button
                type="submit"
                className="composer-send"
                disabled={tab.busy || !tab.input.trim() || !tab.project}
                title="Send message"
                aria-label="Send message"
              >
                ↑
              </button>
            </div>
          </div>
        </form>
        </main>
      </div>

      {pickerOpen && (
        <ProjectPicker onSelect={bindProject} onClose={() => setPickerOpen(false)} cwd={cwd} />
      )}
    </div>
  );
}
