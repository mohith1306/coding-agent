import React, { useEffect, useState } from "react";

export default function ProjectPicker({ onSelect, onClose, cwd }) {
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
      .then((res) =>
        res.ok ? res.json() : Promise.reject(new Error("Failed to list projects"))
      )
      .then((data) => {
        if (!alive) return;
        setProjects(data.projects || []);
        if (!browsePath && data.cwd) setBrowsePath(data.cwd);
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
      const res = await fetch(
        `/api/projects/browse?path=${encodeURIComponent(dirPath)}`
      );
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
    if (next === "browse" && !browseDirs && browsePath) loadBrowse(browsePath);
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
              {browseLoading && (
                <div className="picker-loading">Loading folder…</div>
              )}
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
                placeholder={
                  cwd
                    ? `Type a path (e.g. ${cwd})`
                    : "Type a full path…"
                }
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
              {!projects && !error && (
                <div className="picker-loading">Scanning your directories…</div>
              )}
              {projects && projects.length === 0 && (
                <div className="picker-loading">
                  No projects found. Try the Browse tab or type a path.
                </div>
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
