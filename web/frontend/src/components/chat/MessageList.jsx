import React from "react";

export default function MessageList({ messages, pending, busy, status, endRef }) {
  return (
    <div className="messages">
      {messages.length === 0 && (
        <div className="empty">
          Ask me to search, read, create, modify, or run code in this project.
        </div>
      )}
      {messages.map((msg, i) => (
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

      {pending && (
        <div className="msg agent">
          <p>
            <strong>{pending.action || "Action"}</strong>
            {pending.target && (
              <>
                {" "}
                on <code>{pending.target}</code>
              </>
            )}
          </p>
          {pending.response && (
            <pre className="confirm-preview">{pending.response}</pre>
          )}
          <p className="muted">
            Proceed? This may modify files in the workspace.
          </p>
          <div className="actions">
            <button className="btn yes">Yes, proceed</button>
            <button className="btn no">Cancel</button>
          </div>
        </div>
      )}
      {busy && !pending && !status && (
        <div className="typing">Agent is thinking…</div>
      )}
      {status && <div className="status-bar">{status}</div>}
      <div ref={endRef} />
    </div>
  );
}
