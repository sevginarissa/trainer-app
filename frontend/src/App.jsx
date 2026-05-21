import { useState, useRef, useCallback, useEffect } from 'react';
import TabBar from './components/TabBar';
import Chat from './screens/Chat';
import Calendar from './screens/Calendar';
import Students from './screens/Students';
import Balance from './screens/Balance';
import { mcpCall, chatCall } from './utils/mcp';
import { CLAUDE_TOOLS, minifyTools } from './utils/constants';
import { buildSystemPrompt } from './utils/systemPrompt';

const LAST_OPEN_KEY = 'lastOpenDatetime';
const MAX_LOOP_ITERATIONS = 12;

export default function App() {
  const [activeTab, setActiveTab] = useState('chat');

  // ── Chat conversation state ────────────────────────────────────────────────
  //
  // Lives in App so it is never destroyed by tab switches.
  // Chat.jsx is just a rendering shell that receives these as props.

  const [messages,  setMessages]  = useState([]);
  const [loading,   setLoading]   = useState(false);
  const [chatReady, setChatReady] = useState(false); // false while initialising

  // Stable refs — never cause re-renders
  const apiHistoryRef   = useRef([]);   // full Claude API turn history
  const systemPromptRef = useRef('');   // hydrated system prompt
  const initCalledRef   = useRef(false); // guard against StrictMode double-fire

  // ── Agentic loop ───────────────────────────────────────────────────────────

  const runLoop = useCallback(async (prevHistory, newTurns, system) => {
    setLoading(true);
    let apiMessages = [...prevHistory, ...newTurns];
    let iters = 0;

    try {
      while (iters < MAX_LOOP_ITERATIONS) {
        iters++;
        const res = await chatCall({
          messages: apiMessages,
          system,
          tools: minifyTools(CLAUDE_TOOLS),
        });

        const textBlock = res.content?.find((c) => c.type === 'text');

        if (res.stop_reason !== 'tool_use') {
          if (textBlock?.text) {
            setMessages((prev) => [...prev, { role: 'assistant', text: textBlock.text }]);
          }
          apiHistoryRef.current = [...apiMessages, { role: 'assistant', content: res.content }];
          break;
        }

        // Execute all tool calls in parallel
        const toolUses   = res.content.filter((c) => c.type === 'tool_use');
        const toolResults = await Promise.all(
          toolUses.map(async (tu) => {
            try {
              const result = await mcpCall(tu.name, tu.input ?? {});
              return {
                type: 'tool_result',
                tool_use_id: tu.id,
                content: JSON.stringify(result),
              };
            } catch (e) {
              return {
                type: 'tool_result',
                tool_use_id: tu.id,
                content: JSON.stringify({ error: e.message }),
                is_error: true,
              };
            }
          }),
        );

        apiMessages = [
          ...apiMessages,
          { role: 'assistant', content: res.content },
          { role: 'user',      content: toolResults },
        ];
      }
    } catch (err) {
      console.error('Chat loop error:', err);
      const isRateLimit = err.message?.includes('(429)') || err.message?.toLowerCase().includes('rate_limit');
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: isRateLimit
            ? 'Çok fazla istek gönderildi, lütfen birkaç saniye bekleyin ve tekrar deneyin.'
            : `Bağlantı hatası: ${err.message}\n\nAPI sunucusunun çalıştığını kontrol edin.`,
          isError: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, []); // empty deps — runLoop identity is stable for the app's entire lifetime

  // ── One-time startup init ─────────────────────────────────────────────────
  //
  // The initCalledRef guard prevents React 18 StrictMode from firing this
  // twice (StrictMode mounts → unmounts → remounts in development, but the
  // ref value is preserved across that cycle).

  useEffect(() => {
    if (initCalledRef.current) return;
    initCalledRef.current = true;

    async function init() {
      const lastOpen =
        localStorage.getItem(LAST_OPEN_KEY) ??
        new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
      localStorage.setItem(LAST_OPEN_KEY, new Date().toISOString());

      try {
        const [pending, overrides, todayLessons, pendingRequests] = await Promise.all([
          mcpCall('get_pending_lessons', { since_datetime: lastOpen }),
          mcpCall('get_pending_overrides', {}),
          mcpCall('get_todays_lessons', {}),
          mcpCall('get_pending_requests', {}),
        ]);

        const system = buildSystemPrompt({
          lastOpen,
          pending,
          overrides,
          pendingRequests,
          todayLessons,
        });

        systemPromptRef.current = system;
        setChatReady(true);

        // Trigger Claude's proactive greeting — fires exactly once
        await runLoop([], [{ role: 'user', content: 'Uygulama açıldı.' }], system);
      } catch (err) {
        console.error('Init error:', err);
        setChatReady(true);
        setMessages([
          {
            role: 'assistant',
            text: 'Sunucuya bağlanılamadı. Lütfen API sunucusunun çalıştığını kontrol edin:\n\nuvicorn server.api_server:app --port 8000',
            isError: true,
          },
        ]);
      }
    }

    init();
  }, []); // empty deps — fires once on mount, never again

  // ── User sends a message ──────────────────────────────────────────────────

  const handleSend = useCallback(async (text) => {
    if (!text.trim()) return;
    setMessages((prev) => [...prev, { role: 'user', text }]);
    await runLoop(
      apiHistoryRef.current,
      [{ role: 'user', content: text }],
      systemPromptRef.current,
    );
  }, [runLoop]); // runLoop is stable, so handleSend is stable too

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-[100dvh] flex flex-col bg-slate-900 text-white overflow-hidden">
      <main className="flex-1 overflow-hidden relative">
        {/*
          Chat is always mounted — conversation state lives in App above, so
          switching tabs and back never resets the session or re-triggers init.
        */}
        <div className={`absolute inset-0 ${activeTab === 'chat' ? '' : 'hidden'}`}>
          <Chat
            messages={messages}
            loading={loading}
            chatReady={chatReady}
            onSend={handleSend}
          />
        </div>

        {activeTab !== 'chat' && (
          <div className="absolute inset-0">
            {activeTab === 'takvim'     && <Calendar />}
            {activeTab === 'ogrenciler' && <Students />}
            {activeTab === 'bakiye'     && <Balance />}
          </div>
        )}
      </main>

      <TabBar activeTab={activeTab} onChange={setActiveTab} />
    </div>
  );
}
