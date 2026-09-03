import React, { useEffect, useRef, useState, useCallback } from "react";
import { useTabs } from "./hooks/useTabs";
import { useSession } from "./hooks/useSession";
import { useChat } from "./hooks/useChat";
import { useResizable } from "./hooks/useResizable";
import { useAgentProgress } from "./hooks/useAgentProgress";
import { apiPost, apiGet } from "./utils/api";
import FileExplorer from "./components/sidebar/FileExplorer";
import EditorPanel from "./components/editor/EditorPanel";
import Message from "./components/chat/Message";
import ProjectPicker from "./components/chat/ProjectPicker";
import ChatComposer from "./components/chat/ChatComposer";
import ConfirmationDialog from "./components/chat/ConfirmationDialog";
import AgentStatusBar from "./components/agent/AgentStatusBar";
import TerminalPanel from "./components/terminal/TerminalPanel";
import Divider from "./components/layout/Divider";

export default function App() {
  const {
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
  } = useTabs();

  const [downloading, setDownloading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [cwd, setCwd] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const endRef = useRef(null);

  const { sizes, startResize, containerRef } = useResizable(
    { sidebar: 260, editor: 500, chat: 400 },
    "horizontal"
  );

  const { nodes: agentNodes, handleEvent: handleAgentEvent, reset: resetAgent } = useAgentProgress();

  const {
    ensureSession,
    bindProject,
    refreshFiles,
    loadFile,
    saveFile,
    deleteFile,
  } = useSession(patchTab, activeIdRef);

  const { send, decide } = useChat(patchTab, activeIdRef, () =>
    refreshFiles(tab, patchTab), handleAgentEvent
  );

  // Sync active ID ref
  useEffect(() => {
    if (tab.id) activeIdRef.current = tab.id;
  }, [tab.id]);

  // Fetch CWD
  useEffect(() => {
    fetch("/api/projects")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setCwd(data.cwd || ""));
  }, []);

  // Folder selection is optional: new sessions start with the picker's
  // "Open project…" button in the header. Chatting without a project
  // uses a per-session workspace the agent creates on first message.

  // Re-bind project on refresh (backend may have lost the workspace mapping)
  const rebindRef = useRef(null);
  useEffect(() => {
    if (tab.id && tab.project?.path && rebindRef.current !== tab.id) {
      rebindRef.current = tab.id;
      const rebind = async () => {
        try {
          await apiPost(`/api/sessions/${tab.id}`, {
            message: tab.project.path,
          });
          const filesData = await apiGet(`/api/sessions/${tab.id}/files`);
          if (filesData?.tree) {
            patchTab(tab.id, { tree: filesData.tree });
          }
        } catch {
          // Session might already be bound, ignore errors
        }
      };
      rebind();
    }
  }, [tab.id, tab.project?.path]);

  // Auto-scroll chat
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [tab.messages, tab.pending]);

  // Refresh files on tab switch (skip if re-bind just handled it)
  useEffect(() => {
    if (rebindRef.current === tab.id) return;
    refreshFiles(tab, patchTab);
  }, [activeTab]);

  const toggleFolder = useCallback(
    (path) => {
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
    },
    [tab.id, setTabs]
  );

  const handleDeleteFile = useCallback(
    (path) => {
      deleteFile(path, tab, patchTab, () => refreshFiles(tab, patchTab));
    },
    [tab, deleteFile, patchTab, refreshFiles]
  );

  const handleSend = useCallback(
    (e) => {
      e.preventDefault();
      const trimmed = tab.input.trim();
      if (!trimmed || tab.busy) return;
      patchTab(tab.id, { input: "" });
      send(trimmed, tab);
    },
    [tab, patchTab, send]
  );

  const handleDecide = useCallback(
    (confirm) => {
      decide(tab.pending, tab, confirm);
    },
    [tab, decide]
  );

  const handleBindProject = useCallback(
    (project) => {
      bindProject(project, patchTab, setPickerOpen);
      resetAgent();
    },
    [bindProject, patchTab, resetAgent]
  );

  const downloadWorkspace = useCallback(async () => {
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
  }, [activeIdRef, tab, patchTab]);

  const editorWidth = `calc(100% - ${sizes.sidebar}px - ${4}px - ${sizes.chat}px - ${4}px)`;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <button
            className="btn icon-btn"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title="Toggle sidebar"
          >
            {sidebarOpen ? "◧" : "◨"}
          </button>
          <h1>Coding Agent</h1>
        </div>
        {tab.project ? (
          <button
            onClick={() => setPickerOpen(true)}
            className="btn project-switch"
            title={tab.project.path}
          >
            📁 {tab.project.name}
          </button>
        ) : (
          <button
            onClick={() => setPickerOpen(true)}
            className="btn project-switch"
          >
            Open project…
          </button>
        )}
        <div className="header-right">
          <button
            onClick={() => setTerminalOpen(!terminalOpen)}
            className="btn icon-btn"
            title="Toggle terminal"
          >
            ⌘
          </button>
          <button
            onClick={() => newTab()}
            className="btn icon-btn"
            title="New session"
          >
            +
          </button>
        </div>
      </header>

      <div className="workspace" ref={containerRef}>
        {sidebarOpen && (
          <>
            <aside className="sidebar" style={{ width: sizes.sidebar }}>
              <FileExplorer
                tree={tab.tree}
                selected={tab.selected}
                openFolders={new Set(tab.openFolders || [])}
                onSelect={(path) => loadFile(path, undefined, patchTab)}
                onToggle={toggleFolder}
                onDelete={handleDeleteFile}
              />
            </aside>
            <Divider direction="horizontal" onResize={startResize} panelId="sidebar" />
          </>
        )}

        <section className="editor-pane">
          <div className="editor-tabs">
            {tab.selected && (
              <div className="editor-tab active">
                <span>{tab.selected.split("/").pop()}</span>
              </div>
            )}
          </div>
          <EditorPanel
            file={tab.selected ? { name: tab.selected, content: tab.fileContent } : null}
            readOnly
          />
          {terminalOpen && tab.project && (
            <>
              <Divider direction="vertical" onResize={startResize} panelId="terminal" />
              <div className="terminal-pane">
                <TerminalPanel sessionId={tab.id} />
              </div>
            </>
          )}
        </section>

        <Divider direction="horizontal" onResize={startResize} panelId="chat" />

        <main className="chat" style={{ width: `${sizes.chat}px` }}>
          <div className="messages-container">
            <div className="messages">
              {tab.messages.length === 0 && (
                <div className="empty">
                  {tab.project
                    ? "Ask me to search, read, create, modify, or run code in this project."
                    : "Ask anything — no folder needed. Or open a project to work on existing code."}
                </div>
              )}
              {tab.messages.map((msg, i) => (
                <Message key={i} msg={msg} />
              ))}

              <ConfirmationDialog
                pending={tab.pending}
                onConfirm={() => handleDecide(true)}
                onCancel={() => handleDecide(false)}
              />
              {tab.busy && !tab.pending && !tab.status && (
                <div className="typing">Agent is thinking…</div>
              )}
              {tab.status && <div className="status-bar">{tab.status}</div>}
              <AgentStatusBar nodes={agentNodes} />
              <div ref={endRef} />
            </div>
          </div>

          <ChatComposer
            input={tab.input}
            model={tab.model}
            busy={tab.busy}
            onInputChange={(val) => patchTab(tab.id, { input: val })}
            onSubmit={handleSend}
            onModelChange={(val) => patchTab(tab.id, { model: val })}
          />
        </main>
      </div>

      {pickerOpen && (
        <ProjectPicker
          onSelect={handleBindProject}
          onClose={() => setPickerOpen(false)}
          cwd={cwd}
        />
      )}
    </div>
  );
}
