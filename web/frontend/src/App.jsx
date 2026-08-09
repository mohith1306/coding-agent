import React, { useEffect, useRef, useState } from "react";

const SESSION_KEY = "coding_agent_session_id";

function getSessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
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
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [tree, setTree] = useState(null);
  const [selected, setSelected] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState("");
  const [openFolders, setOpenFolders] = useState(() => new Set());
  const endRef = useRef(null);
  const sessionIdRef = useRef(getSessionId());

  async function refreshFiles() {
    try {
      const res = await fetch(`/api/sessions/${sessionIdRef.current}/files`);
      if (!res.ok) return;
      const data = await res.json();
      setTree(data.tree);
      if (selected) {
        loadFile(selected);
      }
    } catch {
      // ignore transient refresh errors
    }
  }

  function toggleFolder(path) {
    setOpenFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function revealPath(path) {
    const parts = path.split("/");
    parts.pop();
    setOpenFolders((prev) => {
      const next = new Set(prev);
      let acc = "";
      for (const part of parts) {
        acc = acc ? `${acc}/${part}` : part;
        next.add(acc);
      }
      return next;
    });
  }

  async function loadFile(path) {
    setSelected(path);
    revealPath(path);
    setFileContent("");
    setDirty(false);
    setRunResult("");
    try {
      const res = await fetch(
        `/api/sessions/${sessionIdRef.current}/files/${path}`
      );
      if (!res.ok) {
        setFileContent("(unable to read file)");
        return;
      }
      const data = await res.json();
      setFileContent(data.content);
    } catch {
      setFileContent("(unable to read file)");
    }
  }

  async function saveFile() {
    if (!selected || !dirty) return;
    setSaving(true);
    try {
      const res = await fetch(
        `/api/sessions/${sessionIdRef.current}/files/${selected}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: fileContent }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Save failed");
      }
      setDirty(false);
      refreshFiles();
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: `Error saving: ${error.message}` },
      ]);
    } finally {
      setSaving(false);
    }
  }

  async function deleteFile(path) {
    if (!window.confirm(`Delete ${path}?`)) return;
    try {
      const res = await fetch(
        `/api/sessions/${sessionIdRef.current}/files/${path}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Delete failed");
      }
      if (selected === path) {
        setSelected("");
        setFileContent("");
        setDirty(false);
        setRunResult("");
      }
      refreshFiles();
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: `Error deleting: ${error.message}` },
      ]);
    }
  }

  async function runFile() {
    if (!selected) return;
    setRunning(true);
    setRunResult("");
    try {
      const res = await fetch(`/api/sessions/${sessionIdRef.current}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: selected }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Run failed");
      }
      setRunResult(data.result);
    } catch (error) {
      setRunResult(`Error: ${error.message}`);
    } finally {
      setRunning(false);
    }
  }

  async function downloadWorkspace() {
    setDownloading(true);
    try {
      const res = await fetch(
        `/api/sessions/${sessionIdRef.current}/download`,
        { headers: { Accept: "application/zip" } }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Download failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${sessionIdRef.current}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: `Error: ${error.message}` },
      ]);
    } finally {
      setDownloading(false);
    }
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  useEffect(() => {
    refreshFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function send(text, confirmed = false) {
    setBusy(true);
    setPending(null);
    setMessages((prev) => [...prev, { role: "user", text }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: sessionIdRef.current,
          confirmed,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Request failed");
      }

      if (data.requires_confirmation) {
        const parsed = parseConfirmation(data.response);
        setPending({
          message: text,
          action: parsed.action,
          target: parsed.target,
          response: data.response,
        });
        return;
      }

      setMessages((prev) => [...prev, { role: "agent", text: data.response }]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: `Error: ${error.message}` },
      ]);
    } finally {
      setBusy(false);
      refreshFiles();
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || busy) return;
    setInput("");
    send(trimmed);
  }

  function decide(confirm) {
    const message = pending.message;
    setPending(null);
    if (confirm) {
      send(message, true);
    } else {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: "Cancelled." },
      ]);
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

      <div className="workspace">
        <aside className="files-panel">
          <div className="files-header">Explorer</div>
          {!tree && <div className="files-empty">No files yet.</div>}
          {tree && tree.length === 0 && (
            <div className="files-empty">Empty workspace.</div>
          )}
          {tree && tree.length > 0 && (
            <div className="files-tree">
              {tree.map((node, i) => (
                <FileTree
                  key={`${node.name}-${i}`}
                  node={{ ...node, path: node.name }}
                  onSelect={loadFile}
                  selected={selected}
                  open={openFolders}
                  onToggle={toggleFolder}
                  onDelete={deleteFile}
                />
              ))}
            </div>
          )}
        </aside>

        <main className="editor-panel">
          {!selected && (
            <div className="editor-empty">
              Select a file from the explorer to view or edit it.
            </div>
          )}
          {selected && (
            <div className="file-preview">
              <div className="editor-toolbar">
                <span className="file-preview-name">{selected}</span>
                <div className="editor-actions">
                  {selected.endsWith(".py") && (
                    <button
                      onClick={runFile}
                      className="btn run"
                      disabled={running || dirty}
                      title={
                        dirty
                          ? "Save changes before running"
                          : "Run in sandbox (Python only)"
                      }
                    >
                      {running ? "Running…" : "Run"}
                    </button>
                  )}
                  <button
                    onClick={saveFile}
                    className="btn save"
                    disabled={saving || !dirty}
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={() => deleteFile(selected)}
                    className="btn del"
                  >
                    Delete
                  </button>
                </div>
              </div>
              <textarea
                className="code-editor"
                value={fileContent}
                onChange={(e) => {
                  setFileContent(e.target.value);
                  setDirty(true);
                }}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
              />
              {runResult && (
                <div className="run-output">
                  <div className="run-output-title">Output</div>
                  <pre>{runResult}</pre>
                </div>
              )}
            </div>
          )}
        </main>

        <main className="chat">
          <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              Ask me to search, read, create, modify, or run code in this
              workspace.
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`msg ${msg.role}`}>
              <pre>{msg.text}</pre>
            </div>
          ))}

          {pending && (
            <div className="msg agent">
              <p>
                <strong>{pending.action || "Action"}</strong>
                {pending.target && <> on <code>{pending.target}</code></>}
              </p>
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
          {busy && !pending && <div className="typing">Agent is thinking…</div>}
          <div ref={endRef} />
        </div>

        <form onSubmit={handleSubmit} className="input-row">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your request…"
            disabled={busy}
            autoFocus
          />
          <button type="submit" disabled={busy || !input.trim()}>
            Send
          </button>
        </form>
        </main>
      </div>
    </div>
  );
}
