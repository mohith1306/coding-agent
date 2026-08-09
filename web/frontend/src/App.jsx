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

function FileTree({ node, depth = 0, onSelect, selected }) {
  const indent = { paddingLeft: `${depth * 14 + 8}px` };
  if (node.type === "file") {
    const isSel = selected === node.path;
    return (
      <div
        className={`file-entry file ${isSel ? "selected" : ""}`}
        style={indent}
        onClick={() => onSelect(node.path)}
        title={`${node.path} (${node.size} bytes)`}
      >
        {node.name}
      </div>
    );
  }
  return (
    <div>
      <div className="file-entry dir" style={indent}>
        {node.name}
      </div>
      {node.children.map((child, i) => (
        <FileTree
          key={`${child.name}-${i}`}
          node={{ ...child, path: `${node.path}/${child.name}` }}
          depth={depth + 1}
          onSelect={onSelect}
          selected={selected}
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

  async function loadFile(path) {
    setSelected(path);
    setFileContent("");
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
          <div className="files-header">Workspace</div>
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
                />
              ))}
            </div>
          )}
          {selected && (
            <div className="file-preview">
              <div className="file-preview-name">{selected}</div>
              <pre>{fileContent}</pre>
            </div>
          )}
        </aside>

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
