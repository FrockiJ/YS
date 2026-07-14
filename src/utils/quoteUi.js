import { i18n } from '../i18n'

export const DEFAULT_QUOTE_LANG = 'zh-Hant'
export const QUOTE_ACTION_RELAX = 'relax_constraints_and_regenerate'
export const QUOTE_ACTION_SHOW_RECOMMENDED = 'show_recommended_alternatives'
export const QUOTE_ACTION_INCLUDE_SIMILAR = 'include_similar_in_stock'
export const QUOTE_ACTION_FILL_SIMILAR = 'fill_with_similar_until_target'
export const QUOTE_ACTION_CONTINUE = 'continue_with_same_context'
export const QUOTE_ACTION_PIVOT_TO_QUOTE = 'pivot_to_quote_chat'

const normalizeStringList = (value) =>
  Array.isArray(value)
    ? value.map((entry) => String(entry || '').trim()).filter(Boolean)
    : []

const normalizeQuoteItems = (value) =>
  Array.isArray(value) ? value.filter((entry) => entry && typeof entry === 'object') : []

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
      const code = String(entry.no || entry.code || entry.id || '').trim()
      const name = String(entry.name || entry.name_en || entry.name_ch || entry.product || entry.title || '').trim()
      const producer = String(entry.producer || '').trim()
      if (!code && !name && !producer) return null
      return {
        ...entry,
        no: code || entry.no || entry.code || '',
        code: code || entry.code || entry.no || '',
        name: name || entry.name || entry.product || '',
        producer,
        stock_qty: entry.stock_qty ?? entry.stock ?? entry.total_stock ?? null,
        price: entry.price ?? entry.list_price ?? entry.vip_price ?? entry.quote_price ?? null,
        match_type: entry.match_type || 'cerp_result',
        source: entry.source || 'CERP',
      }
    })
    .filter(Boolean)
}

export const normalizeQuoteLanguage = (value, fallback = DEFAULT_QUOTE_LANG) => {
  if (value === 'en' || value === 'zh-Hant' || value === 'ja') return value
  return fallback
}

export const resolveQuoteLocale = (value, fallback = 'zh-TW') => {
  const normalized = normalizeQuoteLanguage(
    value,
    fallback === 'en' ? 'en' : fallback === 'ja' ? 'ja' : DEFAULT_QUOTE_LANG
  )
  if (normalized === 'en') return 'en'
  if (normalized === 'ja') return 'ja'
  return 'zh-TW'
}

export const detectQuoteLanguage = (value = '') => {
  if (!value) return DEFAULT_QUOTE_LANG
  if (/[\u3040-\u30ff]/.test(value)) return 'ja'
  return /[\u4e00-\u9fff]/.test(value) ? 'zh-Hant' : 'en'
}

export const formatQuoteUiGeneratedAt = (value, localeCode = 'zh-tw') => {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) return ''
  const normalizedLocale = String(localeCode || '').toLowerCase()
  const browserLocale = normalizedLocale.startsWith('zh')
    ? 'zh-TW'
    : normalizedLocale.startsWith('ja')
      ? 'ja-JP'
      : 'en-US'
  return date.toLocaleString(browserLocale, {
    hour12: false,
  })
}

const labelQuoteAlternative = (item = {}) =>
  [String(item.producer || '').trim(), String(item.name || item.product || item.no || '').trim()]
    .filter(Boolean)
    .join(' ')

const translateQuoteUi = (key, params = {}, language = DEFAULT_QUOTE_LANG) =>
  i18n.global.t(key, params, { locale: resolveQuoteLocale(language) })

