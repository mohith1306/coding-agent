import React from "react";
import MarkdownRenderer from "../shared/MarkdownRenderer";

export default function Message({ msg }) {
  return (
    <div className={`msg ${msg.role}${msg.streaming ? " streaming" : ""}`}>
      {msg.bullets?.length > 0 && (
        <ul className="action-bullets">
          {msg.bullets.map((bullet, i) => (
            <li key={`${bullet}-${i}`}>{bullet}</li>
          ))}
        </ul>
      )}
      <div className="msg-content">
        <MarkdownRenderer content={msg.text} />
        {msg.streaming && <span className="caret" />}
      </div>
    </div>
  );
}
