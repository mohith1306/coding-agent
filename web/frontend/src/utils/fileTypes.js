const FILE_TYPES = {
  py: { icon: "\u{1F40D}", color: "#3572A5" },
  js: { icon: "\u{1F381}", color: "#f1e05a" },
  jsx: { icon: "\u26A1", color: "#61dafb" },
  ts: { icon: "\u{1F5C4}\uFE0F", color: "#3178c6" },
  tsx: { icon: "\u26A1", color: "#61dafb" },
  json: { icon: "\u{1F4CB}", color: "#cbcb41" },
  html: { icon: "\u{1F4F1}", color: "#e34c26" },
  css: { icon: "\u{1F3A8}", color: "#563d7c" },
  md: { icon: "\u{1F4DD}", color: "#519aba" },
  txt: { icon: "\u{1F4C4}", color: "#9ca3af" },
  yml: { icon: "\u2699\uFE0F", color: "#e34c26" },
  yaml: { icon: "\u2699\uFE0F", color: "#e34c26" },
  sh: { icon: "\u{1F4F4}", color: "#89e051" },
  bash: { icon: "\u{1F4F4}", color: "#89e051" },
  Dockerfile: { icon: "\u{1F6E2}\uFE0F", color: "#2496ed" },
  env: { icon: "\u{1F512}", color: "#9ca3af" },
  lock: { icon: "\u{1F512}", color: "#9ca3af" },
  toml: { icon: "\u2699\uFE0F", color: "#9ca3af" },
  cfg: { icon: "\u2699\uFE0F", color: "#9ca3af" },
  ini: { icon: "\u2699\uFE0F", color: "#9ca3af" },
  gitignore: { icon: "\u{1F511}", color: "#f05033" },
  csv: { icon: "\u{1F4CA}", color: "#2ea44f" },
  sql: { icon: "\u{1F4BE}", color: "#e38c00" },
  zip: { icon: "\u{1F4E6}", color: "#9ca3af" },
};

export const FOLDER_ICON = "\u{1F4C1}";
export const FOLDER_OPEN_ICON = "\u{1F4C2}";
export const FILE_ICON = "\u{1F4C4}";

export function fileTypeFor(name) {
  const lower = name.toLowerCase();
  if (lower in FILE_TYPES) return lower;
  const dot = lower.lastIndexOf(".");
  if (dot > 0 && lower.slice(dot + 1) in FILE_TYPES) {
    return lower.slice(dot + 1);
  }
  return null;
}

export function getFileTypeInfo(name) {
  const key = fileTypeFor(name);
  return key ? FILE_TYPES[key] : null;
}

export function getLanguage(name) {
  const ext = name.split(".").pop()?.toLowerCase();
  const map = {
    py: "python", js: "javascript", jsx: "javascript", ts: "typescript",
    tsx: "typescript", json: "json", html: "html", css: "css",
    md: "markdown", yml: "yaml", yaml: "yaml", sh: "shell", bash: "shell",
    toml: "toml", sql: "sql", csv: "plaintext", txt: "plaintext",
    xml: "xml", rs: "rust", go: "go", java: "java", rb: "ruby",
    cpp: "cpp", c: "c", h: "c", hpp: "cpp",
  };
  return map[ext] || "plaintext";
}

export default FILE_TYPES;
