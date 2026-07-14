const coercePriceNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const cleaned = String(value)
    .replace(/[,$\s]/g, '')
    .replace(/^US/i, '')
    .replace(/[^0-9.-]/g, '')
  if (!cleaned || cleaned === '-' || cleaned === '.' || cleaned === '-.') return null
  const numeric = Number(cleaned)
  return Number.isFinite(numeric) ? numeric : null
}

export const parseUsdInput = (value) => coercePriceNumber(value)

export const formatUsdPrice = (value, fallback = '-') => {
  const numeric = coercePriceNumber(value)
  if (numeric === null) return fallback
  const rounded = Math.round(numeric)
  return `$${rounded.toLocaleString('en-US')}`
}

export const formatUsdInput = (value) => formatUsdPrice(value, '$0')
