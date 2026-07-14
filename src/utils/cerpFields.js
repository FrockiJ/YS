export const DEFAULT_EDM_QUOTE_TIER = 'vip'
export const EDM_QUOTE_TIERS = ['vip', 'fb', 'wholesale']
export const ELEVEN_PLUS_ONE_BUNDLE_TYPE = 'eleven_plus_one'

const hasValue = (value) => value !== undefined && value !== null && value !== ''

const COLOR_PLACEHOLDER_VALUES = new Set([
  '-',
  'unknown',
  '未知',
  'n/a',
  'na',
  'null',
  'undefined',
])

const BUNDLE_PLACEHOLDER_VALUES = new Set([
  ...COLOR_PLACEHOLDER_VALUES,
  '無',
  'none',
  'no',
  'not applicable',
])

const STORE_STOCK_TEXT_KEYS = [
  'name002',
  'warehouse_name',
  'warehouseName',
  'location',
  'name',
  'note',
  'inv1049',
  'inv1002',
  'warehouse_code',
  'code',
]

const STORE_STOCK_KEYWORDS = ['精品', '門市', '門店', '店面', 'store', 'boutique', 'shop', 'retail']

const pickFirst = (row = {}, keys = []) => {
  for (const key of keys) {
    const value = row?.[key]
    if (hasValue(value)) return value
  }
  return null
}

export const resolveCerpField = (row = {}, sourceKeys = [], fallback = '') =>
  toDisplayString(pickFirst(row, sourceKeys), fallback)

const toDisplayString = (value, fallback = '') => {
  if (!hasValue(value)) return fallback
  const numeric = Number(value)
  if (Number.isFinite(numeric) && String(value).trim() !== '') {
    if (Number.isInteger(numeric)) return String(numeric)
  }
  return String(value).trim() || fallback
}

