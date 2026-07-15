const normalizeQuoteItems = (value) =>
  Array.isArray(value) ? value.filter((entry) => entry && typeof entry === 'object') : []

const normalizePlainObject = (value) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}

const normalizeCerpResultItems = (value) => {
  const sourceItems =
    value && typeof value === 'object' && Array.isArray(value.items)
      ? value.items
      : Array.isArray(value)
        ? value
        : []
  return sourceItems
    .filter((entry) => entry && typeof entry === 'object')
    .map((entry) => {
      const code = String(entry.sku || entry.no || entry.code || entry.id || '').trim()
      const name = String(entry.name || entry.name_en || entry.name_ch || entry.product || entry.title || '').trim()
      const brand = String(entry.brand || '').trim()
      if (!code && !name && !brand) return null
      return {
        ...entry,
        no: code || entry.no || entry.code || '',
        code: code || entry.code || entry.no || '',
        name: name || entry.name || entry.product || '',
        brand,
        stock_qty: entry.stock_qty ?? entry.stock ?? entry.total_stock ?? null,
        price: entry.price ?? entry.list_price ?? entry.vip_price ?? entry.quote_price ?? null,
        match_type: entry.match_type || 'cerp_result',
        source: entry.source || 'CERP',
      }
    })
    .filter(Boolean)
}

export const extractActionableQuoteRows = (source = {}) => {
  const metadata = normalizePlainObject(source)
  const followup = normalizePlainObject(metadata.quote_followup)
  const productResults = normalizeCerpResultItems(metadata.product_results)
  if (productResults.length) return productResults
  const quoteItems = normalizeQuoteItems(metadata.quote_items)
  if (quoteItems.length) return quoteItems
  const exactQuoteItems = normalizeQuoteItems(followup.exact_quote_items || metadata.exact_quote_items)
  if (exactQuoteItems.length) return exactQuoteItems
  const suggestedAlternatives = normalizeQuoteItems(
    metadata.suggested_alternatives || followup.suggested_alternatives
  )
  if (suggestedAlternatives.length) return suggestedAlternatives
  const cerpResultItems = normalizeCerpResultItems(metadata.cerp_results)
  if (cerpResultItems.length) return cerpResultItems
  return normalizeQuoteItems(metadata.recommended_alternatives || followup.recommended_alternatives)
}
