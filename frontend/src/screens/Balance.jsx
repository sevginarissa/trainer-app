import { useState, useEffect, useCallback } from 'react';
import { mcpCall } from '../utils/mcp';
import { buildColorMap, getStudentColor } from '../utils/constants';

// ─── Sub-components ───────────────────────────────────────────────────────────

function Row({ label, value, cls = 'text-slate-200' }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-sm ${cls}`}>{value}</span>
    </div>
  );
}

function Stat({ label, value, cls }) {
  return (
    <div className="text-center">
      <p className={`text-xl font-bold ${cls}`}>{value}</p>
      <p className="text-[10px] text-slate-600 mt-0.5">{label}</p>
    </div>
  );
}

// ─── Skeleton placeholder ─────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="rounded-2xl bg-slate-800/80 overflow-hidden animate-pulse">
      <div className="flex items-center gap-3 px-4 py-3.5 border-b border-slate-700/40">
        <div className="w-10 h-10 rounded-full bg-slate-700" />
        <div className="flex-1 space-y-2">
          <div className="h-3.5 bg-slate-700 rounded w-28" />
          <div className="h-2.5 bg-slate-700 rounded w-16" />
        </div>
        <div className="h-7 w-14 bg-slate-700 rounded-full" />
      </div>
      <div className="px-4 py-3 space-y-2.5">
        <div className="h-2.5 bg-slate-700 rounded w-full" />
        <div className="h-2.5 bg-slate-700 rounded w-5/6" />
        <div className="h-2.5 bg-slate-700 rounded w-4/6 mt-3" />
      </div>
    </div>
  );
}

// ─── Payment numpad sheet ─────────────────────────────────────────────────────

function PaymentSheet({ student, onClose, onDone }) {
  const [count, setCount] = useState(0);
  const [busy,  setBusy]  = useState(false);

  // ── Numpad helpers ─────────────────────────────────────────────────────────

  function pressDigit(d) {
    setCount((prev) => (prev === 0 ? d : prev * 10 + d));
  }

  function backspace() { setCount((prev) => Math.floor(prev / 10)); }
  function clear()     { setCount(0); }
  function inc()       { setCount((c) => c + 1); }
  function dec()       { setCount((c) => Math.max(c - 1, 0)); }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function handleDeduct() {
    if (count === 0) return;
    setBusy(true);
    try {
      await mcpCall('add_credit', { student_id: student.id, amount: -count, reason: 'Ders' });
      onDone();
    } catch (e) {
      alert('Hata: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCredit() {
    if (count === 0) return;
    setBusy(true);
    try {
      await mcpCall('add_credit', { student_id: student.id, amount: count, reason: 'Ön ödeme' });
      onDone();
    } catch (e) {
      alert('Hata: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  // ── Numpad key ─────────────────────────────────────────────────────────────

  function Key({ label, onPress, cls = '' }) {
    return (
      <button
        onClick={onPress}
        disabled={busy}
        className={`h-14 rounded-2xl flex items-center justify-center text-xl font-semibold
          bg-slate-700 text-slate-100 active:bg-slate-600 active:scale-95 transition-all
          disabled:opacity-40 ${cls}`}
      >
        {label}
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-6 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full bg-slate-800 rounded-3xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <p className="text-base font-semibold text-slate-100">{student.name}</p>

        {/* ── Count display ──────────────────────────────────────────────── */}
        <div className="flex items-center justify-between bg-slate-900/60 rounded-2xl px-5 py-3">
          <button
            onClick={dec}
            disabled={count === 0}
            className="w-10 h-10 rounded-xl bg-slate-700 text-slate-100 text-2xl font-bold flex items-center justify-center disabled:opacity-30 active:scale-95 transition-transform"
          >−</button>

          <div className="text-center">
            <p className="text-5xl font-bold text-slate-100 tabular-nums">{count}</p>
            <p className="text-xs text-slate-500 mt-0.5">ders</p>
          </div>

          <button
            onClick={inc}
            className="w-10 h-10 rounded-xl bg-slate-700 text-slate-100 text-2xl font-bold flex items-center justify-center active:scale-95 transition-transform"
          >+</button>
        </div>

        {/* ── Numpad ─────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-2">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => (
            <Key key={d} label={d} onPress={() => pressDigit(d)} />
          ))}
          <Key label="✕" onPress={clear} cls="text-slate-500 text-base" />
          <Key label="0" onPress={() => pressDigit(0)} />
          <Key
            label={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M12 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M3 12l6.414 6.414a2 2 0 001.414.586H19a2 2 0 002-2V7a2 2 0 00-2-2h-8.172a2 2 0 00-1.414.586L3 12z" />
              </svg>
            }
            onPress={backspace}
            cls="text-slate-400"
          />
        </div>

        {/* ── Action buttons ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={handleDeduct}
            disabled={busy || count === 0}
            className="py-3.5 rounded-2xl bg-rose-700 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
          >
            {busy ? '…' : `Kredi Eksilt${count > 0 ? ` (${count})` : ''}`}
          </button>
          <button
            onClick={handleCredit}
            disabled={busy || count === 0}
            className="py-3.5 rounded-2xl bg-blue-600 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
          >
            {busy ? '…' : `Kredi Ekle${count > 0 ? ` (${count})` : ''}`}
          </button>
        </div>

        <button onClick={onClose} className="w-full py-2 text-slate-600 text-xs text-center">
          Kapat
        </button>
      </div>
    </div>
  );
}

// ─── Balance card ─────────────────────────────────────────────────────────────

function BalanceCard({ student, color, balance, onPay }) {
  const net      = balance.balance ?? 0;
  const netCls   = net > 0 ? 'text-emerald-400' : net < 0 ? 'text-rose-400' : 'text-slate-400';
  const netLabel = net > 0 ? 'ders alacak' : net < 0 ? 'ders verecek' : 'kapalı';

  return (
    <div className="rounded-2xl bg-slate-800/80 overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-3.5 border-b border-slate-700/50">
        <span
          className="w-10 h-10 rounded-full flex items-center justify-center text-base font-bold text-white flex-shrink-0"
          style={{ background: color.hex }}
        >
          {student.name[0]}
        </span>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-100">{student.name}</p>
        </div>

        {/* Net badge */}
        <div className="text-right flex-shrink-0 mr-2">
          <p className={`text-xl font-bold ${netCls}`}>
            {net > 0 ? '+' : ''}{net}
          </p>
          <p className="text-[10px] text-slate-500">{netLabel}</p>
        </div>

        {/* Pay button */}
        <button
          onClick={onPay}
          className="flex-shrink-0 w-9 h-9 rounded-xl bg-slate-700 flex items-center justify-center active:opacity-60 transition-opacity"
          aria-label="Ödeme yap"
        >
          <svg className="w-5 h-5 text-slate-300" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2 7a2 2 0 012-2h16a2 2 0 012 2v1H2V7zm0 4h20v6a2 2 0 01-2 2H4a2 2 0 01-2-2v-6zm3 3a1 1 0 000 2h3a1 1 0 000-2H5z" />
          </svg>
        </button>
      </div>

      {/* ── Detail rows ────────────────────────────────────────────────────── */}
      <div className="px-4 py-3 space-y-2.5">
        <Row
          label="Kredi (ders)"
          value={`+${balance.credits_total ?? 0}`}
          cls="text-emerald-400"
        />
        <Row
          label="Gerçekleşen dersler"
          value={`−${balance.sessions_occurred ?? 0}`}
          cls="text-slate-300"
        />

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 pt-1.5 border-t border-slate-700/50">
          <Stat label="Ödendi"   value={balance.lessons?.confirmed_paid   ?? 0} cls="text-blue-400"  />
          <Stat label="Borçlu"   value={balance.lessons?.confirmed_unpaid ?? 0} cls="text-amber-400" />
          <Stat label="Bekliyor" value={balance.lessons?.unconfirmed      ?? 0} cls="text-slate-500" />
        </div>
      </div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function Balance() {
  const [students,  setStudents]  = useState([]);
  const [colorMap,  setColorMap]  = useState({});
  const [balances,  setBalances]  = useState({});
  const [loading,   setLoading]   = useState(true);
  const [payingFor, setPayingFor] = useState(null); // { student, balance }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await mcpCall('get_students', {});
      const s = data ?? [];
      setStudents(s);
      setColorMap(buildColorMap(s));

      const results = await Promise.all(
        s.map((st) => mcpCall('generate_balance', { student_id: st.id }).catch(() => null)),
      );
      const map = {};
      s.forEach((st, i) => { if (results[i]) map[st.id] = results[i]; });
      setBalances(map);
    } catch (e) {
      console.error('Balance screen load error:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function handlePayDone() {
    setPayingFor(null);
    load();
  }

  // Summary totals
  const loaded = students.filter((s) => balances[s.id]);
  const totalOwed   = loaded.reduce((sum, s) => { const b = balances[s.id].balance; return sum + (b < 0 ? Math.abs(b) : 0); }, 0);
  const totalCredit = loaded.reduce((sum, s) => { const b = balances[s.id].balance; return sum + (b > 0 ? b : 0); }, 0);

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-slate-700/60">
        <h1 className="text-base font-semibold text-slate-100">Bakiye</h1>
        {!loading && loaded.length > 0 && (
          <div className="flex gap-4 mt-1">
            {totalOwed > 0 && (
              <p className="text-xs text-rose-400">
                Alacak: <span className="font-semibold">{totalOwed} ders</span>
              </p>
            )}
            {totalCredit > 0 && (
              <p className="text-xs text-emerald-400">
                Kredi: <span className="font-semibold">{totalCredit} ders</span>
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Card list ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-3 space-y-3">
        {loading ? (
          <>
            <SkeletonCard />
            <SkeletonCard />
          </>
        ) : students.length === 0 ? (
          <p className="text-center text-slate-600 text-sm mt-12">Öğrenci bulunamadı.</p>
        ) : (
          students.map((s) =>
            balances[s.id] ? (
              <BalanceCard
                key={s.id}
                student={s}
                color={getStudentColor(s.id, colorMap)}
                balance={balances[s.id]}
                onPay={() => setPayingFor({ student: s, balance: balances[s.id] })}
              />
            ) : null,
          )
        )}
      </div>

      {/* ── Payment sheet ─────────────────────────────────────────────────── */}
      {payingFor && (
        <PaymentSheet
          student={payingFor.student}
          onClose={() => setPayingFor(null)}
          onDone={handlePayDone}
        />
      )}
    </div>
  );
}
