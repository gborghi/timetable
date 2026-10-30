import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ALTERNATIVA_ROOM_CHOICES,
  ALTERNATIVA_ROOM_KIND,
  addFreeRoom,
  defaultAlternativaRoomPreset,
  isComplete,
  isDefaultSelected,
  presetSummary,
  removeFreeRoom,
  removePreset,
  restoreDefault,
  selectMode,
  setRoomName,
} from "./alternativa_room_preset.ts";

test("all'apertura è selezionata l'aula di tipo alternativa", () => {
  const preset = defaultAlternativaRoomPreset();
  assert.equal(preset.active, true);
  assert.equal(preset.mode, "alternativa");
  assert.equal(preset.kind, "alternativa");
  assert.equal(preset.kind, ALTERNATIVA_ROOM_KIND);
  assert.equal(preset.roomName, "");
  assert.deepEqual(preset.freeRooms, []);
  assert.equal(isDefaultSelected(preset), true);
  assert.equal(isComplete(preset), true);
  assert.match(presetSummary(preset), /già selezionata/);
});

test("le altre due scelte sono aula fissa e aule libere, in italiano", () => {
  const modes = ALTERNATIVA_ROOM_CHOICES.map((choice) => choice.mode);
  assert.deepEqual(modes, ["alternativa", "fissa", "libere"]);
  const byMode = Object.fromEntries(
    ALTERNATIVA_ROOM_CHOICES.map((choice) => [choice.mode, choice]),
  );
  assert.equal(byMode.alternativa.label, "Aula di tipo alternativa");
  assert.match(byMode.alternativa.hint, /già selezionata/);
  assert.equal(byMode.fissa.label, "Aula fissa");
  assert.match(byMode.fissa.hint, /nome della stanza/);
  assert.equal(byMode.libere.label, "Aule libere");
  assert.match(byMode.libere.hint, /aule libere/);
});

test("aula fissa: il nome della stanza si può cambiare senza perdere le altre scelte", () => {
  const start = defaultAlternativaRoomPreset();
  const named = setRoomName(start, "  Aula 12");
  assert.equal(named.mode, "alternativa");
  assert.equal(named.roomName, "  Aula 12");
  const fixed = selectMode(named, "fissa");
  assert.equal(fixed.mode, "fissa");
  assert.equal(fixed.kind, "alternativa");
  assert.equal(fixed.roomName, "  Aula 12");
  assert.equal(isDefaultSelected(fixed), false);
  assert.equal(isComplete(fixed), true);
  assert.equal(presetSummary(fixed), "Aula fissa: Aula 12.");
  assert.equal(isComplete(selectMode(start, "fissa")), false);
  assert.match(presetSummary(selectMode(start, "fissa")), /manca il nome della stanza/);
});

test("aule libere: i nomi si aggiungono e si tolgono", () => {
  let preset = selectMode(defaultAlternativaRoomPreset(), "libere");
  assert.match(presetSummary(preset), /aule libere in quell'ora/i);
  preset = addFreeRoom(preset, "  Lab 1 ");
  preset = addFreeRoom(preset, "Lab 1");
  preset = addFreeRoom(preset, "   ");
  preset = addFreeRoom(preset, "Aula 4");
  assert.deepEqual(preset.freeRooms, ["Lab 1", "Aula 4"]);
  assert.equal(presetSummary(preset), "Aule libere: Lab 1, Aula 4.");
  preset = removeFreeRoom(preset, "Lab 1");
  assert.deepEqual(preset.freeRooms, ["Aula 4"]);
  assert.equal(preset.mode, "libere");
});

test("la scelta si può togliere e la predefinita si può rimettere", () => {
  const edited = addFreeRoom(
    setRoomName(selectMode(defaultAlternativaRoomPreset(), "fissa"), "Aula 3"),
    "Palestra",
  );
  const removed = removePreset(edited);
  assert.equal(removed.active, false);
  assert.equal(removed.roomName, "Aula 3");
  assert.deepEqual(removed.freeRooms, ["Palestra"]);
  assert.equal(isDefaultSelected(removed), false);
  assert.match(presetSummary(removed), /Scelta tolta/);
  const back = restoreDefault(removed);
  assert.equal(isDefaultSelected(back), true);
  assert.equal(back.roomName, "Aula 3");
  assert.deepEqual(back.freeRooms, ["Palestra"]);
  assert.equal(back.kind, "alternativa");
});
