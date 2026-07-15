import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeEdmTableColumns,
  resolveEdmTableValue,
  snapshotEdmTableColumns,
} from '../src/utils/edmTable.js'

test('keeps the Quote-view visible column order and widths for an EDM snapshot', () => {
  const columns = snapshotEdmTableColumns([
    { key: 'product', label: 'Product', width: 220 },
    { key: 'stock', label: 'Stock', width: 80 },
    { key: 'supplier', label: 'Supplier', width: 130 },
  ])

  assert.deepEqual(columns, [
    { key: 'product', label: 'Product', width: 220 },
    { key: 'stock', label: 'Stock', width: 80 },
    { key: 'supplier', label: 'Supplier', width: 130 },
  ])
})

test('renders dynamic and unknown Quote fields without dropping their values', () => {
  const row = {
    no: 'CAMP0721',
    product: 'PeakPath Carbon Trekking Pole',
    stock: 12,
    supplier: 'PeakPath',
    price: 1680,
  }

  assert.equal(resolveEdmTableValue(row, 'product'), 'PeakPath Carbon Trekking Pole')
  assert.equal(resolveEdmTableValue(row, 'stock'), 12)
  assert.equal(resolveEdmTableValue(row, 'supplier'), 'PeakPath')
  assert.equal(resolveEdmTableValue(row, 'price'), 1680)
})

test('uses a single legacy fallback when an existing preview lacks a snapshot', () => {
  const columns = normalizeEdmTableColumns([])
  assert.equal(columns[0].key, 'no')
  assert.equal(columns.at(-1).key, 'bundle')
})

test('normalizes legacy spec columns and falls back from an empty spec value', () => {
  const columns = normalizeEdmTableColumns([
    { key: 'spec', label: 'Spec / Model', width: 130 },
    { key: 'specification', label: '型號／規格', width: 130 },
  ])
  assert.deepEqual(columns, [{ key: 'specification', label: 'Spec / Model', width: 130 }])
  assert.equal(
    resolveEdmTableValue({ spec: '', specification: '4x4m / UV coated' }, 'spec'),
    '4x4m / UV coated'
  )
})
