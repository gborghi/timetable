// Italian locale strings for piTantum (audit F2).
// Import as: import { _ } from '$lib/locales/it';
// Usage: {_.schedule.hero}  (plain object, NOT a Svelte store — no $ prefix)

export const _ = {
  nav: {
    dashboard: 'Dashboard',
    teachers: 'Docenti',
    classes: 'Classi',
    subjects: 'Materie',
    classrooms: 'Aule',
    students: 'Studenti',
    curricula: 'Indirizzi',
    groups: 'Gruppi',
    assignments: 'Cattedre',
    schedule: 'Orario',
    constraints: 'Vincoli',
    plessi: 'Plessi',
    optimize: 'Ottimizza',
    monitor: 'Eventi',
    diagnostics: 'Statistiche',
    imports: 'Importa',
    ore: 'Ore',
    coteaching: 'Compresenze',
    coverage: 'Assenze e supplenze',
    runs: 'Esecuzioni',
  },
  dashboard: {
    hero: "Il tuo orario, in quattro tappe",
  },
  common: {
    save: 'Salva',
    cancel: 'Annulla',
    delete: 'Elimina',
    confirm: 'Conferma',
    edit: 'Modifica',
    create: 'Crea',
    search: 'Cerca',
    loading: 'Caricamento...',
    error: 'Errore',
    empty: 'Nessun elemento',
    actions: 'Azioni',
  },
} as const;
