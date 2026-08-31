import React from "react";

export default function TabBar({ tabs, activeIndex, onSelect, onClose, onNew, label }) {
  return (
    <div className="tab-bar">
      {tabs.map((tab, i) => (
        <div
          key={tab.id || i}
          className={`tab ${i === activeIndex ? "active" : ""}`}
          onClick={() => onSelect(i)}
        >
          <span className="tab-label">{tab.title || `Tab ${i + 1}`}</span>
          <button
            className="tab-close"
            onClick={(e) => {
              e.stopPropagation();
              onClose(i);
            }}
            title="Close tab"
          >
            ×
          </button>
        </div>
      ))}
      {onNew && (
        <button className="tab-new" onClick={onNew} title={`New ${label || "tab"}`}>
          +
        </button>
      )}
    </div>
  );
}
