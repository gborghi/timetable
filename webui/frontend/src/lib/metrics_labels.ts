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
  n_evicted: 'Lezioni sfrattate',
  // passo aule (classroom_assignment)
  rooms_assigned: 'Lezioni con aula',
  rooms_total_lessons: 'Lezioni totali',
  rooms_unplaced: 'Lezioni senza aula',
  rooms_fallback: 'Aule da euristica',
  rooms_rescued: 'Lezioni recuperate dal greedy',
  rooms_exact_status: 'Esito solver aule',
  rooms_joint: 'Aule risolte insieme all’orario',
  rooms_error: 'Errore aule',
  rooms_skipped: 'Passo aule saltato',
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

// Keys that report a DEGRADED outcome. When they carry a non-zero value they
// are floated to the front of the list, because callers cap the line at a few
// entries and a run that left 40 lezioni senza aula must not read as a clean
// success merely because `coverage` happened to be declared first.
const ALARM_KEYS = new Set([
  'rooms_unplaced', 'rooms_fallback', 'rooms_error', 'rooms_rescued',
  'unplaced', 'n_evicted',
]);

function isAlarming(key: string, v: unknown): boolean {
  if (!ALARM_KEYS.has(key)) return false;
  return typeof v === 'number' ? v > 0 : Boolean(v);
}

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
  const alarms: HumanMetric[] = [];
  for (const [k, v] of Object.entries(metrics)) {
    if (v == null) continue;
    if (typeof v === 'object') continue;                 // skip nested
    if (typeof v === 'string' && v.length > 48) continue; // skip prose
    const m = { key: k, label: LABELS[k] ?? prettyKey(k), value: formatValue(k, v) };
    (isAlarming(k, v) ? alarms : out).push(m);
  }
  const max = opts.max ?? alarms.length + out.length;
  return alarms.concat(out).slice(0, max);
}

/**
 * Explain, in one sentence, why the room step's result is not a clean
 * success — or `null` when it is. The backend has reported `rooms_unplaced`
 * / `rooms_exact_status` / `rooms_fallback` for a while but nothing read
 * them, so a run that silently fell back to the greedy heuristic, or that
 * left lessons with no aula at all, looked identical to a perfect one.
 *
 * The three signals mean different things and must not be merged:
 *  - `rooms_exact_status` starting with NO_ELIGIBLE / NO_CLASSROOMS /
 *    LOCKED_INELIGIBLE is a CONFIGURATION error: some lesson has no room
 *    that could ever host it. Rescheduling cannot help.
 *  - `rooms_fallback` means what you see was placed by the greedy
 *    heuristic, not by the exact solver.
 *  - `rooms_unplaced` means the placement succeeded but N lessons got no
 *    real room: a capacity/plesso shortage for the headmaster to resolve.
 */
export function roomsWarning(
  metrics: Record<string, unknown> | null | undefined,
): string | null {
  if (!metrics || typeof metrics !== 'object') return null;
  const status = String(metrics.rooms_exact_status ?? '');
  const parts: string[] = [];
  if (status.startsWith('NO_CLASSROOMS')) {
    parts.push('nessuna aula configurata');
  } else if (status.startsWith('NO_ELIGIBLE')) {
    parts.push('alcune lezioni non hanno nessuna aula compatibile (errore di configurazione, non di orario)');
  } else if (status.startsWith('LOCKED_INELIGIBLE')) {
    parts.push('un’aula bloccata a mano non può ospitare la sua lezione');
  }
  const unplaced = Number(metrics.rooms_unplaced ?? 0);
  if (unplaced > 0) {
    parts.push(`${unplaced} lezioni sono rimaste senza aula (capienza o plesso)`);
  }
  if (metrics.rooms_fallback) {
    const rescued = Number(metrics.rooms_rescued ?? 0);
    parts.push(rescued > 0
      ? `la ricerca esatta è stata troncata: le aule vengono dall’euristica, che ha collocato ${rescued} lezioni in più`
      : 'le aule sono state assegnate dall’euristica di ripiego, non dal solver esatto');
  }
  if (metrics.rooms_error) parts.push(String(metrics.rooms_error));
  if (!parts.length) return null;
  return 'Aule: ' + parts.join('; ') + '.';
}

/** One-line "Copertura: 100% · Ore buche: 12" summary. */
export function humanMetricsLine(
  metrics: Record<string, unknown> | null | undefined,
  opts: { max?: number } = {},
): string {
  return humanMetrics(metrics, opts).map((m) => `${m.label}: ${m.value}`).join(' · ');
}
