import assert from 'node:assert/strict'

import { formatUsdInput, formatUsdPrice, parseUsdInput } from '../src/utils/currency.js'
import {
  buildCerpPricingState,
  calculateBundlePayableQuantity,
  calculateEdmLineSubtotal,
  resolveCerpBundle,
  resolveCerpBundleDisplay,
  resolveCerpColor,
  resolveCerpProductName,
  resolveCerpRating,
  resolveCerpStoreStock,
  resolveCerpVintage,
  resolveEdmUnitPrice,
  resolveEdmQuotePriceForTier,
} from '../src/utils/cerpFields.js'

const pricing = buildCerpPricingState({
  invn013: 6300,
  invn015: 5040,
  invn017: 4410,
  invn048: '11+1',
  invn080: 4095,
  invn807: 2022,
  invn051: 'legacy-2022',
})

assert.equal(pricing.list_price, 6300, 'list_price should read invn013')
assert.equal(pricing.vip_price, 5040, 'vip_price should read invn015')
assert.equal(pricing.fb_price, 4410, 'fb_price should read invn017')
assert.equal(pricing.wholesale_price, 4095, 'wholesale_price should read invn080')
assert.equal(pricing.selected_quote_tier, 'vip', 'EDM quote tier should default to vip')
assert.equal(pricing.quote_price, 5040, 'EDM quote price should default to VIP price')
assert.equal(resolveEdmQuotePriceForTier({ invn015: 5040, invn080: 4095 }, 'wholesale'), 4095, 'wholesale tier should still read invn080')
assert.equal(resolveEdmUnitPrice({ invn015: 5040, invn080: 4095 }), 5040, 'raw EDM unit price should default to VIP price')

assert.equal(resolveCerpBundle({ invn048: '11+1', invn155: 'wrong' }), '11+1', 'bundle should prefer invn048')
assert.equal(formatUsdPrice(1000), '$1,000', 'USD display should use plain dollar sign')
assert.equal(formatUsdInput(100000), '$100,000', 'USD filter input should include dollar sign in value')
assert.equal(parseUsdInput('$1,000'), 1000, 'USD parser should accept dollar formatted input')
assert.equal(parseUsdInput('US$1,000'), 1000, 'USD parser should accept legacy US$ input')
assert.equal(resolveCerpBundleDisplay('無'), '-', 'empty bundle display should normalize 無 to dash')
assert.equal(resolveCerpBundleDisplay(''), '-', 'empty bundle display should normalize blank to dash')
assert.equal(resolveCerpBundleDisplay('11+1'), '11+1', 'bundle display should preserve real bundle value')
assert.equal(calculateBundlePayableQuantity(0, { bundle: '11+1' }), 0, '11+1 payable qty should handle zero')
assert.equal(calculateBundlePayableQuantity(11, { bundle: '11+1' }), 11, '11+1 payable qty should not discount 11')
assert.equal(calculateBundlePayableQuantity(12, { bundle: '11+1' }), 11, '11+1 payable qty should discount one bottle at 12')
assert.equal(calculateBundlePayableQuantity(13, { bundle: '11+1' }), 12, '11+1 payable qty should discount one bottle at 13')
assert.equal(calculateBundlePayableQuantity(24, { bundle: '11+1' }), 22, '11+1 payable qty should discount two bottles at 24')
assert.equal(calculateBundlePayableQuantity(12, { bundle: '11+1', bundle_discount_enabled: false }), 12, 'disabled 11+1 should charge all bottles')
assert.equal(calculateEdmLineSubtotal({ bundle: '11+1', quote_price: 5040 }, 12), 55440, '11+1 line subtotal should charge 11 units for 12 bottles')
assert.equal(resolveCerpVintage({ invn807: 2022, invn051: '2019' }), '2022', 'vintage should prefer invn807')
assert.equal(resolveCerpVintage({ invn051: '2019' }), '2019', 'vintage should fall back to invn051')
assert.equal(resolveCerpRating({ invn804: 'RP 95', invn803: '14.0%', invn805: 'Still' }), 'RP 95', 'rating should only use invn804')
assert.equal(resolveCerpProductName({ name_en: 'English Name', invn005: '中文名' }), 'English Name', 'product name should preserve normalized name_en')
assert.equal(resolveCerpColor({ color: 'Unknown', invn801: 'Red' }, '-'), 'Red', 'color should skip placeholders and use invn801')
assert.equal(
  resolveCerpStoreStock({
    wd4inv1as: [
      { name002: '仁愛-門市', inv1015: 4 },
      { name002: '潭美-A區', inv1015: 194 },
    ],
  }),
  4,
  'store stock should sum only store warehouse rows'
)
assert.equal(
  resolveCerpStoreStock({ wd4inv1as: [{ name002: '潭美-A區', inv1015: 194 }] }),
  0,
  'store stock should be zero when no store warehouse row is present'
)

console.log('verifyCerpMapping: mapping cases passed')