const resolveFollowupCopy = (language = DEFAULT_QUOTE_LANG) => ({
  summaryFill: translateQuoteUi('home.quote_followup.summary_fill', {}, language),
  summaryInclude: translateQuoteUi('home.quote_followup.summary_include', {}, language),
  summaryRelax: translateQuoteUi('home.quote_followup.summary_relax', {}, language),
  summaryShow: translateQuoteUi('home.quote_followup.summary_show', {}, language),
  summaryContinue: translateQuoteUi('home.quote_followup.summary_continue', {}, language),
  fill: translateQuoteUi('home.quote_followup.fill', {}, language),
  fillPrompt: translateQuoteUi('home.quote_followup.fill_prompt', {}, language),
  include: translateQuoteUi('home.quote_followup.include', {}, language),
  includePrompt: translateQuoteUi('home.quote_followup.include_prompt', {}, language),
  relax: translateQuoteUi('home.quote_followup.relax', {}, language),
  relaxPrompt: translateQuoteUi('home.quote_followup.relax_prompt', {}, language),
  show: translateQuoteUi('home.quote_followup.show', {}, language),
  showPrompt: translateQuoteUi('home.quote_followup.show_prompt', {}, language),
  continueLabel: translateQuoteUi('home.quote_followup.continue_label', {}, language),
  continuePrompt: translateQuoteUi('home.quote_followup.continue_prompt', {}, language),
  pivotLabel: translateQuoteUi('home.quote_followup.pivot_label', {}, language),
  pivotPrompt: translateQuoteUi('home.quote_followup.pivot_prompt', {}, language),
})

const fillTemplate = (template, params = {}) =>
  String(template || '').replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? ''))

export const hasQuoteMetadata = (metadata = {}) =>
  Boolean(
    (metadata?.quote_ui && typeof metadata.quote_ui === 'object') ||
      (Array.isArray(metadata?.quote_items) && metadata.quote_items.length) ||
      (Array.isArray(metadata?.recommended_alternatives) && metadata.recommended_alternatives.length) ||
      (Array.isArray(metadata?.suggested_alternatives) && metadata.suggested_alternatives.length) ||
      (metadata?.quote_followup && typeof metadata.quote_followup === 'object') ||
      (metadata?.requested_filters && typeof metadata.requested_filters === 'object') ||
      (metadata?.recommendation_profile && typeof metadata.recommendation_profile === 'object') ||
      (Array.isArray(metadata?.available_actions) && metadata.available_actions.length) ||
      Number(metadata?.near_match_count || 0) > 0 ||
      String(metadata?.availability_result || '').trim() === 'near_match' ||
      String(metadata?.pending_goal || '').trim()
  )

const normalizePlainObject = (value) => (value && typeof value === 'object' && !Array.isArray(value) ? value : {})

export const collectStructuredUrlInputs = (source = {}) => {
  const metadata = normalizePlainObject(source)
  const urlInputs = normalizeStringList(metadata.url_inputs)
  if (urlInputs.length) return urlInputs
  const primaryUrl = String(metadata.primary_url || '').trim()
  return primaryUrl ? [primaryUrl] : []
}

export const buildVisibleUserPrompt = (message = '', urlInputs = []) => {
  const baseText = String(message || '').trim()
  const normalizedUrls = normalizeStringList(urlInputs)
  if (!normalizedUrls.length) return baseText
  const lines = baseText ? baseText.split('\n').map((line) => line.trim()) : []
  const existing = new Set(lines.filter(Boolean))
  normalizedUrls.forEach((url) => {
    if (!existing.has(url)) {
      lines.push(url)
      existing.add(url)
    }
  })
  return lines.filter(Boolean).join('\n')
}

