import React from "react";
import { FOLDER_ICON, FOLDER_OPEN_ICON, FILE_ICON, getFileTypeInfo } from "../../utils/fileTypes";

export default function FileTree({ node, depth = 0, onSelect, selected, open, onToggle, onDelete }) {
  const indent = { paddingLeft: `${depth * 14 + 8}px` };

  if (node.type === "file") {
    const isSel = selected === node.path;
    const info = getFileTypeInfo(node.name);
    const style = info ? { color: info.color } : null;
    const icon = info ? info.icon : FILE_ICON;
    return (
      <div
        className={`file-entry file ${isSel ? "selected" : ""}`}
        style={indent}
        onClick={() => onSelect(node.path)}
        title={`${node.path} (${node.size} bytes)`}
      >
        <span className="file-icon" style={style}>
          {icon}
        </span>
        <span className="file-name">{node.name}</span>
        <span
          className="file-del"
          title="Delete file"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(node.path);
          }}
        >
          ✕
        </span>
      </div>
    );
  }

  const isOpen = open.has(node.path);
  return (
    <div>
      <div
        className="file-entry dir"
        style={indent}
        onClick={() => onToggle(node.path)}
      >
        <span className="file-icon">
          {isOpen ? FOLDER_OPEN_ICON : FOLDER_ICON}
        </span>
        <span className="file-name">{node.name}</span>
      </div>
      {isOpen &&
        node.children.map((child, i) => (
          <FileTree
            key={`${child.name}-${i}`}
            node={{ ...child, path: `${node.path}/${child.name}` }}
            depth={depth + 1}
            onSelect={onSelect}
            selected={selected}
            open={open}
            onToggle={onToggle}
            onDelete={onDelete}
          />
        ))}
    </div>
  );
}
