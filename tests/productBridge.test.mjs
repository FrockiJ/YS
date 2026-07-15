import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getProductBridgeSourceId,
  isPendingProductBridge,
  normalizeProductResults,
  formatProductRecommendationReason,
} from '../src/utils/productBridge.js'

test('shows a product bridge only for a pending button trigger', () => {
  const message = {
    id: 'assistant-1',
    metadata: {
      product_bridge: {
        eligible: true,
        trigger: 'button',
        fulfilled: false,
        source_message_id: 'assistant-1',
      },
    },
  }

  assert.equal(getProductBridgeSourceId(message), 'assistant-1')
  assert.equal(isPendingProductBridge(message), true)
  assert.equal(isPendingProductBridge(message, new Set(['assistant-1'])), false)
})

test('never shows a duplicate button for immediate or fulfilled responses', () => {
  const immediate = {
    id: 'assistant-2',
    metadata: { product_bridge: { eligible: true, trigger: 'immediate', fulfilled: true } },
  }
  assert.equal(isPendingProductBridge(immediate), false)
})

test('normalizes only ERP product contract rows with a SKU', () => {
  const rows = normalizeProductResults({
    product_results: [
      {
        sku: 'CAMP0001',
        name: 'Tent',
        brand: 'TrailForge',
        category: 'Tent & Shelter',
        specification: '2P',
        price: 2800,
        stock: 4,
        recommendation_reason: 'Matches shelter',
        matched_requirements: ['category:shelter'],
        source_timestamp: '2026-07-14T00:00:00Z',
      },
      { name: 'Invented row without SKU', price: 1 },
    ],
  })

  assert.equal(rows.length, 1)
  assert.equal(rows[0].sku, 'CAMP0001')
  assert.equal(rows[0].brand, 'TrailForge')
})

test('rebuilds legacy internal recommendation codes into readable text', () => {
  const reason = formatProductRecommendationReason(
    { matched_requirements: ['category:shelter', 'in_stock'] },
    'category:shelter'
  )
  assert.equal(reason, '符合遮蔽需求，且為 ERP 實際可用商品。')
  assert.doesNotMatch(reason, /category:|[a-z]+_[a-z_]+/)
})
