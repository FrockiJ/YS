import { createLabelQrSvg, normalizeLabelCode } from './labelQr.js'

export const LABEL_SIZES = Object.freeze(['small', 'medium', 'large'])
export const LABEL_QR_SIZES_MM = Object.freeze({ small: 14, medium: 18, large: 24 })
export const MAX_LABEL_DESCRIPTION_LENGTH = 220

export const normalizeLabelSize = (size) =>
  LABEL_SIZES.includes(String(size || '').toLowerCase()) ? String(size).toLowerCase() : 'large'

const asObject = (value) => (value && typeof value === 'object' ? value : {})
const firstValue = (...values) => values.find((value) => String(value ?? '').trim()) ?? ''

const resolveProduct = (source) => {
  const item = asObject(source)
  return Object.keys(asObject(item.product_snapshot)).length ? item.product_snapshot : item
}

const resolvePrice = (source, product, override) => {
  const explicit = Number(override ?? source?.price_override)
  const raw = Number.isFinite(explicit) && explicit > 0
    ? explicit
    : Number(product?.list_price ?? product?.invn013 ?? product?.price ?? product?.invn015)
  if (!Number.isFinite(raw) || raw <= 0) return ''
  return `$${raw.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

export const buildLabelPreviewModel = (source = {}, options = {}) => {
  const item = asObject(source)
  const product = resolveProduct(item)
  const size = normalizeLabelSize(options.size || item.size)
  const code = normalizeLabelCode(
    firstValue(item.code, item.sku, item.no, product.no, product.sku, product.code, product.id, product.invn002)
  )
  const description = String(options.description ?? item.description ?? '').trim()

  return {
    size,
    code,
    qrSvg: createLabelQrSvg(code),
    qrSizeMm: LABEL_QR_SIZES_MM[size],
    brand: String(firstValue(product.brand, product.supplier, product.invn006)).trim(),
    name: String(firstValue(product.name_en, product.name_ch, product.name, product.invn005, product.title)).trim(),
    price: resolvePrice(item, product, options.priceOverride),
    feature: String(firstValue(product.feature, product.material, product.invn804, product.invn805)).trim() || '-',
    specification: String(firstValue(product.specification, product.spec, product.invn051, product.invn807)).trim() || '-',
    category: String(firstValue(product.category, product.invn030)).trim() || '-',
    description: description.slice(0, MAX_LABEL_DESCRIPTION_LENGTH),
  }
}
