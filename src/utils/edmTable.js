import {
  resolveCerpBrand,
  resolveCerpBundleDisplay,
  resolveCerpCode,
  resolveCerpColor,
  resolveCerpFeature,
  resolveCerpProductName,
  resolveCerpSpecification,
} from './cerpFields.js'

export const LEGACY_EDM_TABLE_COLUMNS = Object.freeze([
  { key: 'no', label: 'Code', width: 110 },
  { key: 'specification', label: 'Model Year', width: 100 },
  { key: 'brand', label: 'Brand / Supplier', width: 130 },
  { key: 'product', label: 'Product', width: 220 },
  { key: 'color', label: 'Color', width: 90 },
  { key: 'feature', label: 'Feature', width: 100 },
  { key: 'list_price', label: 'Price', width: 110 },
  { key: 'quote_price', label: 'VIP Price', width: 110 },
  { key: 'bundle', label: 'Bundle', width: 90 },
])

const hasValue = (value) => value !== undefined && value !== null && value !== ''

export const normalizeEdmTableColumns = (columns) => {
  const source = Array.isArray(columns) && columns.length ? columns : LEGACY_EDM_TABLE_COLUMNS
  const seen = new Set()
  return source.reduce((normalized, column) => {
    const rawKey = String(column?.key || '').trim()
    const key = rawKey === 'spec' ? 'specification' : rawKey
    if (!key || seen.has(key)) return normalized
    seen.add(key)
    const width = Number(column?.width)
    normalized.push({
      key,
      label: String(column?.label || (key === 'specification' ? '型號／規格' : key)),
      ...(Number.isFinite(width) && width > 0 ? { width } : {}),
    })
    return normalized
  }, [])
}

export const snapshotEdmTableColumns = (columns) =>
  normalizeEdmTableColumns(columns).map(({ key, label, width }) => ({
    key,
    label,
    ...(width ? { width } : {}),
  }))

export const isEdmProductColumn = (key) => key === 'product'
export const isEdmColorColumn = (key) => key === 'color'
export const isEdmBundleColumn = (key) => key === 'bundle'
export const isEdmPriceColumn = (key) =>
  ['price', 'list_price', 'vip', 'quote_price', 'display_quote_price', 'vip_price', 'fb_price', 'wholesale_price'].includes(key)

export const resolveEdmTableValue = (row = {}, key = '') => {
  if (key === 'no') return resolveCerpCode(row, '-')
  if (key === 'specification' || key === 'spec') return resolveCerpSpecification(row, '-')
  if (key === 'brand') return resolveCerpBrand(row, '-')
  if (key === 'product') return resolveCerpProductName(row, '-')
  if (key === 'color') return resolveCerpColor(row, '-')
  if (key === 'feature') return resolveCerpFeature(row, '-')
  if (key === 'bundle') return resolveCerpBundleDisplay(row)
  if (key === 'price' || key === 'list_price') return row.price ?? row.list_price
  if (key === 'vip' || key === 'quote_price' || key === 'display_quote_price') {
    return row.display_quote_price ?? row.quote_price ?? row.vip ?? row.vip_price
  }
  return hasValue(row?.[key]) ? row[key] : '-'
}
