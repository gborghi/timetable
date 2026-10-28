import { test } from 'node:test';
import assert from 'node:assert/strict';

import { replaceSchoolMessage } from './replace_school.ts';

test('DB vuoto: nessuna conferma', () => {
  assert.equal(replaceSchoolMessage({ classes: 0, teachers: 0 }, 'Importa'), null);
  assert.equal(replaceSchoolMessage(null, 'Importa'), null);
});

test('scuola presente: il messaggio riporta classi e docenti', () => {
  const m = replaceSchoolMessage({ classes: 100, teachers: 178 }, 'Importare il profilo');
  assert.match(m, /^Importare il profilo sostituisce la scuola attuale/);
  assert.match(m, /100 classi, 178 docenti/);
  assert.match(m, /backup/);
});

test('singolari', () => {
  const m = replaceSchoolMessage({ classes: 1, teachers: 1 }, 'Generare');
  assert.match(m, /1 classe, 1 docente/);
});
