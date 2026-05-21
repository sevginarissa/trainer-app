// ─── Day names ────────────────────────────────────────────────────────────────

export const TR_DAYS = {
  0: 'Pazartesi',
  1: 'Salı',
  2: 'Çarşamba',
  3: 'Perşembe',
  4: 'Cuma',
  5: 'Cumartesi',
  6: 'Pazar',
};

// ─── Student colours ──────────────────────────────────────────────────────────
// Assigned by stable student ID order; stored in localStorage as { [id]: colorIndex }

export const STUDENT_PALETTE = [
  { bg: 'bg-blue-500',   hex: '#3b82f6' },
  { bg: 'bg-purple-500', hex: '#a855f7' },
  { bg: 'bg-emerald-500',hex: '#10b981' },
  { bg: 'bg-amber-500',  hex: '#f59e0b' },
  { bg: 'bg-rose-500',   hex: '#f43f5e' },
  { bg: 'bg-cyan-500',   hex: '#06b6d4' },
];

export function getStudentColor(studentId, colorMap) {
  const idx = colorMap[studentId] ?? 0;
  return STUDENT_PALETTE[idx % STUDENT_PALETTE.length];
}

/** Build / persist a stable studentId→colorIndex map in localStorage. */
export function buildColorMap(students) {
  const stored = JSON.parse(localStorage.getItem('studentColorMap') || '{}');
  let changed = false;
  students.forEach((s, i) => {
    if (stored[s.id] === undefined) {
      stored[s.id] = i % STUDENT_PALETTE.length;
      changed = true;
    }
  });
  if (changed) localStorage.setItem('studentColorMap', JSON.stringify(stored));
  return stored;
}

// ─── Claude tool definitions ──────────────────────────────────────────────────