export const extractActionableQuoteRows = (source = {}) => {
  const metadata = normalizePlainObject(source)
  const followup = normalizePlainObject(metadata.quote_followup)
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

export const hasActionableQuoteRows = (source = {}) => extractActionableQuoteRows(source).length > 0

export const extractQuoteContinuityPayload = (metadata = {}, options = {}) => {
  const source = normalizePlainObject(
    metadata?.quote_continuity && typeof metadata.quote_continuity === 'object'
      ? metadata.quote_continuity
      : metadata
  )
  const quoteFollowup = normalizePlainObject(source.quote_followup)
  const requestedFilters = normalizePlainObject(source.requested_filters)
  const recommendationProfile = normalizePlainObject(source.recommendation_profile)
  const contextResolution = normalizePlainObject(source.context_resolution)
  const availableActions = Array.isArray(source.available_actions)
    ? source.available_actions.map((entry) => String(entry || '').trim()).filter(Boolean)
    : []
  const intent = String(source.intent || '').trim().toUpperCase()

  if (
    !hasQuoteMetadata(source) &&
    !Object.keys(quoteFollowup).length &&
    !Object.keys(requestedFilters).length &&
    !Object.keys(recommendationProfile).length &&
    !availableActions.length &&
    !String(source.pending_goal || '').trim()
  ) {
    return null
  }

  return {
    intent: intent || 'QUOTE_LIST',
    conversation_id: options.conversationId || source.conversation_id || null,
    project: options.project || source.project || null,
    lang: normalizeQuoteLanguage(options.lang || source.lang || source.language, DEFAULT_QUOTE_LANG),
    surface_origin: String(options.surfaceOrigin || source.surface_origin || '').trim() || null,
    quote_intent_active: true,
    quote_followup: quoteFollowup,
    requested_filters: requestedFilters,
    recommendation_profile: recommendationProfile,
    available_actions: availableActions,
    pending_goal: String(source.pending_goal || '').trim() || null,
    default_confirm_action: String(source.default_confirm_action || '').trim() || null,
    target_count: Number(source.target_count || 0) || null,
    exact_count: Number(source.exact_count || 0) || null,
    remaining_needed: Number(source.remaining_needed || 0) || null,
    context_resolution: contextResolution,
    last_quote_message_id: options.messageId || source.last_quote_message_id || null,
    last_quote_created_at: options.createdAt || source.last_quote_created_at || null,
  }
}

const normalizeCount = (value) => {
  const count = Number(value)
  return Number.isFinite(count) && count > 0 ? count : null
}

const buildActionPrompt = (actionId, continuity = {}, language = DEFAULT_QUOTE_LANG) => {
  const targetCount = normalizeCount(continuity?.target_count)
  const copy = resolveFollowupCopy(language)
  switch (actionId) {
    case QUOTE_ACTION_FILL_SIMILAR:
      return fillTemplate(targetCount ? copy.fillPrompt : copy.fill, { target: targetCount || 5 })
    case QUOTE_ACTION_INCLUDE_SIMILAR:
      return copy.includePrompt
    case QUOTE_ACTION_RELAX:
      return copy.relaxPrompt
    case QUOTE_ACTION_SHOW_RECOMMENDED:
      return copy.showPrompt
    case QUOTE_ACTION_CONTINUE:
      return copy.continuePrompt
    default:
      return ''
  }
}

export const buildQuoteFollowupSummary = (continuity = {}, language = DEFAULT_QUOTE_LANG) => {
  if (hasActionableQuoteRows(continuity)) {
    return ''
  }
  const customSummary = String(continuity?.quote_followup?.summary || '').trim()
  if (customSummary) {
    return customSummary
  }
  const pendingGoal = String(continuity?.pending_goal || '').trim()
  const targetCount = normalizeCount(continuity?.target_count)
  const remainingNeeded = normalizeCount(continuity?.remaining_needed)
  const copy = resolveFollowupCopy(language)
  if (pendingGoal === QUOTE_ACTION_FILL_SIMILAR && targetCount && remainingNeeded) {
    return fillTemplate(copy.summaryFill, { remaining: remainingNeeded, target: targetCount })
  }
  if (pendingGoal === QUOTE_ACTION_INCLUDE_SIMILAR) {
    return copy.summaryInclude
  }
  if (pendingGoal === QUOTE_ACTION_RELAX) {
    return copy.summaryRelax
  }
  if (pendingGoal === QUOTE_ACTION_SHOW_RECOMMENDED) {
    return copy.summaryShow
  }
  if (pendingGoal === QUOTE_ACTION_CONTINUE) {
    return copy.summaryContinue
  }
  return ''
}

export const buildQuoteFollowupActions = (continuity = {}, language = DEFAULT_QUOTE_LANG) => {
  if (hasActionableQuoteRows(continuity)) {
    return []
  }
  const availableActions = Array.isArray(continuity?.available_actions)
    ? continuity.available_actions.map((entry) => String(entry || '').trim()).filter(Boolean)
    : []
  const defaultAction = String(continuity?.default_confirm_action || '').trim()
  const targetCount = normalizeCount(continuity?.target_count)
  const copy = resolveFollowupCopy(language)
  const customDefinitions =
    continuity?.quote_followup && typeof continuity.quote_followup === 'object'
      ? continuity.quote_followup.action_definitions || {}
      : {}
  const deduped = Array.from(new Set(availableActions))
  return deduped
    .map((actionId) => {
      const customDefinition =
        customDefinitions && typeof customDefinitions === 'object'
          ? customDefinitions[actionId] || null
          : null
      switch (actionId) {
        case QUOTE_ACTION_FILL_SIMILAR:
          return {
            id: actionId,
            label: fillTemplate(copy.fill, { target: targetCount || 5 }),
            prompt: buildActionPrompt(actionId, continuity, language),
            preferred: actionId === defaultAction,
          }
        case QUOTE_ACTION_INCLUDE_SIMILAR:
          return {
            id: actionId,
            label: copy.include,
            prompt: buildActionPrompt(actionId, continuity, language),
            preferred: actionId === defaultAction,
          }
        case QUOTE_ACTION_RELAX:
          return {
            id: actionId,
            label: copy.relax,
            prompt: buildActionPrompt(actionId, continuity, language),
            preferred: actionId === defaultAction,
          }
        case QUOTE_ACTION_SHOW_RECOMMENDED:
          return {
            id: actionId,
            label: copy.show,
            prompt: buildActionPrompt(actionId, continuity, language),
            preferred: actionId === defaultAction,
          }
        case QUOTE_ACTION_CONTINUE:
          return {
            id: actionId,
            label: copy.continueLabel,
            prompt: buildActionPrompt(actionId, continuity, language),
            preferred: actionId === defaultAction,
          }
        case QUOTE_ACTION_PIVOT_TO_QUOTE:
          return {
            id: actionId,
            label:
              String(customDefinition?.label || copy.pivotLabel || '').trim() ||
              (normalizeQuoteLanguage(language, DEFAULT_QUOTE_LANG) === 'en'
                ? 'Go to Quote'
                : '\u8f49\u5230\u8a62\u50f9'),
            prompt:
              String(customDefinition?.prompt || copy.pivotPrompt || '').trim() ||
              (normalizeQuoteLanguage(language, DEFAULT_QUOTE_LANG) === 'en'
                ? 'Continue this product in quote chat'
                : '\u628a\u9019\u6b3e\u9152\u5e36\u5230\u8a62\u50f9\u9801\u7e7c\u7e8c\u8655\u7406'),
            preferred:
              typeof customDefinition?.preferred === 'boolean'
                ? customDefinition.preferred
                : actionId === defaultAction,
          }
        default:
          if (customDefinition) {
            return {
              id: actionId,
              label: String(customDefinition?.label || actionId).trim(),
              prompt: String(customDefinition?.prompt || '').trim(),
              preferred:
                typeof customDefinition?.preferred === 'boolean'
                  ? customDefinition.preferred
                  : actionId === defaultAction,
            }
          }
          return null
      }
    })
    .filter((item) => item && item.prompt)
}

export const hasQuoteContinuity = (value = {}) => Boolean(extractQuoteContinuityPayload(value))

const buildFallbackQuoteUi = (metadata = {}, options = {}) => {
  const { createdAt = '', localeCode = 'zh-tw', language = DEFAULT_QUOTE_LANG } = options
  const quoteItems = Array.isArray(metadata.quote_items) ? metadata.quote_items : []
  const query =
    String(metadata.query || '').trim() || translateQuoteUi('home.quote_ui.default_query', {}, language)
  const count = quoteItems.length
  const resultLimit = Number(metadata.applied_result_limit || 0)
  const stockPolicy = String(metadata.stock_policy || '').trim()
  const availabilityResult = String(metadata.availability_result || '').trim()
  const nearMatchCount = Number(metadata.near_match_count || 0)
  const recommendedAlternatives = Array.isArray(metadata.recommended_alternatives)
    ? metadata.recommended_alternatives
        .map((item) => labelQuoteAlternative(item))
        .filter(Boolean)
        .slice(0, 3)
    : []
  const suggestedAlternatives = Array.isArray(metadata.suggested_alternatives)
    ? metadata.suggested_alternatives
        .map((item) => labelQuoteAlternative(item))
        .filter(Boolean)
        .slice(0, 3)
    : []

  if (!count) {
    if (recommendedAlternatives.length || suggestedAlternatives.length || availabilityResult === 'near_match' || nearMatchCount > 0) {
      const candidateCount = nearMatchCount || recommendedAlternatives.length || suggestedAlternatives.length
      const fallbackClosingBullets = [
        translateQuoteUi('home.quote_ui.near_match_closing_bullet_count', { count: candidateCount }, language),
        translateQuoteUi('home.quote_ui.near_match_closing_bullet_review', {}, language),
        translateQuoteUi('home.quote_ui.near_match_closing_bullet_continue', {}, language),
      ]
      const closingBullets =
        recommendedAlternatives.length > 0
          ? recommendedAlternatives
          : suggestedAlternatives.length > 0
            ? suggestedAlternatives
            : fallbackClosingBullets
      return {
        kind: 'quote_response',
        title: translateQuoteUi('home.quote_ui.near_match_title', { query }, language),
        status: translateQuoteUi('home.quote_ui.status_warning', {}, language),
        statusVariant: 'warning',
        generatedAt: formatQuoteUiGeneratedAt(createdAt, localeCode),
        intro: translateQuoteUi('home.quote_ui.near_match_intro', {}, language),
        introBullets: [
          translateQuoteUi('home.quote_ui.near_match_bullet_count', { count: candidateCount }, language),
          translateQuoteUi('home.quote_ui.near_match_bullet_review', {}, language),
          translateQuoteUi('home.quote_ui.near_match_bullet_action', {}, language),
        ],
        closing: translateQuoteUi('home.quote_ui.near_match_closing', {}, language),
        closingBullets,
      }
    }
    return {
      kind: 'quote_response',
      title: translateQuoteUi('home.quote_ui.empty_title', { query }, language),
      status: translateQuoteUi('home.quote_ui.status_empty', {}, language),
      statusVariant: 'empty',
      generatedAt: formatQuoteUiGeneratedAt(createdAt, localeCode),
      intro: translateQuoteUi('home.quote_ui.empty_intro', { query }, language),
      introBullets: [
        translateQuoteUi('home.quote_ui.empty_bullet_request', {}, language),
        translateQuoteUi('home.quote_ui.empty_bullet_inventory', {}, language),
        translateQuoteUi('home.quote_ui.empty_bullet_refine', {}, language),
      ],
      closing: translateQuoteUi('home.quote_ui.empty_closing', {}, language),
      closingBullets: [
        translateQuoteUi('home.quote_ui.empty_closing_bullet_alternative', {}, language),
        translateQuoteUi('home.quote_ui.empty_closing_bullet_region', {}, language),
        translateQuoteUi('home.quote_ui.empty_closing_bullet_style', {}, language),
      ],
    }
  }

  if (stockPolicy === 'in_stock_only' && resultLimit && count < resultLimit) {
    return {
      kind: 'quote_response',
      title: translateQuoteUi(
        'home.quote_ui.shortage_title',
        { count, requested: resultLimit, query },
        language
      ),
      status: translateQuoteUi('home.quote_ui.status_warning', {}, language),
      statusVariant: 'warning',
      generatedAt: formatQuoteUiGeneratedAt(createdAt, localeCode),
      intro: translateQuoteUi(
        'home.quote_ui.shortage_intro',
        { query, count, requested: resultLimit },
        language
      ),
      introBullets: [
        translateQuoteUi(
          'home.quote_ui.shortage_bullet_count',
          { count, requested: resultLimit },
          language
        ),
        translateQuoteUi('home.quote_ui.bullet_quote_info', {}, language),
        translateQuoteUi('home.quote_ui.bullet_wine_details', {}, language),
        ...(suggestedAlternatives.length
          ? [
              translateQuoteUi(
                'home.quote_ui.shortage_bullet_alternatives',
                { count: suggestedAlternatives.length },
                language
              ),
            ]
          : []),
      ],
      closing: translateQuoteUi('home.quote_ui.shortage_closing', {}, language),
      closingBullets:
        suggestedAlternatives.length > 0
          ? suggestedAlternatives
          : [translateQuoteUi('home.quote_ui.closing_bullet_more', {}, language)],
    }
  }

  return {
    kind: 'quote_response',
    title: translateQuoteUi('home.quote_ui.success_title', { query, count }, language),
    status: translateQuoteUi('home.quote_ui.status_ready', {}, language),
    statusVariant: 'success',
    generatedAt: formatQuoteUiGeneratedAt(createdAt, localeCode),
    intro: translateQuoteUi('home.quote_ui.success_intro', { query }, language),
    introBullets: [
      translateQuoteUi('home.quote_ui.success_bullet_count', { count }, language),
      translateQuoteUi('home.quote_ui.bullet_quote_info', {}, language),
      translateQuoteUi('home.quote_ui.bullet_wine_details', {}, language),
      translateQuoteUi('home.quote_ui.bullet_compare', {}, language),
    ],
    closing: translateQuoteUi('home.quote_ui.success_closing', {}, language),
    closingBullets: [
      translateQuoteUi('home.quote_ui.closing_bullet_filter', {}, language),
      translateQuoteUi('home.quote_ui.closing_bullet_save', {}, language),
      translateQuoteUi('home.quote_ui.closing_bullet_more', {}, language),
    ],
  }
}

export const normalizeQuoteUiPayload = (metadata = {}, options = {}) => {
  const { createdAt = '' } = options
  const language = normalizeQuoteLanguage(
    options.language || metadata?.language || metadata?.lang,
    DEFAULT_QUOTE_LANG
  )
  const localeCode = options.localeCode || resolveQuoteLocale(language)
  const value = metadata?.quote_ui
  if (value && typeof value === 'object') {
    return {
      kind: String(value.kind || '').trim(),
      title: String(value.title || '').trim(),
      status: String(value.status || '').trim(),
      statusVariant: String(value.status_variant || '').trim() || 'success',
      generatedAt:
        String(value.generated_at || '').trim() || formatQuoteUiGeneratedAt(createdAt, localeCode),
      intro: String(value.intro || '').trim(),
      introBullets: Array.isArray(value.intro_bullets)
        ? value.intro_bullets.map((entry) => String(entry || '').trim()).filter(Boolean)
        : [],
      closing: String(value.closing || '').trim(),
      closingBullets: Array.isArray(value.closing_bullets)
        ? value.closing_bullets.map((entry) => String(entry || '').trim()).filter(Boolean)
        : [],
    }
  }

  return hasQuoteMetadata(metadata)
    ? buildFallbackQuoteUi(metadata, {
        ...options,
        language,
        localeCode,
      })
    : null
}

export const buildQuoteShareText = (quoteUi = null, fallbackText = '') => {
  if (!quoteUi) {
    return String(fallbackText || '').trim()
  }

  return [
    quoteUi.intro,
    ...(quoteUi.introBullets || []).map((entry) => `• ${entry}`),
    quoteUi.title,
    quoteUi.closing,
    ...(quoteUi.closingBullets || []).map((entry) => `• ${entry}`),
  ]
    .map((entry) => String(entry || '').trim())
    .filter(Boolean)
    .join('\n')
}
