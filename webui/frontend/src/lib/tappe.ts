/**
 * Stato di avanzamento del percorso in quattro tappe.
 *
 * La logica viveva dentro OnboardingChecklist.svelte; sta qui perche'
 * ora la leggono in due: il checklist (che continua a mostrare i nove
 * passi in dettaglio) e la dashboard (che ne mostra la sintesi in
 * quattro card). Una sola definizione di "fatto", due viste.
 */
import { TAPPE, type Tappa } from '$lib/nav';

/** Il sottoinsieme di $datasetState che ci serve. */
export interface DatasetLike {
  subjects?: number;
  teachers?: number;
  classes?: number;
  classrooms?: number;
  students?: number;
  assignments?: number;
  solutions?: number;
  active_solution?: unknown;
}

/** Il sottoinsieme di $workingHoursConfig che ci serve. */
export interface WorkingHoursLike {
  days?: { is_active?: boolean; slots?: unknown[] }[];
}

export interface Step {
  label: string;
  href: string;
  done: boolean;
  /** I passi facoltativi non contano nel conteggio di avanzamento. */
  optional?: boolean;
  /** A quale delle quattro tappe appartiene il passo. */
  tappa: Tappa['n'];
}

/** "Ore configurate" = almeno un giorno attivo con almeno una fascia. */
export function oreConfigurate(wh: WorkingHoursLike | null | undefined): boolean {
  return Array.isArray(wh?.days)
    && wh.days.some((d) => d?.is_active && (d?.slots?.length ?? 0) > 0);
}

/** C'e' un orario: soluzione attiva o almeno una salvata. */
export function haSoluzione(s: DatasetLike | null | undefined): boolean {
  return !!s?.active_solution || (s?.solutions ?? 0) > 0;
}

/**
 * I nove passi guidati, nell'ordine in cui vanno fatti. E' la stessa
 * lista che il checklist mostrava prima, con in piu' il campo `tappa`.
 */
export function steps(
  s: DatasetLike | null | undefined,
  wh: WorkingHoursLike | null | undefined,
): Step[] {
  const d = s || {};
  const sol = haSoluzione(d);
  return [
    { tappa: 1, label: 'Configura le Ore (la settimana scolastica)', href: '/ore',         done: oreConfigurate(wh) },
    { tappa: 1, label: 'Inserisci le Materie',                       href: '/subjects',    done: (d.subjects ?? 0) > 0 },
    { tappa: 1, label: 'Inserisci i Docenti',                        href: '/teachers',    done: (d.teachers ?? 0) > 0 },
    { tappa: 1, label: 'Inserisci le Classi',                        href: '/classes',     done: (d.classes ?? 0) > 0 },
    { tappa: 1, label: 'Inserisci le Aule',                          href: '/classrooms',  done: (d.classrooms ?? 0) > 0 },
    { tappa: 2, label: 'Assegna le Cattedre (docente → classe → materia)', href: '/assignments', done: (d.assignments ?? 0) > 0 },
    { tappa: 3, label: 'Imposta i Vincoli', href: '/constraints', optional: true, done: false },
    { tappa: 4, label: "Genera l'orario",                     href: '/optimize', done: sol },
    { tappa: 4, label: "Visualizza e modifica l'orario",      href: '/schedule', done: sol },
  ];
}

export interface TappaStato extends Tappa {
  /** Passi obbligatori completati / totali della tappa. */
  fatti: number;
  totali: number;
  /** Tutti i passi obbligatori della tappa sono fatti. */
  completa: boolean;
  /** E' la prima tappa non completa: quella su cui l'utente sta lavorando. */
  corrente: boolean;
  /** Riga di dettaglio a destra nella card ("5/5 completate", "210 assegnate"). */
  meta: string;
}

/**
 * Le quattro tappe con il loro stato. La tappa corrente e' la prima
 * non completa; se sono tutte complete nessuna e' corrente e la
 * dashboard mostra quattro spunte.
 *
 * Nota sulla tappa 3 (Vincoli): DatasetState non conta i vincoli e
 * comunque il solver gira anche senza. La consideriamo quindi conclusa
 * quando l'utente e' andato oltre, cioe' quando esiste un orario:
 * cosi' resta la tappa corrente nel momento giusto (dopo le cattedre,
 * prima di generare) senza bloccare per sempre chi non la usa.
 */
export function statoTappe(
  s: DatasetLike | null | undefined,
  wh: WorkingHoursLike | null | undefined,
): TappaStato[] {
  const d = s || {};
  const all = steps(d, wh);
  const sol = haSoluzione(d);

  const parziali = TAPPE.map((t) => {
    const miei = all.filter((st) => st.tappa === t.n && !st.optional);
    const fatti = miei.filter((st) => st.done).length;
    const completa = t.n === 3 ? sol : miei.length > 0 && fatti === miei.length;
    return { ...t, fatti, totali: miei.length, completa };
  });

  const primaAperta = parziali.findIndex((t) => !t.completa);
  return parziali.map((t, i) => ({
    ...t,
    corrente: i === primaAperta,
    meta: metaPerTappa(t.n, d, t.fatti, t.totali),
  }));
}

/** Il dato piu' parlante per ciascuna tappa, come nel design. */
function metaPerTappa(n: Tappa['n'], d: DatasetLike, fatti: number, totali: number): string {
  switch (n) {
    case 1: return `${fatti}/${totali} completate`;
    case 2: return `${d.assignments ?? 0} assegnate`;
    case 3: return 'facoltativa';
    case 4: return haSoluzione(d)
      ? `${d.solutions ?? 0} ${(d.solutions ?? 0) === 1 ? 'soluzione' : 'soluzioni'}`
      : 'nessuna soluzione';
  }
}
