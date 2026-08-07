/**
 * Pure helpers shared across WeeklyCalendarView and its subcomponents
 * (audit Q1 — extracted from WeeklyCalendarView.svelte).
 *
 * Colour palette, hashing, lesson labels, and compresenza formatting —
 * all deterministic and side-effect-free.
 */

/** Deterministic palette: colour by (teacher_name | subject | class)
 *  so siblings of the same cattedra share a hue across views. */
export const PALETTE = [
  { bg: '#dbeafe', bd: '#2563eb', fg: '#1e3a8a' }, // blue
  { bg: '#dcfce7', bd: '#16a34a', fg: '#14532d' }, // green
  { bg: '#fee2e2', bd: '#dc2626', fg: '#7f1d1d' }, // red
  { bg: '#fef3c7', bd: '#d97706', fg: '#78350f' }, // amber
  { bg: '#f3e8ff', bd: '#9333ea', fg: '#581c87' }, // violet
  { bg: '#ccfbf1', bd: '#0d9488', fg: '#134e4a' }, // teal
  { bg: '#ffe4e6', bd: '#e11d48', fg: '#881337' }, // rose
  { bg: '#e0e7ff', bd: '#4f46e5', fg: '#3730a3' }, // indigo
  { bg: '#fef9c3', bd: '#ca8a04', fg: '#713f12' }, // yellow
  { bg: '#cffafe', bd: '#0891b2', fg: '#155e75' }, // cyan
];

/** FNV-1a 32-bit hash (deterministic, no Math.random). */
export function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h;
}

/**
 * Pick a palette colour for a lesson based on the active filter.
 * @param {object} lesson
 * @param {{type:string|null, id:string|null}} filter_by
 * @returns {{bg:string, bd:string, fg:string}}
 */
export function colourFor(lesson, filter_by) {
  const t = filter_by?.type;
  let key;
  if (t === 'teacher') key = lesson.subject || lesson.class_name || '';
  else if (t === 'class') key = lesson.subject || lesson.teacher_name || '';
  else if (t === 'room')  key = lesson.class_name || lesson.subject || '';
  else key = (lesson.teacher_name || '') + '|' + (lesson.subject || '');
  return PALETTE[hashStr(key) % PALETTE.length];
}

/**
 * Single-line label for a lesson tooltip / aria.
 * @param {object} l
 * @param {{type:string|null, id:string|null}} filter_by
 * @returns {string}
 */
export function lessonLabel(l, filter_by) {
  const t = filter_by?.type;
  if (t === 'class')   return (l.subject || '') + ' - ' + (l.teacher_name || '');
  if (t === 'teacher') return (l.class_name || '') + ' - ' + (l.subject || '');
  if (t === 'room')    return (l.class_name || '') + ' / ' + (l.subject || '');
  return (l.class_name || '') + ' - ' + (l.subject || '');
}

/**
 * Two-part label so the SUBJECT is always prominent.
 * `primary` is bold, `secondary` muted below it, per view.
 * @param {object} l
 * @param {{type:string|null, id:string|null}} filter_by
 * @returns {{primary:string, secondary:string}}
 */
export function lessonParts(l, filter_by) {
  const t = filter_by?.type;
  const subj = l.subject || '';
  const cls = l.class_name || l.group_name || '';
  const tea = l.teacher_name || '';
  if (t === 'teacher') return { primary: subj, secondary: cls };
  if (t === 'room')    return { primary: cls, secondary: subj };
  if (t === 'class')   return { primary: subj, secondary: tea };
  return { primary: cls, secondary: subj };
}

/** @param {object} l @returns {boolean} */
export function isSupportLesson(l) {
  return (l.subject || '').toLowerCase() === 'sostegno';
}

/**
 * The "main" lesson of a shared slot: the ordinary (non-sostegno) subject.
 * @param {object[]} lst
 * @returns {object}
 */
export function primaryLesson(lst) {
  return lst.find((l) => !isSupportLesson(l)) || lst[0];
}

/**
 * Format one row of the compresenza popup.
 * "subject — teacher · class @ room", dropping empty parts.
 * @param {object} l
 * @returns {{head:string, who:string, room:string}}
 */
export function compresenzaRow(l) {
  const bits = [];
  if (l.subject) bits.push(l.subject);
  const who = [l.teacher_name, (l.class_name || l.group_name)]
    .filter(Boolean).join(' · ');
  return { head: bits.join(''), who, room: l.classroom_name || '' };
}
