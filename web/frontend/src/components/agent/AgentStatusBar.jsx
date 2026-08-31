import React from "react";

export default function AgentStatusBar({ nodes }) {
  if (!nodes || nodes.length === 0) return null;

  return (
    <div className="agent-progress">
      {nodes.map((node) => (
        <div key={node.name} className={`agent-node ${node.status}`}>
          <span className="node-indicator">
            {node.status === "running" && "●"}
            {node.status === "completed" && "✓"}
            {node.status === "error" && "✕"}
            {!node.status && "○"}
          </span>
          <span className="node-name">{node.name.replace(/_/g, " ")}</span>
          {node.latencyMs > 0 && (
            <span className="node-latency">{node.latencyMs}ms</span>
          )}
        </div>
      ))}
    </div>
  );
}
