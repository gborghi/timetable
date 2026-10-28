// Messaggio di conferma per le azioni della Dashboard che SOSTITUISCONO la
// scuola nel DB (Importa profilo, Genera scuola di test). Restituisce null
// quando il DB e' vuoto: non c'e' niente da perdere, niente domanda.

export interface SchoolCounts {
  classes?: number | null;
  teachers?: number | null;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function replaceSchoolMessage(
  state: SchoolCounts | null | undefined,
  action: string,
): string | null {
  const nc = Number(state?.classes ?? 0) || 0;
  const nt = Number(state?.teachers ?? 0) || 0;
  if (nc === 0 && nt === 0) return null;
  return (
    `${action} sostituisce la scuola attuale ` +
    `(${plural(nc, 'classe', 'classi')}, ${plural(nt, 'docente', 'docenti')}) ` +
    `e il suo orario. Se ti serve, prima fai un backup con «Esporta DB».\n\n` +
    `Vuoi continuare?`
  );
}
