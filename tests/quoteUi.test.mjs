import test from 'node:test'
import assert from 'node:assert/strict'

import { extractActionableQuoteRows } from '../src/utils/actionableQuoteRows.js'

test('uses the displayed product_results rows when opening QuoteView from an ERP table', () => {
  const rows = extractActionableQuoteRows({
    product_results: [
      { sku: 'CAMP0721', name: 'Carbon Trekking Pole', brand: 'PeakPath', stock: 12, price: 1680 },
      { sku: 'CAMP0722', name: 'Trail Stove', brand: 'TrailForge', stock: 4, price: 980 },
    ],
    quote_items: [{ no: 'OTHER001', name: 'Unrelated quote item' }],
  })

  assert.equal(rows.length, 2)
  assert.equal(rows[0].no, 'CAMP0721')
  assert.equal(rows[0].code, 'CAMP0721')
  assert.equal(rows[0].brand, 'PeakPath')
})

test('keeps canonical specification when product results are handed to QuoteView', () => {
  const rows = extractActionableQuoteRows({
    product_results: [
      { sku: 'CAMP0002', name: 'PinePeak Tarp', specification: '4x4m / UV coated', stock: 3 },
    ],
  })
  assert.equal(rows[0].specification, '4x4m / UV coated')
})

test('continues to accept the existing cerp_results.items contract', () => {
  const rows = extractActionableQuoteRows({
    cerp_results: {
      items: [{ code: 'CAMP0801', name: 'Water Filter', brand: 'SummitNest', stock_qty: 6 }],
    },
  })

  assert.equal(rows.length, 1)
  assert.equal(rows[0].no, 'CAMP0801')
  assert.equal(rows[0].stock_qty, 6)
})