export const toNullableNumber = (value) => {
  if (!hasValue(value)) return null
  const normalized = String(value).trim().replace(/,/g, '')
  if (!normalized) return null
  const numeric = Number(normalized)
  if (Number.isFinite(numeric)) return numeric
  const match = normalized.match(/-?\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : null
}

const isPlaceholderDisplayValue = (value) => {
  if (!hasValue(value)) return true
  const normalized = String(value).trim().toLowerCase()
  return !normalized || COLOR_PLACEHOLDER_VALUES.has(normalized)
}

export const normalizeEdmQuoteTier = (value) =>
  EDM_QUOTE_TIERS.includes(value) ? value : DEFAULT_EDM_QUOTE_TIER

export const resolveCerpCode = (row = {}, fallback = '-') =>
  toDisplayString(pickFirst(row, ['no', 'id', 'invn002']), fallback)

export const resolveCerpVintage = (row = {}, fallback = '') =>
  toDisplayString(pickFirst(row, ['invn807', 'vintage', 'invn051']), fallback)

export const resolveCerpProducer = (row = {}, fallback = '') =>
  toDisplayString(pickFirst(row, ['producer', 'invn006']), fallback)

export const resolveCerpProductName = (row = {}, fallback = '') =>
  toDisplayString(
    pickFirst(row, [
      'invn077',
      'product',
      'product_name',
      'productName',
      'name_en',
      'name',
      'name_ch',
      'invn005',
      'title',
    ]),
    fallback
  )

export const resolveCerpColor = (row = {}, fallback = '') => {
  const colorKeys = ['color', 'invn801', 'wine_color', 'wineColor', 'Color']
  for (const key of colorKeys) {
    const displayValue = toDisplayString(row?.[key], '')
    if (!isPlaceholderDisplayValue(displayValue)) return displayValue
  }
  return fallback
}

export const resolveCerpRating = (row = {}, fallback = '') =>
  toDisplayString(pickFirst(row, ['rating', 'invn804']), fallback)

export const resolveCerpBundle = (row = {}, fallback = '') =>
  toDisplayString(pickFirst(row, ['invn048', 'bundle']), fallback)

export const resolveCerpBundleDisplay = (rowOrValue = {}, fallback = '-') => {
  const value =
    rowOrValue && typeof rowOrValue === 'object'
      ? resolveCerpBundle(rowOrValue, '')
      : toDisplayString(rowOrValue, '')
  const display = String(value || '').trim()
  const normalized = display.toLowerCase()
  if (!display || BUNDLE_PLACEHOLDER_VALUES.has(normalized)) return fallback
  return display
}

export const isElevenPlusOneBundle = (rowOrBundle = '') => {
  const bundle =
    rowOrBundle && typeof rowOrBundle === 'object'
      ? resolveCerpBundle(rowOrBundle, '')
      : toDisplayString(rowOrBundle, '')
  const normalized = String(bundle || '')
    .replace(/\s+/g, '')
    .replace(/＋/g, '+')
    .toLowerCase()
  return /(^|[^0-9])11\+1($|[^0-9])/.test(normalized)
}

export const resolveBundleDiscountType = (row = {}) =>
  isElevenPlusOneBundle(row) ? ELEVEN_PLUS_ONE_BUNDLE_TYPE : ''

export const isBundleDiscountEnabled = (row = {}) =>
  isElevenPlusOneBundle(row) && row?.bundle_discount_enabled !== false

export const calculateBundleFreeQuantity = (quantity = 0, row = {}) => {
  const qty = Math.max(0, Math.floor(toNullableNumber(quantity) ?? 0))
  if (!isBundleDiscountEnabled(row)) return 0
  return Math.floor(qty / 12)
}

export const calculateBundlePayableQuantity = (quantity = 0, row = {}) => {
  const qty = Math.max(0, Math.floor(toNullableNumber(quantity) ?? 0))
  return Math.max(0, qty - calculateBundleFreeQuantity(qty, row))
}

export const resolveCerpListPrice = (row = {}) =>
  toNullableNumber(pickFirst(row, ['list_price', 'amount', 'invn013', 'price']))

export const resolveCerpVipPrice = (row = {}) =>
  toNullableNumber(pickFirst(row, ['vip_price', 'quote_price', 'display_quote_price', 'invn015', 'amount', 'invn013', 'vip']))

export const resolveCerpFbPrice = (row = {}) =>
  toNullableNumber(pickFirst(row, ['fb_price', 'invn017', 'fb']))

export const resolveCerpWholesalePrice = (row = {}) =>
  toNullableNumber(
    pickFirst(row, ['wholesale_price', 'invn808', 'invn080', 'wholesale', 'dealer_price', 'dealer'])
  )

const sumCerpWarehouseStock = (rows = []) => {
  if (!Array.isArray(rows)) return 0
  return rows.reduce((total, entry) => {
    const value = toNullableNumber(entry?.inv1015 ?? entry?.quantity ?? entry?.stock ?? entry?.stock_qty)
    return total + (value ?? 0)
  }, 0)
}

const getCerpWarehouseRows = (row = {}) => {
  if (Array.isArray(row?.wd4inv1as)) return row.wd4inv1as
  if (Array.isArray(row?.warehouses)) return row.warehouses
  return []
}

export const resolveCerpStock = (row = {}) => {
  const direct = toNullableNumber(pickFirst(row, ['stock_qty', 'total_stock', 'stock']))
  if (direct !== null) return Math.max(0, direct)
  return Math.max(0, sumCerpWarehouseStock(getCerpWarehouseRows(row)))
}

const isStoreWarehouseEntry = (entry = {}) =>
  STORE_STOCK_TEXT_KEYS.some((key) => {
    const value = entry?.[key]
    if (!hasValue(value)) return false
    const normalized = String(value).trim().toLowerCase()
    return STORE_STOCK_KEYWORDS.some((keyword) => normalized.includes(keyword))
  })

export const resolveCerpStoreStock = (row = {}) => {
  const direct = toNullableNumber(pickFirst(row, ['store_stock', 'boutique_stock', 'retail_stock']))
  if (direct !== null) return Math.max(0, direct)
  const warehouseRows = getCerpWarehouseRows(row).filter(isStoreWarehouseEntry)
  return Math.max(0, sumCerpWarehouseStock(warehouseRows))
}

export const resolveCerpStockSourceType = (row = {}) => {
  const direct = toDisplayString(pickFirst(row, ['stock_source_type']), '')
  if (direct) return direct
  return resolveCerpStoreStock(row) > 0 ? 'store_stock' : 'overall_stock'
}

export const resolveCerpStockSourceLabel = (row = {}, fallback = '', labels = {}) => {
  const direct = toDisplayString(pickFirst(row, ['stock_source_label']), '')
  if (direct) return direct
  const sourceType = resolveCerpStockSourceType(row)
  if (sourceType === 'store_stock') return labels.store_stock || fallback
  if (sourceType === 'overall_stock') return labels.overall_stock || fallback
  return fallback
}

export const resolveStoredEdmQuotePrice = (row = {}) =>
  toNullableNumber(pickFirst(row, ['display_quote_price', 'quote_price', 'quote', 'amount', 'invn015', 'invn013']))

export const resolveEdmQuotePriceForTier = (row = {}, tier = DEFAULT_EDM_QUOTE_TIER) => {
  const normalizedTier = normalizeEdmQuoteTier(tier)
  if (normalizedTier === 'vip') return resolveCerpVipPrice(row)
  if (normalizedTier === 'fb') return resolveCerpFbPrice(row)
  return resolveCerpWholesalePrice(row)
}

export const resolveEdmUnitPrice = (row = {}) => {
  const storedQuotePrice = resolveStoredEdmQuotePrice(row)
  if (storedQuotePrice !== null) return storedQuotePrice
  const tierPrice = resolveEdmQuotePriceForTier(row, row?.selected_quote_tier || DEFAULT_EDM_QUOTE_TIER)
  if (tierPrice !== null) return tierPrice
  return toNullableNumber(pickFirst(row, ['quote', 'vip_price', 'fb_price', 'wholesale_price']))
}

export const buildCerpPricingState = (
  row = {},
  preferredTier = row?.selected_quote_tier || DEFAULT_EDM_QUOTE_TIER
) => {
  const listPrice = resolveCerpListPrice(row)
  const vipPrice = resolveCerpVipPrice(row)
  const fbPrice = resolveCerpFbPrice(row)
  const wholesalePrice = resolveCerpWholesalePrice(row)
  const normalizedTier = normalizeEdmQuoteTier(preferredTier)
  const storedTier = normalizeEdmQuoteTier(row?.selected_quote_tier)
  const storedQuotePrice = resolveStoredEdmQuotePrice(row)
  const explicitTierQuotePrice = resolveEdmQuotePriceForTier(row, normalizedTier)
  const displayQuotePrice =
    explicitTierQuotePrice ??
    (storedQuotePrice !== null && storedTier === normalizedTier ? storedQuotePrice : null)

  return {
    list_price: listPrice,
    vip_price: vipPrice,
    fb_price: fbPrice,
    wholesale_price: wholesalePrice,
    selected_quote_tier: normalizedTier,
    display_quote_price: displayQuotePrice,
    quote_price: displayQuotePrice,
  }
}

export const calculateEdmLineSubtotal = (row = {}, quantity = row?.quantity) => {
  const unitPrice = resolveEdmUnitPrice(row) ?? 0
  return unitPrice * calculateBundlePayableQuantity(quantity, row)
}
