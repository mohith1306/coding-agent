import React from "react";

const MODELS = [
  { value: "openrouter/auto", label: "Auto" },
  { value: "openrouter/deepseek-coder-v2", label: "DeepSeek Coder V2" },
  { value: "openrouter/codellama-34b", label: "CodeLlama 34B" },
  { value: "openrouter/mistral-7b", label: "Mistral 7B" },
  { value: "openai/gpt-4o", label: "GPT-4o" },
  { value: "gemini/gemini-1.5-flash", label: "Gemini 1.5 Flash" },
  { value: "groq/llama-3.3-70b-versatile", label: "Llama 3.3 70B" },
];

export default function ChatComposer({ input, model, busy, hasProject, onInputChange, onSubmit, onModelChange }) {
  return (
    <form onSubmit={onSubmit} className="input-row">
      <div className="chat-composer">
        <textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit(e);
            }
          }}
          placeholder={
            hasProject
              ? "Ask anything, / for commands, @ for context..."
              : "Open a project first…"
          }
          disabled={busy || !hasProject}
          rows={1}
          autoFocus
        />
        <div className="composer-footer">
          <button
            type="button"
            className="composer-icon"
            title="Add context"
            disabled={busy || !hasProject}
            onClick={() => {}}
          >
            +
          </button>
          <div className="model-selector">
            <select
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={busy || !hasProject}
              aria-label="Select model"
            >
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            className="composer-send"
            disabled={busy || !input.trim() || !hasProject}
            title="Send message"
            aria-label="Send message"
          >
            ↑
          </button>
        </div>
      </div>
    </form>
  );
}
