// Etichette testuali degli stati delle griglie di preferenza (aule,
// materie, docenti). Servono perche' lo stato non sia leggibile solo
// dal colore: badge visibile nella cella e nome accessibile.

/** @type {Record<string, string>} */
export const PREF_STATE_LABEL = {
  allowed: 'consentita',
  soft: 'SOFT (penalità)',
  preferred: 'preferita (bonus)',
  forbidden: 'vietata (HARD)',
  enforced: 'obbligatoria (HARD)',
};

/** Badge breve dentro la cella; vuoto per lo stato di default. */
/** @type {Record<string, string>} */
export const PREF_STATE_BADGE = {
  allowed: '',
  soft: 'SOFT',
  preferred: 'PREF',
  forbidden: 'VIETATA',
  enforced: 'OBBLIG.',
};

/**
 * Nome accessibile di una cella: «Lab1: SOFT (penalità) 100. Invio per cambiare stato».
 * @param {string} label
 * @param {string} state
 * @param {number|null|undefined} [weight]
 */
export function prefCellAriaLabel(label, state, weight) {
  const s = PREF_STATE_LABEL[state] || PREF_STATE_LABEL.allowed;
  const w = (state === 'soft' || state === 'preferred') && weight != null
    ? ` ${Math.abs(Number(weight))}` : '';
  return `${label}: ${s}${w}. Invio o click per passare allo stato successivo`;
}
