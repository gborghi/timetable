// Human-readable rendering of the ad-hoc `metrics` dict attached to runs
// and solutions. The backend keys are engine-internal; here we label the
// known ones in Italian and format values sensibly, falling back to a
// clean "Chiave: valore" for the rest — the UI must never show a user the
// raw JSON.stringify(metrics).

const LABELS: Record<string, string> = {
  coverage: 'Copertura',
  obj_value: 'Obiettivo',
  soft_obj: 'Costo soft',
  assignments: 'Cattedre',
  buchi: 'Ore buche',
  holes: 'Ore buche',
  sixth: 'Seste ore',
  five: 'Giornate da 5 ore',
  one: 'Ore isolate',
  placed: 'Lezioni piazzate',
  unplaced: 'Lezioni non piazzate',
  n_lessons: 'Lezioni',
  // diagnostics (Monte Carlo & co.)
  n_samples: 'Campioni',
  mean: 'Media',
  std: 'Deviazione std',
  min: 'Minimo',
  max: 'Massimo',
  coefficient_of_variation: 'Variabilità (CV)',
};

// Keys whose numeric value is a fraction in [0,1] to be shown as a percentage.
const PERCENT_KEYS = new Set(['coverage', 'coefficient_of_variation']);

export interface HumanMetric {
  key: string;
  label: string;
  value: string;
}

function prettyKey(k: string): string {
  const s = k.replace(/[_-]+/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : k;
}

function formatValue(key: string, v: unknown): string {
  if (typeof v === 'boolean') return v ? 'sì' : 'no';
  if (typeof v === 'number') {
    if (PERCENT_KEYS.has(key)) return Math.round(v * 100) + '%';
    if (Number.isInteger(v)) return String(v);
    return (Math.round(v * 100) / 100).toString();
  }
  return String(v);
}

/**
 * Turn a metrics dict into an ordered list of `{label, value}` ready for
 * display. Nested objects/arrays and long prose (e.g. an "interpretation"
 * sentence) are skipped; `null`/`undefined` are dropped. `opts.max` caps
 * how many are returned.
 */
export function humanMetrics(
  metrics: Record<string, unknown> | null | undefined,
  opts: { max?: number } = {},
): HumanMetric[] {
  if (!metrics || typeof metrics !== 'object') return [];
  const out: HumanMetric[] = [];
  for (const [k, v] of Object.entries(metrics)) {
    if (v == null) continue;
    if (typeof v === 'object') continue;                 // skip nested
    if (typeof v === 'string' && v.length > 48) continue; // skip prose
    out.push({ key: k, label: LABELS[k] ?? prettyKey(k), value: formatValue(k, v) });
  }
  const max = opts.max ?? out.length;
  return out.slice(0, max);
}

/** One-line "Copertura: 100% · Ore buche: 12" summary. */
export function humanMetricsLine(
  metrics: Record<string, unknown> | null | undefined,
  opts: { max?: number } = {},
): string {
  return humanMetrics(metrics, opts).map((m) => `${m.label}: ${m.value}`).join(' · ');
}
