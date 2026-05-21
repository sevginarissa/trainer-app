// Dev:  VITE_API_URL is unset → falls back to http://localhost:8000
// Prod: set VITE_API_URL=https://your-app.up.railway.app in Vercel env vars (no trailing slash)
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const BASE = `${API_BASE}/api`;

/** Call an MCP tool via the local API server. Returns the tool result (parsed). */
export async function mcpCall(toolName, args = {}) {
  const res = await fetch(`${BASE}/mcp/${toolName}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ arguments: args }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`MCP ${toolName} failed: ${detail}`);
  }
  const data = await res.json();
  return data.result;
}

/** Send a messages array to Claude via the local API proxy. */
export async function chatCall({ messages, system = '', tools = [], maxTokens = 4096 }) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, system, tools, max_tokens: maxTokens }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Chat API failed (${res.status}): ${detail}`);
  }
  return res.json();
}
