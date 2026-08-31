export const AGENT_EVENTS = {
  PHASE: "phase",
  INTENT: "intent",
  ACTION: "action",
  CHUNK: "chunk",
  CONFIRMATION: "confirmation",
  DONE: "done",
  ERROR: "error",
};

export const NODE_MESSAGES = {
  "Understanding your request": "understand_request",
  "Building context": "build_context",
  "Planning": "plan",
  "Thinking": "agent",
  "Executing tools": "tools",
  "Verifying": "verify",
  "Repairing": "repair",
  "Finalizing": "finish",
  "Connecting": "connecting",
};

export function classifyPhase(message) {
  if (!message) return null;
  for (const [prefix, node] of Object.entries(NODE_MESSAGES)) {
    if (message.startsWith(prefix)) return node;
  }
  return null;
}

export function makeTab(id = crypto.randomUUID(), title = "New session") {
  return {
    id,
    title,
    project: null,
    input: "",
    messages: [],
    pending: null,
    busy: false,
    status: "",
    tree: null,
    selected: "",
    fileContent: "",
    dirty: false,
    saving: false,
    running: false,
    runResult: "",
    openFolders: [],
    model: "openrouter/auto",
    openFiles: [],
    activeEditor: null,
  };
}
