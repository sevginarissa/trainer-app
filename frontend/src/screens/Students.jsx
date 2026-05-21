import { useState, useEffect, useCallback, useMemo } from 'react';
import { mcpCall } from '../utils/mcp';
import { buildColorMap, getStudentColor, TR_DAYS } from '../utils/constants';

// ─── Day definitions ──────────────────────────────────────────────────────────

const DAYS = [
  { key: 'Mon', label: 'Pazartesi', dow: 0 },
  { key: 'Tue', label: 'Salı',      dow: 1 },
  { key: 'Wed', label: 'Çarşamba',  dow: 2 },
  { key: 'Thu', label: 'Perşembe',  dow: 3 },
  { key: 'Fri', label: 'Cuma',      dow: 4 },
  { key: 'Sat', label: 'Cumartesi', dow: 5 },
  { key: 'Sun', label: 'Pazar',     dow: 6 },
];

// Convert DB schedules array → { Mon: "09:00", ... } map for ScheduleBuilder
function schedulesToMap(schedules) {
  const result = {};
  for (const { day_of_week, lesson_time } of schedules ?? []) {
    const day = DAYS.find((d) => d.dow === day_of_week);
    if (day) result[day.key] = lesson_time;
  }
  return result;
}

// ─── Icons ────────────────────────────────────────────────────────────────────

