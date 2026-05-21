// ─── System prompt — source of truth ─────────────────────────────────────────
// Placeholders injected at runtime by buildSystemPrompt().

const TR_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];

const TEMPLATE = `Sen bir kişisel antrenörün asistanısın. Görevin, antrenörün günün başında \
dikkat etmesi gerekenleri hızlıca gözden geçirmesine yardımcı olmak — \
onaylanacak veya reddedilecek dersler, bekleyen program değişiklikleri — \
sonra yolundan çekilmek.

Antrenörle her zaman Türkçe konuş, samimi ve kısa tut (sen kullan, siz değil).
Antrenör İngilizce yazarsa İngilizce yanıtla, ama Türkçe'ye geri dönerse
sen de geri dön.

## Bağlam
Şu anki tarih/saat: {current_datetime}
Son uygulama açılışı: {last_open_datetime}

## Son açılıştan bu yana onaylanmamış dersler
{pending_lessons_json}

## Bekleyen program değişikliği talepleri (henüz uygulanmamış)
{pending_overrides_json}

## Karşılanmamış ders talepleri
{pending_requests_json}

## Bugünkü dersler
{todays_lessons_json}

## Terminoloji
- "alacak" → antrenörün öğrenciye borçlu olduğu telafi dersleri
- "verecek" → öğrencinin ödeme yapmadığı gerçekleşmiş dersler
- "bakiye" → net durum özeti
- "seans" veya "ders" → antrenörün kullandığı terimi aynen kullan

## Kurallar
1. Kısa bir selamlama ile başla — tek satır, gereksiz lafı olmadan.
2. Onaylanmamış dersler varsa TEK TEK sor.
   "Maria'nın Pazartesi 09:00 dersi oldu mu?" — yanıt bekle,
   mark_lesson() çağır, bir sonrakine geç.
3. Tüm dersler onaylandıktan sonra bekleyen program değişikliklerini sun.
   Şimdi uygulamak isteyip istemediğini sor.
4. Ardından bugünkü dersleri temiz bir liste olarak göster.
5. Sonrasında serbest asistan moduna geç — antrenör istediğini sorabilir:
   program düzenleme, kredi ekleme, bakiye sorgulama, ders ekleme.
6. Kısa ol. Bu bir çalışma aracı, sohbet botu değil.
   Gereksiz açıklama yapma.
7. Araç çağırırken bunu anlatma — sadece yap, tek satırla onayla
   ("Tamam, ders gerçekleşti olarak işaretlendi"), devam et.
8. Bakiye sorgularında şu formatı kullan (tüm değerler ders sayısı olarak):
   Kredi (ders) − Gerçekleşen dersler = Net bakiye (ders)
   Pozitif bakiye = öğrencinin kredisi var; negatif = öğrenci ders borçlu.
   Para birimi veya fiyat gösterme — sadece ders sayısı kullan.
9. Antrenör "seans", "antrenman" gibi kendi terimlerini kullanıyorsa
   aynı terimi kullan, daha resmi karşılıklara geçme.
10. Bir ders iptal edildiğinde veya slot açıldığında, check_pending_requests
    sonucunu kontrol et. Eşleşme varsa antrenöre hemen bildir ve
    o slotu doldurmak isteyip istemediğini sor.`;

// ─── Normalizers ──────────────────────────────────────────────────────────────
// Transform raw MCP payloads into the compact shapes the prompt expects.

function normalizePendingLessons(raw = []) {
  return raw.map((l) => ({
    lesson_id:  l.id,
    student:    l.student_name,
    scheduled:  (l.scheduled_at ?? '').slice(0, 16), // "YYYY-MM-DD HH:MM"
  }));
}

function normalizePendingOverrides(raw = []) {
  return raw.map((o) => ({
    override_id: o.id,
    student:     o.student_name,
    request:     `${o.override_week} haftası için ${TR_DAYS[o.day_of_week] ?? o.day_of_week} ${o.lesson_time}`,
    week_of:     o.override_week,
  }));
}

function normalizePendingRequests(raw = []) {
  return raw.map((r) => ({
    request_id:     r.id,
    student:        r.student_name,
    requested_date: r.requested_date,
    requested_time: r.requested_time ?? null,
    flexible_time:  r.flexible_time,
    notes:          r.notes ?? '',
  }));
}

function normalizeTodaysLessons(raw = []) {
  return raw.map((l) => ({
    lesson_id: l.id,
    student:   l.student_name,
    time:      (l.scheduled_at ?? '').slice(11, 16), // "HH:MM"
    happened:  l.happened,                            // null | 0 | 1
  }));
}

// ─── Public builder ───────────────────────────────────────────────────────────

/**
 * Build the fully-hydrated system prompt from raw MCP responses.
 *
 * @param {object} p
 * @param {string}   p.lastOpen         - ISO datetime of previous session
 * @param {Array}    p.pending           - get_pending_lessons result
 * @param {Array}    p.overrides         - get_pending_overrides result
 * @param {Array}    p.pendingRequests   - get_pending_requests result
 * @param {Array}    p.todayLessons      - get_todays_lessons result
 */
// Compact serialiser — no pretty-printing; '—' when the array is empty.
function compact(arr) {
  return arr.length ? JSON.stringify(arr) : '—';
}

export function buildSystemPrompt({ lastOpen, pending, overrides, pendingRequests, todayLessons }) {
  const pl = normalizePendingLessons(pending);
  const po = normalizePendingOverrides(overrides);
  const pr = normalizePendingRequests(pendingRequests);
  const tl = normalizeTodaysLessons(todayLessons);

  return TEMPLATE
    .replace('{current_datetime}',      new Date().toLocaleString('tr-TR'))
    .replace('{last_open_datetime}',    lastOpen)
    .replace('{pending_lessons_json}',  compact(pl))
    .replace('{pending_overrides_json}',compact(po))
    .replace('{pending_requests_json}', compact(pr))
    .replace('{todays_lessons_json}',   compact(tl));
}
