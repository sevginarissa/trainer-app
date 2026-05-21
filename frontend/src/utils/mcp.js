// In dev: VITE_API_URL is unset → '' → Vite proxy forwards /api/* to localhost:8000
// In prod: VITE_API_URL = 'https://your-app.up.railway.app' (set in Vercel dashboard)
const BASE = `${import.meta.env.VITE_API_URL ?? ''}/api`;

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
