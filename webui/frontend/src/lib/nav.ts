/**
 * Navigazione: unica fonte di verita' per la barra in alto, per la
 * striscia della tappa e per le fasce introduttive delle pagine.
 *
 * `navGroups` viveva dentro +layout.svelte; sta qui perche' ora lo
 * leggono in tre: il layout (barra + sub-nav) e le pagine che chiedono
 * a `tappaFor()` quale occhiello mostrare.
 *
 * ATTENZIONE: la struttura (8 voci di primo livello, ordine dei figli,
 * href e label) e' bloccata da cypress/e2e/navbar_completeness.cy.ts.
 * Modificarla richiede di aggiornare quello spec.
 */

export interface NavChild {
  href: string;
  label: string;
  hint: string;
}

export interface NavGroup {
  kind: 'link' | 'menu';
  label: string;
  hint: string;
  href?: string;
  exact?: boolean;
  children?: NavChild[];
}

// Top-level nav: 8 entries. Anagrafica, Pianificazione, Gestione e
// Esecuzione sono dropdown che raggruppano sotto-pagine; le altre
// sono link diretti. Vincoli sta sotto Pianificazione (e' un'azione
// della fase di pianificazione, non un capitolo a parte). Orario
// sale a tab standalone perche' e' la pagina che si visita di gran
// lunga piu' spesso. Eventi (ex Monitor) e' standalone perche' e'
// il pannello di run real-time, indipendente dalla pipeline di
// ottimizzazione. Gestione raggruppa tutto cio' che riguarda la
// gestione operativa post-orario (assenze, supplenze, ...).
export const navGroups: NavGroup[] = [
  { kind: 'link', href: '/', label: 'Dashboard', exact: true,
    hint: 'Panoramica: carica/genera la scuola, stato dei dati e dei run in corso.' },
  { kind: 'menu', label: 'Anagrafica',
    hint: 'I dati di base della scuola: chi insegna, quali classi, materie, aule.', children: [
    { href: '/teachers',   label: 'Docenti',
      hint: 'Docenti: ore, disponibilita oraria, giorni liberi, preferenze e materie insegnabili.' },
    { href: '/classes',    label: 'Classi',
      hint: 'Classi: monte ore per materia, indirizzo, n. studenti e vincoli di classe.' },
    { href: '/curricula',  label: 'Indirizzi',
      hint: 'Indirizzi (curricula): il piano orario per anno di corso, riusabile fra classi.' },
    { href: '/students',   label: 'Studenti',
      hint: 'Studenti: anagrafica, tag e appartenenza a gruppi.' },
    { href: '/groups',     label: 'Gruppi',
      hint: 'Gruppi studio: sottogruppi inter/intra-classe (potenziamento, splitting).' },
    { href: '/subjects',   label: 'Materie',
      hint: 'Materie: nomi, pesi di distribuzione e preferenze d\'aula.' },
    { href: '/classrooms', label: 'Aule',
      hint: 'Aule e laboratori: capienza, tipo, disponibilita e preferenze per materia.' },
    { href: '/plessi',     label: 'Plessi',
      hint: 'Plessi (sedi): regole di spostamento fra edifici e politiche per giorno.' },
    { href: '/ore',        label: 'Ore',
      hint: 'Tab Ore: definisce la settimana scolastica (giorni attivi e fasce orarie).' },
  ] },
  { kind: 'menu', label: 'Pianificazione',
    hint: 'Le decisioni a monte del solver: compresenze, cattedre e vincoli.', children: [
    { href: '/coteaching',  label: 'Compresenze',
      hint: 'Compresenze: due o piu docenti nella stessa ora/classe (es. laboratorio).' },
    { href: '/assignments', label: 'Cattedre',
      hint: 'Cattedre (Fase A): assegna ogni (classe, materia) a un docente.' },
    { href: '/constraints', label: 'Vincoli',
      hint: 'Vincoli: regole hard/soft sull\'orario, anche in linguaggio DSL generale.' },
  ] },
  { kind: 'link', href: '/schedule', label: 'Orario',
    hint: 'Orario: editor settimanale drag-and-drop con anteprima dei conflitti.' },
  { kind: 'menu', label: 'Gestione',
    hint: 'Gestione operativa dopo l\'orario: assenze e supplenze.', children: [
    { href: '/assenze-supplenze', label: 'Assenze e supplenze',
      hint: 'Assenze e supplenze: copertura settimanale e riassegnazione docenti.' },
  ] },
  { kind: 'menu', label: 'Esecuzione',
    hint: 'Far girare il solver e analizzare i risultati.', children: [
    { href: '/optimize',    label: 'Workflow',
      hint: 'Workflow: pipeline del solver (Fase A, Fase B, metaeuristiche, aule).' },
    { href: '/runs',        label: 'Runs',
      hint: 'Runs: storico delle esecuzioni con stato, log e metriche.' },
    { href: '/diagnostics', label: 'Statistiche',
      hint: 'Statistiche: pre-check Hall, Monte Carlo, matching e distribuzioni.' },
  ] },
  { kind: 'link', href: '/monitor', label: 'Eventi',
    hint: 'Eventi: editor delle cattedre/lezioni grezze con filtri e azioni di massa.' },
  { kind: 'link', href: '/import',  label: 'Import bulk',
    hint: 'Import bulk: carica docenti, classi, aule e altro da file xlsx/csv.' },
];

