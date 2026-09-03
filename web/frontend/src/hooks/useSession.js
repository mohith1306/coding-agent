import { useCallback } from "react";
import { apiPost, apiGet } from "../utils/api";

export function useSession(patchTab, activeIdRef) {
  const ensureSession = useCallback(
    async (id) => {
      try {
        await apiPost(`/api/sessions/${id}`);
      } catch {
        // workspace is created lazily on first chat anyway
      }
    },
    []
  );

  const bindProject = useCallback(
    async (project, patchTab, setPickerOpen) => {
      const id = activeIdRef.current;
      if (!id) {
        setPickerOpen(false);
        return;
      }

      setPickerOpen(false);

      patchTab(id, {
        project,
        title: project.name || id.slice(0, 8),
        tree: null,
        selected: "",
        fileContent: "",
        dirty: false,
        saving: false,
        running: false,
        runResult: "",
        openFolders: [],
        messages: [],
        pending: null,
        busy: false,
        status: "Opening project…",
      });

      try {
        const data = await apiPost(`/api/sessions/${id}`, {
          message: project.path,
        });

        patchTab(id, {
          messages: [
            {
              role: "agent",
              text: `Opened project **${project.name}** at \`${project.path}\`. What would you like to work on?`,
            },
          ],
          status: "",
        });

        try {
          const filesData = await apiGet(`/api/sessions/${id}/files`);
          patchTab(id, { tree: filesData.tree });
        } catch {
          // retry on tab switch
        }
      } catch (error) {
        patchTab(id, {
          project: null,
          status: "",
          messages: [
            {
              role: "agent",
              text: `Error opening project: ${error.message}`,
            },
          ],
        });
        setPickerOpen(true);
      }
    },
    [activeIdRef]
  );

  const refreshFiles = useCallback(
    async (tab, patchTab) => {
      const id = activeIdRef.current;
      if (!id) return;
      // No project gate: folder-less sessions have a per-session workspace
      // the agent creates files in — the tree must reflect those too.
      // 404 (no workspace yet) is caught below and ignored.

      try {
        const data = await apiGet(`/api/sessions/${id}/files`);
        patchTab(id, { tree: data.tree });

        if (tab.selected) {
          loadFile(tab.selected, id, patchTab);
        }
      } catch {
        // ignore transient refresh errors
      }
    },
    [activeIdRef]
  );

  const loadFile = useCallback(
    async (path, sessionId = activeIdRef.current, patchTab) => {
      const id = sessionId;
      patchTab(id, {
        selected: path,
        fileContent: "",
        dirty: false,
        runResult: "",
      });
      try {
        const data = await apiGet(`/api/sessions/${id}/files/${path}`);
        patchTab(id, { fileContent: data.content });
      } catch {
        patchTab(id, { fileContent: "(unable to read file)" });
      }
    },
    [activeIdRef]
  );

  const saveFile = useCallback(
    async (tab, patchTab) => {
      const id = activeIdRef.current;
      const { fileContent, selected } = tab;
      if (!selected || !tab.dirty) return;
      patchTab(id, { saving: true });
      try {
        await apiPut(`/api/sessions/${id}/files/${selected}`, {
          content: fileContent,
        });
        patchTab(id, { dirty: false });
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
    },
    [activeIdRef]
  );

  const deleteFile = useCallback(
    async (path, tab, patchTab, refreshFn) => {
      const id = activeIdRef.current;
      if (!window.confirm(`Delete ${path}?`)) return;
      try {
        await apiDelete(`/api/sessions/${id}/files/${path}`);
        if (tab.selected === path) {
          patchTab(id, {
            selected: "",
            fileContent: "",
            dirty: false,
            runResult: "",
          });
        }
        refreshFn?.();
      } catch (error) {
        patchTab(id, {
          messages: [
            ...(tab.messages || []),
            { role: "agent", text: `Error deleting: ${error.message}` },
          ],
        });
      }
    },
    [activeIdRef]
  );

  return {
    ensureSession,
    bindProject,
    refreshFiles,
    loadFile,
    saveFile,
    deleteFile,
  };
}

// Need to import apiDelete
import { apiDelete } from "../utils/api";
