// ─── Config ──────────────────────────────────────────────────────────────────
const BASE = window.location.origin + '/api';

// ─── API helpers ─────────────────────────────────────────────────────────────
async function mcpCall(tool, args = {}) {
  const res = await fetch(`${BASE}/mcp/${tool}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ arguments: args }),
  });
  if (!res.ok) throw new Error(`${tool} failed: ${await res.text()}`);
  return (await res.json()).result;
}

async function chatRun(messages, system = '') {
  const res = await fetch(`${BASE}/chat/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, system }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`chat/run ${res.status}: ${detail}`);
  }
  return (await res.json()).response;
}

// ─── Navigation ───────────────────────────────────────────────────────────────
const TABS = ['chat', 'calendar', 'students', 'balance'];
let activeTab = 'chat';

function showTab(tab) {
  TABS.forEach(t => {
    document.getElementById(`panel-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`nav-${t}`).classList.toggle('active', t === tab);
  });
  activeTab = tab;
  if (tab === 'calendar') renderCalendar();
  if (tab === 'students') loadStudents();
  if (tab === 'balance')  loadBalance();
}

// ─── Chat ─────────────────────────────────────────────────────────────────────
let chatMessages = [];

function buildSystemPrompt() {
  const now = new Date().toLocaleString('tr-TR');
  return `Sen Türkçe konuşan bir kişisel antrenörün AI asistanısın.
Şu an: ${now}

Ders kayıtlarını, ödemeleri ve programları yönetebilirsin.
Araçları gerektiğinde kullan. Özlü yanıtlar ver.`;
}

function renderChatMessages() {
  const el = document.getElementById('chat-messages');
  el.innerHTML = chatMessages.map(m => {
    const cls = m.role === 'user' ? 'msg-user' : (m.isError ? 'msg-error' : 'msg-ai');
    const text = m.content.replace(/\n/g, '<br>');
    return `<div class="msg ${cls}">${text}</div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  chatMessages.push({ role: 'user', content: text });
  renderChatMessages();

  const spinner = document.getElementById('chat-spinner');
  spinner.classList.remove('hidden');

  try {
    // Send only the last 20 turns to keep context manageable
    const msgs = chatMessages.slice(-20).map(m => ({ role: m.role, content: m.content }));
    const reply = await chatRun(msgs, buildSystemPrompt());
    chatMessages.push({ role: 'assistant', content: reply });
  } catch (err) {
    const isRate = err.message.includes('429') || err.message.toLowerCase().includes('rate_limit');
    chatMessages.push({
      role: 'assistant',
      content: isRate
        ? 'Çok fazla istek gönderildi, lütfen birkaç saniye bekleyin ve tekrar deneyin.'
        : `Hata: ${err.message}`,
      isError: true,
    });
  } finally {
    spinner.classList.add('hidden');
    renderChatMessages();
  }
}

// ─── Calendar ─────────────────────────────────────────────────────────────────
const TR_DAYS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
const TR_MONTHS = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];

let calMonday = getMondayOf(new Date());

function getMondayOf(d) {
  const date = new Date(d);
  const day  = date.getDay(); // 0=Sun
  const diff = (day === 0 ? -6 : 1 - day);
  date.setDate(date.getDate() + diff);
  date.setHours(0, 0, 0, 0);
  return date;
}

function calPrev() { calMonday = new Date(calMonday.getTime() - 7 * 86400000); renderCalendar(); }
function calNext() { calMonday = new Date(calMonday.getTime() + 7 * 86400000); renderCalendar(); }

function lessonStatusClass(l) {
  if (l.late_cancel) return 'lesson-late-cancel';
  if (l.happened === 1) return 'lesson-happened';
  if (l.happened === 0) return 'lesson-cancelled';
  return 'lesson-null';
}

function lessonStatusIcon(l) {
  if (l.late_cancel) return '⚡';
  if (l.happened === 1) return '✓';
  if (l.happened === 0) return '✗';
  return '·';
}

async function markLesson(id, status) {
  try {
    await mcpCall('mark_lesson', { lesson_id: id, status });
    renderCalendar();
  } catch (e) {
    alert('Hata: ' + e.message);
  }
}

async function renderCalendar() {
  const monday = calMonday;
  const sunday = new Date(monday.getTime() + 6 * 86400000);

  // Title
  const fmt = d => `${d.getDate()} ${TR_MONTHS[d.getMonth()]}`;
  document.getElementById('cal-title').textContent =
    `${fmt(monday)} – ${fmt(sunday)} ${sunday.getFullYear()}`;

  const body = document.getElementById('cal-body');
  body.innerHTML = '<div class="text-center py-4"><span class="spinner"></span></div>';

  try {
    const weekDate = monday.toISOString().slice(0, 10);
    const lessons  = await mcpCall('get_week_lessons', { week_date: weekDate });

    // Group by day index (0=Mon)
    const byDay = Array.from({ length: 7 }, () => []);
    for (const l of lessons) {
      const d = new Date(l.scheduled_at);
      const dow = (d.getDay() + 6) % 7; // convert Sun=0 → Mon=0
      byDay[dow].push(l);
    }

    body.innerHTML = byDay.map((dayLessons, i) => {
      const d = new Date(monday.getTime() + i * 86400000);
      const isToday = d.toDateString() === new Date().toDateString();
      const dayLabel = `${TR_DAYS[i]} ${d.getDate()}`;

      const items = dayLessons.length === 0
        ? '<p class="text-xs text-slate-600 py-1">—</p>'
        : dayLessons.map(l => {
            const time = l.scheduled_at.slice(11, 16);
            const sc   = lessonStatusClass(l);
            const icon = lessonStatusIcon(l);
            return `
              <div class="lesson-chip ${sc}">
                <span>${time} ${l.student_name}</span>
                <div class="flex gap-1 items-center">
                  <span class="text-xs opacity-60">${icon}</span>
                  <select onchange="markLesson(${l.id}, this.value)"
                    class="text-xs bg-transparent border border-slate-700 rounded px-1 py-0.5 cursor-pointer">
                    <option value="">─</option>
                    <option value="happened" ${l.happened === 1 && !l.late_cancel ? 'selected' : ''}>✓ Gerçekleşti</option>
                    <option value="late_cancel" ${l.late_cancel ? 'selected' : ''}>⚡ Geç iptal</option>
                    <option value="cancelled" ${l.happened === 0 && !l.late_cancel ? 'selected' : ''}>✗ İptal</option>
                  </select>
                </div>
              </div>`;
          }).join('');

      return `
        <div class="card mb-2 ${isToday ? 'ring-1 ring-indigo-500' : ''}">
          <p class="text-xs font-semibold mb-2 ${isToday ? 'text-indigo-400' : 'text-slate-400'}">${dayLabel}</p>
          ${items}
        </div>`;
    }).join('');
  } catch (e) {
    body.innerHTML = `<p class="text-red-400 p-4 text-sm">Hata: ${e.message}</p>`;
  }
}

// ─── Students ─────────────────────────────────────────────────────────────────
const DOW_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

async function loadStudents() {
  const body = document.getElementById('students-body');
  const spin = document.getElementById('students-spinner');
  body.innerHTML = '';
  spin.classList.remove('hidden');
  try {
    const students = await mcpCall('get_students', {});
    body.innerHTML = students.map(s => {
      const sched = (s.schedules || [])
        .map(sc => `${DOW_TR[sc.day_of_week]} ${sc.lesson_time}`)
        .join(', ') || '—';
      const price = s.price_per_lesson > 0 ? `${s.price_per_lesson} ₺/ders` : '—';
      return `
        <div class="card">
          <div class="flex justify-between items-start">
            <div>
              <p class="font-semibold">${s.name}</p>
              <p class="text-xs text-slate-400 mt-0.5">${sched}</p>
            </div>
            <span class="text-xs text-slate-500">${price}</span>
          </div>
        </div>`;
    }).join('') || '<p class="p-4 text-slate-500 text-sm">Öğrenci yok.</p>';
  } catch (e) {
    body.innerHTML = `<p class="text-red-400 p-4 text-sm">Hata: ${e.message}</p>`;
  } finally {
    spin.classList.add('hidden');
  }
}

// ─── Balance ──────────────────────────────────────────────────────────────────
async function loadBalance() {
  const body = document.getElementById('balance-body');
  body.innerHTML = '<div class="text-center py-4"><span class="spinner"></span></div>';
  try {
    const students = await mcpCall('get_students', {});
    const balances = await Promise.all(
      students.map(s => mcpCall('generate_balance', { student_id: s.id }))
    );

    body.innerHTML = balances.map(b => {
      const statusColor = b.balance > 0 ? 'text-green-400' : b.balance < 0 ? 'text-red-400' : 'text-slate-400';
      const statusLabel = b.balance > 0 ? `+${b.balance} ders kredisi` : b.balance < 0 ? `${Math.abs(b.balance)} ders borçlu` : 'Hesap dengede';
      const price = b.price_per_lesson > 0 ? `${b.price_per_lesson} ₺/ders` : '—';
      return `
        <div class="card">
          <div class="flex justify-between items-baseline mb-2">
            <p class="font-semibold">${b.student_name}</p>
            <span class="text-xs text-slate-500">${price}</span>
          </div>
          <p class="text-sm ${statusColor} font-medium">${statusLabel}</p>
          <div class="mt-2 grid grid-cols-3 gap-2 text-center">
            <div class="bg-slate-900 rounded-lg p-2">
              <p class="text-lg font-bold text-slate-200">${b.credits_total}</p>
              <p class="text-xs text-slate-500">Kredi</p>
            </div>
            <div class="bg-slate-900 rounded-lg p-2">
              <p class="text-lg font-bold text-slate-200">${b.sessions_occurred}</p>
              <p class="text-xs text-slate-500">Gerçekleşen</p>
            </div>
            <div class="bg-slate-900 rounded-lg p-2">
              <p class="text-lg font-bold text-slate-200">${b.lessons?.confirmed_unpaid ?? 0}</p>
              <p class="text-xs text-slate-500">Ödenmedi</p>
            </div>
          </div>
          ${b.lessons?.late_cancel > 0 ? `<p class="text-xs text-orange-400 mt-2">⚡ ${b.lessons.late_cancel} geç iptal</p>` : ''}
        </div>`;
    }).join('') || '<p class="p-4 text-slate-500 text-sm">Öğrenci yok.</p>';
  } catch (e) {
    body.innerHTML = `<p class="text-red-400 p-4 text-sm">Hata: ${e.message}</p>`;
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
(async function init() {
  // Pre-populate upcoming lessons silently
  try { await mcpCall('generate_upcoming_lessons', { weeks_ahead: 8 }); } catch {}
  renderChatMessages();
})();
