import React from "react";
import FileTree from "./FileTree";

export default function FileExplorer({ tree, selected, openFolders, onSelect, onToggle, onDelete }) {
  if (!tree || tree.length === 0) {
    return (
      <div className="file-browser">
        <div className="files-empty">No files</div>
      </div>
    );
  }

  return (
    <div className="file-browser">
      <div className="files-tree">
        {tree.map((node, i) => (
          <FileTree
            key={`${node.name}-${i}`}
            node={{ ...node, path: node.name }}
            onSelect={onSelect}
            selected={selected}
            open={openFolders}
            onToggle={onToggle}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
}