export const CLAUDE_TOOLS = [
  {
    name: 'get_students',
    description: 'Tüm aktif öğrencileri ve haftalık ders programlarını listeler.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'get_pending_lessons',
    description: 'Belirtilen tarihten itibaren onaylanmamış (gerçekleşmedi/gelmedi işareti olmayan) dersleri getirir.',
    input_schema: {
      type: 'object',
      properties: {
        since_datetime: {
          type: 'string',
          description: "ISO datetime alt sınırı, ör. '2026-05-01T00:00:00'",
        },
      },
      required: ['since_datetime'],
    },
  },
  {
    name: 'get_pending_overrides',
    description: 'Henüz uygulanmamış program değişikliği taleplerini getirir.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'get_todays_lessons',
    description: "Bugünkü tüm dersleri öğrenci adı ve onay durumuyla getirir.",
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'mark_lesson',
    description: "Bir dersin gerçekleşip gerçekleşmediğini işaretler.",
    input_schema: {
      type: 'object',
      properties: {
        lesson_id: { type: 'integer', description: 'Ders ID' },
        happened: { type: 'boolean', description: 'true → gerçekleşti, false → gelmedi/iptal' },
      },
      required: ['lesson_id', 'happened'],
    },
  },
  {
    name: 'add_credit',
    description: 'Öğrenci hesabına kredi ekler (ön ödeme veya telafi dersi).',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
        amount: { type: 'number', description: 'Kredi miktarı (ders sayısı)' },
        reason: { type: 'string', description: 'Açıklama' },
      },
      required: ['student_id', 'amount'],
    },
  },
  {
    name: 'apply_payment',
    description: 'Seçilen dersleri ödenmiş olarak işaretler ve ödeme kaydı oluşturur.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
        lesson_ids: {
          type: 'array',
          items: { type: 'integer' },
          description: 'Ödenecek ders ID listesi',
        },
      },
      required: ['student_id', 'lesson_ids'],
    },
  },
  {
    name: 'update_schedule',
    description: 'Öğrenci programını kalıcı veya tek seferlik olarak değiştirir.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
        day: {
          type: 'integer',
          description: '0=Pazartesi … 6=Pazar',
        },
        time: { type: 'string', description: 'Ders saati HH:MM' },
        override_week: {
          type: 'string',
          description:
            "Tek seferlik değişiklik için haftanın Pazartesi tarihi (ISO, ör. '2026-05-25'). Kalıcı değişiklik için boş bırakın.",
        },
      },
      required: ['student_id', 'day', 'time'],
    },
  },
  {
    name: 'generate_balance',
    description: 'Öğrencinin kredi/ödeme bakiyesini ve ders özetini hesaplar.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
      },
      required: ['student_id'],
    },
  },
  {
    name: 'add_pending_request',
    description: 'Bir öğrencinin belirli bir tarihte (ve isteğe bağlı saatte) ders istediğini kaydeder.',
    input_schema: {
      type: 'object',
      properties: {
        student_id:     { type: 'integer', description: 'Öğrenci ID' },
        requested_date: { type: 'string',  description: 'ISO tarih YYYY-MM-DD' },
        requested_time: { type: 'string',  description: 'HH:MM — flexible_time true ise boş bırakın' },
        flexible_time:  { type: 'boolean', description: 'true = o gün herhangi bir saat uyar' },
        notes:          { type: 'string' },
      },
      required: ['student_id', 'requested_date'],
    },
  },
  {
    name: 'check_pending_requests',
    description: 'Yeni boşalan bir slota uyan bekleyen talepleri getirir.',
    input_schema: {
      type: 'object',
      properties: {
        freed_date: { type: 'string', description: 'Boşalan slotun ISO tarihi YYYY-MM-DD' },
        freed_time: { type: 'string', description: 'Boşalan slotun saati HH:MM' },
      },
      required: ['freed_date'],
    },
  },
  {
    name: 'get_pending_requests',
    description: 'Tüm öğrencilerin yerine getirilmemiş ders talepleri listesini döner.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'get_week_lessons',
    description: 'Belirtilen tarihi içeren haftanın tüm derslerini (gerçekleşen, gelmedi, bekleyen) getirir.',
    input_schema: {
      type: 'object',
      properties: {
        week_date: {
          type: 'string',
          description: 'Haftanın herhangi bir gününün ISO tarihi (YYYY-MM-DD)',
        },
      },
      required: ['week_date'],
    },
  },
  {
    name: 'add_lesson',
    description: 'Öğrenci için tek seferlik bir ders ekler.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
        scheduled_datetime: {
          type: 'string',
          description: "Ders tarihi ve saati ISO formatında, ör. '2026-05-28T09:00:00'",
        },
      },
      required: ['student_id', 'scheduled_datetime'],
    },
  },
  {
    name: 'add_student',
    description: 'Yeni öğrenci oluşturur ve isteğe bağlı haftalık programını belirler.',
    input_schema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Öğrenci adı' },
        schedule: {
          type: 'object',
          description: 'Haftalık program: {"Mon": "09:00", "Wed": "09:00"} — Mon/Tue/Wed/Thu/Fri/Sat/Sun',
          additionalProperties: { type: 'string' },
        },
      },
      required: ['name'],
    },
  },
  {
    name: 'update_student',
    description: 'Öğrencinin adını değiştirir.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
        name:       { type: 'string',  description: 'Yeni ad' },
      },
      required: ['student_id', 'name'],
    },
  },
  {
    name: 'deactivate_student',
    description: 'Öğrenciyi pasife alır (soft delete). Ders geçmişi korunur.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
      },
      required: ['student_id'],
    },
  },
  {
    name: 'reactivate_student',
    description: 'Pasif öğrenciyi yeniden aktif yapar.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
      },
      required: ['student_id'],
    },
  },
  {
    name: 'cancel_lesson',
    description: 'Bir dersi siler. Boşalan slot için bekleyen talepleri döner.',
    input_schema: {
      type: 'object',
      properties: {
        lesson_id: { type: 'integer', description: 'İptal edilecek ders ID' },
      },
      required: ['lesson_id'],
    },
  },
  {
    name: 'reschedule_lesson',
    description: 'Bir dersi yeni bir tarih/saate taşır ve onay durumunu sıfırlar.',
    input_schema: {
      type: 'object',
      properties: {
        lesson_id:    { type: 'integer', description: 'Ders ID' },
        new_datetime: { type: 'string',  description: "Yeni tarih ve saat ISO formatında, ör. '2026-05-28T09:00:00'" },
      },
      required: ['lesson_id', 'new_datetime'],
    },
  },
  {
    name: 'generate_upcoming_lessons',
    description: 'Tekrar eden programlardan önümüzdeki N hafta için ders satırlarını otomatik oluşturur.',
    input_schema: {
      type: 'object',
      properties: {
        weeks_ahead: { type: 'integer', description: 'Kaç hafta ileri oluşturulacak (varsayılan 8)' },
      },
    },
  },
  {
    name: 'remove_schedule_day',
    description: 'Öğrencinin belirli bir gündeki tekrar eden program slotunu deaktif eder.',
    input_schema: {
      type: 'object',
      properties: {
        student_id: { type: 'integer', description: 'Öğrenci ID' },
        day:        { type: 'integer', description: '0=Pazartesi … 6=Pazar' },
      },
      required: ['student_id', 'day'],
    },
  },
  {
    name: 'delete_pending_request',
    description: 'Bekleyen ders talebini kalıcı olarak siler.',
    input_schema: {
      type: 'object',
      properties: {
        request_id: { type: 'integer', description: 'Talep ID' },
      },
      required: ['request_id'],
    },
  },
  {
    name: 'update_pending_request',
    description: 'Bekleyen ders talebinin tarih, saat, esneklik bayrağı veya notlarını günceller.',
    input_schema: {
      type: 'object',
      properties: {
        request_id:     { type: 'integer', description: 'Talep ID' },
        requested_date: { type: 'string',  description: 'ISO tarih YYYY-MM-DD' },
        requested_time: { type: 'string',  description: 'HH:MM — flexible_time true ise boş bırakın' },
        flexible_time:  { type: 'boolean' },
        notes:          { type: 'string' },
      },
      required: ['request_id', 'requested_date'],
    },
  },
];

// ─── Tool minifier ────────────────────────────────────────────────────────────
// Strips property-level `description` fields from input_schema to reduce token
// usage in every Claude API call.  Tool-level `description` is preserved because
// Claude needs it to choose the right tool.

export function minifyTools(tools) {
  return tools.map((tool) => {
    const props = tool.input_schema?.properties;
    if (!props || Object.keys(props).length === 0) return tool;
    const minifiedProps = {};
    for (const [key, val] of Object.entries(props)) {
      const { description: _d, ...rest } = val;
      minifiedProps[key] = rest;
    }
    return {
      ...tool,
      input_schema: { ...tool.input_schema, properties: minifiedProps },
    };
  });
}

// System prompt lives in systemPrompt.js