/**
 * Il percorso in quattro tappe che struttura il redesign. La dashboard
 * lo disegna come quattro card, ogni pagina ne mostra l'occhiello
 * ("TAPPA 2 - CATTEDRE") sopra il titolo.
 *
 * Nota: il documento di design usa "Tappa 3 - Pianificazione" nella
 * sub-nav di Vincoli e "Tappa 2 Cattedre / Tappa 3 Vincoli" nella
 * dashboard. Abbiamo tenuto la numerazione della dashboard (quella
 * che l'utente vede per prima) e lasciato che la striscia mostri
 * comunque i fratelli del gruppo di navigazione.
 */
export interface Tappa {
  n: 1 | 2 | 3 | 4;
  label: string;
  /** Sottotitolo della card in dashboard. */
  blurb: string;
  /** Dove porta "Continua". */
  href: string;
}

export const TAPPE: Tappa[] = [
  { n: 1, label: 'Anagrafica',          blurb: 'Ore, materie, docenti, classi, aule',      href: '/ore' },
  { n: 2, label: 'Cattedre',            blurb: 'Chi insegna cosa, e le compresenze',       href: '/assignments' },
  { n: 3, label: 'Vincoli',             blurb: 'Giorni liberi, aule, regole hard e soft',  href: '/constraints' },
  { n: 4, label: 'Genera e rifinisci',  blurb: 'Solver, orario, assenze e supplenze',      href: '/optimize' },
];

/** Route -> numero di tappa. Le route non elencate non hanno occhiello. */
const TAPPA_BY_ROUTE: Record<string, Tappa['n']> = {
  '/teachers': 1, '/classes': 1, '/curricula': 1, '/students': 1,
  '/groups': 1, '/subjects': 1, '/classrooms': 1, '/plessi': 1, '/ore': 1,
  '/coteaching': 2, '/assignments': 2,
  '/constraints': 3,
  '/optimize': 4, '/runs': 4, '/diagnostics': 4, '/schedule': 4,
  '/assenze-supplenze': 4, '/monitor': 4,
};

/** Il segmento di primo livello del path ('/runs/12' -> '/runs'). */
function topSegment(pathname: string): string {
  const seg = pathname.split('/')[1] ?? '';
  return seg ? `/${seg}` : '/';
}

/** La tappa a cui appartiene una route, o null (dashboard, import bulk). */
export function tappaFor(pathname: string): Tappa | null {
  const n = TAPPA_BY_ROUTE[topSegment(pathname)];
  return n ? (TAPPE.find((t) => t.n === n) ?? null) : null;
}

/**
 * Le pagine sorelle da mostrare nella striscia sotto l'header: i figli
 * del menu che contiene la route corrente. Null per i link di primo
 * livello senza figli (Dashboard, Orario, Eventi, Import bulk).
 */
export function siblingsFor(pathname: string): NavChild[] | null {
  const top = topSegment(pathname);
  for (const g of navGroups) {
    if (g.kind !== 'menu' || !g.children) continue;
    if (g.children.some((c) => c.href === top)) return g.children;
  }
  return null;
}
