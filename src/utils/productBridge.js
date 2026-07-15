export const getProductBridge = (message = {}) => {
  const bridge = message?.metadata?.product_bridge
  return bridge && typeof bridge === 'object' && !Array.isArray(bridge) ? bridge : null
}

export const getProductBridgeSourceId = (message = {}) => {
  const bridge = getProductBridge(message)
  return String(bridge?.source_message_id || message?.id || '').trim()
}

export const isPendingProductBridge = (message = {}, fulfilledIds = new Set()) => {
  const bridge = getProductBridge(message)
  const sourceId = getProductBridgeSourceId(message)
  return Boolean(
    sourceId &&
      bridge?.eligible === true &&
      bridge?.trigger === 'button' &&
      bridge?.fulfilled !== true &&
      !fulfilledIds.has(sourceId)
  )
}

const DEFAULT_REQUIREMENT_LABELS = {
  rain_protection: '防雨',
  shelter: '遮蔽',
  sleeping_gear: '睡眠保暖',
  lighting: '照明',
  cooking_water: '炊事與飲水',
  storage_packs: '背負與乾燥收納',
  power: '供電',
  safety_repair: '安全與維修',
  fishing_gear: '釣魚裝備',
  waterproof: '防水',
  lightweight: '輕量',
  compact: '易收納',
  warm: '保暖',
}

export const formatProductRecommendationReason = (item = {}, rawReason = '', translate = null) => {
  const raw = String(rawReason || '').trim()
  const exposesInternalCode = /(?:category|feature|weather|activity|brand):|\b[a-z]+_[a-z_]+\b/.test(raw)
  if (raw && !exposesInternalCode) return raw
  const matched = Array.isArray(item?.matched_requirements) ? item.matched_requirements : []
  const labels = matched
    .map((value) => String(value || '').split(':').pop())
    .map((code) => {
      if (typeof translate === 'function') {
        const key = `home.product_bridge.requirements.${code}`
        const translated = translate(key)
        if (translated && translated !== key) return translated
      }
      return DEFAULT_REQUIREMENT_LABELS[code]
    })
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .slice(0, 3)
  if (!labels.length) {
    return typeof translate === 'function'
      ? translate('home.product_bridge.generic_reason')
      : '符合目前的商品需求與可售條件。'
  }
  return typeof translate === 'function'
    ? translate('home.product_bridge.legacy_reason', { requirements: labels.join('、') })
    : `符合${labels.join('、')}需求，且為 ERP 實際可用商品。`
}

export const normalizeProductResults = (metadata = {}, translate = null) => {
  if (!Array.isArray(metadata?.product_results)) return []
  return metadata.product_results
    .filter((item) => item && typeof item === 'object' && String(item.sku || '').trim())
    .map((item) => ({
      sku: String(item.sku).trim(),
      name: String(item.name || '').trim(),
      brand: String(item.brand || '').trim(),
      category: String(item.category || '').trim(),
      specification: String(item.specification || '').trim(),
      price: item.price ?? null,
      stock: item.stock ?? null,
      recommendationReason: formatProductRecommendationReason(
        item,
        item.recommendation_reason,
        translate
      ),
      matchedRequirements: Array.isArray(item.matched_requirements) ? item.matched_requirements : [],
      sourceTimestamp: String(item.source_timestamp || '').trim(),
    }))
}
