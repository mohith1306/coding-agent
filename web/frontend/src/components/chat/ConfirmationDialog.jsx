import React from "react";

export default function ConfirmationDialog({ pending, onConfirm, onCancel }) {
  if (!pending) return null;

  return (
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
        <button onClick={onConfirm} className="btn yes">
          Yes, proceed
        </button>
        <button onClick={onCancel} className="btn no">
          Cancel
        </button>
      </div>
    </div>
  );
}
