import { useCallback } from "react";
import { readSSE } from "../utils/sse";
import { apiStream } from "../utils/api";

export function useChat(patchTab, activeIdRef, refreshFiles, handleAgentEvent) {
  const send = useCallback(
    async (text, tab, confirmed = false) => {
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
        patchTab(id, {
          messages: baseMessages.concat([{ role: "agent", text: "", streaming: true }]).map((m, i) =>
            i === liveIndex ? updater(m) : m
          ),
        });

      // Simpler update: patch the specific message in state
      const updateLiveMsg = (updater) =>
        patchTab(id, {
          _liveUpdater: { index: liveIndex, updater },
        });

      try {
        const res = await apiStream("/api/chat/stream", {
          message: text,
          session_id: id,
          confirmed,
          model: tab.model,
        });

        const contentType = res.headers.get("content-type") || "";
        if (!contentType.includes("text/event-stream")) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Request failed");
        }

        let accumulatedText = "";
        let actionData = null;
        let bullets = [];

        await readSSE(res, (event) => {
          // Forward events to agent progress tracker
          handleAgentEvent?.(event);

          if (event.type === "chunk") {
            accumulatedText += event.text;
            const snap = accumulatedText;
            patchTab(id, {
              messages: baseMessages.concat([
                {
                  role: "agent",
                  text: snap,
                  streaming: true,
                  action: actionData?.action,
                  actionTarget: actionData?.target,
                  bullets,
                },
              ]),
            });
          } else if (event.type === "action") {
            actionData = { action: event.action, target: event.target };
            bullets = Array.isArray(event.bullets) ? event.bullets : [];
          } else if (event.type === "phase") {
            patchTab(id, { status: event.message });
          } else if (event.type === "confirmation") {
            patchTab(id, {
              messages: baseMessages,
              pending: {
                message: text,
                action: event.action,
                target: event.target,
                response: event.response,
              },
              status: "",
            });
          } else if (event.type === "done") {
            patchTab(id, {
              messages: baseMessages.concat([
                { role: "agent", text: event.response, streaming: false },
              ]),
              status: "",
            });
          } else if (event.type === "error") {
            patchTab(id, {
              messages: baseMessages.concat([
                { role: "agent", text: `Error: ${event.message}` },
              ]),
              status: "",
            });
          }
        });
      } catch (error) {
        patchTab(id, {
          messages: baseMessages.concat([
            { role: "agent", text: `Error: ${error.message}` },
          ]),
        });
      } finally {
        patchTab(id, { busy: false, status: "" });
        refreshFiles?.();
      }
    },
    [activeIdRef, patchTab, refreshFiles]
  );

  const decide = useCallback(
    (pending, tab, confirm) => {
      const message = pending.message;
      patchTab(tab.id, { pending: null });
      if (confirm) {
        send(message, tab, true);
      } else {
        patchTab(tab.id, {
          messages: [
            ...(tab.messages || []),
            { role: "agent", text: "Cancelled." },
          ],
        });
      }
    },
    [patchTab, send]
  );

  return { send, decide };
}
