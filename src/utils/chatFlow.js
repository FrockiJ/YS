const OPENAI_RATE_LIMIT_PATTERNS = [
  /\bhttp\s*429\b/i,
  /\bgeneration_error_status['"]?\s*[:=]\s*['"]?429\b/i,
  /\binsufficient_quota\b/i,
  /\brate_limit_exceeded\b/i,
  /\bOpenAIChatHTTPError\b/i,
  /\bRateLimitError\b/i,
]

const normalizeMetadata = (raw) => {
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
      return {}
    }
  }
  return {}
}

const collectSearchText = (value, seen = new Set()) => {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value instanceof Error) return [value.name, value.message, value.status, value.code, collectSearchText(value.payload, seen)].join(' ')
  if (typeof value !== 'object' || seen.has(value)) return ''
  seen.add(value)
  if (Array.isArray(value)) return value.map((item) => collectSearchText(item, seen)).join(' ')
  return Object.entries(value).map(([key, item]) => `${key} ${collectSearchText(item, seen)}`).join(' ')
}

export const isOpenAiRateLimitPayload = (value) => {
  if (!value) return false
  if (value?.status === 429 || value?.error?.status === 429 || value?.payload?.status === 429) return true
  return OPENAI_RATE_LIMIT_PATTERNS.some((pattern) => pattern.test(collectSearchText(value)))
}

export const resolveChatFlowErrorMessage = (error, t) => {
  if (error?.code === 'openai_429' || isOpenAiRateLimitPayload(error)) {
    const translated = t?.('api_errors.openai_429')
    return translated && translated !== 'api_errors.openai_429'
      ? translated
      : 'OpenAI 429: rate limit or quota exceeded. Please retry after quota recovers.'
  }
  return error?.message || ''
}

export const assertUsableChatResponse = (response, t) => {
  if (!isOpenAiRateLimitPayload(response)) return
  const error = new Error(resolveChatFlowErrorMessage(response, t))
  error.status = 429
  error.code = 'openai_429'
  error.payload = response
  throw error
}

export const normalizeChatAnswerPayload = (response, { fallbackLanguage, normalizeLanguage } = {}) => {
  const answer = response?.answer || {}
  const metadata = normalizeMetadata(answer.metadata)
  const responseLang = normalizeLanguage
    ? normalizeLanguage(metadata?.language || metadata?.lang || response?.language, fallbackLanguage)
    : metadata?.language || metadata?.lang || response?.language || fallbackLanguage
  return {
    answer,
    metadata: {
      ...metadata,
      answer_citations: Array.isArray(answer.citations) ? answer.citations : metadata?.answer_citations,
      result_card_summary_points:
        Array.isArray(answer.summary_points) && answer.summary_points.length
          ? answer.summary_points
          : metadata?.result_card_summary_points,
      summary_generation: metadata?.summary_generation || answer.summary_generation,
      language: metadata?.language || responseLang,
      lang: metadata?.lang || responseLang,
    },
    text: answer.text || response?.content || '',
    language: responseLang,
  }
}
