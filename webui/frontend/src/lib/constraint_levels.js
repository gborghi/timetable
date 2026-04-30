// Centralised constraint-level taxonomy.
//
// The same 5 levels (HARD / SOFT / PREFERITO / ENFORCED / ALLOWED) are
// surfaced in 4-5 different files. This module is the single source of
// truth. Used by:
//   * AvailabilityMatrix.svelte
//   * ClassroomGrid.svelte
//   * LogicalUnavailabilitiesPanel.svelte
//   * BulkApplyModal.svelte
//   * /curricula, /constraints pages
//   * /monitor (cell colouring)

export const LEVELS = [
  'allowed',
  'soft',
  'preferred',
  'hard',
  'forbidden',
  'enforced',
];

// 4 kinds for logical constraints (no allowed/forbidden -- those are
// only meaningful for matrix cells / classroom prefs).
export const LOGICAL_KINDS = ['hard', 'soft', 'preferred', 'enforced'];

// Mapping level -> human label (italian)
export const LEVEL_LABEL = {
  allowed:   'ALLOWED',
  soft:      'SOFT',
  preferred: 'PREFERITO',
  hard:      'HARD',
  forbidden: 'FORBIDDEN',
  enforced:  'ENFORCED',
};

// Mapping level -> Tailwind classes that produce the canonical pill.
// Reads tokens from `tailwind.config.js::theme.extend.colors.c.*`.
export const LEVEL_PILL_CLASS = {
  allowed:   'pill-c-allowed',
  soft:      'pill-c-soft',
  preferred: 'pill-c-preferred',
  hard:      'pill-c-hard',
  forbidden: 'pill-c-forbidden',
  enforced:  'pill-c-enforced',
};

// Mapping level -> bg/border classes for cells (e.g. AvailabilityMatrix).
export const LEVEL_CELL_CLASS = {
  allowed:   'bg-c-allow-bg border-c-allow-border text-c-allow-fg',
  soft:      'bg-c-soft-bg  border-c-soft-border  text-c-soft-fg',
  preferred: 'bg-c-pref-bg  border-c-pref-border  text-c-pref-fg',
  hard:      'bg-c-hard-bg  border-c-hard-border  text-c-hard-fg',
  forbidden: 'bg-c-hard-bg  border-c-hard-border  text-c-hard-fg',
  enforced:  'bg-c-enf-bg   border-c-enf-border   text-c-enf-fg',
};

// Default penalties when the user hasn't entered a number yet.
export const DEFAULT_PENALTY = {
  hard:      0,
  soft:      100,
  preferred: -100,
  enforced:  0,
  allowed:   0,
  forbidden: 0,
};

/**
 * Given a logical-rule row from the backend, classify it as one of the
 * 4 LOGICAL_KINDS. Backend now sends `kind` explicitly; this helper
 * also handles legacy rows (kind missing) by falling back to is_hard
 * + sign(soft_penalty).
 */
export function kindFromRule(r) {
  if (!r) return 'soft';
  if (r.kind && LOGICAL_KINDS.includes(r.kind)) return r.kind;
  if (r.is_hard) return 'hard';
  if (Number(r.soft_penalty) < 0) return 'preferred';
  return 'soft';
}

/**
 * Pill class for a level value (string).
 */
export function levelPill(level) {
  return LEVEL_PILL_CLASS[level] || 'pill';
}

/**
 * Human label for a level value.
 */
export function levelLabel(level) {
  return LEVEL_LABEL[level] || (level || '?').toUpperCase();
}

/**
 * Cell class for a state value (used by matrices). Returns Tailwind
 * background+border+text classes.
 */
export function levelCellClass(level) {
  return LEVEL_CELL_CLASS[level] || '';
}

/**
 * Convert a UI kind + penalty (always positive value chosen by the user)
 * into the backend payload shape used by /api/.../logical-unavailabilities
 * etc. Sign-clamps the penalty for SOFT/PREFERITO; sets is_hard for
 * HARD/ENFORCED.
 */
export function payloadFromKind(kind, expr, penalty, extra = {}) {
  const base = { expression: expr, kind, ...extra };
  const p = Number(penalty);
  if (kind === 'hard' || kind === 'enforced') {
    return { ...base, is_hard: true, soft_penalty: 100 };
  }
  if (kind === 'soft') {
    return { ...base, is_hard: false,
             soft_penalty: Math.abs(Number.isFinite(p) ? p : 100) };
  }
  // preferred
  return { ...base, is_hard: false,
           soft_penalty: -Math.abs(Number.isFinite(p) ? p : 100) };
}

/**
 * Given a level + a numeric input by the user, sign-clamp the value to
 * the level's expected sign. Used by inputs in matrices and pickers.
 */
export function clampPenalty(level, value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return DEFAULT_PENALTY[level] ?? 0;
  if (level === 'soft' && v < 0) return Math.abs(v);
  if (level === 'preferred' && v > 0) return -v;
  return v;
}
