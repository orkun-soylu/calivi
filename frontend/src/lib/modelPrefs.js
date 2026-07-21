// Remembering the server/model selection in localStorage.

export const LAST_SERVER_KEY = "calivi_last_server_id";
export const MODEL_BY_SERVER_KEY = "calivi_model_by_server";
export const USE_TOOLS_KEY = "calivi_use_tools";
const LEGACY_WEB_SEARCH_KEY = "calivi_web_search"; // pre-rename; read once so the toggle
                                                   // does not silently reset to off on upgrade

export function loadUseTools() {
  const v = localStorage.getItem(USE_TOOLS_KEY);
  if (v !== null) return v === "1";
  return localStorage.getItem(LEGACY_WEB_SEARCH_KEY) === "1";
}

export function loadModelMap() {
  try {
    return JSON.parse(localStorage.getItem(MODEL_BY_SERVER_KEY) || "{}");
  } catch {
    return {};
  }
}

export function saveModelForServer(serverId, model) {
  const map = loadModelMap();
  map[String(serverId)] = model;
  localStorage.setItem(MODEL_BY_SERVER_KEY, JSON.stringify(map));
}

export function initialServerId() {
  const saved = localStorage.getItem(LAST_SERVER_KEY);
  const n = Number(saved);
  return n || null; // invalid/legacy "auto" → null, an effect settles it on the first server
}

/** Preferred model for a server: the remembered one if still valid, otherwise the first model. */
export function preferredModel(server) {
  const remembered = loadModelMap()[String(server.id)];
  return remembered && server.models.includes(remembered) ? remembered : server.models[0] || "";
}
