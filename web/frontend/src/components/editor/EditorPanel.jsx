import React, { useRef, useEffect, useState, useCallback } from "react";
import Editor from "@monaco-editor/react";
import useFileTypes from "../../utils/fileTypes";
import TabBar from "../layout/TabBar";

const languageMap = {
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  py: "python",
  rb: "ruby",
  go: "go",
  rs: "rust",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  cpp: "cpp",
  h: "c",
  hpp: "cpp",
  cs: "csharp",
  php: "php",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  less: "less",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  toml: "ini",
  xml: "xml",
  md: "markdown",
  markdown: "markdown",
  sql: "sql",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  dockerfile: "dockerfile",
  docker: "dockerfile",
  makefile: "makefile",
  csv: "plaintext",
  txt: "plaintext",
};

function getLanguage(filename) {
  if (!filename) return "plaintext";
  const ext = filename.split(".").pop().toLowerCase();
  return languageMap[ext] || "plaintext";
}

export default function EditorPanel({ file, readOnly = false, onSave }) {
  const editorRef = useRef(null);
  const [modified, setModified] = useState(false);
  const [currentValue, setCurrentValue] = useState("");
  const language = getLanguage(file?.name);

  useEffect(() => {
    if (file) {
      setCurrentValue(file.content || "");
      setModified(false);
    }
  }, [file?.name, file?.content]);

  const handleMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    editor.updateOptions({
      readOnly,
      minimap: { enabled: false },
      fontSize: 14,
      fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monaco, Consolas, "Liberation Mono", monospace',
      lineHeight: 22,
      padding: { top: 12 },
      scrollBeyondLastLine: false,
      renderWhitespace: "selection",
      bracketPairColorization: { enabled: true },
      smoothScrolling: true,
      cursorBlinking: "smooth",
      cursorSmoothCaretAnimation: "on",
      tabSize: file?.tabSize || 2,
    });
  }, [readOnly, file?.tabSize]);

  const handleChange = useCallback((value) => {
    setCurrentValue(value || "");
    setModified(true);
  }, []);

  const handleSave = useCallback(() => {
    if (onSave && modified) {
      onSave(currentValue);
      setModified(false);
    }
  }, [onSave, modified, currentValue]);

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSave]);

  if (!file) {
    return (
      <div className="editor-area">
        <div className="editor-empty">Select a file to view it.</div>
      </div>
    );
  }

  return (
    <div className="editor-area">
      <Editor
        height="100%"
        language={language}
        value={currentValue}
        onChange={handleChange}
        onMount={handleMount}
        theme="vs-dark"
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 14,
          fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monaco, Consolas, "Liberation Mono", monospace',
          lineHeight: 22,
          padding: { top: 12 },
          scrollBeyondLastLine: false,
          renderWhitespace: "selection",
          bracketPairColorization: { enabled: true },
          smoothScrolling: true,
          cursorBlinking: "smooth",
          cursorSmoothCaretAnimation: "on",
          tabSize: file?.tabSize || 2,
        }}
      />
    </div>
  );
}
