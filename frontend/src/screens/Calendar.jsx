import { useState, useEffect, useCallback, useRef } from 'react';
import { mcpCall } from '../utils/mcp';
import { buildColorMap, getStudentColor } from '../utils/constants';

// ─── Date helpers ─────────────────────────────────────────────────────────────

function toISO(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function getMonday(date) {
  const d = new Date(date);
  const dow = d.getDay();
  d.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1));
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

function formatWeekHeader(monday) {
  const sunday = addDays(monday, 6);
  const opts = { day: 'numeric', month: 'short' };
  return `${monday.toLocaleDateString('tr-TR', opts)} – ${sunday.toLocaleDateString('tr-TR', { ...opts, year: 'numeric' })}`;
}

function fmtDate(dateStr) {
  return new Date(dateStr + 'T12:00:00').toLocaleDateString('tr-TR', {
    weekday: 'long', day: 'numeric', month: 'long',
  });
}

const DAY_SHORT = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

// ─── Lesson status helpers ────────────────────────────────────────────────────

function cardBorder(happened) {
  if (happened === 1) return 'border-emerald-600 bg-emerald-900/20';
  if (happened === 0) return 'border-rose-700   bg-rose-900/20';
  return                     'border-slate-700   bg-slate-800/60';
}

function statusBadge(happened) {
  if (happened === 1) return { text: '✓', cls: 'text-emerald-400 font-bold' };
  if (happened === 0) return { text: '✗', cls: 'text-rose-400   font-bold' };
  return                     { text: '?', cls: 'text-slate-600' };
}

// ─── Icons ────────────────────────────────────────────────────────────────────

function PencilIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
    </svg>
  );
}

// ─── Lesson card ──────────────────────────────────────────────────────────────

