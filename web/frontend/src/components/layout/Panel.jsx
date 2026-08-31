import React from "react";

export default function Panel({ title, children, className = "", style = {} }) {
  return (
    <div className={`panel ${className}`} style={style}>
      {title && (
        <div className="panel-header">
          <span className="panel-title">{title}</span>
        </div>
      )}
      <div className="panel-content">{children}</div>
    </div>
  );
}
