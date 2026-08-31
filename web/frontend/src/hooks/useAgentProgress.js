import { useState, useCallback } from "react";
import { classifyPhase } from "../utils/events";

export function useAgentProgress() {
  const [nodes, setNodes] = useState([]);

  const handleEvent = useCallback((event) => {
    if (event.type === "phase") {
      const nodeName = classifyPhase(event.message);
      if (nodeName) {
        setNodes((prev) => {
          const existing = prev.find((n) => n.name === nodeName);
          if (existing) {
            if (existing.status === "running") return prev; // already running
            return prev.map((n) =>
              n.name === nodeName ? { ...n, status: "running", message: event.message } : n
            );
          }
          return [...prev, { name: nodeName, status: "running", message: event.message, latencyMs: 0 }];
        });
      }
    } else if (event.type === "done" || event.type === "error") {
      setNodes((prev) =>
        prev.map((n) =>
          n.status === "running"
            ? { ...n, status: event.type === "done" ? "completed" : "error" }
            : n
        )
      );
    }
  }, []);

  const reset = useCallback(() => {
    setNodes([]);
  }, []);

  return { nodes, handleEvent, reset };
}
