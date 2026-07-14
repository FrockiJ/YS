import assert from 'node:assert/strict'

import { resolveCerpColor } from '../src/utils/cerpFields.js'

const cases = [
  {
    name: 'preserves normalized color',
    row: { color: 'White', invn801: 'Red' },
    expected: 'White',
  },
  {
    name: 'falls back to invn801 when color is missing',
    row: { invn801: 'Rose' },
    expected: 'Rose',
  },
  {
    name: 'skips localized unknown placeholder when raw color exists',
    row: { color: '未知', invn801: 'White' },
    expected: 'White',
  },
  {
    name: 'skips english unknown placeholder when raw color exists',
    row: { color: 'Unknown', invn801: 'Red' },
    expected: 'Red',
  },
  {
    name: 'does not use invn032 as generic color fallback',
    row: { invn032: 'B281' },
    expected: '未知',
    fallback: '未知',
  },
]

for (const testCase of cases) {
  const actual = resolveCerpColor(testCase.row, testCase.fallback ?? '未知')
  assert.equal(actual, testCase.expected, testCase.name)
}

console.log(`verifyCerpColor: ${cases.length} cases passed`)