function PencilIcon({ size = 4 }) {
  return (
    <svg className={`w-${size} h-${size}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M8 7V5a1 1 0 011-1h6a1 1 0 011 1v2" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  );
}

// ─── Balance sub-components ───────────────────────────────────────────────────

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

// ─── Schedule builder ─────────────────────────────────────────────────────────

function ScheduleBuilder({ value, onChange }) {
  return (
    <div className="space-y-2.5">
      {DAYS.map(({ key, label }) => {
        const checked = key in value;
        const time    = value[key] ?? '09:00';

        return (
          <div key={key} className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                if (checked) {
                  const next = { ...value };
                  delete next[key];
                  onChange(next);
                } else {
                  onChange({ ...value, [key]: '09:00' });
                }
              }}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors flex-shrink-0 ${
                checked ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400'
              }`}
              style={{ minWidth: '8.5rem' }}
            >
              <span className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                checked ? 'bg-white border-white' : 'border-slate-500'
              }`}>
                {checked && (
                  <svg className="w-3 h-3 text-blue-600" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth={1.8}
                      strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </span>
              {label}
            </button>

            {checked && (
              <input
                type="time"
                value={time}
                step={1800}
                onChange={(e) => onChange({ ...value, [key]: e.target.value })}
                className="flex-1 bg-slate-700 text-slate-100 rounded-xl px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Pending requests panel ───────────────────────────────────────────────────

function PendingRequestsPanel({ requests, onEdit, onDelete }) {
  // undefined = still loading, [] = loaded but empty
  if (requests === undefined) {
    return (
      <div className="flex justify-center py-2">
        <div className="w-4 h-4 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
      </div>
    );
  }
  if (requests.length === 0) return null;

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold text-slate-600 uppercase tracking-widest">Ders Talepleri</p>
      {requests.map((req) => (
        <div
          key={req.id}
          className="flex items-start gap-2 rounded-xl bg-slate-700/40 px-3 py-2.5"
        >
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-slate-200">
              {req.requested_date}
              {req.flexible_time
                ? ' · Esnek saat'
                : req.requested_time
                ? ` · ${req.requested_time}`
                : ''}
            </p>
            {req.notes ? (
              <p className="text-xs text-slate-500 mt-0.5 truncate">{req.notes}</p>
            ) : null}
          </div>

          <button
            onClick={() => onEdit(req)}
            className="w-6 h-6 flex items-center justify-center text-slate-500 active:opacity-60 flex-shrink-0"
            aria-label="Düzenle"
          >
            <PencilIcon size={3.5} />
          </button>

          <button
            onClick={() => onDelete(req)}
            className="w-6 h-6 flex items-center justify-center text-rose-700 text-sm font-bold active:opacity-60 flex-shrink-0"
            aria-label="Sil"
          >✕</button>
        </div>
      ))}
    </div>
  );
}

// ─── Student card ─────────────────────────────────────────────────────────────

function StudentCard({
  student, color, expanded, balance, requests,
  onExpand, onEdit, onDeactivate, onReactivate,
  onEditSchedule, onEditRequest, onDeleteRequest,
}) {
  const isActive = student.active !== 0;

  const schedule = (student.schedules ?? [])
    .map((s) => `${TR_DAYS[s.day_of_week] ?? s.day_of_week} ${s.lesson_time}`)
    .join(' · ') || '—';

  const net    = balance?.balance ?? null;
  const netPos = net !== null && net > 0;
  const netNeg = net !== null && net < 0;

  return (
    <div className={`rounded-2xl bg-slate-800/80 overflow-hidden transition-opacity ${!isActive ? 'opacity-55' : ''}`}>

      {/* ── Header row ──────────────────────────────────────────────────── */}
      <div
        className={`flex items-center gap-2.5 px-4 py-3.5 ${isActive ? 'cursor-pointer active:opacity-70' : ''}`}
        onClick={isActive ? onExpand : undefined}
      >
        <span
          className="w-10 h-10 rounded-full flex items-center justify-center text-base font-bold text-white flex-shrink-0"
          style={{ background: isActive ? color.hex : '#475569' }}
        >
          {student.name[0]}
        </span>

        <div className="flex-1 text-left min-w-0">
          <p className={`text-sm font-semibold truncate ${isActive ? 'text-slate-100' : 'text-slate-400'}`}>
            {student.name}
          </p>
          <p className="text-xs text-slate-500 truncate">{schedule}</p>
        </div>

        {isActive ? (
          <>
            {net !== null && net !== 0 && (
              <span className={`text-xs font-semibold rounded-full px-2.5 py-0.5 flex-shrink-0 ${
                netPos ? 'bg-emerald-900/40 text-emerald-400' :
                         'bg-rose-900/40    text-rose-400'
              }`}>
                {net > 0 ? '+' : ''}{net}
              </span>
            )}

            <button
              onClick={(e) => { e.stopPropagation(); onEdit(student); }}
              className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-blue-400 hover:bg-slate-700/60 active:opacity-60 flex-shrink-0"
              aria-label="Düzenle"
            >
              <PencilIcon />
            </button>

            <button
              onClick={(e) => { e.stopPropagation(); onDeactivate(student); }}
              className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-900/30 active:opacity-60 flex-shrink-0"
              aria-label="Pasife al"
            >
              <TrashIcon />
            </button>

            <svg
              className={`w-4 h-4 text-slate-600 flex-shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
              fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </>
        ) : (
          <button
            onClick={(e) => { e.stopPropagation(); onReactivate(student); }}
            className="flex-shrink-0 text-xs font-medium text-slate-400 bg-slate-700 hover:bg-slate-600 active:opacity-60 rounded-lg px-2.5 py-1.5 transition-colors"
          >
            Yeniden aktif et
          </button>
        )}
      </div>

      {/* ── Expanded panel ───────────────────────────────────────────────── */}
      {isActive && expanded && (
        <div className="border-t border-slate-700/50 px-4 py-3 space-y-4">

          {/* Balance detail */}
          {!balance ? (
            <div className="flex justify-center py-3">
              <div className="w-5 h-5 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
            </div>
          ) : (
            <div className="space-y-2.5">
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
              <div className="border-t border-slate-700/50 pt-2">
                <Row
                  label="Net bakiye (ders)"
                  value={`${(balance.balance ?? 0) > 0 ? '+' : ''}${balance.balance ?? 0}`}
                  cls={
                    (balance.balance ?? 0) > 0 ? 'text-emerald-400 font-bold' :
                    (balance.balance ?? 0) < 0 ? 'text-rose-400    font-bold' :
                                                 'text-slate-400   font-bold'
                  }
                />
              </div>
              <div className="grid grid-cols-3 gap-3 pt-1 border-t border-slate-700/50">
                <Stat label="Ödendi"   value={balance.lessons?.confirmed_paid   ?? 0} cls="text-blue-400"  />
                <Stat label="Borçlu"   value={balance.lessons?.confirmed_unpaid ?? 0} cls="text-amber-400" />
                <Stat label="Bekliyor" value={balance.lessons?.unconfirmed      ?? 0} cls="text-slate-500" />
              </div>
            </div>
          )}

          {/* Edit schedule button */}
          <button
            onClick={onEditSchedule}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-slate-700/60 text-slate-300 text-sm font-medium active:opacity-60 transition-opacity"
          >
            <CalendarIcon />
            Programı Düzenle
          </button>

          {/* Pending requests */}
          <PendingRequestsPanel
            requests={requests}
            onEdit={onEditRequest}
            onDelete={onDeleteRequest}
          />
        </div>
      )}
    </div>
  );
}