function LessonCard({ lesson, color, onDetail, onMark, onCancel, onReschedule }) {
  const time  = (lesson.scheduled_at ?? '').slice(11, 16);
  const badge = statusBadge(lesson.happened);
  const isPending = lesson.happened === null;

  return (
    <div className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-2 ${cardBorder(lesson.happened)}`}>
      {/* ← left tap zone → opens detail modal */}
      <button
        onClick={() => onDetail(lesson)}
        className="flex items-center gap-2 flex-1 min-w-0 text-left active:opacity-70"
      >
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color.hex }} />
        <span className="flex-1 text-sm font-medium text-slate-200 truncate">{lesson.student_name}</span>
        <span className="text-xs text-slate-500 tabular-nums">{time}</span>
      </button>

      {/* ← action zone */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {isPending ? (
          <>
            <button
              onClick={() => onMark(lesson, true)}
              className="w-7 h-7 rounded-lg bg-emerald-700/50 text-emerald-300 text-sm font-bold flex items-center justify-center active:opacity-60 transition-opacity"
              aria-label="Gerçekleşti"
            >✓</button>
            <button
              onClick={() => onMark(lesson, false)}
              className="w-7 h-7 rounded-lg bg-rose-800/50 text-rose-300 text-sm font-bold flex items-center justify-center active:opacity-60 transition-opacity"
              aria-label="Gelmedi"
            >✗</button>
          </>
        ) : (
          <span className={`w-6 text-center text-sm ${badge.cls}`}>{badge.text}</span>
        )}

        <button
          onClick={() => onReschedule(lesson)}
          className="w-6 h-6 flex items-center justify-center text-slate-500 active:opacity-60 transition-opacity"
          aria-label="Yeniden planla"
        >
          <PencilIcon />
        </button>

        <button
          onClick={() => onCancel(lesson)}
          className="w-6 h-6 flex items-center justify-center text-rose-800 text-sm font-bold active:opacity-60 transition-opacity"
          aria-label="İptal et"
        >✕</button>
      </div>
    </div>
  );
}

// ─── Detail / mark modal ──────────────────────────────────────────────────────

function DetailModal({ lesson, color, onClose, onMarked }) {
  const [busy,   setBusy]   = useState(false);
  const [notice, setNotice] = useState(null);

  async function mark(happened) {
    setBusy(true);
    try {
      const result = await mcpCall('mark_lesson', { lesson_id: lesson.id, happened });
      if (!happened && result?.freed_slot_matches?.length) {
        const names = result.freed_slot_matches.map((r) => r.student_name).join(', ');
        setNotice(`Bu slot için bekleyen talep var: ${names}`);
        return;
      }
      onMarked();
    } catch (e) {
      alert('Hata: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  const date    = (lesson.scheduled_at ?? '').slice(0, 10);
  const time    = (lesson.scheduled_at ?? '').slice(11, 16);
  const dateStr = fmtDate(date);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-8 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full bg-slate-800 rounded-2xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <span
            className="w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold text-white flex-shrink-0"
            style={{ background: color.hex }}
          >
            {lesson.student_name[0]}
          </span>
          <div className="flex-1">
            <p className="text-base font-semibold text-slate-100">{lesson.student_name}</p>
            <p className="text-xs text-slate-400">{dateStr} · {time}</p>
          </div>
          {lesson.happened === 1 && <span className="text-emerald-400 text-sm font-semibold">Gerçekleşti</span>}
          {lesson.happened === 0 && <span className="text-rose-400   text-sm font-semibold">Gelmedi</span>}
          {lesson.happened === null && <span className="text-slate-500 text-sm">Onay bekliyor</span>}
        </div>

        {notice && (
          <div className="rounded-xl bg-amber-900/30 border border-amber-700/50 px-3 py-2.5 text-sm text-amber-300">
            {notice}
          </div>
        )}

        {!notice && (
          <div className="flex gap-3">
            <button
              onClick={() => mark(true)}
              disabled={busy || lesson.happened === 1}
              className="flex-1 py-3 rounded-xl bg-emerald-700 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
            >
              Gerçekleşti
            </button>
            <button
              onClick={() => mark(false)}
              disabled={busy || lesson.happened === 0}
              className="flex-1 py-3 rounded-xl bg-rose-800 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
            >
              Gelmedi
            </button>
          </div>
        )}

        <button
          onClick={notice ? () => { setNotice(null); onMarked(); } : onClose}
          className="w-full py-2 text-slate-500 text-sm"
        >
          {notice ? 'Tamam' : 'Kapat'}
        </button>
      </div>
    </div>
  );
}

// ─── Cancel confirm modal ─────────────────────────────────────────────────────

function CancelModal({ lesson, onClose, onCancelled }) {
  const [busy,   setBusy]   = useState(false);
  const [notice, setNotice] = useState(null);

  async function doCancel() {
    setBusy(true);
    try {
      const result = await mcpCall('cancel_lesson', { lesson_id: lesson.id });
      if (result?.freed_slot_matches?.length) {
        const names = result.freed_slot_matches.map((r) => r.student_name).join(', ');
        setNotice(`Bu slot için bekleyen talep var: ${names}`);
      } else {
        onCancelled();
      }
    } catch (e) {
      alert('Hata: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  const date = (lesson.scheduled_at ?? '').slice(0, 10);
  const time = (lesson.scheduled_at ?? '').slice(11, 16);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end px-4 pb-8 bg-black/60 backdrop-blur-sm"
      onClick={notice ? undefined : onClose}
    >
      <div
        className="w-full bg-slate-800 rounded-2xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        {notice ? (
          <>
            <div className="rounded-xl bg-amber-900/30 border border-amber-700/50 px-3 py-2.5 text-sm text-amber-300">
              {notice}
            </div>
            <button
              onClick={onCancelled}
              className="w-full py-3 rounded-xl bg-slate-700 text-slate-200 font-semibold text-sm active:scale-95 transition-transform"
            >
              Tamam
            </button>
          </>
        ) : (
          <>
            <p className="text-base font-semibold text-slate-100 text-center">Bu dersi iptal et?</p>
            <p className="text-sm text-slate-400 text-center">{lesson.student_name} · {date} {time}</p>
            <div className="flex gap-3">
              <button
                onClick={onClose}
                className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-200 font-semibold text-sm active:scale-95 transition-transform"
              >
                Hayır
              </button>
              <button
                onClick={doCancel}
                disabled={busy}
                className="flex-1 py-3 rounded-xl bg-rose-800 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
              >
                {busy ? '…' : 'Evet, iptal et'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Reschedule modal ─────────────────────────────────────────────────────────

function RescheduleModal({ lesson, onClose, onRescheduled }) {
  const [date, setDate] = useState((lesson.scheduled_at ?? '').slice(0, 10));
  const [time, setTime] = useState((lesson.scheduled_at ?? '').slice(11, 16));
  const [busy, setBusy] = useState(false);

  async function handleSave() {
    if (!date || !time) return;
    setBusy(true);
    try {
      await mcpCall('reschedule_lesson', { lesson_id: lesson.id, new_datetime: `${date}T${time}:00` });
      onRescheduled();
    } catch (e) {
      alert('Hata: ' + e.message);
    } finally {
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
          <p className="text-base font-semibold text-slate-100">Dersi Yeniden Planla</p>
          <p className="text-xs text-slate-400 mt-0.5">{lesson.student_name}</p>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Tarih</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-2.5 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Saat</label>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-2.5 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
            />
          </div>
        </div>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-200 font-semibold text-sm active:scale-95 transition-transform"
          >
            İptal
          </button>
          <button
            onClick={handleSave}
            disabled={busy || !date || !time}
            className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
          >
            {busy ? '…' : 'Kaydet'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Add lesson modal ─────────────────────────────────────────────────────────

function AddLessonModal({ date, students, onClose, onAdded }) {
  const [studentId, setStudentId] = useState(students[0]?.id ?? '');
  const [time,      setTime]      = useState('09:00');
  const [busy,      setBusy]      = useState(false);

  const displayDate = fmtDate(date);

  async function handleAdd() {
    if (!studentId || !time) return;
    setBusy(true);
    try {
      await mcpCall('add_lesson', {
        student_id: Number(studentId),
        scheduled_datetime: `${date}T${time}:00`,
      });
      onAdded();
    } catch (e) {
      alert('Hata: ' + e.message);
    } finally {
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
          <p className="text-base font-semibold text-slate-100">Ders Ekle</p>
          <p className="text-xs text-slate-400 mt-0.5 capitalize">{displayDate}</p>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Öğrenci</label>
            <select
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-2.5 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
            >
              {students.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Saat</label>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="w-full bg-slate-700 text-slate-100 rounded-xl px-4 py-2.5 text-sm outline-none focus:ring-1 focus:ring-blue-500/50"
            />
          </div>
        </div>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-3 rounded-xl bg-slate-700 text-slate-200 font-semibold text-sm active:scale-95 transition-transform"
          >
            İptal
          </button>
          <button
            onClick={handleAdd}
            disabled={busy || !studentId}
            className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-semibold text-sm disabled:opacity-40 active:scale-95 transition-transform"
          >
            {busy ? '…' : 'Ekle'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Freed-slot notice ────────────────────────────────────────────────────────

function FreedSlotNotice({ names, onDismiss }) {
  return (
    <div
      className="fixed inset-x-4 bottom-24 z-50 rounded-2xl bg-amber-900/90 border border-amber-700/60 px-4 py-3.5 flex items-start gap-3 shadow-xl"
      onClick={onDismiss}
    >
      <span className="text-amber-400 text-lg flex-shrink-0">⚠</span>
      <div className="flex-1">
        <p className="text-sm font-semibold text-amber-200">Boşalan slot — bekleyen talep</p>
        <p className="text-xs text-amber-400 mt-0.5">{names}</p>
      </div>
      <button onClick={onDismiss} className="text-amber-600 text-sm font-bold flex-shrink-0">✕</button>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function Calendar() {
  const [monday,       setMonday]       = useState(() => getMonday(new Date()));
  const [lessons,      setLessons]      = useState([]);
  const [students,     setStudents]     = useState([]);
  const [colorMap,     setColorMap]     = useState({});
  const [loading,      setLoading]      = useState(true);

  // Modal states
  const [detail,       setDetail]       = useState(null); // lesson
  const [cancelling,   setCancelling]   = useState(null); // lesson
  const [rescheduling, setRescheduling] = useState(null); // lesson
  const [addingLesson, setAddingLesson] = useState(null); // { date: 'YYYY-MM-DD' }
  const [freedNotice,  setFreedNotice]  = useState(null); // string of names

  const today = toISO(new Date());
  const generatedRef = useRef(false); // fire generate_upcoming_lessons only once

  // ── Load week ──────────────────────────────────────────────────────────────

  const load = useCallback(async (mon) => {
    setLoading(true);
    try {
      const [weekLessons, studs] = await Promise.all([
        mcpCall('get_week_lessons', { week_date: toISO(mon) }),
        mcpCall('get_students', {}),
      ]);
      setLessons(weekLessons ?? []);
      setStudents(studs ?? []);
      setColorMap(buildColorMap(studs ?? []));
    } catch (e) {
      console.error('Calendar load error:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    async function doLoad() {
      // On first mount, seed the DB from recurring schedules before fetching
      if (!generatedRef.current) {
        generatedRef.current = true;
        try { await mcpCall('generate_upcoming_lessons', { weeks_ahead: 8 }); } catch {}
      }
      load(monday);
    }
    doLoad();
  }, [monday, load]);

  // ── Week navigation ────────────────────────────────────────────────────────

  function prevWeek() { setMonday((m) => addDays(m, -7)); }
  function nextWeek() { setMonday((m) => addDays(m,  7)); }

  function reload() { load(monday); }

  // ── Inline mark (✓/✗ on card) ─────────────────────────────────────────────

  async function handleInlineMark(lesson, happened) {
    try {
      const result = await mcpCall('mark_lesson', { lesson_id: lesson.id, happened });
      if (!happened && result?.freed_slot_matches?.length) {
        const names = result.freed_slot_matches.map((r) => r.student_name).join(', ');
        setFreedNotice(names);
      }
      reload();
    } catch (e) {
      alert('Hata: ' + e.message);
    }
  }

  // ── Group lessons by date ──────────────────────────────────────────────────

  const byDay = {};
  for (let i = 0; i < 7; i++) byDay[toISO(addDays(monday, i))] = [];
  lessons.forEach((l) => {
    const d = (l.scheduled_at ?? '').slice(0, 10);
    if (byDay[d]) byDay[d].push(l);
  });

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* ── Week nav header ─────────────────────────────────────────────── */}
      <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
        <button
          onClick={prevWeek}
          className="w-9 h-9 flex items-center justify-center rounded-xl bg-slate-800 active:opacity-60"
        >
          <svg className="w-5 h-5 text-slate-300" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <span className="text-sm font-medium text-slate-200">{formatWeekHeader(monday)}</span>

        <button
          onClick={nextWeek}
          className="w-9 h-9 flex items-center justify-center rounded-xl bg-slate-800 active:opacity-60"
        >
          <svg className="w-5 h-5 text-slate-300" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* ── Day list ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-3 space-y-5">
        {loading ? (
          <div className="flex justify-center pt-16">
            <div className="w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
          </div>
        ) : (
          Object.entries(byDay).map(([dateStr, dayLessons], idx) => {
            const isToday = dateStr === today;
            const displayDate = new Date(dateStr + 'T12:00:00').toLocaleDateString('tr-TR', {
              day: 'numeric', month: 'short',
            });

            return (
              <div key={dateStr}>
                {/* Day header */}
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className={`text-xs font-bold uppercase tracking-widest ${
                      isToday ? 'text-blue-400' : 'text-slate-600'
                    }`}
                  >
                    {DAY_SHORT[idx]}
                  </span>
                  <span className={`text-sm font-medium ${isToday ? 'text-blue-300' : 'text-slate-400'}`}>
                    {displayDate}
                  </span>
                  {isToday && (
                    <span className="text-[10px] font-bold text-blue-400 bg-blue-900/40 rounded-full px-2 py-0.5">
                      Bugün
                    </span>
                  )}

                  {/* Add lesson "+" button */}
                  <div className="flex-1" />
                  <button
                    onClick={() => setAddingLesson({ date: dateStr })}
                    className="w-7 h-7 flex items-center justify-center rounded-lg bg-slate-800 text-slate-500 text-lg font-light active:opacity-60 transition-opacity"
                    aria-label="Ders ekle"
                  >+</button>
                </div>

                {/* Lesson cards */}
                {dayLessons.length === 0 ? (
                  <p className="text-xs text-slate-700 pl-1">—</p>
                ) : (
                  <div className="space-y-1.5">
                    {dayLessons.map((lesson) => (
                      <LessonCard
                        key={lesson.id}
                        lesson={lesson}
                        color={getStudentColor(lesson.student_id, colorMap)}
                        onDetail={setDetail}
                        onMark={handleInlineMark}
                        onCancel={setCancelling}
                        onReschedule={setRescheduling}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* ── Modals ──────────────────────────────────────────────────────── */}

      {detail && (
        <DetailModal
          lesson={detail}
          color={getStudentColor(detail.student_id, colorMap)}
          onClose={() => setDetail(null)}
          onMarked={() => { setDetail(null); reload(); }}
        />
      )}

      {cancelling && (
        <CancelModal
          lesson={cancelling}
          onClose={() => setCancelling(null)}
          onCancelled={() => { setCancelling(null); reload(); }}
        />
      )}

      {rescheduling && (
        <RescheduleModal
          lesson={rescheduling}
          onClose={() => setRescheduling(null)}
          onRescheduled={() => { setRescheduling(null); reload(); }}
        />
      )}

      {addingLesson && students.length > 0 && (
        <AddLessonModal
          date={addingLesson.date}
          students={students}
          onClose={() => setAddingLesson(null)}
          onAdded={() => { setAddingLesson(null); reload(); }}
        />
      )}

      {/* ── Freed-slot toast ─────────────────────────────────────────────── */}
      {freedNotice && (
        <FreedSlotNotice
          names={freedNotice}
          onDismiss={() => setFreedNotice(null)}
        />
      )}
    </div>
  );
}
