/**
 * Preset di aula per l'attività alternativa (la materia che sta
 * in parallelo all'IRC). È una scelta per chi non imposta i vincoli
 * a mano: all'apertura è già selezionata l'aula di tipo
 * «alternativa». Le altre due scelte si possono cambiare, e l'intera
 * scelta si può togliere. Non è una regola del motore.
 */

export const ALTERNATIVA_ROOM_KIND = "alternativa" as const;

export type AlternativaRoomMode = "alternativa" | "fissa" | "libere";

export interface AlternativaRoomPreset {
  /** false dopo «Togli questa scelta». I nomi già scritti restano. */
  active: boolean;
  mode: AlternativaRoomMode;
  /** Tipo dell'aula predefinita. Resta «alternativa» anche se si cambia modo. */
  kind: typeof ALTERNATIVA_ROOM_KIND;
  /** Nome della stanza, usato quando mode è «fissa». */
  roomName: string;
  /** Nomi delle aule del gruppo «libere». Lista vuota = qualunque aula libera. */
  freeRooms: string[];
}

export interface AlternativaRoomChoice {
  mode: AlternativaRoomMode;
  label: string;
  hint: string;
}

export const ALTERNATIVA_ROOM_CHOICES: readonly AlternativaRoomChoice[] = [
  {
    mode: "alternativa",
    label: "Aula di tipo alternativa",
    hint: "Le ore di attività alternativa finiscono in un'aula il cui tipo è alternativa. All'apertura questa scelta è già selezionata.",
  },
  {
    mode: "fissa",
    label: "Aula fissa",
    hint: "Le ore finiscono sempre nella stessa stanza. Il nome della stanza si può cambiare.",
  },
  {
    mode: "libere",
    label: "Aule libere",
    hint: "Nessuna stanza è obbligata: si usano le aule libere in quell'ora. I nomi, se li indichi, si possono aggiungere e togliere.",
  },
];

export function defaultAlternativaRoomPreset(): AlternativaRoomPreset {
  return {
    active: true,
    mode: "alternativa",
    kind: ALTERNATIVA_ROOM_KIND,
    roomName: "",
    freeRooms: [],
  };
}

export function isDefaultSelected(preset: AlternativaRoomPreset): boolean {
  return (
    preset.active
    && preset.mode === "alternativa"
    && preset.kind === ALTERNATIVA_ROOM_KIND
  );
}

export function selectMode(
  preset: AlternativaRoomPreset,
  mode: AlternativaRoomMode,
): AlternativaRoomPreset {
  return { ...preset, active: true, mode, kind: ALTERNATIVA_ROOM_KIND };
}

/** Il nome si aggiorna anche se l'aula fissa non è la scelta attiva. */
export function setRoomName(
  preset: AlternativaRoomPreset,
  roomName: string,
): AlternativaRoomPreset {
  return { ...preset, roomName };
}

export function addFreeRoom(
  preset: AlternativaRoomPreset,
  roomName: string,
): AlternativaRoomPreset {
  const name = roomName.trim();
  if (!name || preset.freeRooms.includes(name)) return preset;
  return { ...preset, freeRooms: [...preset.freeRooms, name] };
}

export function removeFreeRoom(
  preset: AlternativaRoomPreset,
  roomName: string,
): AlternativaRoomPreset {
  return {
    ...preset,
    freeRooms: preset.freeRooms.filter((name) => name !== roomName),
  };
}

export function removePreset(
  preset: AlternativaRoomPreset,
): AlternativaRoomPreset {
  return { ...preset, active: false };
}

/** Rimette la scelta predefinita, senza cancellare i nomi già scritti. */
export function restoreDefault(
  preset: AlternativaRoomPreset,
): AlternativaRoomPreset {
  return {
    ...preset,
    active: true,
    mode: "alternativa",
    kind: ALTERNATIVA_ROOM_KIND,
  };
}

export function presetSummary(preset: AlternativaRoomPreset): string {
  if (!preset.active) {
    return "Scelta tolta. L'attività alternativa non ha un'aula impostata.";
  }
  if (preset.mode === "alternativa") {
    return "Aula di tipo alternativa, già selezionata.";
  }
  if (preset.mode === "fissa") {
    const name = preset.roomName.trim();
    if (!name) return "Aula fissa: manca il nome della stanza.";
    return `Aula fissa: ${name}.`;
  }
  if (preset.freeRooms.length === 0) {
    return "Aule libere: nessuna stanza indicata. Si usano le aule libere in quell'ora.";
  }
  return `Aule libere: ${preset.freeRooms.join(", ")}.`;
}

/** L'aula fissa senza nome non è ancora una scelta completa. */
export function isComplete(preset: AlternativaRoomPreset): boolean {
  if (!preset.active) return true;
  if (preset.mode === "fissa") return preset.roomName.trim().length > 0;
  return true;
}