// ─── Edit schedule modal (bottom sheet) ───────────────────────────────────────

function EditScheduleModal({ student, onClose, onSaved }) {
  const original = useMemo(() => schedulesToMap(student.schedules), [student.schedules]);
  const [schedule, setSchedule] = useState(original);
  const [busy,     setBusy]     = useState(false);
  const [error,    setError]    = useState('');

  async function save() {
    setBusy(true);
    setError('');
    try {
      const ops = [];

      // Days removed — deactivate
      for (const { key, dow } of DAYS) {
        if (key in original && !(key in schedule)) {
          ops.push(mcpCall('remove_schedule_day', { student_id: student.id, day: dow }));
        }
      }
      // Days added or time changed — upsert
      for (const { key, dow } of DAYS) {
        if (key in schedule) {
          const wasPresent  = key in original;
          const timeChanged = !wasPresent || original[key] !== schedule[key];
          if (!wasPresent || timeChanged) {
            ops.push(mcpCall('update_schedule', { student_id: student.id, day: dow, time: schedule[key] }));
          }
        }
      }

      if (ops.length === 0) { onClose(); return; }
      await Promise.all(ops);
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full bg-slate-800 rounded-t-3xl px-4 pt-5 pb-8 max-h-[88vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Title bar */}
        <div className="flex items-center justify-between mb-1 flex-shrink-0">
          <button onClick={onClose} disabled={busy} className="text-slate-400 text-sm py-1 pr-2">
            İptal
          </button>
          <h2 className="text-base font-semibold text-slate-100">Programı Düzenle</h2>
          <button
            onClick={save}
            disabled={busy}
            className="text-blue-400 text-sm font-semibold py-1 pl-2 disabled:opacity-40"
          >
            {busy ? '…' : 'Kaydet'}
          </button>
        </div>
        <p className="text-xs text-slate-500 mb-4 flex-shrink-0">{student.name}</p>

        {/* Scrollable day list */}
        <div className="overflow-y-auto no-scrollbar flex-1">
          <ScheduleBuilder value={schedule} onChange={setSchedule} />
          {error && <p className="text-sm text-rose-400 mt-3">{error}</p>}
        </div>
      </div>
    </div>
  );
}

// ─── Edit pending request modal ───────────────────────────────────────────────

function EditRequestModal({ request, onClose, onSaved }) {
  const [date,         setDate]         = useState(request.requested_date ?? '');
  const [time,         setTime]         = useState(request.requested_time ?? '');
  const [flexibleTime, setFlexibleTime] = useState(!!request.flexible_time);
  const [notes,        setNotes]        = useState(request.notes ?? '');
  const [busy,         setBusy]         = useState(false);
  const [error,        setError]        = useState('');

  async function save() {
    if (!date) { setError('Tarih gerekli.'); return; }
    setBusy(true);
    setError('');
    try {
      await mcpCall('update_pending_request', {
        request_id:     request.id,
        requested_date: date,
        requested_time: flexibleTime ? null : time || null,
        flexible_time:  flexibleTime,
        notes,
      });
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-8 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full bg-slate-800 rounded-2xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-slate-100">Talebi Düzenle</h2>

        {/* Date */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Tarih</label>
          <input
            type="date"
            value={date}
            onChange={(e) => { setDate(e.target.value); setError(''); }}
            className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-3 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
          />
        </div>

        {/* Flexible time toggle */}
        <button
          type="button"
          onClick={() => setFlexibleTime((v) => !v)}
          className={`flex items-center gap-2 text-sm font-medium transition-colors ${
            flexibleTime ? 'text-blue-400' : 'text-slate-500'
          }`}
        >
          <span className={`relative w-8 h-4 rounded-full transition-colors flex-shrink-0 ${
            flexibleTime ? 'bg-blue-600' : 'bg-slate-700'
          }`}>
            <span className={`absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-all ${
              flexibleTime ? 'left-4' : 'left-0.5'
            }`} />
          </span>
          Esnek saat
        </button>

        {/* Time — hidden when flexible */}
        {!flexibleTime && (
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Saat</label>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-3 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
            />
          </div>
        )}

        {/* Notes */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Notlar</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="İsteğe bağlı"
            className="w-full bg-slate-700 text-slate-100 placeholder-slate-600 rounded-xl px-4 py-3 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
          />
        </div>

        {error && <p className="text-sm text-rose-400">{error}</p>}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-300 text-sm font-medium disabled:opacity-40"
          >
            İptal
          </button>
          <button
            onClick={save}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-blue-600 text-white text-sm font-semibold disabled:opacity-40"
          >
            {busy ? '…' : 'Kaydet'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Confirm delete request modal ─────────────────────────────────────────────

function ConfirmDeleteRequestModal({ request, onClose, onConfirmed }) {
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await mcpCall('delete_pending_request', { request_id: request.id });
      onConfirmed();
    } catch (e) {
      alert('Hata: ' + e.message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-8 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full bg-slate-800 rounded-2xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <h2 className="text-base font-semibold text-slate-100">Bu talebi sil?</h2>
          <p className="text-sm text-slate-400 mt-1.5">
            {request.requested_date}
            {request.flexible_time
              ? ' · Esnek saat'
              : request.requested_time
              ? ` · ${request.requested_time}`
              : ''}
            {request.notes ? ` — ${request.notes}` : ''}
          </p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-300 text-sm font-medium disabled:opacity-40"
          >
            Hayır
          </button>
          <button
            onClick={confirm}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-rose-700 text-white text-sm font-semibold disabled:opacity-40"
          >
            {busy ? '…' : 'Evet, Sil'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Add student modal ────────────────────────────────────────────────────────

function AddStudentModal({ onClose, onSaved }) {
  const [name,     setName]     = useState('');
  const [schedule, setSchedule] = useState({});
  const [busy,     setBusy]     = useState(false);
  const [error,    setError]    = useState('');

  async function save() {
    const trimmed = name.trim();
    if (!trimmed) { setError('İsim boş olamaz.'); return; }
    setBusy(true);
    setError('');
    try {
      await mcpCall('add_student', { name: trimmed, schedule });
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-900">
      <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
        <button onClick={onClose} disabled={busy} className="text-slate-400 text-sm py-1 pr-2">
          İptal
        </button>
        <h2 className="text-base font-semibold text-slate-100">Öğrenci Ekle</h2>
        <button
          onClick={save}
          disabled={busy}
          className="text-blue-400 text-sm font-semibold py-1 pl-2 disabled:opacity-40"
        >
          {busy ? 'Kaydediliyor…' : 'Kaydet'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-5 space-y-6">
        <div className="space-y-2">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">İsim</label>
          <input
            autoFocus
            type="text"
            value={name}
            onChange={(e) => { setName(e.target.value); setError(''); }}
            placeholder="Öğrenci adı"
            className="w-full bg-slate-800 text-slate-100 placeholder-slate-600 rounded-xl px-4 py-3 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
          />
        </div>

        <div className="space-y-3">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Program</label>
          <ScheduleBuilder value={schedule} onChange={setSchedule} />
        </div>

        {error && <p className="text-sm text-rose-400">{error}</p>}
      </div>
    </div>
  );
}

// ─── Edit student name modal ──────────────────────────────────────────────────

function EditStudentModal({ student, onClose, onSaved }) {
  const [name,  setName]  = useState(student.name);
  const [busy,  setBusy]  = useState(false);
  const [error, setError] = useState('');

  async function save() {
    const trimmed = name.trim();
    if (!trimmed) { setError('İsim boş olamaz.'); return; }
    if (trimmed === student.name) { onClose(); return; }
    setBusy(true);
    setError('');
    try {
      await mcpCall('update_student', { student_id: student.id, name: trimmed });
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-8 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="w-full bg-slate-800 rounded-2xl p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-base font-semibold text-slate-100">Öğrenci Düzenle</h2>

        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">İsim</label>
          <input
            autoFocus
            type="text"
            value={name}
            onChange={(e) => { setName(e.target.value); setError(''); }}
            className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-3 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
          />
        </div>

        {error && <p className="text-sm text-rose-400">{error}</p>}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-300 text-sm font-medium disabled:opacity-40"
          >
            İptal
          </button>
          <button
            onClick={save}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-blue-600 text-white text-sm font-semibold disabled:opacity-40"
          >
            {busy ? '…' : 'Kaydet'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Confirm deactivate modal ─────────────────────────────────────────────────

function ConfirmModal({ student, onClose, onConfirmed }) {
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await mcpCall('deactivate_student', { student_id: student.id });
      onConfirmed();
    } catch (e) {
      alert('Hata: ' + e.message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-8 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="w-full bg-slate-800 rounded-2xl p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div>
          <h2 className="text-base font-semibold text-slate-100">Emin misin?</h2>
          <p className="text-sm text-slate-400 mt-1.5">
            <span className="font-semibold text-slate-200">{student.name}</span>
            {' '}— Bu öğrenciyi pasife al. Ders geçmişi korunur.
          </p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-300 text-sm font-medium disabled:opacity-40"
          >
            İptal
          </button>
          <button
            onClick={confirm}
            disabled={busy}
            className="flex-1 py-3 rounded-xl bg-rose-700 text-white text-sm font-semibold disabled:opacity-40"
          >
            {busy ? '…' : 'Pasife al'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function Students() {
  const [students,         setStudents]         = useState([]);
  const [colorMap,         setColorMap]         = useState({});
  const [loading,          setLoading]          = useState(true);
  const [expanded,         setExpanded]         = useState(null);
  const [balances,         setBalances]         = useState({});
  const [pendingRequests,  setPendingRequests]  = useState({}); // { [id]: [] | undefined }
  const [showInactive,     setShowInactive]     = useState(false);
  const [showAddModal,     setShowAddModal]     = useState(false);
  const [editTarget,       setEditTarget]       = useState(null);   // rename
  const [confirmTarget,    setConfirmTarget]    = useState(null);   // deactivate
  const [scheduleTarget,   setScheduleTarget]   = useState(null);   // edit schedule
  const [editingRequest,   setEditingRequest]   = useState(null);   // { studentId, request }
  const [confirmDeleteReq, setConfirmDeleteReq] = useState(null);   // { studentId, request }

  // ── Load students ─────────────────────────────────────────────────────────

  const loadStudents = useCallback(async () => {
    setLoading(true);
    try {
      const data = await mcpCall('get_students', { include_inactive: showInactive });
      const s = data ?? [];
      setStudents(s);
      setColorMap(buildColorMap(s.filter((st) => st.active !== 0)));
    } catch (e) {
      console.error('Students load error:', e);
    } finally {
      setLoading(false);
    }
  }, [showInactive]);

  useEffect(() => { loadStudents(); }, [loadStudents]);

  // ── Refresh requests for one student ─────────────────────────────────────

  async function refreshRequests(studentId) {
    try {
      const all      = await mcpCall('get_pending_requests', {});
      const filtered = (all ?? []).filter((r) => r.student_id === studentId);
      setPendingRequests((prev) => ({ ...prev, [studentId]: filtered }));
    } catch (e) {
      console.error('Refresh requests error:', e);
    }
  }

  // ── Expand / collapse card ────────────────────────────────────────────────

  async function toggleExpand(student) {
    const id = student.id;
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);

    // Lazy-fetch balance
    if (!balances[id]) {
      mcpCall('generate_balance', { student_id: id })
        .then((b) => setBalances((prev) => ({ ...prev, [id]: b })))
        .catch((e) => console.error('Balance fetch error:', e));
    }

    // Lazy-fetch pending requests (undefined = not yet fetched, [] = none)
    if (pendingRequests[id] === undefined) {
      mcpCall('get_pending_requests', {})
        .then((all) => {
          const filtered = (all ?? []).filter((r) => r.student_id === id);
          setPendingRequests((prev) => ({ ...prev, [id]: filtered }));
        })
        .catch((e) => console.error('Pending requests fetch error:', e));
    }
  }

  // ── Handlers ─────────────────────────────────────────────────────────────

  async function handleReactivate(student) {
    try {
      await mcpCall('reactivate_student', { student_id: student.id });
      loadStudents();
    } catch (e) {
      alert('Hata: ' + e.message);
    }
  }

  function handleSaved() {
    setShowAddModal(false);
    setEditTarget(null);
    setBalances({});
    loadStudents();
  }

  function handleDeactivated() {
    setConfirmTarget(null);
    setExpanded(null);
    setBalances({});
    loadStudents();
  }

  function handleScheduleSaved() {
    setScheduleTarget(null);
    loadStudents(); // schedule text in header needs refreshing
  }

  function handleRequestEdited() {
    const { studentId } = editingRequest;
    setEditingRequest(null);
    refreshRequests(studentId);
  }

  function handleRequestDeleted() {
    const { studentId } = confirmDeleteReq;
    setConfirmDeleteReq(null);
    refreshRequests(studentId);
  }

  const activeCount = students.filter((s) => s.active !== 0).length;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-4 pt-3 pb-2 border-b border-slate-700/60 space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-base font-semibold text-slate-100">Öğrenciler</h1>
            <p className="text-xs text-slate-500 mt-0.5">{activeCount} aktif öğrenci</p>
          </div>

          <button
            onClick={() => setShowAddModal(true)}
            className="w-9 h-9 flex items-center justify-center rounded-xl bg-blue-600 active:opacity-70 flex-shrink-0"
            aria-label="Öğrenci Ekle"
          >
            <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
          </button>
        </div>

        <button
          onClick={() => setShowInactive((v) => !v)}
          className={`flex items-center gap-2 text-xs font-medium transition-colors ${
            showInactive ? 'text-blue-400' : 'text-slate-600'
          }`}
        >
          <span className={`relative w-8 h-4 rounded-full transition-colors flex-shrink-0 ${
            showInactive ? 'bg-blue-600' : 'bg-slate-700'
          }`}>
            <span className={`absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-all ${
              showInactive ? 'left-4' : 'left-0.5'
            }`} />
          </span>
          Pasif öğrencileri göster
        </button>
      </div>

      {/* ── Student list ──────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-3 space-y-3">
        {loading ? (
          <div className="flex justify-center pt-12">
            <div className="w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
          </div>
        ) : students.length === 0 ? (
          <p className="text-center text-slate-600 text-sm mt-12">Öğrenci bulunamadı.</p>
        ) : (
          students.map((s) => (
            <StudentCard
              key={s.id}
              student={s}
              color={getStudentColor(s.id, colorMap)}
              expanded={expanded === s.id}
              balance={balances[s.id] ?? null}
              requests={pendingRequests[s.id]}
              onExpand={() => toggleExpand(s)}
              onEdit={(st) => setEditTarget(st)}
              onDeactivate={(st) => setConfirmTarget(st)}
              onReactivate={handleReactivate}
              onEditSchedule={() => setScheduleTarget(s)}
              onEditRequest={(req) => setEditingRequest({ studentId: s.id, request: req })}
              onDeleteRequest={(req) => setConfirmDeleteReq({ studentId: s.id, request: req })}
            />
          ))
        )}
      </div>

      {/* ── Modals ───────────────────────────────────────────────────────── */}
      {showAddModal && (
        <AddStudentModal
          onClose={() => setShowAddModal(false)}
          onSaved={handleSaved}
        />
      )}
      {editTarget && (
        <EditStudentModal
          student={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={handleSaved}
        />
      )}
      {confirmTarget && (
        <ConfirmModal
          student={confirmTarget}
          onClose={() => setConfirmTarget(null)}
          onConfirmed={handleDeactivated}
        />
      )}
      {scheduleTarget && (
        <EditScheduleModal
          student={scheduleTarget}
          onClose={() => setScheduleTarget(null)}
          onSaved={handleScheduleSaved}
        />
      )}
      {editingRequest && (
        <EditRequestModal
          request={editingRequest.request}
          onClose={() => setEditingRequest(null)}
          onSaved={handleRequestEdited}
        />
      )}
      {confirmDeleteReq && (
        <ConfirmDeleteRequestModal
          request={confirmDeleteReq.request}
          onClose={() => setConfirmDeleteReq(null)}
          onConfirmed={handleRequestDeleted}
        />
      )}
    </div>
  );
}
