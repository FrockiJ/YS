const ERP_LOOKUP_OPERATIONS = new Set([
  'inventory_lookup',
  'brand_catalog',
  'product_lookup',
])

const normalizeToken = (value) => String(value || '').trim().toLowerCase()

const hasFactLookupMetadata = (metadata = {}) => {
  const answerMode = normalizeToken(
    metadata?.execution_plan?.answer_mode || metadata.answer_mode
  )
  if (answerMode === 'mixed') return false
  const erpLookup =
    metadata?.erp_lookup && typeof metadata.erp_lookup === 'object'
      ? metadata.erp_lookup
      : {}
  const operation = normalizeToken(
    erpLookup.operation || metadata.intent_lookup_operation || metadata.lookup_operation
  )
  return Boolean(
    ERP_LOOKUP_OPERATIONS.has(operation) ||
      normalizeToken(metadata.intent_task_type) === 'erp_lookup' ||
      (answerMode === 'erp_only' && metadata?.erp_query)
  )
}

const legacySourceKind = (metadata = {}, references = []) => {
  const sourceTiers = Array.isArray(metadata.source_tier)
    ? metadata.source_tier
    : [metadata.source_tier]
  const hasExternalEvidence =
    sourceTiers.map(normalizeToken).includes('external_evidence') ||
    Boolean(metadata?.external_search?.attempted) ||
    (Array.isArray(references) && references.some((reference) => reference?.kind === 'external'))
  return hasExternalEvidence ? 'external' : 'rag'
}

export const resolveKnowledgeSourceKind = (metadata = {}, references = []) => {
  if (hasFactLookupMetadata(metadata)) return 'erp'

  const knowledge =
    metadata?.knowledge && typeof metadata.knowledge === 'object'
      ? metadata.knowledge
      : null
  if (!knowledge) return legacySourceKind(metadata, references)

  const mode = normalizeToken(knowledge.mode)
  const ragStatus = normalizeToken(knowledge.rag_status)
  const externalStatus = normalizeToken(knowledge.external_status)
  const externalAttempted = knowledge.external_attempted === true

  if (mode === 'external_grounded' || externalStatus === 'used') return 'external'
  if (mode === 'rag_grounded' || ragStatus === 'used') return 'rag'
  if (externalAttempted && externalStatus === 'unavailable') return 'external_unavailable'
  if (externalAttempted && externalStatus !== 'used') return 'external_incomplete'
  return 'general'
}

const SOURCE_LOCALE_KEYS = {
  erp: {
    title: 'home.rag.erp_source_title',
    status: 'home.rag.erp_source_status',
  },
  external: {
    title: 'home.rag.external_search_title',
    status: 'home.rag.external_search_status',
  },
  external_unavailable: {
    title: 'home.rag.external_verification_unavailable_title',
    status: 'home.rag.external_verification_unavailable_status',
  },
  external_incomplete: {
    title: 'home.rag.external_verification_incomplete_title',
    status: 'home.rag.external_verification_incomplete_status',
  },
  rag: {
    title: 'home.rag.summary_title',
    status: 'home.rag.status_label',
  },
  general: {
    title: 'home.rag.general_knowledge_title',
    status: 'home.rag.general_knowledge_status',
  },
}

export const resolveKnowledgeSourceLocaleKey = (
  metadata = {},
  references = [],
  variant = 'title'
) => {
  const kind = resolveKnowledgeSourceKind(metadata, references)
  return SOURCE_LOCALE_KEYS[kind]?.[variant === 'status' ? 'status' : 'title']
}
