import { useState, useEffect, useRef } from 'react';

// ─── Message bubble ───────────────────────────────────────────────────────────

function Bubble({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-none'
            : msg.isError
            ? 'bg-red-900/40 text-red-300 rounded-bl-none border border-red-800/50'
            : 'bg-slate-700/80 text-slate-100 rounded-bl-none'
        }`}
      >
        {msg.text}
      </div>
    </div>
  );
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function Thinking() {
  return (
    <div className="flex justify-start">
      <div className="bg-slate-700/80 text-slate-400 rounded-2xl rounded-bl-none px-4 py-2.5 text-sm flex items-center gap-1.5">
        <span className="animate-pulse">Düşünüyor</span>
        <span className="flex gap-0.5">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-1 h-1 bg-slate-400 rounded-full animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
//
// Pure rendering shell. All conversation state and the agentic loop live in
// App.jsx so they survive tab switches without re-triggering init.
//
// Props:
//   messages  — display message array  [{ role, text, isError? }]
//   loading   — true while Claude is thinking / tool calls are running
//   chatReady — false while the startup data fetch is in progress
//   onSend    — (text: string) => void — called when user submits a message

export default function Chat({ messages, loading, chatReady, onSend }) {
  const [input, setInput] = useState('');

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  // ── Auto-scroll to latest message ─────────────────────────────────────────

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // ── Auto-resize textarea ───────────────────────────────────────────────────

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  // ── Send ───────────────────────────────────────────────────────────────────

  function handleSend() {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    onSend(text);
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // ── Loading screen (while startup data fetch runs) ─────────────────────────

  if (!chatReady) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-2 text-slate-400">
          <div className="w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
          <span className="text-sm">Yükleniyor…</span>
        </div>
      </div>
    );
  }

  // ── Chat UI ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* ── Messages ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 no-scrollbar">
        {messages.length === 0 && !loading && (
          <p className="text-center text-slate-600 text-xs mt-8">
            Asistanınız hazır.
          </p>
        )}
        {messages.map((msg, i) => (
          <Bubble key={i} msg={msg} />
        ))}
        {loading && <Thinking />}
        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 border-t border-slate-700/60 bg-slate-900 px-3 py-2 flex items-end gap-2">
        <textarea
          ref={inputRef}
          rows={1}
          className="flex-1 bg-slate-800 text-slate-100 placeholder-slate-500 rounded-xl px-4 py-2.5 text-sm resize-none outline-none focus:ring-1 focus:ring-blue-500/50 min-h-[42px] max-h-[120px]"
          placeholder="Mesajınızı yazın…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          aria-label="Gönder"
          className="flex-shrink-0 w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center disabled:opacity-40 transition-opacity active:scale-95"
        >
          <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
