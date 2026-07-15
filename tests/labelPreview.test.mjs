import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import { buildLabelPreviewModel, LABEL_QR_SIZES_MM } from '../src/utils/labelPreviewModel.js'
import { createLabelQrSvg } from '../src/utils/labelQr.js'

test('encodes the raw SKU into a local QR SVG and omits empty codes', () => {
  const svg = createLabelQrSvg('CAMP0721')

  assert.match(svg, /^<svg\b/)
  assert.match(svg, /<path|<rect/)
  assert.equal(createLabelQrSvg('  '), '')
})

test('builds a label model from a product and keeps the requested size QR dimensions', () => {
  const label = buildLabelPreviewModel(
    {
      no: 'CAMP0721',
      brand: 'TrailForge',
      name_en: 'Alpine Shelter Tent',
      list_price: 5680,
      specification: '2P / 3-season',
      category: 'Tent & Shelter',
      feature: 'Rainproof',
    },
    { size: 'medium' }
  )

  assert.equal(label.code, 'CAMP0721')
  assert.equal(label.qrSizeMm, LABEL_QR_SIZES_MM.medium)
  assert.equal(label.price, '$5,680')
  assert.equal(label.brand, 'TrailForge')
  assert.match(label.qrSvg, /^<svg\b/)
})

test('uses print item code before its product snapshot and falls back to snapshot fields', () => {
  const label = buildLabelPreviewModel(
    {
      code: 'PRINT-0001',
      size: 'large',
      description: 'A compact outdoor label description.',
      product_snapshot: {
        no: 'SNAPSHOT-0001',
        supplier: 'Summit Works',
        name: 'Trekking Backpack',
        invn015: 3200,
        invn051: '35 L',
        invn030: 'Packs',
      },
    }
  )

  assert.equal(label.code, 'PRINT-0001')
  assert.equal(label.brand, 'Summit Works')
  assert.equal(label.name, 'Trekking Backpack')
  assert.equal(label.price, '$3,200')
  assert.equal(label.specification, '35 L')
  assert.equal(label.category, 'Packs')
  assert.equal(label.description, 'A compact outdoor label description.')
})

test('the print renderer consumes the shared model and includes QR markup', async () => {
  const template = await readFile(new URL('../src/print/labelPrintTemplate.js', import.meta.url), 'utf8')
  assert.match(template, /buildLabelPreviewModel/)
  assert.match(template, /print-card__qr/)
  assert.match(template, /label\.qrSvg/)
})
