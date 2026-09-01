import React, { useRef, useEffect, useState } from "react";

const MODELS = [
  { value: "openrouter/auto", label: "Auto" },
  { value: "google/gemini-3.5-flash", label: "Gemini 3.5 Flash" },
  { value: "google/gemini-3.7-flash", label: "Gemini 3.7 Flash" },
  { value: "deepseek/deepseek-chat", label: "DeepSeek V3" },
  { value: "meta-llama/llama-4-maverick", label: "Llama 4 Maverick" },
  { value: "qwen/qwen3-235b-a22b", label: "Qwen3 235B" },
];

export default function ChatComposer({ input, model, busy, hasProject, onInputChange, onSubmit, onModelChange }) {
  const textareaRef = useRef(null);
  const [isFocused, setIsFocused] = useState(false);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [input]);

  return (
    <form onSubmit={onSubmit} className="composer-form">
      <div className={`composer-box ${isFocused ? "focused" : ""} ${busy ? "busy" : ""}`}>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit(e);
            }
          }}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={
            hasProject
              ? "Ask anything, / for commands, @ for context..."
              : "Open a project first..."
          }
          disabled={busy || !hasProject}
          rows={1}
          autoFocus
          className="composer-textarea"
        />
        <div className="composer-toolbar">
          <div className="toolbar-left">
            <button
              type="button"
              className="toolbar-btn"
              title="Attach file"
              disabled={busy || !hasProject}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            <button
              type="button"
              className="toolbar-btn"
              title="Add context (@)"
              disabled={busy || !hasProject}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="4" />
                <path d="M16 8v5a3 3 0 006 0v-1a10 10 0 10-3.92 7.94" />
              </svg>
            </button>
          </div>
          <div className="toolbar-right">
            <div className="model-select-wrapper">
              <select
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
                disabled={busy || !hasProject}
                className="model-select"
                aria-label="Select model"
              >
                {MODELS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <svg className="model-select-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </div>
            <button
              type="submit"
              className="send-btn"
              disabled={busy || !input.trim() || !hasProject}
              title="Send message (Enter)"
            >
              {busy ? (
                <svg className="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 11-6.219-8.56" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="12" y1="19" x2="12" y2="5" />
                  <polyline points="5 12 12 5 19 12" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
      <div className="composer-hints">
        <span><kbd>Enter</kbd> to send</span>
        <span><kbd>Shift+Enter</kbd> for new line</span>
        <span><kbd>/</kbd> commands</span>
        <span><kbd>@</kbd> context</span>
      </div>
    </form>
  );
}
