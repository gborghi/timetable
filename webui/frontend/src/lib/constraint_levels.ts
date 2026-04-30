// Centralised constraint-level taxonomy.
//
// The same 5 levels (HARD / SOFT / PREFERITO / ENFORCED / ALLOWED) are
// surfaced in 4-5 different files. This module is the single source of
// truth.

import type { ConstraintLevel, LogicalKind } from "./types";

export const LEVELS: readonly ConstraintLevel[] = [
  "allowed",
  "soft",
  "preferred",
  "hard",
  "forbidden",
  "enforced",
];

/** 4 kinds for logical constraints (no allowed / forbidden). */
export const LOGICAL_KINDS: readonly LogicalKind[] = [
  "hard",
  "soft",
  "preferred",
  "enforced",
];

export const LEVEL_LABEL: Record<ConstraintLevel, string> = {
  allowed: "ALLOWED",
  soft: "SOFT",
  preferred: "PREFERITO",
  hard: "HARD",
  forbidden: "FORBIDDEN",
  enforced: "ENFORCED",
};

export const LEVEL_PILL_CLASS: Record<ConstraintLevel, string> = {
  allowed: "pill-c-allowed",
  soft: "pill-c-soft",
  preferred: "pill-c-preferred",
  hard: "pill-c-hard",
  forbidden: "pill-c-forbidden",
  enforced: "pill-c-enforced",
};

export const LEVEL_CELL_CLASS: Record<ConstraintLevel, string> = {
  allowed: "bg-c-allow-bg border-c-allow-border text-c-allow-fg",
  soft: "bg-c-soft-bg  border-c-soft-border  text-c-soft-fg",
  preferred: "bg-c-pref-bg  border-c-pref-border  text-c-pref-fg",
  hard: "bg-c-hard-bg  border-c-hard-border  text-c-hard-fg",
  forbidden: "bg-c-hard-bg  border-c-hard-border  text-c-hard-fg",
  enforced: "bg-c-enf-bg   border-c-enf-border   text-c-enf-fg",
};

export const DEFAULT_PENALTY: Record<ConstraintLevel, number> = {
  hard: 0,
  soft: 100,
  preferred: -100,
  enforced: 0,
  allowed: 0,
  forbidden: 0,
};

/**
 * Logical-rule shape (loose -- backend types still vary).
 */
export interface LogicalRule {
  kind?: string;
  is_hard?: boolean;
  soft_penalty?: number;
  [k: string]: unknown;
}

/**
 * Given a logical-rule row from the backend, classify it as one of the
 * 4 LOGICAL_KINDS. Backend now sends `kind` explicitly; this helper
 * also handles legacy rows (kind missing) by falling back to is_hard
 * + sign(soft_penalty).
 */
export function kindFromRule(r: LogicalRule | null | undefined): LogicalKind {
  if (!r) return "soft";
  if (r.kind && (LOGICAL_KINDS as readonly string[]).includes(r.kind)) {
    return r.kind as LogicalKind;
  }
  if (r.is_hard) return "hard";
  if (Number(r.soft_penalty) < 0) return "preferred";
  return "soft";
}

export function levelPill(level: ConstraintLevel | string): string {
  return LEVEL_PILL_CLASS[level as ConstraintLevel] ?? "pill";
}

export function levelLabel(level: ConstraintLevel | string | null | undefined): string {
  if (!level) return "?";
  return (
    LEVEL_LABEL[level as ConstraintLevel] ??
    String(level).toUpperCase()
  );
}

export function levelCellClass(level: ConstraintLevel | string): string {
  return LEVEL_CELL_CLASS[level as ConstraintLevel] ?? "";
}

/**
 * Convert a UI kind + penalty (always positive value chosen by the user)
 * into the backend payload shape used by /api/.../logical-unavailabilities
 * etc. Sign-clamps the penalty for SOFT/PREFERITO; sets is_hard for
 * HARD/ENFORCED.
 */
export function payloadFromKind(
  kind: LogicalKind,
  expr: string,
  penalty: number | string,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  const base = { expression: expr, kind, ...extra };
  const p = Number(penalty);
  if (kind === "hard" || kind === "enforced") {
    return { ...base, is_hard: true, soft_penalty: 100 };
  }
  if (kind === "soft") {
    return {
      ...base,
      is_hard: false,
      soft_penalty: Math.abs(Number.isFinite(p) ? p : 100),
    };
  }
  // preferred
  return {
    ...base,
    is_hard: false,
    soft_penalty: -Math.abs(Number.isFinite(p) ? p : 100),
  };
}

/**
 * Given a level + a numeric input by the user, sign-clamp the value to
 * the level's expected sign. Used by inputs in matrices and pickers.
 */
export function clampPenalty(
  level: ConstraintLevel,
  value: number | string | null | undefined,
): number {
  const v = Number(value);
  if (!Number.isFinite(v)) return DEFAULT_PENALTY[level] ?? 0;
  if (level === "soft" && v < 0) return Math.abs(v);
  if (level === "preferred" && v > 0) return -v;
  return v;
}
