import { test } from 'node:test';
import assert from 'node:assert/strict';

import { variantClass, BUTTON_VARIANTS } from './button_variants.ts';

test('variantClass maps known variants', () => {
  assert.equal(variantClass('primary'), BUTTON_VARIANTS.primary);
  assert.equal(variantClass('danger'), BUTTON_VARIANTS.danger);
  assert.equal(variantClass('icon'), BUTTON_VARIANTS.icon);
});

test('variantClass falls back to primary on unknown/undefined', () => {
  assert.equal(variantClass('nope'), BUTTON_VARIANTS.primary);
  assert.equal(variantClass(undefined), BUTTON_VARIANTS.primary);
});
