<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import logoMain from '../assets/ysLogo_transparent.png'
import iconChatProject from '../assets/ic_chat_p.svg'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import arrowButtonAsset from '../assets/arrow-button.svg'
import topPenIcon from '../assets/top-pen.svg'
import chatToolbarCopy from '../assets/chat-toolbar-copy.svg'
import chatToolbarShare from '../assets/chat-toolbar-share.svg'
import chatToolbarShareIc from '../assets/chat-toolbar-share-ic.svg'
import LoginLayout from '../components/LoginLayout.vue'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import TopAdviceBar from '../components/TopAdviceBar.vue'
import ChatComposer from '../components/ChatComposer.vue'
import ChatProductCard from '../components/ChatProductCard.vue'
import QuoteResponseRenderer from '../components/QuoteResponseRenderer.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import {
  sendChatMessage,
  fetchConversationHistory,
  fetchConversationMessages,
  fetchProjects,
  fetchProjectConversationSearch,
  fetchProjectNameMap,
  renameConversation,
  updateConversationProject,
  updateConversationVisibility,
  archiveConversation,
  fetchConversationInvitations,
  createConversationInvitation,
  deleteConversationInvitation,
  searchInvitationCandidates,
} from '../services/ysApi'
import { useAuth } from '../composables/useAuth'
import { useFileUploader } from '../composables/useFileUploader'
import { canAccessPermissionModule } from '../utils/accessControl'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'
import { writeClipboard } from '../utils/clipboard'
import { buildUserAvatarLabel, normalizeAuthorField } from '../utils/userAvatarLabel'
import { resolveCerpColor, resolveCerpStock } from '../utils/cerpFields'
import {
  QUOTE_ACTION_PIVOT_TO_QUOTE,
  buildVisibleUserPrompt,
  buildQuoteFollowupActions,
  buildQuoteFollowupSummary,
  buildQuoteShareText as buildQuoteShareTextContent,
  collectStructuredUrlInputs,
  detectQuoteLanguage,
  extractActionableQuoteRows,
  extractQuoteContinuityPayload,
  hasQuoteContinuity,
  normalizeQuoteLanguage,
  normalizeQuoteUiPayload,
} from '../utils/quoteUi'

const router = useRouter()
const { t, tm, locale } = useI18n()

const { isAuthenticated, userProfile, clearSession } = useAuth()
const INVITE_LOOKUP_MIN_LENGTH = 2
const canViewPermissionMembers = computed(() => {
  return canAccessPermissionModule(userProfile.value)
})

const iconImages = PRIMARY_NAV_ICON_IMAGES

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'home.nav'))

const DEFAULT_CONVERSATION_TITLE = t('home.defaults.conversation_title')
const INBOX_LABEL = t('home.sections.inbox')
const defaultAssistantText = t('home.defaults.assistant_text')
const DEFAULT_HIGHLIGHTS = (tm('home.defaults.highlights') || []).slice()
const DEFAULT_NEXT_STEPS = (tm('home.defaults.next_steps') || []).slice()
const defaultUserPrompt = t('home.defaults.user_prompt')

const dialogHistory = ref([])
const isHistoryLoading = ref(false)
const historyError = ref('')

const PINNED_STORAGE_KEY = 'ys-pinned-conversations'

const readPinnedIdList = () => {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(PINNED_STORAGE_KEY)
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed.filter(Boolean) : []
  } catch {
    return []
  }
}

const persistPinnedIdList = (ids) => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(ids))
  } catch {
    window.localStorage.removeItem(PINNED_STORAGE_KEY)
  }
}

const pinnedConversationIds = ref(new Set(readPinnedIdList()))

const ensureIsoString = (value) => {
  if (!value) return null
  if (typeof value === 'string') return value
  if (value instanceof Date) return value.toISOString()
  return null
}

const normalizeWhitespace = (value = '') =>
  String(value || '')
    .replace(/\s+/g, ' ')
    .trim()

const normalizeVisibility = (value = '') => (value === 'public' ? 'public' : 'private')
const formatVisibilityLabel = (value = '') =>
  normalizeVisibility(value) === 'public'
    ? t('home.visibility.public')
    : t('home.visibility.private')
const resolveVisibilityClass = (value = '') =>
  normalizeVisibility(value) === 'public' ? 'is-public' : 'is-private'

const escapeRegExp = (value = '') => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const deriveOwnerTag = (value = '') => {
  const label = normalizeWhitespace(value)
  if (!label) return t('home.labels.ai')
  const chinese = label.match(/[\u4e00-\u9fff]/u)
  if (chinese) {
    return chinese[0]
  }
  const tokens = label.split(/[^A-Za-z0-9]+/).filter(Boolean)
  if (tokens.length >= 2) {
    return `${tokens[0][0]}${tokens[1][0]}`.toUpperCase()
  }
  const solo = tokens[0] || label
  return solo.slice(0, 2).toUpperCase()
}

const deriveConversationOwnerTag = (payload = {}, fallback = '') => {
  const explicitOwner = normalizeWhitespace(
    payload.owner || payload.owner_name || payload.username || payload.user_name || ''
  )
  if (explicitOwner) {
    return deriveOwnerTag(explicitOwner)
  }

  const ownerUserId = Number(payload.user_id ?? payload.userId)
  const currentUserId = Number(userProfile.value?.id ?? userProfile.value?.user_id)
  if (
    Number.isFinite(ownerUserId) &&
    Number.isFinite(currentUserId) &&
    ownerUserId === currentUserId
  ) {
    const myName = normalizeWhitespace(
      userProfile.value?.name || userProfile.value?.username || userProfile.value?.email || ''
    )
    if (myName) {
      return deriveOwnerTag(myName)
    }
  }

  const ownerRole = normalizeWhitespace(payload.owner_role || payload.ownerRole || '')
  if (ownerRole) {
    return deriveOwnerTag(ownerRole)
  }

  if (Number.isFinite(ownerUserId)) {
    const suffix = String(ownerUserId).slice(-2)
    return `U${suffix}`
  }

  return deriveOwnerTag(fallback)
}

const truncateSummary = (value = '', maxChars = 20) => {
  const clean = normalizeWhitespace(value)
  if (!clean) return ''
  const glyphs = Array.from(clean)
  if (glyphs.length <= maxChars) {
    return clean
  }
  return `${glyphs.slice(0, maxChars).join('')}...`
}

const hasCustomConversationTitle = (title = '') => {
  const normalized = normalizeWhitespace(title)
  if (!normalized) return false
  const lowered = normalized.toLowerCase()
  return lowered !== 'new conversation' && normalized !== DEFAULT_CONVERSATION_TITLE
}

const getUserIdentifier = () => {
  const profile = userProfile.value || {}
  const source =
    normalizeWhitespace(
      profile.username || profile.name || profile.email || t('home.user.default_name')
    )
      .replace(/[^A-Za-z0-9\u4e00-\u9fa5]/g, '')
      .trim() || t('home.user.default_name')
  const glyphs = Array.from(source)
  const limit = glyphs.some((char) => /[\u4e00-\u9fa5]/.test(char)) ? 2 : 4
  return glyphs.slice(0, limit).join('') || t('home.user.default_name')
}

const buildQuestionSeed = (question = '', maxChars = 5) => {
  const glyphs = Array.from((question || '').replace(/\s+/g, ''))
  return glyphs.slice(0, maxChars).join('') || t('home.user.default_seed')
}

const getNextConversationSerial = (base) => {
  const pattern = new RegExp(`^${escapeRegExp(base)}-(\\d{3})$`)
  let maxSerial = 0
  dialogHistory.value.forEach((record) => {
    const label = record.projectLabel || ''
    const match = pattern.exec(label)
    if (match) {
      const value = Number(match[1])
      if (!Number.isNaN(value)) {
        maxSerial = Math.max(maxSerial, value)
      }
    }
  })
  return String(maxSerial + 1).padStart(3, '0')
}

const generateConversationLabel = (question = '') => {
  const base = `${getUserIdentifier()}${buildQuestionSeed(question)}`
  const serial = getNextConversationSerial(base)
  return `${base}-${serial}`
}

const buildConversationSummary = (payload = {}, fallback = '') => {
  const rawSummary =
    payload.summary ||
    payload.last_user_message ||
    payload.last_message ||
    payload.lastMessage ||
    payload.subtitle ||
    fallback ||
    payload.title
  const summary = truncateSummary(rawSummary, 20)
  return summary || t('home.history.empty_summary')
}

const currentUserNumericId = computed(() => Number(userProfile.value?.id ?? userProfile.value?.user_id))

const createCurrentUserAuthor = () => {
  const profile = userProfile.value || {}
  return {
    authorUserId: Number(profile.id ?? profile.user_id) || null,
    authorUsername: normalizeAuthorField(profile.username || ''),
    authorName: normalizeAuthorField(profile.name || profile.username || profile.email || ''),
  }
}

const resolveUserMessageAuthorLabel = (message = {}) => {
  if (message.role !== 'user') return t('home.labels.ai')
  const authorUserId = Number(message.authorUserId)
  if (
    Number.isFinite(authorUserId) &&
    Number.isFinite(currentUserNumericId.value) &&
    authorUserId === currentUserNumericId.value
  ) {
    return t('home.labels.you')
  }
  return buildUserAvatarLabel({
    authorName: message.authorName,
    authorUsername: message.authorUsername,
    fallback: t('home.labels.you'),
  })
}

const isConversationOwnerRecord = (record = {}) => {
  const ownerId = Number(record.userId ?? record.user_id)
  const selfId = currentUserNumericId.value
  if (!Number.isFinite(ownerId) || !Number.isFinite(selfId)) return false
  return ownerId === selfId
}

const canManageHistoryContext = (context = {}) => {
  const selfId = currentUserNumericId.value
  if (!Number.isFinite(selfId)) return false
  const projectOwnerId = Number(context.owner_user_id)
  if (Number.isFinite(projectOwnerId)) {
    return projectOwnerId === selfId
  }
  return isConversationOwnerRecord(context)
}

const normalizeHistoryRecord = (payload = {}) => {
  const conversationId = payload.id || payload.conversation_id || payload.conversationId
  if (!conversationId) return null
  const projectId = normalizeWhitespace(
    payload.project_id || payload.projectId || payload.project?.id || payload.project_key || ''
  ) || null
  const rawProjectLabel =
    payload.project_label ||
    payload.projectLabel ||
    payload.project?.label ||
    ''
  const projectLabel = normalizeWhitespace(rawProjectLabel)
  const updatedAt =
    ensureIsoString(payload.updated_at || payload.updatedAt || payload.last_message_at) ||
    ensureIsoString(payload.created_at || payload.createdAt)
  const createdAt = ensureIsoString(payload.created_at || payload.createdAt) || updatedAt
  const lastMessage = payload.last_message || payload.lastMessage || payload.subtitle || ''
  const lastUserMessage =
    payload.last_user_message || payload.lastUserMessage || payload.lastUserPrompt || ''
  const summary = buildConversationSummary(
    { ...payload, last_user_message: lastUserMessage || payload.last_user_message },
    projectLabel || lastMessage || lastUserMessage
  )
  const displayTitle = payload.title || lastUserMessage || projectLabel || DEFAULT_CONVERSATION_TITLE
  const hasCustomTitle =
    Object.prototype.hasOwnProperty.call(payload, 'has_custom_title') ||
    Object.prototype.hasOwnProperty.call(payload, 'hasCustomTitle')
      ? Boolean(payload.has_custom_title ?? payload.hasCustomTitle)
      : hasCustomConversationTitle(displayTitle)
  const ownerTag = deriveConversationOwnerTag(payload, projectLabel)
  const isArchived = Boolean(
    payload.is_archived ?? payload.isArchived ?? payload.archived ?? false
  )
  const archivedAt = ensureIsoString(payload.archived_at || payload.archivedAt) || null
  return {
    id: conversationId,
    conversationId,
    projectId,
    projectLabel: projectLabel || '',
    projectDisplayLabel: projectLabel || INBOX_LABEL,
    title: displayTitle,
    hasCustomTitle,
    subtitle: lastMessage,
    lastMessage,
    lastUserMessage,
    summary,
    visibility: normalizeVisibility(payload.visibility),
    ownerRole: payload.owner_role || payload.ownerRole || null,
    userId: payload.user_id || payload.userId || null,
    status: payload.status || ownerTag,
    owner: ownerTag,
    datetime: updatedAt || createdAt || null,
    updatedAt: updatedAt || createdAt || null,
    createdAt: createdAt || null,
    pinned: pinnedConversationIds.value.has(conversationId),
    isArchived,
    archivedAt,
  }
}

const normalizeSearchResultRecord = (payload = {}) => {
  const record = normalizeHistoryRecord(payload)
  if (!record) return null
  return {
    ...record,
    matchExcerpt: normalizeWhitespace(payload.match_excerpt || payload.matchExcerpt || ''),
    matchedBy: normalizeWhitespace(payload.matched_by || payload.matchedBy || ''),
  }
}

const syncProjectDisplayLabels = async (records = []) => {
  const projectIds = Array.from(
    new Set(
      records
        .map((item) => (item?.projectId || '').toString().trim())
        .filter(Boolean)
    )
  )
  if (!projectIds.length) return records
  try {
    const response = await fetchProjectNameMap(projectIds)
    const mapping = response?.items || {}
    return records.map((item) => {
      const projectId = (item?.projectId || '').toString().trim()
      const projectName = mapping[projectId]
      if (!projectId || !projectName) return item
      return {
        ...item,
        projectLabel: projectName,
        projectDisplayLabel: projectName,
      }
    })
  } catch (error) {
    console.error('Fetch project name map failed', error)
    return records
  }
}

const syncPinnedFlags = () => {
  dialogHistory.value = dialogHistory.value.map((record) => ({
    ...record,
    pinned: pinnedConversationIds.value.has(record.id),
  }))
}

const resolveDisplayLocale = () => {
  const current = locale.value || 'zh-TW'
  const normalized = String(current)
  const lower = normalized.toLowerCase()
  if (lower === 'en') return 'en-US'
  if (lower === 'zh' || lower === 'zh-hant') return 'zh-TW'
  return normalized
}

const formatDisplayTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString(resolveDisplayLocale(), {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const upsertHistoryRecord = (record) => {
  if (!record?.id) return
  const enriched = {
    ...record,
    pinned: pinnedConversationIds.value.has(record.id),
    summary: record.summary || buildConversationSummary(record),
  }
  const next = [...dialogHistory.value]
  const index = next.findIndex((item) => item.id === record.id)
  if (index >= 0) {
    next.splice(index, 1, { ...next[index], ...enriched })
  } else {
    next.unshift(enriched)
  }
  dialogHistory.value = next
}

const setPinnedStateForId = (id, shouldPin) => {
  if (!id) return
  const next = new Set(pinnedConversationIds.value)
  if (shouldPin) {
    next.add(id)
  } else {
    next.delete(id)
  }
  pinnedConversationIds.value = next
  persistPinnedIdList(Array.from(next))
  syncPinnedFlags()
}

const removeConversationFromHistory = (record) => {
  const targetId = record?.id
  if (!targetId) return
  dialogHistory.value = dialogHistory.value.filter((item) => item.id !== targetId)
  if (record?.projectId) {
    setConversationIdForProject(record.projectId, null)
  }
  if (pinnedConversationIds.value.has(targetId)) {
    setPinnedStateForId(targetId, false)
  }
  if (activeConversationId.value === targetId) {
    clearActiveConversationId()
    chatMessages.value = []
    assistantAnswer.value = ''
    submittedTask.value = ''
    conversationTitle.value = DEFAULT_CONVERSATION_TITLE
    isChatActive.value = false
  }
}

const loadConversationHistory = async (options = { silent: false }) => {
  if (!isAuthenticated.value) {
    dialogHistory.value = []
    return
  }
  const { silent } = options || {}
  if (!silent) {
    isHistoryLoading.value = true
    historyError.value = ''
  }
  try {
    const response = await fetchConversationHistory({ limit: 60 })
    const items = Array.isArray(response?.items) ? response.items : []
    const normalized = items
      .map((item) => normalizeHistoryRecord(item))
      .filter((item) => item && item.id)
    const synced = await syncProjectDisplayLabels(normalized)
    dialogHistory.value = synced.filter((item) => !item.isArchived)
    historyError.value = ''
  } catch (error) {
    if (!silent) {
      historyError.value = error?.message || t('home.errors.load_history')
    }
    if (error?.shouldLogout) {
      handleSessionExpired()
    }
  } finally {
    if (!silent) {
      isHistoryLoading.value = false
    }
  }
}

const refreshHistorySilently = () => loadConversationHistory({ silent: true })

const updateHistoryFromResponse = (response, fallbackLabel, lastUserQuestion = '') => {
  const conversationId = response?.answer?.conversation_id
  if (!conversationId) return
  const metadata = response?.answer?.metadata || {}
  const project = response?.project || metadata.project || {}
  const resolvedProjectId = normalizeWhitespace(project.id || activeProjectId.value || '')
  const resolvedProjectLabel = resolvedProjectId
    ? normalizeWhitespace(project.label || fallbackLabel || '')
    : ''
  const existingRecord = dialogHistory.value.find((item) => item.id === conversationId)
  const nextTitle =
    existingRecord?.hasCustomTitle && normalizeWhitespace(existingRecord?.title || '')
      ? existingRecord.title
      : lastUserQuestion || project.label || fallbackLabel || metadata.summary
  const normalized = normalizeHistoryRecord({
    id: conversationId,
    project_id: resolvedProjectId || null,
    project_label: resolvedProjectLabel,
    title: nextTitle,
    has_custom_title: Boolean(existingRecord?.hasCustomTitle),
    last_message: response?.content || metadata.summary || '',
    last_user_message: lastUserQuestion || metadata.last_user_message || '',
    summary: metadata.summary || response?.content || fallbackLabel,
    updated_at: new Date().toISOString(),
    visibility: existingRecord?.visibility || activeConversationVisibility.value,
    owner_role: existingRecord?.ownerRole,
    user_id: existingRecord?.userId,
  })
  if (normalized) {
    upsertHistoryRecord(normalized)
  }
}

const toTimestamp = (value) => {
  if (typeof value === 'number' && !Number.isNaN(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value)
    if (!Number.isNaN(parsed)) {
      return parsed
    }
  }
  return null
}

const getDialogTimestamp = (item, fallback = 0) => {
  if (!item) return fallback
  return (
    toTimestamp(item.timestamp) ??
    toTimestamp(item.updatedAt) ??
    toTimestamp(item.datetime) ??
    toTimestamp(item.schedule) ??
    fallback
  )
}

const getPinnedTimestamp = (item, fallback = 0) => {
  const pinValue = toTimestamp(item?.pinnedAt)
  if (pinValue != null) {
    return pinValue
  }
  return getDialogTimestamp(item, fallback)
}

const sortedDialogs = computed(() => {
  const source = dialogHistory.value
  const total = source.length
  return source
    .map((item, index) => ({
      item,
      ts: getDialogTimestamp(item, total - index),
    }))
    .sort((a, b) => b.ts - a.ts)
    .map(({ item }) => item)
})

const projectKey = (item = {}) =>
  item.projectId ||
  item.project_id ||
  item.projectLabel ||
  item.project_label ||
  item.id ||
  item.title ||
  item.summary ||
  null

const uniqueByProject = (list = []) => {
  const seen = new Set()
  return list.filter((item, index) => {
    const key = projectKey(item) || `idx-${index}`
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

const currentUserId = computed(() => Number(userProfile.value?.id ?? userProfile.value?.user_id))

const projectRowDialogs = computed(() =>
  sortedDialogs.value
    .filter((item) => {
      if (normalizeWhitespace(item.projectId || '')) return false
      const ownerId = Number(item.userId)
      const selfId = currentUserId.value
      if (!Number.isFinite(ownerId) || !Number.isFinite(selfId)) return false
      return ownerId === selfId
    })
    .slice(0, 8)
)

const pinnedDialogs = computed(() =>
  uniqueByProject(sortedDialogs.value.filter((item) => item.pinned))
)

const historyDialogs = computed(() =>
  sortedDialogs.value.filter((item) => !item.pinned)
)

const resolveHistoryInfoLabel = (record = {}) => {
  const title = normalizeWhitespace(record?.title || '')
  const hasCustomTitle = Boolean(record?.hasCustomTitle)
  if (hasCustomTitle && title) {
    return title
  }
  const question = truncateSummary(record?.lastUserMessage || '', 20)
  if (question) {
    return question
  }
  return record?.summary || title || t('home.history.empty_summary')
}

const resolveSearchPanelItemExcerpt = (record = {}) =>
  normalizeWhitespace(
    record?.matchExcerpt || record?.summary || record?.lastUserMessage || record?.subtitle || ''
  )

const resolveDialogId = (target) => {
  if (typeof target === 'object' && target) {
    return target.id
  }
  return target
}

const pinDialog = (target) => {
  const id = resolveDialogId(target)
  if (!id || pinnedConversationIds.value.has(id)) return
  setPinnedStateForId(id, true)
}

const unpinDialog = (target) => {
  const id = resolveDialogId(target)
  if (!id || !pinnedConversationIds.value.has(id)) return
  setPinnedStateForId(id, false)
}

function openNewConversationFromContext(context = {}) {
  const nextProjectId = normalizeWhitespace(
    context?.projectId || context?.project_id || context?.project?.id || ''
  )
  const nextProjectLabel = normalizeWhitespace(
    context?.projectDisplayLabel ||
      context?.projectLabel ||
      context?.project_label ||
      context?.project?.label ||
      context?.project_name ||
      ''
  )
  const query = {}
  if (nextProjectId) {
    query.compose_project_id = nextProjectId
  }
  if (nextProjectLabel) {
    query.compose_project_label = nextProjectLabel
  }
  resetConversationState()
  if (nextProjectId) {
    activeProjectId.value = nextProjectId
  }
  activeMenu.value = null
  router.push({ name: 'home', query }).catch(() => {})
}

const menuBlueprint = {
  card: [
    { label: t('home.menu.pin'), action: (context) => pinDialog(context) },
    { label: t('home.menu.select_folder'), modal: 'selectFolder' },
    { label: t('home.menu.visibility'), modal: 'permission' },
    { label: t('home.menu.rename'), modal: 'rename' },
    { label: t('home.menu.delete'), danger: true, modal: 'deleteConversation' },
  ],
  pinned: [
    { label: t('home.menu.unpin'), action: (context) => unpinDialog(context) },
    { label: t('home.menu.visibility'), modal: 'permission' },
    { label: t('home.menu.rename'), modal: 'rename' },
    { label: t('home.menu.delete'), danger: true, modal: 'deleteConversation' },
  ],
  dialog: [
    { label: t('home.menu.pin'), action: (context) => pinDialog(context) },
    { label: t('home.menu.visibility'), modal: 'permission' },
    { label: t('home.menu.rename'), modal: 'rename' },
    { label: t('home.menu.delete'), danger: true, modal: 'deleteConversation' },
  ],
}

const getMenuOptions = (section, context = {}) => {
  const base = menuBlueprint[section] || []
  if (canManageHistoryContext(context)) return base
  return base.filter(
    (option) => !['permission', 'rename', 'deleteConversation', 'selectFolder'].includes(option.modal)
  )
}

const avatarPalette = {
  LD: '#5f758a',
  AC: '#55b77f',
  MN: '#8bd8a8',
  JW: '#f4b83f',
  ST: '#263847',
}

const initialViewport = typeof window !== 'undefined' ? window.innerWidth : 1440
const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const TOP_BAR_HEIGHT = 76
const TOP_ADVICE_HEIGHT = 56
const TOP_BAR_PADDING = 48
const stageWidth = ref(initialViewport)
const isSidebarCollapsed = ref(initialViewport <= SIDEBAR_COLLAPSE_BREAKPOINT)
const activeMenu = ref(null)
const activeModal = ref(null)
const renameValue = ref(DEFAULT_CONVERSATION_TITLE)
const renameTarget = ref(null)
const renameError = ref('')
const deleteTarget = ref(null)
const deleteError = ref('')
const isDeleting = ref(false)
const isRenaming = ref(false)
const messageInput = ref('')
const composerValue = ref('')
const submittedTask = ref(defaultUserPrompt)
const CHAT_COMPOSER_PLACEHOLDER = computed(() => t('home.placeholders.chat_outdoor'))
const QUOTE_PENDING_COMPOSE_KEY = 'ys-quote-pending-compose'
const QUOTE_CHAT_HANDOFF_KEY = 'ys-quote-chat-handoff'
const QUOTE_CHATUI_RETURN_KEY = 'ys-quote-chatui-return'
const QUOTE_SHOW_GENERATED_KEY = 'ys-quote-show-generated'
const OUTPUT_TYPE_QUOTE_VALUE = 'quote_list'
const QUOTE_DEFAULT_TAB = 'report'
const SIDEBAR_DESKTOP_WIDTH = 104
const quoteOutputDefinitions = computed(() => [
  { value: OUTPUT_TYPE_QUOTE_VALUE, label: t('home.output_types.quote_list'), tab: 'report' },
  { value: 'gallery', label: t('home.output_types.guide_list'), tab: 'gallery' },
  { value: 'slides', label: t('home.output_types.text_message'), tab: 'slides' },
  { value: 'social', label: t('home.output_types.store_recommendation'), tab: 'social' },
])
const outputTypes = computed(() => quoteOutputDefinitions.value.map((item) => item.label))
const selectedOutputValue = ref('')
const selectedOutputType = computed(
  () => quoteOutputDefinitions.value.find((item) => item.value === selectedOutputValue.value)?.label || ''
)
const chatOutputPlaceholder = computed(() => t('home.output_types.placeholder'))
const QUOTE_STORAGE_KEY = 'ys-quote-items'
const QUOTE_CONTEXT_KEY = 'ys-quote-context'
const isChatActive = ref(false)
const showGeneratedResults = ref(false)
const showAssistantResultSummary = ref(true)
const activeNavId = ref(navItems.value[0].id)
const searchQuery = ref('')
const searchResults = ref([])
const lastSearchQuery = ref('')
const isSearchLoading = ref(false)
const searchError = ref('')
const showSearchPanel = ref(false)
const searchPanelInput = ref(null)
const topBarRef = ref(null)
const topAdviceRef = ref(null)
const dockedPanelCoords = ref({ top: TOP_BAR_HEIGHT, left: TOP_BAR_PADDING })
const showSnackbar = ref(false)
const snackbarTimer = ref(null)
const showShareDialog = ref(false)
const shareEmail = ref('')
const shareInputRef = ref(null)
const shareMessageOverride = ref('')
const isSending = ref(false)
const chatError = ref('')
const chatMessages = ref([])
const expandedReferenceMessageIds = ref(new Set())
const assistantAnswer = ref('')
const chatHighlights = ref([...DEFAULT_HIGHLIGHTS])
const ignoreHistoryBeforeToday = ref(false)
const chatNextSteps = ref([...DEFAULT_NEXT_STEPS])
const {
  accept: uploadAccept,
  attachments: uploadAttachments,
  warning: uploadWarning,
  fileInputRef: uploadFileInput,
  triggerSelect: triggerUploadSelect,
  handleFilesSelected: handleUploadFilesSelected,
  addUrlsFromText: addComposerUrls,
  removeAttachment: removeUploadAttachment,
  clear: clearUploadAttachments,
  clearFiles: clearUploadFiles,
  uploadAll: uploadAttachmentsBeforeSend,
  extractUrlInputs: extractComposerUrlInputs,
} = useFileUploader()
const conversationTitle = ref(DEFAULT_CONVERSATION_TITLE)
const conversationSchedule = ref(t('home.defaults.schedule'))
const DEFAULT_RESULT_STATUS = t('home.status.summary')
const chatResultCard = ref({
  id: 'seed-card',
  title: conversationTitle.value,
  datetime: conversationSchedule.value,
  status: DEFAULT_RESULT_STATUS,
  references: [],
})
const chatProductCard = ref(null)
const latestCerpMessageId = ref(null)
const isHistoryPreview = ref(false)
const activeConversationVisibility = ref('private')
const permissionTarget = ref(null)
const permissionVisibility = ref('private')
const permissionInvitations = ref([])
const permissionEmail = ref('')
const permissionError = ref('')
const isPermissionBusy = ref(false)
const permissionSuggestions = ref([])
const permissionLookupBusy = ref(false)
const permissionLookupOpen = ref(false)
const selectedPermissionCandidate = ref(null)
const permissionLookupTimer = ref(null)
const selectFolderTarget = ref(null)
const folderPickerQuery = ref('')
const folderPickerSelectedId = ref('')
const folderPickerItems = ref([])
const folderPickerError = ref('')
const isFolderPickerLoading = ref(false)
const isFolderPickerSaving = ref(false)

const permissionTargetTitle = computed(() => {
  if (!permissionTarget.value) return DEFAULT_CONVERSATION_TITLE
  return (
    permissionTarget.value.title ||
    permissionTarget.value.summary ||
    DEFAULT_CONVERSATION_TITLE
  )
})

const permissionTargetIconSrc = computed(() => iconChatProject)

const permissionOwnerLabel = computed(() => {
  const profile = userProfile.value || {}
  const label = normalizeWhitespace(
    profile.name || profile.username || profile.email || t('home.labels.you')
  )
  return label || t('home.labels.you')
})

const formatPermissionStatus = (value = '') => {
  const status = String(value || '').toLowerCase()
  if (status === 'accepted') return t('home.permission.accepted')
  if (status === 'pending') return t('home.permission.pending')
  if (status === 'rejected') return t('home.permission.rejected')
  if (status === 'revoked') return t('home.permission.revoked')
  return status || '-'
}

const permissionAccessRows = computed(() => {
  const invitationRows = (permissionInvitations.value || []).map((invite) => ({
    id: invite.id,
    label: invite.name || invite.username || invite.email || '-',
    secondary: invite.username || invite.email || '',
    status: formatPermissionStatus(invite.status),
    revokable: invite.status !== 'revoked',
  }))
  invitationRows.push({
    id: 'owner',
    label: permissionOwnerLabel.value,
    secondary: normalizeWhitespace(userProfile.value?.username || ''),
    status: t('home.permission.owner'),
    revokable: false,
  })
  return invitationRows
})
const normalizedPermissionInviteQuery = computed(() => String(permissionEmail.value || '').trim().toLowerCase())
const permissionInvitedIdentifierSet = computed(
  () =>
    new Set(
      (permissionInvitations.value || [])
        .filter((invite) => String(invite?.status || '').toLowerCase() !== 'revoked')
        .map((invite) => String(invite?.email || '').trim().toLowerCase())
        .filter(Boolean)
    )
)
const canSubmitPermissionInvite = computed(() => {
  if (isPermissionBusy.value || permissionVisibility.value !== 'private') return false
  const candidate = selectedPermissionCandidate.value
  if (!candidate?.username) return false
  const normalizedUsername = String(candidate.username).trim().toLowerCase()
  if (!normalizedUsername || normalizedUsername !== normalizedPermissionInviteQuery.value) return false
  if (permissionInvitedIdentifierSet.value.has(normalizedUsername)) return false
  return true
})

const clearPermissionLookupState = ({ clearInput = false } = {}) => {
  if (permissionLookupTimer.value) {
    clearTimeout(permissionLookupTimer.value)
    permissionLookupTimer.value = null
  }
  if (clearInput) {
    permissionEmail.value = ''
  }
  permissionSuggestions.value = []
  permissionLookupBusy.value = false
  permissionLookupOpen.value = false
  selectedPermissionCandidate.value = null
}

const loadPermissionCandidates = async (keyword) => {
  if (
    activeModal.value !== 'permission' ||
    !permissionTarget.value?.id ||
    permissionVisibility.value !== 'private'
  ) {
    clearPermissionLookupState()
    return
  }
  const normalizedKeyword = String(keyword || '').trim()
  if (normalizedKeyword.length < INVITE_LOOKUP_MIN_LENGTH) {
    permissionSuggestions.value = []
    permissionLookupOpen.value = false
    permissionLookupBusy.value = false
    return
  }

  permissionLookupBusy.value = true
  try {
    const data = await searchInvitationCandidates({
      query: normalizedKeyword,
      scope: 'conversation',
      targetId: permissionTarget.value.id,
    })
    const items = (data?.items || []).filter((item) => {
      const username = String(item?.username || '').trim().toLowerCase()
      return username && !permissionInvitedIdentifierSet.value.has(username)
    })
    permissionSuggestions.value = items
    permissionLookupOpen.value = true
  } catch (error) {
    permissionSuggestions.value = []
    permissionLookupOpen.value = false
    permissionError.value = error?.message || t('home.permission.search_failed')
  } finally {
    permissionLookupBusy.value = false
  }
}

const selectPermissionCandidate = (candidate) => {
  if (!candidate?.username) return
  permissionEmail.value = candidate.username
  selectedPermissionCandidate.value = candidate
  permissionSuggestions.value = []
  permissionLookupOpen.value = false
  permissionError.value = ''
}

const handlePermissionInviteFocus = () => {
  if (permissionSuggestions.value.length) {
    permissionLookupOpen.value = true
  }
}

const filteredFolderPickerItems = computed(() => {
  const keyword = normalizeWhitespace(folderPickerQuery.value).toLowerCase()
  if (!keyword) return folderPickerItems.value
  return folderPickerItems.value.filter((item) =>
    String(item?.name || '').toLowerCase().includes(keyword)
  )
})

const resolvePermissionTarget = (context = {}) => {
  const conversationId = String(
    context?.id || context?.conversationId || context?.conversation_id || ''
  ).trim()
  const normalizedVisibility = normalizeVisibility(
    context?.visibility || activeConversationVisibility.value
  )
  const title = normalizeWhitespace(context?.title || context?.summary || '')

  if (!conversationId) return null

  return {
    scope: 'conversation',
    id: conversationId,
    projectId: String(context?.projectId || context?.project_id || '').trim(),
    conversationId,
    summary: context?.summary || '',
    title: title || DEFAULT_CONVERSATION_TITLE,
    visibility: normalizedVisibility,
  }
}

const loadPermissionInvitations = async () => {
  if (!permissionTarget.value?.id) {
    permissionInvitations.value = []
    return
  }
  try {
    const data = await fetchConversationInvitations(permissionTarget.value.id)
    permissionInvitations.value = data?.items || []
  } catch (error) {
    permissionInvitations.value = []
    permissionError.value = error?.message || t('home.permission.load_failed')
    if (error?.shouldLogout) {
      handleSessionExpired()
    }
  }
}

const openPermissionModal = async (context = {}) => {
  const target = resolvePermissionTarget(context)
  if (!target) {
    permissionError.value = t('home.errors.visibility_missing')
    return
  }
  permissionTarget.value = target
  permissionVisibility.value = target.visibility
  clearPermissionLookupState({ clearInput: true })
  permissionError.value = ''
  permissionInvitations.value = []
  openModal('permission')
  await loadPermissionInvitations()
}

const loadFolderPickerProjects = async () => {
  const profile = userProfile.value || {}
  const myUserId = Number(profile.id ?? profile.user_id)
  const myRole = String(profile.role || '').toLowerCase()
  isFolderPickerLoading.value = true
  folderPickerError.value = ''
  try {
    const response = await fetchProjects({ page: 1, pageSize: 100 })
    const allItems = Array.isArray(response?.items) ? response.items : []
    const manageable = allItems.filter((item) => {
      if (myRole === 'sadmin') return true
      if (!Number.isFinite(myUserId)) return false
      return Number(item?.owner_user_id) === myUserId
    })
    folderPickerItems.value = manageable
    if (!manageable.find((item) => String(item.id) === String(folderPickerSelectedId.value))) {
      folderPickerSelectedId.value = manageable.length ? String(manageable[0].id) : ''
    }
  } catch (error) {
    folderPickerItems.value = []
    folderPickerSelectedId.value = ''
    folderPickerError.value = error?.message || t('home.errors.load_folders')
  } finally {
    isFolderPickerLoading.value = false
  }
}

const openSelectFolderModal = async (context = {}) => {
  const conversationId = String(context?.id || context?.conversationId || context?.conversation_id || '').trim()
  if (!conversationId) {
    return
  }
  selectFolderTarget.value = context
  folderPickerQuery.value = ''
  folderPickerError.value = ''
  folderPickerSelectedId.value = String(
    context?.projectId || context?.project_id || context?.project?.id || ''
  ).trim()
  openModal('selectFolder')
  await loadFolderPickerProjects()
}

const isAssistantTyping = ref(false)

const languagePreference = ref('zh-Hant')

const resetConversationState = () => {
  clearActiveConversationId()
  assignNewProjectContext()
  chatMessages.value = []
  assistantAnswer.value = ''
  chatHighlights.value = [...DEFAULT_HIGHLIGHTS]
  ignoreHistoryBeforeToday.value = false
  chatNextSteps.value = [...DEFAULT_NEXT_STEPS]
  conversationTitle.value = DEFAULT_CONVERSATION_TITLE
  renameValue.value = DEFAULT_CONVERSATION_TITLE
  activeConversationVisibility.value = 'private'
  isAssistantTyping.value = false
  isHistoryPreview.value = false
  chatResultCard.value = {
    title: conversationTitle.value,
    summaryBullets: [],
    datetime: conversationSchedule.value,
    status: DEFAULT_RESULT_STATUS,
  }
}

const normalizeMessageQuoteUi = (metadata = {}, createdAt = '') =>
  normalizeQuoteUiPayload(metadata, {
    createdAt,
    language: normalizeQuoteLanguage(
      metadata?.language || metadata?.lang,
      languagePreference.value
    ),
  })

const resolveMessageLocale = (message = {}) => {
  const metadata = message?.metadata || {}
  const rawValue = String(
    metadata.lang ||
      metadata.language ||
      message.lang ||
      message.language ||
      languagePreference.value ||
      ''
  )
    .trim()
    .toLowerCase()
  if (rawValue === 'en' || rawValue.startsWith('en-')) return 'en'
  if (rawValue === 'ja' || rawValue.startsWith('ja-') || rawValue === 'jp') return 'ja'
  return 'zh-TW'
}

const tMessage = (message, key, params = {}) => t(key, params, { locale: resolveMessageLocale(message) })

const appendReferenceContext = (bucket, items) => {
  if (!Array.isArray(items)) return
  items.forEach((item) => {
    if (item && typeof item === 'object') {
      bucket.push(item)
    } else if (typeof item === 'string' && item.trim()) {
      bucket.push({ source_trace: item.trim(), source_name: t('home.cerp_results.source') })
    }
  })
}

const collectMessageReferenceContext = (record = {}, metadata = {}) => {
  const merged = []
  appendReferenceContext(merged, record.context)
  appendReferenceContext(merged, record.citations)
  appendReferenceContext(merged, record.answer?.citations)
  appendReferenceContext(merged, metadata.citations)
  appendReferenceContext(merged, metadata.answer_citations)
  appendReferenceContext(merged, metadata.citation_validation?.items)
  appendReferenceContext(merged, metadata.cerp_results?.items)
  appendReferenceContext(merged, metadata.official_inventory_binding?.proofs)
  return merged
}

const collectResponseReferenceContext = (response = {}, answer = {}) => {
  const metadata = answer?.metadata || {}
  const merged = []
  appendReferenceContext(merged, response?.context)
  appendReferenceContext(merged, response?.citations)
  appendReferenceContext(merged, answer?.citations)
  appendReferenceContext(merged, metadata.citations)
  appendReferenceContext(merged, metadata.answer_citations)
  appendReferenceContext(merged, metadata.citation_validation?.items)
  appendReferenceContext(merged, metadata.cerp_results?.items)
  appendReferenceContext(merged, metadata.official_inventory_binding?.proofs)
  return merged
}

const normalizeThreadMessage = (record = {}, idx = 0) => {
  let metadata = record.metadata || record.meta || {}
  if (typeof metadata === 'string') {
    try {
      metadata = JSON.parse(metadata)
    } catch {
      metadata = {}
    }
  }
  const product = metadata.cerp_product || null
  const isCerpData = Boolean(metadata.is_cerp_data || product)
  const createdAt = record.created_at || null
  const quoteUi = normalizeMessageQuoteUi(metadata, createdAt)
  const role = record.role === 'assistant' ? 'assistant' : 'user'
  const references = Array.isArray(record.references)
    ? record.references
    : buildContextReferences(collectMessageReferenceContext(record, metadata))
  const content = String(record.content || '')
  const summaryPoints = Array.isArray(record.summary_points)
    ? record.summary_points.filter(Boolean)
    : Array.isArray(metadata.result_card_summary_points)
      ? metadata.result_card_summary_points.filter(Boolean)
      : []
  return {
    id: record.id || record.message_id || `history-${idx}`,
    role,
    content,
    summary: record.summary || record.summary_snapshot || metadata.summary || '',
    summaryPoints,
    highlights: Array.isArray(record.highlights) ? record.highlights.filter(Boolean) : [],
    createdAt,
    metadata,
    references,
    resultCard:
      role === 'assistant'
        ? normalizeMessageResultCard(
            metadata,
            record.summary || record.summary_snapshot || metadata.summary || '',
            Array.isArray(record.highlights) ? record.highlights.filter(Boolean) : [],
            references,
            record.id || record.message_id || `history-${idx}`
          )
        : null,
    authorUserId: record.author_user_id ?? metadata.author_user_id ?? null,
    authorUsername: record.author_username ?? metadata.author_username ?? '',
    authorName: record.author_name ?? metadata.author_name ?? '',
    isCerpData,
    quoteUi,
    cerpProductCard: isCerpData && product ? buildProductCard(product) : null,
  }
}



const hydrateUiFromAssistantMessage = (message = {}, metadata = {}, extras = {}) => {

  const assistantText = message.content || ''

  const mergedMetadata = {

    ...metadata,

    result_card_summary_points:
      Array.isArray(metadata.result_card_summary_points) && metadata.result_card_summary_points.length
        ? metadata.result_card_summary_points
        : Array.isArray(message.summaryPoints)
          ? message.summaryPoints
          : metadata.result_card_summary_points,

    summary: metadata.summary || metadata.compact_summary || message.summary || '',

    highlights: metadata.highlights || message.highlights || [],

  }

  assistantAnswer.value = assistantText

  const hasCerpData = Boolean(
    mergedMetadata.is_cerp_data || mergedMetadata.cerp_product || metadata.is_cerp_data
  )
  let highlightList = []

  if (hasCerpData) {
    chatHighlights.value = []
    chatNextSteps.value = []
  } else {
    highlightList = buildHighlightsFromMetadata(

      mergedMetadata,

      assistantText,

      mergedMetadata.highlights

    )

    chatHighlights.value = highlightList.length ? highlightList : [...DEFAULT_HIGHLIGHTS]

    const steps = buildNextStepsFromMetadata(mergedMetadata)

    chatNextSteps.value = steps.length ? steps : [...DEFAULT_NEXT_STEPS]
  }

  const references = Array.isArray(extras.references) ? extras.references : []

  const card = buildResultCardFromPayload(

    mergedMetadata,

    message.summary || mergedMetadata.summary || '',

    highlightList,

    references

  )

  chatResultCard.value = card
  const nextProductCard = buildProductCard(mergedMetadata.cerp_product)
  if (nextProductCard) {
    chatProductCard.value = nextProductCard
    latestCerpMessageId.value = message.id
  } else {
    latestCerpMessageId.value = null
  }

  conversationSchedule.value = card.datetime

}



const addUserMessageToThread = (content, urlInputs = []) => {
  const author = createCurrentUserAuthor()
  const visibleContent = buildVisiblePromptForThread(content, urlInputs)

  const entry = {

    id: createMessageId('user'),

    role: 'user',

    content: visibleContent,

    createdAt: new Date().toISOString(),
    ...author,

  }

  chatMessages.value.push(entry)
  nextTick(scrollChatToBottom)

  return entry.id

}



const removeMessageFromThread = (id) => {

  if (!id) return

  const index = chatMessages.value.findIndex((msg) => msg.id === id)

  if (index !== -1) {

    chatMessages.value.splice(index, 1)

  }

}



const loadConversationPreview = async (conversationId, fallbackLabel) => {
  if (!conversationId) return
  isHistoryPreview.value = true
  isConversationLoading.value = true
  chatError.value = ''

  try {

    const response = await fetchConversationMessages(conversationId, {
      limit: CONVERSATION_PREVIEW_LIMIT,
    })

    const records = hydrateStructuredUrlsIntoThread(
      (response?.messages || []).map((record, idx) => normalizeThreadMessage(record, idx))
    )

    chatMessages.value = records

    const projectPayload = response?.project || {}

    if (projectPayload.id) {

      activeProjectId.value = projectPayload.id

    }

    if (projectPayload.label) {

      conversationTitle.value = projectPayload.label

    } else if (fallbackLabel) {

      conversationTitle.value = fallbackLabel

    }

    setConversationIdForProject(projectPayload.id || activeProjectId.value, conversationId)
    const resolvedVisibility = normalizeVisibility(response?.visibility)
    activeConversationVisibility.value = resolvedVisibility
    applyLocalVisibility(conversationId, resolvedVisibility)

    const lastAssistant = [...records].reverse().find((msg) => msg.role === 'assistant')

    if (lastAssistant) {
      const lastAssistantLang = normalizeQuoteLanguage(
        lastAssistant.metadata?.language || lastAssistant.metadata?.lang,
        languagePreference.value
      )
      const quoteContinuity =
        buildQuoteContinuityFromMessage(lastAssistant, {
          conversationId,
          project: projectPayload.id
            ? {
                id: projectPayload.id,
                label: projectPayload.label || fallbackLabel || conversationTitle.value,
              }
            : null,
          lang: lastAssistantLang,
          surfaceOrigin: 'chat-ui',
        }) || null
      if (quoteContinuity) {
        persistQuoteContext({
          conversation_id: conversationId,
          project: projectPayload.id
            ? {
                id: projectPayload.id,
                label: projectPayload.label || fallbackLabel || conversationTitle.value,
              }
            : null,
          lang: lastAssistantLang,
          surface_origin: 'chat-ui',
          quote_continuity: quoteContinuity,
        })
      }

      hydrateUiFromAssistantMessage(lastAssistant, lastAssistant.metadata || {}, {

        references: lastAssistant.references || [],

      })

    } else {

      assistantAnswer.value = ''

      chatHighlights.value = [...DEFAULT_HIGHLIGHTS]

      chatNextSteps.value = [...DEFAULT_NEXT_STEPS]

    }

    const lastUser = [...records].reverse().find((msg) => msg.role === 'user')

    if (lastUser?.content) {

      submittedTask.value = lastUser.content

    }

    isChatActive.value = true
    nextTick(scrollChatToBottom)

  } catch (error) {
    chatError.value = error?.message || t('home.errors.load_conversation')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isConversationLoading.value = false
  }
}



const HIGHLIGHT_MIN_ITEMS = 4
const HIGHLIGHT_MAX_ITEMS = 5
const HIGHLIGHT_SECTION_TITLE = t('home.highlights.section_title')
const HIGHLIGHT_KEYWORD_PREFIX = t('home.highlights.keyword_prefix')
const NEXT_STEP_VARIANT_PREFIX = t('home.next_steps.variant_prefix')
const NEXT_STEP_FILTER_PREFIX = t('home.next_steps.filter_prefix')
const RESULT_CARD_SUMMARY_MAX_ITEMS = 3
const RESULT_CARD_SUMMARY_DETAIL_MAX_LENGTH = 84

const normalizeHighlightLine = (line = '') =>
  line
    .replace(/^[\s\-*•·∙\d.、:：()[\]]+/gu, '')
    .replace(/\s+/g, ' ')
    .trim()

const splitSentencesForHighlights = (text = '') => {
  if (!text) return []
  const sanitized = text.replace(/\r/g, '\n')
  const marked = sanitized.replace(/([。！？.!?])/gu, '$1|')
  return marked
    .split('|')
    .map(normalizeHighlightLine)
    .filter((segment) => segment.length >= 6)
}

const splitFragmentsForHighlights = (text = '', minLength = 4) => {
  if (!text) return []
  return text
    .split(/[,，、；;]+/u)
    .map(normalizeHighlightLine)
    .filter((segment) => segment.length >= minLength)
}

const buildHighlightsFromMetadata = (
  metadata = {},
  answerText = '',
  answerHighlights = []
) => {
  const mergedSources = [
    ...(Array.isArray(answerHighlights) ? answerHighlights : []),
    ...(Array.isArray(metadata.highlights) ? metadata.highlights : []),
  ]
  const normalizedMetadataHighlights = mergedSources
    .map((value) => normalizeHighlightLine(String(value || '')))
    .filter(
      (value) =>
        Boolean(value) &&
        !value.startsWith('**') &&
        !value.includes(HIGHLIGHT_SECTION_TITLE) &&
        !value.toLowerCase().startsWith('**')
    )
  const rawAnswer = String(answerText || '')
  const trimmedAnswer = rawAnswer.trim()
  const metadataMatchesAnswer = trimmedAnswer
    ? normalizedMetadataHighlights.filter((value) => trimmedAnswer.includes(value))
    : normalizedMetadataHighlights
  const highlights = []
  const seen = new Set()
  const pushHighlight = (value) => {
    const normalized = normalizeHighlightLine(value)
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    highlights.push(normalized)
  }

  const answerSegments = trimmedAnswer
    ? [
        ...splitSentencesForHighlights(rawAnswer),
        ...splitFragmentsForHighlights(rawAnswer),
      ]
    : []
  for (const segment of answerSegments) {
    pushHighlight(segment)
    if (highlights.length >= HIGHLIGHT_MAX_ITEMS) {
      break
    }
  }

  if (highlights.length < HIGHLIGHT_MAX_ITEMS) {
    for (const value of metadataMatchesAnswer) {
      pushHighlight(value)
      if (highlights.length >= HIGHLIGHT_MAX_ITEMS) {
        break
      }
    }
  }

  if (highlights.length < HIGHLIGHT_MIN_ITEMS) {
    const summaryLines = String(metadata.summary || '')
      .split('\n')
      .map(normalizeHighlightLine)
      .filter(
        (line) =>
          line &&
          !line.startsWith('**') &&
          !line.includes(HIGHLIGHT_SECTION_TITLE) &&
          !line.toLowerCase().startsWith('**')
      )
    summaryLines.forEach(pushHighlight)
  }

  if (highlights.length < HIGHLIGHT_MIN_ITEMS) {
    splitFragmentsForHighlights(answerText).forEach(pushHighlight)
  }

  if (highlights.length < HIGHLIGHT_MIN_ITEMS) {
    splitFragmentsForHighlights(answerText, 1).forEach(pushHighlight)
  }

  if (highlights.length < HIGHLIGHT_MIN_ITEMS) {
    const keywords = Array.isArray(metadata.keywords) ? metadata.keywords : []
    keywords.forEach((kw) => pushHighlight(`${HIGHLIGHT_KEYWORD_PREFIX}${kw}`))
  }

  if (highlights.length < HIGHLIGHT_MIN_ITEMS && trimmedAnswer) {
    pushHighlight(trimmedAnswer)
  }

  return highlights.slice(0, HIGHLIGHT_MAX_ITEMS)
}

const buildNextStepsFromMetadata = (metadata = {}) => {
  const aliases = metadata.aliases || {}
  const suggestions = []
  const variants = Array.isArray(aliases.query_variants)
    ? aliases.query_variants
    : []
  if (variants.length) {
    suggestions.push(`${NEXT_STEP_VARIANT_PREFIX}${variants[0]}`)
  }
  const filterValues = Object.values(aliases.filters || {})
    .flat()
    .filter(Boolean)
  if (filterValues.length) {
    suggestions.push(`${NEXT_STEP_FILTER_PREFIX}${filterValues[0]}`)
  }
  return suggestions.slice(0, 3)
}

const RESULT_CARD_SUMMARY_SKIP_PATTERNS = [
  /^查詢/u,
  /^搜尋/u,
  /^資料來源/u,
  /^匹配/u,
  /^篩選/u,
  /^條件/u,
  /^目前/u,
]

const isLowSignalResultCardBullet = (value = '') => {
  const normalized = normalizeHighlightLine(String(value || ''))
  if (!normalized) return true
  return RESULT_CARD_SUMMARY_SKIP_PATTERNS.some((pattern) => pattern.test(normalized))
}

const clipResultCardDetail = (value = '', maxLength = RESULT_CARD_SUMMARY_DETAIL_MAX_LENGTH) => {
  const normalized = normalizeHighlightLine(value)
  if (!normalized) return ''
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength).trim()}...`
}

const stripResultCardSectionLabel = (value = '') =>
  normalizeHighlightLine(String(value || ''))
    .replace(/^\d+\s*[.)、]\s*/u, '')
    .replace(/\s*[（(][^）)]*[）)]\s*$/u, '')
    .trim()

const buildStructuredResultCardBullets = (answerText = '') => {
  const rawLines = String(answerText || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!rawLines.length) return []

  const sections = []
  let current = null

  rawLines.forEach((line) => {
    if (/^\d+\s*[.)、]\s*/u.test(line)) {
      current = {
        heading: stripResultCardSectionLabel(line),
        details: [],
      }
      sections.push(current)
      return
    }
    if (!current) return
    if (/^[-•*]\s*/u.test(line)) {
      const detail = normalizeHighlightLine(line.replace(/^[-•*]\s*/u, ''))
      if (detail && !isLowSignalResultCardBullet(detail)) {
        current.details.push(detail)
      }
      return
    }
    if (!/^[A-Za-z]+\s*[:：]/u.test(line) && !isLowSignalResultCardBullet(line)) {
      current.details.push(normalizeHighlightLine(line))
    }
  })

  return sections
    .map((section) => {
      const heading = stripResultCardSectionLabel(section.heading)
      const detail = clipResultCardDetail(
        section.details.find((item) => !isLowSignalResultCardBullet(item)) || ''
      )
      if (!heading || !detail) return ''
      return `${heading}: ${detail}`
    })
    .filter(Boolean)
    .slice(0, RESULT_CARD_SUMMARY_MAX_ITEMS)
}

const normalizeMetaPayload = (meta) => {
  if (!meta) return {}
  if (typeof meta === 'string') {
    try {
      return JSON.parse(meta)
    } catch {
      return {}
    }
  }
  return meta
}

const resolveReferenceTitle = (meta, entry, idx) =>
  meta.title ||
  meta.book_title ||
  meta.source_title ||
  meta.source_name ||
  meta.source_site ||
  meta.code ||
  meta.sku ||
  [meta.producer, meta.name || meta.wine_name].filter(Boolean).join(' ') ||
  meta.filename ||
  entry.title ||
  entry.source ||
  entry.source_name ||
  entry.source_site ||
  entry.code ||
  entry.sku ||
  [entry.producer, entry.name || entry.wine_name].filter(Boolean).join(' ') ||
  entry.filename ||
  t('home.references.reference_label', { index: idx + 1 })

const resolveReferenceUrl = (meta, entry) => {
  const candidates = [
    meta.url,
    meta.page_url,
    meta.source_url,
    meta.link,
    entry?.url,
    entry?.page_url,
    entry?.source_url,
    entry?.link,
  ]
  const match = candidates.find(
    (value) => typeof value === 'string' && /^https?:\/\//i.test(value.trim())
  )
  return match ? match.trim() : ''
}

const isExternalReference = (meta, entry) => {
  const sourceTier = String(meta.source_tier || entry?.source_tier || '').toLowerCase()
  const sourceGroup = String(meta.source_group || entry?.source_group || '').toLowerCase()
  const sourceKind = String(meta.source_kind || entry?.source_kind || '').toLowerCase()
  const sourceType = String(meta.source_type || entry?.source_type || '').toLowerCase()
  return (
    sourceTier === 'external_evidence' ||
    sourceGroup === 'external_search' ||
    sourceKind === 'external_search' ||
    sourceType === 'external' ||
    Boolean(resolveReferenceUrl(meta, entry))
  )
}

const resolveEvidenceBadge = (meta = {}, entry = {}) => {
  const sourceFamily = String(meta.source_family || entry?.source_family || '').toLowerCase()
  if (sourceFamily === 'cerp_snapshot') return t('home.cerp_results.source')
  const sourceTier = String(meta.source_tier || entry?.source_tier || '').toLowerCase()
  if (sourceTier === 'internal_approved') return t('home.references.badges.internal_approved')
  if (sourceTier === 'internal_official') return t('home.references.badges.internal_official')
  if (['tier 1', 'tier 2', 'external_evidence'].includes(sourceTier)) {
    return t('home.references.badges.external_authoritative')
  }
  return isExternalReference(meta, entry)
    ? t('home.references.badges.external_other')
    : t('home.references.badges.internal')
}

const resolveAnswerModeLabel = (answerMode = '') => {
  const normalized = String(answerMode || '').trim()
  const knownModes = new Set([
    'generated',
    'grounded_gap',
    'ranking_shortlist',
    'fail_closed',
    'verified_answer',
    'assisted_general_answer',
    'data_or_permission_needed',
  ])
  return t(`home.transparency.answer_modes.${knownModes.has(normalized) ? normalized : 'generated'}`)
}

const resolveTransparencyCopy = (key = '') => {
  const labels = {
    title: t('home.transparency.title'),
    answerMode: t('home.transparency.answer_mode'),
    sourceMix: t('home.transparency.source_mix'),
    rejectedEvidence: t('home.transparency.rejected_evidence'),
  }
  return labels[key] || key
}


const resolveSourceMixLabel = (key = '') => {
  const localeKey = `home.transparency.source_mix_labels.${key}`
  const translated = t(localeKey)
  if (translated && translated !== localeKey) return translated
  return key.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

const resolveFilteredEvidenceBadge = () => t('home.transparency.filtered_out')

const buildSourceMixRows = (sourceMix = {}) =>
  ['internal_approved', 'internal_official', 'internal_other', 'external_authoritative', 'external_other']
    .map((key) => {
      const item = sourceMix?.[key]
      if (!item || (!item.count && !item.percent)) return null
      return {
        key,
        label: resolveSourceMixLabel(key),
        count: Number(item.count || 0),
        percent: Number(item.percent || 0),
      }
    })
    .filter(Boolean)

const collectPageTokens = (bucket, value) => {
  if (value === undefined || value === null) return
  const token = String(value).trim()
  if (!token) return
  bucket.add(token)
}

const collectLineTokens = (bucket, value) => {
  if (value === undefined || value === null) return
  const token = String(value).trim()
  if (!token) return
  bucket.add(token)
}

const buildContextReferences = (context = []) => {
  if (!Array.isArray(context) || !context.length) return []
  const merged = new Map()
  context.forEach((entry, idx) => {
    if (!entry || typeof entry !== 'object') return
    const entryMeta = normalizeMetaPayload(entry?.meta || {})
    const meta = { ...entry, ...entryMeta }
    const external = isExternalReference(meta, entry)
    const url = resolveReferenceUrl(meta, entry)
    const docKey = entry?.document_id ?? meta.document_id
    const title = resolveReferenceTitle(meta, entry, idx)
    const sourceTrace = String(meta.source_trace || entry.source_trace || '').trim()
    const mapKey = external
      ? `url-${url || idx + 1}`
      : docKey !== undefined && docKey !== null
        ? `doc-${docKey}`
        : sourceTrace
          ? `trace-${sourceTrace}`
          : title || `reference-${idx + 1}`
    const current =
      merged.get(mapKey) || {
        kind: external ? 'external' : 'internal',
        title,
        url: url || '',
        pages: new Set(),
        lines: new Set(),
        traces: new Set(),
        badge: resolveEvidenceBadge(meta, entry),
      }
    current.kind = current.kind || (external ? 'external' : 'internal')
    current.title = current.title || title
    current.url = current.url || url
    current.badge = current.badge || resolveEvidenceBadge(meta, entry)
    if (external) {
      merged.set(mapKey, current)
      return
    }
    collectLineTokens(current.traces, sourceTrace)
    collectLineTokens(current.traces, meta.endpoint)
    collectLineTokens(current.traces, meta.timestamp)
    collectPageTokens(current.pages, meta.page)
    collectPageTokens(current.pages, meta.page_label)
    collectPageTokens(
      current.pages,
      meta.start_page !== undefined && meta.end_page !== undefined
        ? `${meta.start_page}-${meta.end_page}`
        : null
    )
    ;(Array.isArray(meta.pages) ? meta.pages : []).forEach((page) =>
      collectPageTokens(current.pages, page)
    )
    collectPageTokens(current.pages, entry?.page)
    collectPageTokens(current.pages, entry?.page_label)
    collectLineTokens(current.lines, meta.line)
    collectLineTokens(current.lines, meta.line_label)
    collectLineTokens(
      current.lines,
      meta.start_line !== undefined && meta.end_line !== undefined
        ? `${meta.start_line}-${meta.end_line}`
        : null
    )
    ;(Array.isArray(meta.lines) ? meta.lines : []).forEach((line) =>
      collectLineTokens(current.lines, line)
    )
    collectLineTokens(current.lines, entry?.line)
    collectLineTokens(current.lines, entry?.line_label)
    merged.set(mapKey, current)
  })

  const formatTokenSet = (tokenSet, prefix) => {
    if (!tokenSet.size) return ''
    const formatted = Array.from(tokenSet)
      .map((value) => {
        const token = value.toString().trim()
        if (/^\d+([-/]\d+)?$/.test(token)) {
          return `${prefix}.${token}`
        }
        return token
      })
      .filter(Boolean)
    return formatted.join(' / ')
  }

  return Array.from(merged.values()).map((item) => {
    if (item.kind === 'external') {
      return {
        kind: 'external',
        title: item.url || item.title,
        url: item.url || '',
        badge: item.badge || t('home.references.badges.external_authoritative'),
      }
    }
    const pageLabel = formatTokenSet(item.pages, 'P')
    const lineLabel = formatTokenSet(item.lines, 'L')
    const traceLabel = Array.from(item.traces || [])
      .map((value) => String(value || '').trim())
      .filter(Boolean)
      .join(' / ')
    return {
      kind: 'internal',
      title: item.title,
      location: [pageLabel, lineLabel, traceLabel].filter(Boolean).join(' / '),
      badge: item.badge || t('home.references.badges.internal'),
    }
  })
}

const buildResultCardSummaryBullets = (
  metadata = {},
  answerSummary = '',
  answerHighlights = []
) => {
  const structuredPoints = Array.isArray(metadata.result_card_summary_points)
    ? metadata.result_card_summary_points
        .map((item) => clipResultCardDetail(item))
        .filter((item) => item && !isLowSignalResultCardBullet(item))
        .slice(0, RESULT_CARD_SUMMARY_MAX_ITEMS)
    : []
  if (structuredPoints.length) return structuredPoints

  const structuredBullets = buildStructuredResultCardBullets(answerSummary)
  if (structuredBullets.length) return structuredBullets

  const bullets = buildHighlightsFromMetadata(metadata, answerSummary, answerHighlights)
    .slice(0, RESULT_CARD_SUMMARY_MAX_ITEMS)
    .map((item) => normalizeHighlightLine(item))
    .filter((item) => item && !isLowSignalResultCardBullet(item))
  if (bullets.length) return bullets
  const fallback = normalizeHighlightLine(
    (answerSummary || '').trim() ||
      String(metadata.compact_summary || metadata.summary || '')
        .split('\n')
        .find((line) => line.trim().length)
  )
  return fallback && !isLowSignalResultCardBullet(fallback) ? [clipResultCardDetail(fallback)] : []
}

const buildResultCardSourceLabel = (metadata = {}, references = [], variant = 'title') => {
  const sourceTiers = Array.isArray(metadata.source_tier) ? metadata.source_tier : [metadata.source_tier]
  const hasExternalEvidence =
    sourceTiers.map((value) => String(value || '').toLowerCase()).includes('external_evidence') ||
    Boolean(metadata?.external_search?.attempted) ||
    (Array.isArray(references) && references.some((ref) => ref?.kind === 'external'))
  if (hasExternalEvidence) {
    return t('home.rag.external_search_title')
  }
  return t('home.rag.summary_title')
}

const resolveResultCardSourceLabel = (metadata = {}, references = [], variant = 'title') => {
  const sourceTiers = Array.isArray(metadata.source_tier) ? metadata.source_tier : [metadata.source_tier]
  const hasExternalEvidence =
    sourceTiers.map((value) => String(value || '').toLowerCase()).includes('external_evidence') ||
    Boolean(metadata?.external_search?.attempted) ||
    (Array.isArray(references) && references.some((ref) => ref?.kind === 'external'))

  if (hasExternalEvidence) {
    return variant === 'status'
      ? t('home.rag.external_search_status')
      : t('home.rag.external_search_title')
  }

  return variant === 'status' ? t('home.rag.status_label') : t('home.rag.summary_title')
}

const buildResultCardFromPayload = (
  metadata = {},
  answerSummary = '',
  answerHighlights = [],
  references = []
) => {
  const summaryBullets = buildResultCardSummaryBullets(
    metadata,
    answerSummary,
    answerHighlights
  )
  const rejectedEvidence = Array.isArray(metadata.rejected_evidence)
    ? metadata.rejected_evidence.slice(0, 5).map((item) => ({
        id: item.id || '',
        label: item.label || item.id || '',
        reasons: Array.isArray(item.rejected_reasons) ? item.rejected_reasons.join(', ') : '',
        badge: resolveFilteredEvidenceBadge(),
      }))
    : []
  return {
    id: `meta-${Date.now()}`,
    title: resolveResultCardSourceLabel(metadata, references, 'title'),
    summaryBullets,
    datetime: new Date().toLocaleString(resolveDisplayLocale(), { hour12: false }),
    status: resolveResultCardSourceLabel(metadata, references, 'status'),
    references: Array.isArray(references) ? references : [],
    answerMode: resolveAnswerModeLabel(metadata.answer_verification_mode || metadata.answer_mode),
    answerModeRaw: metadata.answer_verification_mode || metadata.answer_mode || '',
    answerVerification: metadata.answer_verification || {},
    generalAnswerDisclaimer:
      metadata.answer_verification_mode === 'assisted_general_answer'
        ? t('home.transparency.general_answer_disclaimer')
        : '',
    sourceMixRows: buildSourceMixRows(metadata.source_mix || {}),
    coverageReport: metadata.coverage_report || {},
    citationValidation: metadata.citation_validation || metadata.retrieval_snapshot?.citation_validation || {},
    officialInventoryBinding:
      metadata.official_inventory_binding || metadata.retrieval_snapshot?.official_inventory_binding || {},
    hardErrorFlags: Array.isArray(metadata.hard_error_flags) ? metadata.hard_error_flags : [],
    rejectedEvidence,
  }
}

function normalizeMessageResultCard(
  metadata = {},
  answerSummary = '',
  answerHighlights = [],
  references = [],
  messageId = ''
) {
  if (!metadata || typeof metadata !== 'object') return null
  const card = buildResultCardFromPayload(metadata, answerSummary, answerHighlights, references)
  card.id = `meta-${messageId || metadata.message_id || 'message'}`
  const hasTransparency =
    card.answerModeRaw ||
    card.sourceMixRows?.length ||
    card.rejectedEvidence?.length ||
    card.citationValidation?.citation_count != null ||
    card.officialInventoryBinding?.proof_count != null ||
    card.hardErrorFlags?.length
  const hasVisibleBody =
    card.summaryBullets?.length ||
    card.references?.length ||
    hasTransparency
  return hasVisibleBody ? card : null
}

const getResultCardForMessage = (message = {}) => {
  if (!message || message.role !== 'assistant' || messageShouldUseQuoteRenderer(message)) return null
  if (isLatestAssistantMessage(message.id) && chatResultCard.value) {
    return chatResultCard.value
  }
  return (
    message.resultCard ||
    normalizeMessageResultCard(
      message.metadata || {},
      message.summary || '',
      message.highlights || [],
      message.references || [],
      message.id || ''
    )
  )
}

const getResultCardReferenceKey = (message = {}, card = {}) =>
  String(message?.id || card?.id || '')

const isResultCardReferencesExpanded = (message = {}, card = {}) => {
  const key = getResultCardReferenceKey(message, card)
  return key ? expandedReferenceMessageIds.value.has(key) : false
}

const getVisibleResultCardReferences = (message = {}, card = {}) => {
  const references = Array.isArray(card?.references) ? card.references : []
  if (isResultCardReferencesExpanded(message, card)) return references
  return references.slice(0, 3)
}

const shouldShowResultCardReferenceToggle = (card = {}) =>
  Array.isArray(card?.references) && card.references.length > 3

const toggleResultCardReferences = (message = {}, card = {}) => {
  const key = getResultCardReferenceKey(message, card)
  if (!key) return
  const next = new Set(expandedReferenceMessageIds.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedReferenceMessageIds.value = next
}

const formatCurrency = (value) => {
  if (value === null || value === undefined || value === '') {
    return ''
  }
  const amount = Number(value)
  if (Number.isNaN(amount)) {
    return ''
  }
  return `$${amount.toLocaleString('en-US')}`
}

function buildProductCard(product = {}) {
  if (!product || !product.no) {
    return null
  }
  const toNumber = (value) => {
    const amount = Number(value)
    return Number.isNaN(amount) ? null : amount
  }
  const rows = [
    { label: t('home.product_card.labels.number'), value: product.no },
    { label: t('home.product_card.labels.vintage'), value: product.vintage || '-' },
    { label: t('home.product_card.labels.producer'), value: product.producer || '-' },
    { label: t('home.product_card.labels.product'), value: product.name || '-' },
    { label: t('home.product_card.labels.color'), value: resolveCerpColor(product, '-') },
    { label: t('home.product_card.labels.rating'), value: product.rating || '-' },
    { label: t('home.product_card.labels.stock'), value: product.stock ?? 0 },
    { label: t('home.product_card.labels.list_price'), value: formatCurrency(product.price) || '-' },
    { label: t('home.product_card.labels.vip_quote'), value: formatCurrency(product.vip_price) || '-' },
  ]
  const promoNotes = []
  if (product.promo) {
    promoNotes.push(product.promo)
  }
  if (product.gift) {
    promoNotes.push(t('home.product_card.bundle_1_1'))
  }
  if (promoNotes.length) {
    rows.push({ label: t('home.product_card.labels.promo'), value: promoNotes.join(' / ') })
  }
  const photoUrl = product.photo_url || product.photoUrl || ''
  if (typeof window !== 'undefined' && window.console) {
    if (photoUrl) {
      window.console.debug(`[Product Inventory] product ${product.no} photo resolved: ${photoUrl}`)
    } else {
      window.console.debug(`[Product Inventory] product ${product.no} photo missing, using placeholder`)
    }
  }
  const vipPrice = toNumber(product.vip_price ?? product.vipPrice)
  const listPrice = toNumber(product.price ?? product.list_price ?? product.listPrice)
  const stockCount = toNumber(resolveCerpStock(product))
  const productName =
    product.name || product.name_en || product.name_ch || product.invn005 || product.no
  const displayTitle = [product.producer, productName].filter(Boolean).join(' ')
  const resolvedColor = resolveCerpColor(product, '-')
  return {
    id: `cerp-${product.no}-${Date.now()}`,
    sku: product.no,
    title: displayTitle || t('home.product_card.default_title'),
    vintage: product.vintage || t('home.product_card.non_vintage'),
    color: resolvedColor,
    rating: product.rating || product.invn804 || '-',
    producer: product.producer || '-',
    price: listPrice,
    vipPrice,
    stock: stockCount,
    bundleLabel: product.gift ? t('home.product_card.bundle_label') : product.bundle || '',
    tags: promoNotes,
    description: promoNotes.join(' / ') || '',
    photoText: product.photo_placeholder || t('home.product_card.photo_placeholder'),
    photoUrl,
    fields: rows,
  }
}


const handleComposerUploadClick = () => {
  triggerUploadSelect()
}

const handleComposerFilesSelected = (event) => {
  handleUploadFilesSelected(event)
}

const handleComposerUrlsAdded = (rawValue) => {
  addComposerUrls(rawValue)
}

const clearComposerAttachments = () => {
  clearUploadAttachments()
}

const removeComposerAttachment = (id) => {
  removeUploadAttachment(id)
}

const uploadFileBeforeSend = async () => {
  return uploadAttachmentsBeforeSend()
}

const resolveSingleAttachmentMeta = (metas) => {
  if (!Array.isArray(metas) || !metas.length) return null
  return metas[0] || null
}

const collectComposerUrlInputs = () => extractComposerUrlInputs()

const uploadAttachmentMetaIfNeeded = async () => {
  if (!uploadAttachments.value.length) return null
  const metas = await uploadFileBeforeSend()
  const attachmentMeta = resolveSingleAttachmentMeta(metas)
  if (attachmentMeta) {
    clearUploadFiles()
  }
  return attachmentMeta
}

const handleSessionExpired = () => {
  resetConversationState()
  isChatActive.value = false
  clearAllConversationIds()
  clearSession()
  dialogHistory.value = []
  clearComposerAttachments()
}

const shouldHandleSessionExpired = (error) => Boolean(error?.shouldLogout)

const persistQuoteItems = (items) => {
  try {
    localStorage.setItem(QUOTE_STORAGE_KEY, JSON.stringify(items || []))
  } catch (error) {
    console.warn('Unable to persist quote items', error)
  }
}

const persistQuoteContext = (context) => {
  try {
    localStorage.setItem(
      QUOTE_CONTEXT_KEY,
      JSON.stringify({
        conversation_id: context?.conversation_id || null,
        project: context?.project || null,
        lang: normalizeQuoteLanguage(context?.lang, languagePreference.value),
        surface_origin: context?.surface_origin || null,
        quote_continuity: hasQuoteContinuity(context?.quote_continuity)
          ? extractQuoteContinuityPayload(context?.quote_continuity, {
              conversationId: context?.conversation_id || null,
              project: context?.project || null,
              lang: context?.lang || languagePreference.value,
              surfaceOrigin: context?.surface_origin || 'chat-ui',
            })
          : null,
        saved_at: new Date().toISOString(),
      })
    )
  } catch (error) {
    console.warn('Unable to persist quote context', error)
  }
}

const clearStoredQuoteState = () => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(QUOTE_STORAGE_KEY)
    window.localStorage.removeItem(QUOTE_CONTEXT_KEY)
  } catch (error) {
    console.warn('Unable to clear stored quote state', error)
  }
}

const buildQuoteThreadSnapshot = () =>
  chatMessages.value.map((message, index) => ({
    id: message?.id || `quote-handoff-${index}`,
    role: message?.role === 'assistant' ? 'assistant' : 'user',
    text: String(message?.content || message?.text || ''),
    timestamp: message?.createdAt || message?.created_at || new Date().toISOString(),
    author_user_id: message?.authorUserId ?? null,
    author_username: message?.authorUsername || '',
    author_name: message?.authorName || '',
    metadata:
      message?.metadata && typeof message.metadata === 'object' ? message.metadata : {},
  }))

const buildQuotePendingPayload = (message = '', urlInputs = []) => {
  const normalizedUrls = Array.isArray(urlInputs) ? urlInputs.filter(Boolean) : []
  return {
    rawMessage: String(message || '').trim(),
    displayMessage: buildVisiblePromptForThread(message, normalizedUrls),
    urlInputs: normalizedUrls,
  }
}

const persistQuoteChatHandoff = (payload) => {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(
      QUOTE_CHAT_HANDOFF_KEY,
      JSON.stringify({
        conversation_id: payload?.conversation_id || null,
        project: payload?.project || null,
        thread: Array.isArray(payload?.thread) ? payload.thread : [],
        pending_message: payload?.pending_message || '',
        raw_message: payload?.raw_message || payload?.pending_message || '',
        lang: normalizeQuoteLanguage(payload?.lang, languagePreference.value),
        surface_origin: payload?.surface_origin || 'chat-ui',
        attachment: payload?.attachment || null,
        url_inputs: Array.isArray(payload?.url_inputs) ? payload.url_inputs.filter(Boolean) : [],
        followup_action: payload?.followup_action || null,
        followup_action_source: payload?.followup_action_source || null,
        quote_continuity: hasQuoteContinuity(payload?.quote_continuity)
          ? extractQuoteContinuityPayload(payload?.quote_continuity, {
              conversationId: payload?.conversation_id || null,
              project: payload?.project || null,
              lang: payload?.lang || languagePreference.value,
              surfaceOrigin: payload?.surface_origin || 'chat-ui',
            })
          : null,
        tab: payload?.tab || 'report',
        created_at: new Date().toISOString(),
      })
    )
  } catch (error) {
    console.warn('Unable to persist quote chat handoff payload', error)
  }
}

const loadQuoteDestinationPreference = () => {
  if (typeof window === 'undefined') return false
  try {
    const raw = window.sessionStorage.getItem(QUOTE_SHOW_GENERATED_KEY)
    if (raw === null) return false
    return raw !== '0'
  } catch (error) {
    console.warn('Unable to load quote destination preference', error)
    return false
  }
}

const persistQuoteDestinationPreference = (value) => {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(QUOTE_SHOW_GENERATED_KEY, value ? '1' : '0')
  } catch (error) {
    console.warn('Unable to persist quote destination preference', error)
  }
}

const resetHomeQuoteDestinationPreference = () => {
  showGeneratedResults.value = false
  persistQuoteDestinationPreference(false)
}

const extractQuoteItemsFromMetadata = (metadata = {}) =>
  Array.isArray(metadata?.quote_items) ? metadata.quote_items : []

const findLatestQuoteMessage = (messages = []) => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role !== 'assistant') continue
    const metadata = message.metadata || {}
    const quoteItems = getActionableQuoteRows(metadata)
    const hasFollowupPayload =
      (metadata?.quote_followup && typeof metadata.quote_followup === 'object') ||
      (Array.isArray(metadata?.available_actions) && metadata.available_actions.length)
    if (quoteItems.length || metadata?.quote_ui || hasFollowupPayload) {
      return message
    }
  }
  return null
}

const findLatestAssistantMessage = (messages = []) => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant') return message
  }
  return null
}

const latestQuoteAssistantMessage = computed(() => findLatestQuoteMessage(chatMessages.value))
const latestAssistantMessage = computed(() => findLatestAssistantMessage(chatMessages.value))

const buildQuoteContinuityFromMessage = (message, options = {}) =>
  extractQuoteContinuityPayload(message?.metadata || {}, {
    conversationId: options.conversationId || activeConversationId.value || null,
    project: options.project || activeProjectPayload.value || null,
    lang: options.lang || languagePreference.value,
    surfaceOrigin: options.surfaceOrigin || 'chat-ui',
    messageId: message?.id || null,
    createdAt: message?.createdAt || message?.timestamp || null,
  })

const activeQuoteContinuity = computed(() =>
  buildQuoteContinuityFromMessage(latestQuoteAssistantMessage.value)
)

const getQuoteUiForMessage = (message) =>
  message?.quoteUi || normalizeMessageQuoteUi(message?.metadata || {}, message?.createdAt)

const messageHasQuoteUi = (message) => {
  const metadata = message?.metadata || {}
  const hasExplicitQuotePayload =
    Boolean(metadata?.quote_ui) ||
    getActionableQuoteRows(metadata).length > 0 ||
    Boolean(metadata?.quote_followup && typeof metadata.quote_followup === 'object') ||
    Boolean(Array.isArray(metadata?.available_actions) && metadata.available_actions.length)
  return Boolean(hasExplicitQuotePayload && getQuoteUiForMessage(message))
}

const messageShouldUseQuoteRenderer = (message) => {
  if (!messageHasQuoteUi(message)) return false
  if (messageHasCerpResults(message)) return false
  return true
}

const getQuoteContinuityForMessage = (message) =>
  buildQuoteContinuityFromMessage(message, {
    conversationId: activeConversationId.value || null,
    project: activeProjectPayload.value || null,
    lang: languagePreference.value,
    surfaceOrigin: 'chat-ui',
  })

const getQuoteFollowupSummaryForMessage = (message) =>
  buildQuoteFollowupSummary(getQuoteContinuityForMessage(message), languagePreference.value)

const getQuoteFollowupActionsForMessage = (message) =>
  buildQuoteFollowupActions(getQuoteContinuityForMessage(message), languagePreference.value)

const messageHasStandardFollowup = (message) =>
  Boolean(
    !messageShouldUseQuoteRenderer(message) &&
      (
        getQuoteFollowupSummaryForMessage(message) ||
        getQuoteFollowupActionsForMessage(message)?.length
      )
  )

const buildQuoteShareText = (message) =>
  buildQuoteShareTextContent(getQuoteUiForMessage(message), message?.content || '')

const buildQuoteShareTextLegacy = (message) => {
  const quoteUi = getQuoteUiForMessage(message)
  if (!quoteUi) {
    return String(message?.content || '').trim()
  }
  return [
    quoteUi.intro,
    ...(quoteUi.introBullets || []).map((entry) => `- ${entry}`),
    quoteUi.title,
    quoteUi.closing,
    ...(quoteUi.closingBullets || []).map((entry) => `- ${entry}`),
  ]
    .map((entry) => String(entry || '').trim())
    .filter(Boolean)
    .join('\n')
}

const latestQuoteResultTarget = computed(() => {
  const message = latestAssistantMessage.value
  if (!message) return null
  const rows = getActionableQuoteRows(message.metadata || {})
  if (!rows.length) return null
  return { message, rows }
})

const latestActionableQuoteRows = computed(() => latestQuoteResultTarget.value?.rows || [])

const showQuoteResultToggle = computed(
  () => isChatActive.value && Boolean(latestQuoteResultTarget.value)
)

const persistQuoteChatUiReturnPayload = (payload) => {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(
      QUOTE_CHATUI_RETURN_KEY,
      JSON.stringify({
        conversation_id: payload?.conversation_id || null,
        project: payload?.project || null,
        user_prompt: payload?.user_prompt || '',
        assistant_message: payload?.assistant_message || null,
        lang: normalizeQuoteLanguage(payload?.lang, languagePreference.value),
        surface_origin: payload?.surface_origin || 'quote-chat',
        url_inputs: Array.isArray(payload?.url_inputs) ? payload.url_inputs.filter(Boolean) : [],
        quote_continuity: hasQuoteContinuity(payload?.quote_continuity)
          ? extractQuoteContinuityPayload(payload?.quote_continuity, {
              conversationId: payload?.conversation_id || null,
              project: payload?.project || null,
              lang: payload?.lang || languagePreference.value,
              surfaceOrigin: payload?.surface_origin || 'quote-chat',
            })
          : null,
        created_at: payload?.created_at || new Date().toISOString(),
      })
    )
  } catch (error) {
    console.warn('Unable to persist quote ChatUI return payload', error)
  }
}

const loadQuoteChatUiReturnPayload = () => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(QUOTE_CHATUI_RETURN_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch (error) {
    console.warn('Unable to load quote ChatUI return payload', error)
    return null
  }
}

const clearQuoteChatUiReturnPayload = () => {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(QUOTE_CHATUI_RETURN_KEY)
}

const routeToLatestQuoteView = async () => {
  const target = latestQuoteResultTarget.value
  if (!target) {
    showGeneratedResults.value = false
    return
  }
  const latestQuote = target.message
  const actionableQuoteRows = target.rows
  if (!actionableQuoteRows.length) {
    showGeneratedResults.value = false
    chatError.value = t('home.errors.quote_results_unavailable')
    return
  }
  const quoteContinuity =
    buildQuoteContinuityFromMessage(latestQuote, {
      conversationId: activeConversationId.value || null,
      project: activeProjectPayload.value || null,
      lang: languagePreference.value,
      surfaceOrigin: 'chat-ui',
    }) || null
  persistQuoteItems(actionableQuoteRows)
  const nextProject =
    activeProjectPayload.value ||
    ((activeProjectId.value || conversationTitle.value)
      ? {
          id: activeProjectId.value || undefined,
          label: conversationTitle.value,
        }
      : null)
  persistQuoteContext({
    conversation_id: activeConversationId.value || null,
    project: nextProject,
    lang: languagePreference.value,
    surface_origin: 'chat-ui',
    quote_continuity: quoteContinuity,
  })
  await router.push({ name: 'quote', query: { tab: QUOTE_DEFAULT_TAB } })
}

const handleHomeQuoteResultToggleChange = () => {
  persistQuoteDestinationPreference(showGeneratedResults.value)
  if (showGeneratedResults.value) {
    if (!showQuoteResultToggle.value) {
      showGeneratedResults.value = false
      persistQuoteDestinationPreference(false)
      return
    }
    routeToLatestQuoteView().catch((error) => {
      console.warn('Unable to route to quote view from ChatUI', error)
    })
  }
}

const buildVisiblePromptForThread = (content = '', urlInputs = []) =>
  buildVisibleUserPrompt(content, urlInputs)

const getStructuredUrlsFromMetadata = (metadata = {}) => collectStructuredUrlInputs(metadata)

const hydrateStructuredUrlsIntoThread = (messages = []) => {
  if (!Array.isArray(messages) || !messages.length) return []
  const hydrated = messages.map((message) => ({ ...message }))
  for (let index = 0; index < hydrated.length; index += 1) {
    const current = hydrated[index]
    if (current?.role !== 'user') continue
    const currentContent = String(current?.content || '').trim()
    const nextAssistant = hydrated
      .slice(index + 1)
      .find((entry) => entry?.role === 'assistant' && getStructuredUrlsFromMetadata(entry?.metadata || {}).length)
    if (!nextAssistant) continue
    const urlInputs = getStructuredUrlsFromMetadata(nextAssistant.metadata || {})
    const visibleContent = buildVisiblePromptForThread(currentContent, urlInputs)
    if (visibleContent && visibleContent !== currentContent) {
      current.content = visibleContent
    }
  }
  return hydrated
}

const getActionableQuoteRows = (metadata = {}) => extractActionableQuoteRows(metadata)

const resolveUrlInputsForFollowupMessage = (message = {}) => {
  const metadata = message?.metadata && typeof message.metadata === 'object' ? message.metadata : {}
  const fromMetadata = Array.isArray(metadata.url_inputs) ? metadata.url_inputs.filter(Boolean) : []
  if (fromMetadata.length) {
    return fromMetadata
  }
  const primaryUrl = String(metadata.primary_url || '').trim()
  if (primaryUrl) {
    return [primaryUrl]
  }
  return collectComposerUrlInputs()
}

const handleQuoteFollowupActionFromChatUi = async (message, action) => {
  const actionId = String(action?.id || '').trim()
  const prompt = String(action?.prompt || '').trim()
  if (!actionId || !prompt || !activeConversationId.value) return
  const quoteContinuity = getQuoteContinuityForMessage(message)
  if (!quoteContinuity) return
  const shouldForwardFollowupAction = actionId !== QUOTE_ACTION_PIVOT_TO_QUOTE
  const attachmentMeta = await uploadAttachmentMetaIfNeeded()
  const urlInputs = resolveUrlInputsForFollowupMessage(message)
  const pendingPayload = buildQuotePendingPayload(prompt, urlInputs)
  const projectPayload = activeProjectPayload.value?.id
    ? {
        ...activeProjectPayload.value,
        label:
          activeProjectPayload.value.label ||
          conversationTitle.value ||
          t('home.defaults.project_fallback'),
      }
    : null
  clearStoredQuoteState()
  persistQuoteChatHandoff({
    conversation_id: activeConversationId.value,
    project: projectPayload,
    thread: buildQuoteThreadSnapshot(),
    pending_message: pendingPayload.displayMessage,
    raw_message: pendingPayload.rawMessage,
    lang: languagePreference.value,
    surface_origin: 'chat-ui',
    attachment: attachmentMeta,
    url_inputs: pendingPayload.urlInputs,
    followup_action: shouldForwardFollowupAction ? actionId : null,
    followup_action_source: shouldForwardFollowupAction ? 'button' : null,
    quote_continuity: quoteContinuity,
    tab: QUOTE_DEFAULT_TAB,
  })
  persistPendingQuoteCompose({
    message: pendingPayload.rawMessage,
    display_message: pendingPayload.displayMessage,
    tab: QUOTE_DEFAULT_TAB,
    project: projectPayload,
    conversation_id: activeConversationId.value,
    lang: languagePreference.value,
    surface_origin: 'chat-ui',
    attachment: attachmentMeta,
    url_inputs: pendingPayload.urlInputs,
    followup_action: shouldForwardFollowupAction ? actionId : null,
    followup_action_source: shouldForwardFollowupAction ? 'button' : null,
    quote_continuity: quoteContinuity,
  })
  clearComposerAttachments()
  messageInput.value = ''
  composerValue.value = ''
  await router.push({ name: 'quote', query: { tab: QUOTE_DEFAULT_TAB } }).catch(() => {})
}

const consumeQuoteChatUiReturnPayload = async () => {
  const payload = loadQuoteChatUiReturnPayload()
  if (!payload) return
  clearQuoteChatUiReturnPayload()

  const project =
    payload?.project && typeof payload.project === 'object' ? payload.project : null
  const conversationId = String(payload?.conversation_id || '').trim()
  const fallbackLabel = String(project?.label || conversationTitle.value || '').trim()
  languagePreference.value = normalizeQuoteLanguage(payload?.lang, languagePreference.value)
  const quoteContinuity = hasQuoteContinuity(payload?.quote_continuity)
    ? extractQuoteContinuityPayload(payload?.quote_continuity, {
        conversationId,
        project,
        lang: payload?.lang || languagePreference.value,
        surfaceOrigin: payload?.surface_origin || 'quote-chat',
      })
    : null

  if (project?.id) {
    activeProjectId.value = project.id
  }
  if (fallbackLabel) {
    conversationTitle.value = fallbackLabel
    renameValue.value = fallbackLabel
  }
  if (conversationId) {
    setConversationIdForProject(project?.id || activeProjectId.value, conversationId)
  }
  if (quoteContinuity) {
    persistQuoteContext({
      conversation_id: conversationId || null,
      project,
      lang: languagePreference.value,
      surface_origin: quoteContinuity.surface_origin || 'quote-chat',
      quote_continuity: quoteContinuity,
    })
  }

  const draftMessages = []
  const assistantMessage = payload?.assistant_message
  const createdAt =
    assistantMessage?.created_at || payload?.created_at || new Date().toISOString()
  const userPrompt = String(payload?.user_prompt || '').trim()

  if (userPrompt) {
    draftMessages.push(
      normalizeThreadMessage(
        {
          id: createMessageId('quote-return-user'),
          role: 'user',
          content: userPrompt,
          created_at: createdAt,
        },
        draftMessages.length
      )
    )
    submittedTask.value = userPrompt
  }

  if (assistantMessage && typeof assistantMessage === 'object') {
    const assistantRecord = normalizeThreadMessage(
      {
        id: assistantMessage.id || createMessageId('quote-return-assistant'),
        role: 'assistant',
        content: assistantMessage.text || '',
        created_at: createdAt,
        metadata: assistantMessage.metadata || {},
      },
      draftMessages.length
    )
    draftMessages.push(assistantRecord)
    hydrateUiFromAssistantMessage(assistantRecord, assistantRecord.metadata || {}, {
      references: assistantRecord.references || [],
    })
  }

  if (draftMessages.length) {
    chatMessages.value = draftMessages
    isChatActive.value = true
    await nextTick()
    scrollChatToBottom()
  }

  if (conversationId) {
    await loadConversationPreview(conversationId, fallbackLabel)
  }
}

const applyChatResponse = (response, question) => {
  isHistoryPreview.value = false
  const answer = response?.answer || {}
  const metadata = answer.metadata || {}
  const responseLang = normalizeQuoteLanguage(
    metadata?.language || metadata?.lang || response?.language,
    languagePreference.value
  )
  const normalizedMetadata = {
    ...metadata,
    answer_citations: Array.isArray(answer.citations)
      ? answer.citations
      : metadata?.answer_citations,
    result_card_summary_points:
      Array.isArray(answer.summary_points) && answer.summary_points.length
        ? answer.summary_points
        : metadata?.result_card_summary_points,
    summary_generation: metadata?.summary_generation || answer.summary_generation,
    language: metadata?.language || responseLang,
    lang: metadata?.lang || responseLang,
  }
  const assistantText = answer.text || response?.content || ''
  const references = buildContextReferences(collectResponseReferenceContext(response, answer))
  const assistantRecord = normalizeThreadMessage(
    {
      id: answer.message_id || createMessageId('assistant'),
      role: 'assistant',
      content: assistantText,
      summary: answer.summary || normalizedMetadata.summary || '',
      summary_points: Array.isArray(answer.summary_points) ? answer.summary_points : [],
      highlights: answer.highlights || normalizedMetadata.highlights || [],
      created_at: new Date().toISOString(),
      metadata: normalizedMetadata,
      references,
    },
    chatMessages.value.length
  )
  chatMessages.value.push(assistantRecord)
  hydrateUiFromAssistantMessage(assistantRecord, normalizedMetadata, { references })
  const responseProject = response?.project
  if (responseProject?.id) {
    activeProjectId.value = responseProject.id
  }
  if (responseProject?.label) {
    conversationTitle.value = responseProject.label
  }
  if (answer.conversation_id) {
    const targetProjectId = responseProject?.id || activeProjectId.value
    setConversationIdForProject(targetProjectId, answer.conversation_id)
  }
  const actionableQuoteRows = getActionableQuoteRows(normalizedMetadata)
  if (actionableQuoteRows.length) {
    persistQuoteItems(actionableQuoteRows)
  }
  updateHistoryFromResponse(response, conversationTitle.value, question)
  refreshHistorySilently()
  submittedTask.value = question
  isChatActive.value = true
}

const ensureConversationLabelForNewChat = (question) => {
  if (activeConversationId.value) {
    return conversationTitle.value
  }
  const generated = generateConversationLabel(question)
  conversationTitle.value = generated
  renameValue.value = generated
  return generated
}

const submitPrompt = async (prompt) => {
  const value = (prompt || '').trim()
  if (!value || isSending.value) return
  const selectedQuoteOutput = resolveSelectedQuoteOutput()
  const lang = (languagePreference.value = detectQuoteLanguage(value))
  const quoteContinuity = activeQuoteContinuity.value
  if (selectedQuoteOutput) {
    const attachmentMeta = await uploadAttachmentMetaIfNeeded()
    const urlInputs = collectComposerUrlInputs()
    const pendingPayload = buildQuotePendingPayload(value, urlInputs)
    const projectPayload = activeProjectPayload.value?.id
      ? {
          ...activeProjectPayload.value,
          label:
            activeProjectPayload.value.label ||
            conversationTitle.value ||
            t('home.defaults.project_fallback'),
        }
      : null
    clearStoredQuoteState()
    persistQuoteChatHandoff({
      conversation_id: activeConversationId.value || null,
      project: projectPayload,
      thread: buildQuoteThreadSnapshot(),
      pending_message: pendingPayload.displayMessage,
      raw_message: pendingPayload.rawMessage,
      lang,
      surface_origin: 'chat-ui',
      attachment: attachmentMeta,
      url_inputs: pendingPayload.urlInputs,
      quote_continuity:
        quoteContinuity ||
        extractQuoteContinuityPayload(
          { intent: 'QUOTE_LIST' },
          {
            conversationId: activeConversationId.value || null,
            project: projectPayload,
            lang,
            surfaceOrigin: 'chat-ui',
          }
        ),
      tab: selectedQuoteOutput.tab,
    })
    persistPendingQuoteCompose({
      message: pendingPayload.rawMessage,
      display_message: pendingPayload.displayMessage,
      tab: selectedQuoteOutput.tab,
      project: projectPayload,
      conversation_id: activeConversationId.value || null,
      lang,
      surface_origin: 'chat-ui',
      attachment: attachmentMeta,
      url_inputs: pendingPayload.urlInputs,
      quote_continuity:
        quoteContinuity ||
        extractQuoteContinuityPayload(
          { intent: 'QUOTE_LIST' },
          {
            conversationId: activeConversationId.value || null,
            project: projectPayload,
            lang,
            surfaceOrigin: 'chat-ui',
          }
        ),
    })
    clearComposerAttachments()
    selectedOutputValue.value = ''
    messageInput.value = ''
    composerValue.value = ''
    router.push({ name: 'quote', query: { tab: selectedQuoteOutput.tab } }).catch(() => {})
    return
  }
  isHistoryPreview.value = false
  isChatActive.value = true
  isSending.value = true
  isAssistantTyping.value = true
  chatError.value = ''
  submittedTask.value = value
  const pendingUserMessageId = addUserMessageToThread(value, collectComposerUrlInputs())
  const conversationLabel = ensureConversationLabelForNewChat(value)
  try {
    const attachmentMeta = await uploadAttachmentMetaIfNeeded()
    const urlInputs = collectComposerUrlInputs()
    const payload = {
      message: value,
      conversation_id: activeConversationId.value || undefined,
      create_new_conversation: !activeConversationId.value,
      lang,
      ignore_history_before_today: ignoreHistoryBeforeToday.value,
      output_type: selectedQuoteOutput ? OUTPUT_TYPE_QUOTE_VALUE : undefined,
    }
    if (activeProjectPayload.value?.id) {
      payload.project = {
        ...activeProjectPayload.value,
        label:
          activeProjectPayload.value.label ||
          conversationLabel ||
          conversationTitle.value ||
          t('home.defaults.project_fallback'),
      }
    }
    if (attachmentMeta) {
      payload.attachment = attachmentMeta
    }
    if (urlInputs.length) {
      payload.url_inputs = urlInputs
    }
    const response = await sendChatMessage(payload)
    if (response?.kind === 'system') {
      if (response.action === 'login_required') {
        removeMessageFromThread(pendingUserMessageId)
        handleSessionExpired()
        return
      }
      if (response.action === 'prompt_login') {
        removeMessageFromThread(pendingUserMessageId)
        chatError.value = t('home.errors.login_required')
        return
      }
    }
    if (!response?.ok) {
      throw new Error(response?.error || t('home.errors.chat_failed'))
    }
    applyChatResponse(response, value)
    clearComposerAttachments()
  } catch (error) {
    removeMessageFromThread(pendingUserMessageId)
    chatError.value = error?.message || t('home.errors.chat_busy')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isAssistantTyping.value = false
    isSending.value = false
    messageInput.value = ''
    composerValue.value = ''
  }
}

const DEFAULT_PROJECT_KEY = 'default-project'
const CONVERSATION_STORAGE_KEY = 'ys-chat-conversation-map'

const toProjectKey = (value) => {
  const normalized = typeof value === 'string' ? value.trim() : value != null ? String(value) : ''
  return normalized || DEFAULT_PROJECT_KEY
}

const readConversationStore = () => {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(CONVERSATION_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

const persistConversationStore = (store) => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(store))
  } catch {
    window.localStorage.removeItem(CONVERSATION_STORAGE_KEY)
  }
}

const conversationStore = ref(readConversationStore())

const setConversationIdForProject = (projectId, value) => {
  const key = toProjectKey(projectId)
  const next = { ...conversationStore.value }
  if (value) {
    next[key] = value
  } else {
    delete next[key]
  }
  conversationStore.value = next
  persistConversationStore(next)
}

const getConversationIdForProject = (projectId) => {
  const key = toProjectKey(projectId)
  return conversationStore.value[key] || null
}

const clearAllConversationIds = () => {
  conversationStore.value = {}
  persistConversationStore({})
}

const resolveProjectById = (id) =>
  dialogHistory.value.find((item) => item.projectId === id) || null

const activeProjectId = ref(null)
const activeProject = computed(() => resolveProjectById(activeProjectId.value))
const activeConversationId = computed(
  () => getConversationIdForProject(activeProjectId.value)
)
const activeConversationRecord = computed(() =>
  dialogHistory.value.find((item) => item.id === activeConversationId.value) || null
)
const chatHeaderTitle = computed(() => {
  const recordTitle = normalizeWhitespace(activeConversationRecord.value?.title || '')
  if (activeConversationRecord.value?.hasCustomTitle && recordTitle) {
    return recordTitle
  }
  const currentTitle = normalizeWhitespace(conversationTitle.value || '')
  if (activeConversationId.value && hasCustomConversationTitle(currentTitle)) {
    return currentTitle
  }
  return submittedTask.value || defaultUserPrompt
})

const clearActiveConversationId = () => {
  setConversationIdForProject(activeProjectId.value, null)
}

const assignNewProjectContext = () => {
  activeProjectId.value = null
  setConversationIdForProject(null, null)
  return null
}

watch(
  dialogHistory,
  (list) => {
    if (!Array.isArray(list) || !list.length) {
      if (!isChatActive.value) {
        assignNewProjectContext()
      }
      return
    }
  },
  { immediate: true }
)

const activeProjectPayload = computed(() => {
  const explicitProjectId = normalizeWhitespace(activeProjectId.value || '')
  if (!explicitProjectId) {
    return null
  }
  const descriptor = activeProject.value
  const label =
    descriptor?.projectLabel ||
    descriptor?.title ||
    descriptor?.subtitle ||
    descriptor?.summary ||
    descriptor?.owner ||
    descriptor?.name ||
    t('home.defaults.project_fallback')
  return {
    id: descriptor?.projectId || explicitProjectId,
    label,
  }
})

const chatThreadRef = ref(null)
const isConversationLoading = ref(false)

watch(
  () => [
    chatMessages.value.length,
    isSending.value,
    isConversationLoading.value,
    isAssistantTyping.value,
  ],
  () => {
    nextTick(scrollChatToBottom)
  },
  { deep: false }
)

const latestAssistantMessageId = computed(() => {
  for (let i = chatMessages.value.length - 1; i >= 0; i -= 1) {
    const entry = chatMessages.value[i]
    if (entry?.role === 'assistant' && entry.id) {
      return entry.id
    }
  }
  return null
})

const messageHasCerpData = (message) => {
  const text = String(message?.content || '')
  const hasNotice = text.includes(CERP_DIRECT_NOTICE) || text.includes(CERP_HISTORY_NOTICE)
  return Boolean(
    hasNotice ||
      (message &&
        (message.isCerpData ||
          message?.cerpProductCard ||
          message?.metadata?.is_cerp_data ||
          message?.metadata?.cerp_product ||
          message?.metadata?.cerp_results ||
          message?.cerp_product))
  )
}

const getProductCardForMessage = (message) => message?.cerpProductCard

const CERP_RESULT_PROMPT_CATEGORIES = new Set([
  'quote_recommendation',
  'inventory_lookup',
  'cerp_business_lookup',
  'url_product_lookup',
  'image_product_lookup',
])

const CERP_RESULT_INTENTS = new Set(['QUOTE_LIST'])
const CERP_RESULT_KINDS = new Set([
  'quote_recommendation',
  'inventory_lookup',
  'cerp_business_snapshot',
  'url_product_lookup',
  'image_product_lookup',
  'explicit_cerp_lookup',
])

const messageAllowsCerpResults = (message) => {
  const metadata = message?.metadata || {}
  const cerpResults = metadata?.cerp_results && typeof metadata.cerp_results === 'object'
    ? metadata.cerp_results
    : {}
  const promptCategory = String(metadata.prompt_category || '').trim()
  const intent = String(metadata.intent || message?.intent || '').trim()
  const cerpKind = String(cerpResults.kind || '').trim()
  const lookupGoal = String(metadata.lookup_goal || metadata?.retrieval_snapshot?.lookup_goal || '').trim()
  const attachmentMatchIntent = String(
    metadata.attachment_match_intent ||
    metadata?.attachment_context?.match_intent ||
    ''
  ).trim()
  return (
    CERP_RESULT_PROMPT_CATEGORIES.has(promptCategory) ||
    CERP_RESULT_KINDS.has(cerpKind) ||
    CERP_RESULT_INTENTS.has(intent) ||
    lookupGoal === 'product_availability_from_url' ||
    attachmentMatchIntent === 'cerp_match' ||
    Boolean(metadata.is_cerp_data || metadata.cerp_product || message?.cerpProductCard)
  )
}

const normalizeCerpResultsForMessage = (message) => {
  if (!messageAllowsCerpResults(message)) return []
  const metadata = message?.metadata || {}
  const cerpResults = metadata?.cerp_results && typeof metadata.cerp_results === 'object'
    ? metadata.cerp_results
    : {}
  const sourceItems = Array.isArray(cerpResults.items) ? cerpResults.items : []
  return sourceItems
    .filter((item) => item && typeof item === 'object')
    .map((item, index) => {
      const code = String(item.code || item.no || item.id || '').trim()
      const producer = String(item.producer || '').trim()
      const name = String(item.name || item.name_en || item.name_ch || item.product || item.title || '').trim()
      const vintage = item.vintage ?? ''
      const stock = item.stock ?? item.stock_qty ?? item.total_stock ?? ''
      const price = item.price ?? item.list_price ?? ''
      const vipPrice = item.vip_price ?? item.quote_price ?? ''
      const status = String(item.status || item.availability || '').trim()
      const category = String(item.category || item.recommendation_category_label || '').trim()
      const reason = String(item.recommendation_group_reason || item.recommendation_reason || item.reason || '').trim()
      const usage = String(item.recommendation_usage || '').trim()
      const specialRecommended = Boolean(item.special_recommended || item.specialRecommended)
      const matchKeywords = Array.isArray(item.match_keywords) ? item.match_keywords : []
      const sourceTrace = String(item.source_trace || item.sourceTrace || '').trim()
      const timestamp = String(item.timestamp || item.updated_at || '').trim()
      const proof = item.proof && typeof item.proof === 'object' ? item.proof : {}
      const businessFields = item.business_fields && typeof item.business_fields === 'object'
        ? item.business_fields
        : {}
      const fieldNames = Array.isArray(item.field_names) ? item.field_names : Object.keys(businessFields)
      return {
        key: `${code || name || 'cerp'}-${index}`,
        code,
        producer,
        name,
        vintage,
        stock,
        price,
        vipPrice,
        status,
        category,
        reason: [reason, usage].filter(Boolean).join(' '),
        usage,
        specialRecommended,
        matchKeywords,
        sourceTrace,
        timestamp,
        proof,
        businessFields,
        fieldNames,
      }
    })
}

const messageHasCerpResults = (message) => normalizeCerpResultsForMessage(message).length > 0

const messageHasCerpResultCategories = (message) =>
  normalizeCerpResultsForMessage(message).some((item) => item.category)

const messageHasCerpResultReasons = (message) =>
  normalizeCerpResultsForMessage(message).some((item) => item.reason)

const getCerpResultProofSummary = (message) => {
  const metadata = message?.metadata || {}
  const cerpResults = metadata?.cerp_results && typeof metadata.cerp_results === 'object'
    ? metadata.cerp_results
    : {}
  const binding = metadata?.official_inventory_binding && typeof metadata.official_inventory_binding === 'object'
    ? metadata.official_inventory_binding
    : {}
  const items = normalizeCerpResultsForMessage(message)
  const firstTrace = items.find((item) => item.sourceTrace)?.sourceTrace || ''
  const firstTimestamp =
    cerpResults.generated_at ||
    items.find((item) => item.timestamp)?.timestamp ||
    ''
  const proofCount = binding.proof_count ?? cerpResults.proof_count ?? items.length
  return {
    source: cerpResults.source || tMessage(message, 'home.cerp_results.source'),
    sourceTrace: firstTrace,
    timestamp: firstTimestamp,
    proofCount,
  }
}

const getCerpResultLimitSummary = (message) => {
  const metadata = message?.metadata || {}
  const cerpResults = metadata?.cerp_results && typeof metadata.cerp_results === 'object'
    ? metadata.cerp_results
    : {}
  const total = Number(metadata.total_match_count ?? cerpResults.total_match_count ?? 0)
  const displayed = Number(metadata.displayed_count ?? cerpResults.displayed_count ?? 0)
  const truncated = Boolean(metadata.result_truncated || cerpResults.result_truncated)
  if (!truncated || !Number.isFinite(total) || !Number.isFinite(displayed) || total <= displayed) {
    return ''
  }
  return tMessage(message, 'home.cerp_results.truncated_summary', { total, displayed })
}

const formatCerpResultValue = (value, message = null) => {
  if (value === null || value === undefined || value === '') {
    return message
      ? tMessage(message, 'home.cerp_results.empty_value')
      : t('home.cerp_results.empty_value')
  }
  return String(value)
}

const formatCerpResultPrice = (value, message = null) =>
  formatCurrency(value) || formatCerpResultValue(value, message)

const formatCerpResultStock = (value, message = null) => formatCerpResultValue(value, message)

const formatCerpBusinessFields = (item = {}, message = null) => {
  const fields = item.businessFields && typeof item.businessFields === 'object' ? item.businessFields : {}
  const names = Array.isArray(item.fieldNames) && item.fieldNames.length ? item.fieldNames : Object.keys(fields)
  const separator = message
    ? tMessage(message, 'home.cerp_results.field_separator')
    : t('home.cerp_results.field_separator')
  return names
    .map((field) => {
      const value = fields[field]
      if (value === null || value === undefined || value === '') return ''
      const labelKey = `home.cerp_results.business_fields.${field}`
      const label = message ? tMessage(message, labelKey) : t(labelKey)
      return `${label && label !== labelKey ? label : field}: ${formatCerpResultValue(value, message)}`
    })
    .filter(Boolean)
    .join(separator && separator !== 'home.cerp_results.field_separator' ? separator : ', ')
}

const isCerpAssistantMessage = (messageId) => {
  if (!messageId) {
    return false
  }
  if (latestCerpMessageId.value === messageId) {
    return true
  }
  const message = chatMessages.value.find((msg) => msg.id === messageId)
  return messageHasCerpData(message) || messageHasCerpResults(message)
}

const isLatestAssistantMessage = (messageId) =>
  !!messageId && latestAssistantMessageId.value === messageId

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7a879c" stroke-width="2"/><path d="M12.5 12.5 16 16" stroke="#7a879c" stroke-width="2" stroke-linecap="round"/></svg>',
  plus:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 3v10M3 8h10" stroke="#263847" stroke-width="2" stroke-linecap="round"/></svg>',
  chevron:
    '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m4 6 3 3 3-3" stroke="#263847" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  arrow:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4 9h10M10 5l4 4-4 4" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  more:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="3" r="1.25" fill="#98a3b9"/><circle cx="8" cy="8" r="1.25" fill="#98a3b9"/><circle cx="8" cy="13" r="1.25" fill="#98a3b9"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#263847" stroke-width="2" stroke-linecap="round"/></svg>',
  link:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8.5 5h2a3 3 0 0 1 0 6h-2M7.5 11h-2a3 3 0 0 1 0-6h2" stroke="#263847" stroke-width="1.5" stroke-linecap="round"/><path d="M6 8h4" stroke="#263847" stroke-width="1.5" stroke-linecap="round"/></svg>',
}

const CONVERSATION_PREVIEW_LIMIT = 10

const createMessageId = (prefix = 'msg') =>
  `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

const initialViewportWidth = () =>
  typeof window !== 'undefined' ? window.innerWidth : 1440

const recentDialogs = computed(() => sortedDialogs.value.slice(0, 8))
const isSearchResultsMode = computed(() => Boolean(lastSearchQuery.value))
const searchPanelItems = computed(() =>
  isSearchResultsMode.value ? searchResults.value : recentDialogs.value
)
const searchPanelSubtitle = computed(() =>
  isSearchResultsMode.value ? t('home.search.results') : t('home.search.recent_conversations')
)
const searchPanelEmptyText = computed(() => {
  if (isSearchLoading.value) {
    return t('home.search.loading')
  }
  if (searchError.value) {
    return searchError.value || t('home.search.error')
  }
  return isSearchResultsMode.value ? t('home.search.empty_results') : t('home.search.empty')
})

const isTablet = computed(() => stageWidth.value <= 900)
const isIpad = computed(() => stageWidth.value > 900 && stageWidth.value <= 1366)
const canvasClass = computed(() => ({
  'is-ipad': isIpad.value,
  'is-tablet': isTablet.value,
}))
const isSearchModal = computed(() => isTablet.value)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet,
    isSidebarCollapsed,
  })
const dockedSearchPosition = computed(() => ({
  top: `${dockedPanelCoords.value.top}px`,
  left: `${dockedPanelCoords.value.left}px`,
}))
const sharePreviewBody = computed(
  () => shareMessageOverride.value || assistantAnswer.value || submittedTask.value || defaultUserPrompt
)
const sharePreviewSnippet = computed(() => {
  const text = sharePreviewBody.value
  return text.length > 60 ? `${text.slice(0, 60)}...` : text
})

const escapeHtml = (value) =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

const renderInlineMarkdown = (value) =>
  escapeHtml(value).replace(
    /\*\*([^*\n][\s\S]*?[^*\n]|\S)\*\*/g,
    '<strong class="chat-message__strong">$1</strong>'
  )

const flushMarkdownParagraph = (parts, paragraphLines) => {
  if (!paragraphLines.length) {
    return
  }
  const html = paragraphLines.map((line) => renderInlineMarkdown(line)).join('<br />')
  parts.push(`<p class="chat-message__paragraph">${html}</p>`)
  paragraphLines.length = 0
}

const flushMarkdownList = (parts, listItems) => {
  if (!listItems.length) {
    return
  }
  const html = listItems
    .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
    .join('')
  parts.push(`<ul class="chat-message__markdown-list">${html}</ul>`)
  listItems.length = 0
}

const flushMarkdownNumberedList = (parts, listItems) => {
  if (!listItems.length) {
    return
  }
  const html = listItems
    .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
    .join('')
  parts.push(`<ol class="chat-message__numbered-list">${html}</ol>`)
  listItems.length = 0
}

const flushMarkdownBlockquote = (parts, quoteLines) => {
  if (!quoteLines.length) {
    return
  }
  const html = quoteLines.map((line) => renderInlineMarkdown(line)).join('<br />')
  parts.push(`<blockquote class="chat-message__blockquote">${html}</blockquote>`)
  quoteLines.length = 0
}

const parseMarkdownTableRow = (line) => {
  const trimmed = String(line || '').trim()
  if (!trimmed.includes('|')) {
    return null
  }
  const normalized = trimmed.replace(/^\|/, '').replace(/\|$/, '')
  const cells = normalized.split('|').map((cell) => cell.trim())
  return cells.length >= 2 ? cells : null
}

const isMarkdownTableSeparator = (line) => {
  const cells = parseMarkdownTableRow(line)
  return Boolean(cells?.length) && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

const flushMarkdownTable = (parts, tableLines) => {
  if (!tableLines.length) {
    return
  }
  if (tableLines.length < 2 || !isMarkdownTableSeparator(tableLines[1])) {
    tableLines.forEach((line) => {
      parts.push(`<p class="chat-message__paragraph">${renderInlineMarkdown(line)}</p>`)
    })
    tableLines.length = 0
    return
  }
  const headerCells = parseMarkdownTableRow(tableLines[0]) || []
  const bodyRows = tableLines
    .slice(2)
    .map((line) => parseMarkdownTableRow(line))
    .filter(Boolean)
  const headerHtml = headerCells
    .map((cell) => `<th scope="col">${renderInlineMarkdown(cell)}</th>`)
    .join('')
  const bodyHtml = bodyRows
    .map(
      (row) =>
        `<tr>${row
          .map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`)
          .join('')}</tr>`
    )
    .join('')
  parts.push(
    `<div class="chat-message__table-wrap"><table class="chat-message__table"><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`
  )
  tableLines.length = 0
}

const flushMarkdownBlocks = (parts, paragraphLines, listItems, numberedItems, quoteLines, tableLines) => {
  flushMarkdownParagraph(parts, paragraphLines)
  flushMarkdownList(parts, listItems)
  flushMarkdownNumberedList(parts, numberedItems)
  flushMarkdownBlockquote(parts, quoteLines)
  flushMarkdownTable(parts, tableLines)
}

const formatAssistantAnswer = (text) => {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').split('\n')
  const parts = []
  const paragraphLines = []
  const listItems = []
  const numberedItems = []
  const quoteLines = []
  const tableLines = []

  lines.forEach((line) => {
    const trimmed = line.trim()

    if (!trimmed) {
      flushMarkdownBlocks(parts, paragraphLines, listItems, numberedItems, quoteLines, tableLines)
      return
    }

    const tableRow = parseMarkdownTableRow(trimmed)
    if (tableRow) {
      flushMarkdownParagraph(parts, paragraphLines)
      flushMarkdownList(parts, listItems)
      flushMarkdownNumberedList(parts, numberedItems)
      flushMarkdownBlockquote(parts, quoteLines)
      tableLines.push(trimmed)
      return
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+?)(?:\s+#+)?$/)
    if (headingMatch) {
      flushMarkdownBlocks(parts, paragraphLines, listItems, numberedItems, quoteLines, tableLines)
      const level = headingMatch[1].length
      parts.push(
        `<h3 class="chat-message__heading chat-message__heading--${level}">${renderInlineMarkdown(
          headingMatch[2]
        )}</h3>`
      )
      return
    }

    const listMatch = trimmed.match(/^(?:[-*•])\s+(.+)$/)
    if (listMatch) {
      flushMarkdownParagraph(parts, paragraphLines)
      flushMarkdownNumberedList(parts, numberedItems)
      flushMarkdownBlockquote(parts, quoteLines)
      flushMarkdownTable(parts, tableLines)
      listItems.push(listMatch[1])
      return
    }

    const numberedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/)
    if (numberedMatch) {
      flushMarkdownParagraph(parts, paragraphLines)
      flushMarkdownList(parts, listItems)
      flushMarkdownBlockquote(parts, quoteLines)
      flushMarkdownTable(parts, tableLines)
      numberedItems.push(numberedMatch[1])
      return
    }

    const quoteMatch = trimmed.match(/^>\s?(.+)$/)
    if (quoteMatch) {
      flushMarkdownParagraph(parts, paragraphLines)
      flushMarkdownList(parts, listItems)
      flushMarkdownNumberedList(parts, numberedItems)
      flushMarkdownTable(parts, tableLines)
      quoteLines.push(quoteMatch[1])
      return
    }

    flushMarkdownList(parts, listItems)
    flushMarkdownNumberedList(parts, numberedItems)
    flushMarkdownBlockquote(parts, quoteLines)
    flushMarkdownTable(parts, tableLines)
    paragraphLines.push(line)
  })

  flushMarkdownBlocks(parts, paragraphLines, listItems, numberedItems, quoteLines, tableLines)
  return parts.join('')
}

const CERP_HISTORY_NOTICE = t('home.cerp.notice_history')
const CERP_DIRECT_NOTICE = t('home.cerp.notice_direct')

const formatCerpSummaryFields = (message) => {
  const product = getProductCardForMessage(message)
  if (!product?.fields?.length) {
    return ''
  }
  return product.fields
    .map((field) => {
      const label = escapeHtml(field.label)
      const value = escapeHtml(String(field.value || '-'))
      return `<p><strong>${label}</strong>: ${value}</p>`
    })
    .join('')
}

const renderMessageContent = (message) => {
  if (message && isCerpAssistantMessage(message.id)) {
    const content = String(message.content || '').trim()
    if (content) {
      const contentHtml = formatAssistantAnswer(content)
      const fieldsHtml = formatCerpSummaryFields(message)
      return `${contentHtml}${fieldsHtml ? `<div class="cerp-summary-fields">${fieldsHtml}</div>` : ''}`
    }
    const summary = message.summary || ''
    const noticeBase = isHistoryPreview.value ? CERP_HISTORY_NOTICE : CERP_DIRECT_NOTICE
    const notice = summary.trim()
      ? `${noticeBase}\n\n${summary.trim()}`
      : noticeBase
    const noticeHtml = formatAssistantAnswer(notice)
    const fieldsHtml = formatCerpSummaryFields(message)
    return `${noticeHtml}${fieldsHtml ? `<div class="cerp-summary-fields">${fieldsHtml}</div>` : ''}`
  }
  return formatAssistantAnswer((message && message.content) || '')
}

const scrollChatToBottom = () => {
  if (!chatThreadRef.value) return
  chatThreadRef.value.scrollTop = chatThreadRef.value.scrollHeight
}

const assistantAnswerHtml = computed(() =>
  formatAssistantAnswer(assistantAnswer.value || defaultAssistantText)
)
const currentAnswerText = computed(
  () => assistantAnswer.value || defaultAssistantText
)

const toggleMenu = (section, id, event) => {
  event?.stopPropagation()
  const key = `${section}-${id}`
  activeMenu.value = activeMenu.value === key ? null : key
}

const isMenuOpen = (section, id) => activeMenu.value === `${section}-${id}`

const openModal = (type) => {
  activeModal.value = type
  activeMenu.value = null
}

const ensureNavAccess = (item) => {
  if (!item) return true
  if (item.id === 'permission' && !canViewPermissionMembers.value) {
    openModal('permissionDenied')
    return false
  }
  return true
}

const closeModal = () => {
  if (activeModal.value === 'rename') {
    renameTarget.value = null
    renameError.value = ''
    isRenaming.value = false
  }
  if (activeModal.value === 'permission') {
    permissionTarget.value = null
    permissionInvitations.value = []
    clearPermissionLookupState({ clearInput: true })
    permissionError.value = ''
    isPermissionBusy.value = false
  }
  if (activeModal.value === 'deleteProject' || activeModal.value === 'deleteConversation') {
    deleteTarget.value = null
    deleteError.value = ''
    isDeleting.value = false
  }
  if (activeModal.value === 'selectFolder') {
    selectFolderTarget.value = null
    folderPickerQuery.value = ''
    folderPickerSelectedId.value = ''
    folderPickerItems.value = []
    folderPickerError.value = ''
    isFolderPickerLoading.value = false
    isFolderPickerSaving.value = false
  }
  activeModal.value = null
}

const openActiveConversationRenameModal = () => {
  const targetId = activeConversationId.value
  if (!targetId) return

  const existingRecord = dialogHistory.value.find((record) => record.id === targetId)
  renameTarget.value =
    existingRecord || {
      id: targetId,
      title: normalizeWhitespace(conversationTitle.value || DEFAULT_CONVERSATION_TITLE),
      hasCustomTitle: true,
    }
  renameValue.value =
    normalizeWhitespace(
      existingRecord?.title || conversationTitle.value || DEFAULT_CONVERSATION_TITLE
    ) || DEFAULT_CONVERSATION_TITLE
  renameError.value = ''
  openModal('rename')
}

const modalContent = computed(() => {
  if (!activeModal.value) return null
  const map = {
    deleteProject: {
      title: t('home.modals.delete_project.title'),
      body: t('home.modals.delete_project.body'),
      confirmLabel: t('home.modals.delete_project.confirm'),
      variant: 'danger',
    },
    deleteConversation: {
      title: t('home.modals.delete_conversation.title'),
      body: t('home.modals.delete_conversation.body'),
      confirmLabel: t('home.modals.delete_conversation.confirm'),
      variant: 'danger',
    },
    rename: {
      title: t('home.modals.rename.title'),
      body: '',
      confirmLabel: t('home.modals.rename.confirm'),
      variant: 'primary',
      hasInput: true,
    },
    permissionDenied: {
      title: t('home.modals.permission_denied.title'),
      body: t('home.modals.permission_denied.body'),
      confirmLabel: t('home.modals.permission_denied.confirm'),
      variant: 'primary',
      showCancel: false,
    },
  }
  const config = map[activeModal.value]
  if (!config) return null
  return {
    showCancel: config.showCancel !== false,
    ...config,
  }
})

const handleMenuAction = (option, context) => {
  if (!option) return
  if (option.modal === 'permission') {
    openPermissionModal(context || {})
    return
  }
  if (option.modal === 'selectFolder') {
    openSelectFolderModal(context || {})
    return
  }
  if (option.modal === 'rename') {
    renameTarget.value = context || null
    const seed = normalizeWhitespace(
      context?.title || context?.summary || conversationTitle.value
    ) || DEFAULT_CONVERSATION_TITLE
    renameValue.value = seed
    renameError.value = ''
    openModal('rename')
    return
  }
  if (typeof option.action === 'function') {
    option.action(context)
  }
  if (option.modal === 'deleteProject' || option.modal === 'deleteConversation') {
    deleteTarget.value = context || null
    deleteError.value = ''
  }
  if (option.modal) {
    openModal(option.modal)
  } else {
    activeMenu.value = null
  }
}

const applyLocalRename = (conversationId, nextLabel) => {
  dialogHistory.value = dialogHistory.value.map((record) => {
    if (record.id !== conversationId) return record
    return {
      ...record,
      title: nextLabel,
      hasCustomTitle: true,
    }
  })
}

const applyLocalVisibility = (conversationId, nextVisibility) => {
  if (!conversationId) return
  const normalized = normalizeVisibility(nextVisibility)
  dialogHistory.value = dialogHistory.value.map((record) => {
    if (record.id !== conversationId) {
      return record
    }
    return {
      ...record,
      visibility: normalized,
    }
  })
}

const applyLocalProjectAssignment = (conversationId, projectId, projectLabel) => {
  dialogHistory.value = dialogHistory.value.map((record) => {
    if (record.id !== conversationId) return record
    const normalizedProjectId = normalizeWhitespace(projectId || '')
    const resolvedLabel = normalizeWhitespace(projectLabel || '')
    return {
      ...record,
      projectId: normalizedProjectId || null,
      projectLabel: resolvedLabel || '',
      projectDisplayLabel: resolvedLabel || INBOX_LABEL,
    }
  })
}

const submitRename = async () => {
  const targetId = renameTarget.value?.id
  const nextLabel = normalizeWhitespace(renameValue.value)
  if (!targetId) {
    renameError.value = t('home.errors.rename_missing')
    return
  }
  if (!nextLabel) {
    renameError.value = t('home.errors.rename_project_required')
    return
  }
  isRenaming.value = true
  try {
    await renameConversation(targetId, { label: nextLabel })
    applyLocalRename(targetId, nextLabel)
    if (activeConversationId.value === targetId) {
      conversationTitle.value = nextLabel
    }
    renameError.value = ''
    closeModal()
  } catch (error) {
    renameError.value = error?.message || t('home.errors.rename_failed')
  } finally {
    isRenaming.value = false
  }
}

const addPermissionInvitation = async () => {
  if (!permissionTarget.value?.id || isPermissionBusy.value || permissionVisibility.value !== 'private') {
    return
  }
  const candidate = selectedPermissionCandidate.value
  const selectedIdentifier = String(candidate?.username || '').trim()
  if (!selectedIdentifier || !canSubmitPermissionInvite.value) {
    permissionError.value = t('home.permission.select_candidate')
    return
  }

  permissionError.value = ''
  isPermissionBusy.value = true
  try {
    await createConversationInvitation(permissionTarget.value.id, selectedIdentifier)
    clearPermissionLookupState({ clearInput: true })
    await loadPermissionInvitations()
  } catch (error) {
    permissionError.value = error?.message || t('home.permission.invite_failed')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isPermissionBusy.value = false
  }
}

const revokePermissionInvitation = async (invitation) => {
  if (!permissionTarget.value?.id || !invitation?.id || isPermissionBusy.value) return
  permissionError.value = ''
  isPermissionBusy.value = true
  try {
    await deleteConversationInvitation(permissionTarget.value.id, invitation.id)
    await loadPermissionInvitations()
  } catch (error) {
    permissionError.value = error?.message || t('home.permission.remove_failed')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isPermissionBusy.value = false
  }
}

const confirmPermissionModal = async () => {
  if (!permissionTarget.value?.id || isPermissionBusy.value) return
  const nextVisibility = normalizeVisibility(permissionVisibility.value)
  const targetId = permissionTarget.value.id
  permissionError.value = ''
  isPermissionBusy.value = true
  try {
    await updateConversationVisibility(targetId, { visibility: nextVisibility })
    applyLocalVisibility(targetId, nextVisibility)
    if (activeConversationId.value === targetId) {
      activeConversationVisibility.value = nextVisibility
    }
    closeModal()
  } catch (error) {
    permissionError.value = error?.message || t('home.errors.visibility_failed')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isPermissionBusy.value = false
  }
}

const resolveSelectedQuoteOutput = () => {
  const selected = quoteOutputDefinitions.value.find((item) => item.value === selectedOutputValue.value) || null
  return selected?.value === OUTPUT_TYPE_QUOTE_VALUE ? selected : null
}

const persistPendingQuoteCompose = (payload) => {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(
      QUOTE_PENDING_COMPOSE_KEY,
      JSON.stringify({
        message: payload?.message || '',
        display_message: payload?.display_message || payload?.message || '',
        tab: payload?.tab || 'report',
        project: payload?.project || null,
        conversation_id: payload?.conversation_id || null,
        lang: normalizeQuoteLanguage(payload?.lang, languagePreference.value),
        surface_origin: payload?.surface_origin || 'chat-ui',
        attachment: payload?.attachment || null,
        url_inputs: Array.isArray(payload?.url_inputs) ? payload.url_inputs.filter(Boolean) : [],
        followup_action: payload?.followup_action || null,
        followup_action_source: payload?.followup_action_source || null,
        quote_continuity: hasQuoteContinuity(payload?.quote_continuity)
          ? extractQuoteContinuityPayload(payload?.quote_continuity, {
              conversationId: payload?.conversation_id || null,
              project: payload?.project || null,
              lang: payload?.lang || languagePreference.value,
              surfaceOrigin: payload?.surface_origin || 'chat-ui',
            })
          : null,
        output_type: OUTPUT_TYPE_QUOTE_VALUE,
        created_at: new Date().toISOString(),
      })
    )
  } catch (error) {
    console.warn('Unable to persist pending quote compose payload', error)
  }
}

const submitSelectFolder = async () => {
  const conversationId = String(
    selectFolderTarget.value?.id ||
      selectFolderTarget.value?.conversationId ||
      selectFolderTarget.value?.conversation_id ||
      ''
  ).trim()
  const projectId = normalizeWhitespace(folderPickerSelectedId.value)
  if (!conversationId) {
    folderPickerError.value = t('home.errors.delete_missing')
    return
  }
  if (!projectId) {
    folderPickerError.value = t('home.modals.select_folder.required')
    return
  }
  isFolderPickerSaving.value = true
  folderPickerError.value = ''
  try {
    const response = await updateConversationProject(conversationId, { projectId })
    const projectLabel =
      folderPickerItems.value.find((item) => String(item.id) === String(projectId))?.name ||
      response?.item?.project_label ||
      ''
    applyLocalProjectAssignment(conversationId, projectId, projectLabel)
    if (activeConversationId.value === conversationId) {
      activeProjectId.value = projectId
    }
    closeModal()
    refreshHistorySilently()
  } catch (error) {
    folderPickerError.value = error?.message || t('home.modals.select_folder.submit_failed')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isFolderPickerSaving.value = false
  }
}

const submitArchive = async () => {
  const target = deleteTarget.value
  const targetId = target?.id
  if (!targetId) {
    deleteError.value = t('home.errors.delete_missing')
    return
  }
  deleteError.value = ''
  isDeleting.value = true
  try {
    await archiveConversation(targetId)
    removeConversationFromHistory(target)
    refreshHistorySilently()
    closeModal()
  } catch (error) {
    deleteError.value = error?.message || t('home.errors.delete_failed')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    isDeleting.value = false
  }
}

const handleModalConfirm = async () => {
  if (activeModal.value === 'rename') {
    await submitRename()
    return
  }
  if (activeModal.value === 'permission') {
    await confirmPermissionModal()
    return
  }
  if (activeModal.value === 'selectFolder') {
    await submitSelectFolder()
    return
  }
  if (activeModal.value === 'deleteProject' || activeModal.value === 'deleteConversation') {
    await submitArchive()
    return
  }
  closeModal()
}

const avatarColor = (initial) => avatarPalette[initial] || '#263847'

const selectOutputType = (type) => {
  const selected = quoteOutputDefinitions.value.find((item) => item.label === type) || null
  selectedOutputValue.value = selected?.value || ''
}

const triggerSnackbar = () => {
  if (snackbarTimer.value) {
    clearTimeout(snackbarTimer.value)
  }
  showSnackbar.value = true
  snackbarTimer.value = setTimeout(() => {
    showSnackbar.value = false
    snackbarTimer.value = null
  }, 2600)
}

const closeSnackbar = () => {
  if (snackbarTimer.value) {
    clearTimeout(snackbarTimer.value)
    snackbarTimer.value = null
  }
  showSnackbar.value = false
}

const resolveElement = (targetRef) => {
  const target = targetRef?.value
  if (!target) return null
  if (typeof target.getElement === 'function') {
    return target.getElement()
  }
  if (target.$el) return target.$el
  return target
}

const resolveShareText = (message = null) =>
  message && messageShouldUseQuoteRenderer(message)
    ? buildQuoteShareText(message)
    : currentAnswerText.value

const handleCopyClick = async (message = null) => {
  const text = resolveShareText(message)
  try {
    await writeClipboard(text)
    triggerSnackbar()
  } catch (error) {
    console.warn('Clipboard copy failed', error)
  }
}

const handleShareClick = async (message = null) => {
  const text = resolveShareText(message)
  if (navigator.share) {
    try {
      await navigator.share({
        title: conversationTitle.value || t('home.share.default_title'),
        text,
      })
      return
    } catch (error) {
      if (error?.name !== 'AbortError') {
        console.warn('Web Share failed', error)
      }
    }
  }
  shareMessageOverride.value = text
  showShareDialog.value = true
  shareEmail.value = ''
  nextTick(() => {
    shareInputRef.value?.focus()
  })
}

const closeShareDialog = () => {
  showShareDialog.value = false
  shareMessageOverride.value = ''
}

const handleShareSubmit = () => {
  if (!shareEmail.value.trim()) return
  closeShareDialog()
}

const updateDockedSearchPosition = () => {
  if (isSearchModal.value || !showSearchPanel.value) return
  const barRect = resolveElement(topBarRef)?.getBoundingClientRect()
  if (!barRect) return
  const adviceRect = resolveElement(topAdviceRef)?.getBoundingClientRect()
  const top = adviceRect && isChatActive.value ? adviceRect.bottom : barRect.bottom
  dockedPanelCoords.value = {
    top,
    left: barRect.left,
  }
}

watch([isChatActive, showSearchPanel], ([, panelVisible]) => {
  if (panelVisible && !isSearchModal.value) {
    nextTick(updateDockedSearchPosition)
  }
})

watch(isSearchModal, (isModal) => {
  if (!isModal && showSearchPanel.value) {
    nextTick(updateDockedSearchPosition)
  }
})

watch(permissionEmail, (value) => {
  const normalizedValue = String(value || '').trim().toLowerCase()
  if (
    selectedPermissionCandidate.value &&
    String(selectedPermissionCandidate.value.username || '').trim().toLowerCase() !== normalizedValue
  ) {
    selectedPermissionCandidate.value = null
  }

  if (permissionLookupTimer.value) {
    clearTimeout(permissionLookupTimer.value)
    permissionLookupTimer.value = null
  }

  if (
    activeModal.value !== 'permission' ||
    permissionVisibility.value !== 'private' ||
    normalizedValue.length < INVITE_LOOKUP_MIN_LENGTH
  ) {
    permissionSuggestions.value = []
    permissionLookupOpen.value = false
    permissionLookupBusy.value = false
    return
  }

  permissionLookupTimer.value = setTimeout(() => {
    loadPermissionCandidates(value)
  }, 240)
})

watch(permissionVisibility, (value) => {
  if (value !== 'private') {
    clearPermissionLookupState({ clearInput: true })
  }
})

watch(
  isAuthenticated,
  (authed) => {
    if (authed) {
      loadConversationHistory()
    } else {
      dialogHistory.value = []
    }
  },
  { immediate: true }
)

const toggleSidebar = () => {
  if (!isCompactSidebar.value) return
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

const handleLoginSuccess = () => {
  resetConversationState()
  isChatActive.value = false
  loadConversationHistory()
  const redirectTarget = normalizeWhitespace(router.currentRoute.value.query?.redirect || '')
  if (redirectTarget.startsWith('/')) {
    router.push(redirectTarget).catch(() => {})
  }
}

const buildNavRoute = (item) => {
  if (!item?.route) return null
  return item.routeQuery
    ? { name: item.route, query: { ...item.routeQuery } }
    : { name: item.route }
}

const setActiveNav = (item) => {
  if (!ensureNavAccess(item)) {
    return
  }
  if (item.id === 'permission') {
    handlePermissionNavClick()
    return
  }
  closePermissionMenu()
  activeNavId.value = item.id
  const targetRoute = buildNavRoute(item)
  if (targetRoute) {
    router.push(targetRoute)
  }
}

const selectProjectContext = (source) => {
  if (!source || typeof source !== 'object') return
  const nextId = normalizeWhitespace(
    source.projectId || source.project_id || source.project?.id || ''
  ) || null
  activeProjectId.value = nextId
  const label =
    source.projectLabel ||
    source.project_label ||
    source.project?.label ||
    source.title ||
    source.subtitle ||
    source.summary ||
    source.owner ||
    source.name
  if (label) {
    conversationTitle.value = label
  }
}

const startConversation = async (source = {}) => {
  selectProjectContext(source)
  const fallbackLabel =
    source?.projectLabel || source?.project_label || source?.title || conversationTitle.value
  const lastUserQuestion =
    source?.lastUserMessage || source?.last_user_message || source?.subtitle || ''
  const historyConversationId =
    source?.conversationId ||
    source?.conversation_id ||
    source?.id ||
    getConversationIdForProject(activeProjectId.value)
  if (historyConversationId) {
    await loadConversationPreview(historyConversationId, fallbackLabel)
    if (lastUserQuestion) {
      submittedTask.value = lastUserQuestion
    }
    isChatActive.value = true
    return
  }
  const seed =
    source?.subtitle || source?.summary || source?.title || defaultUserPrompt
  submitPrompt(seed)
}

const openProjectFolderFromHistory = async (source = {}) => {
  const projectId = normalizeWhitespace(source?.projectId || source?.project_id || '')
  const conversationId = normalizeWhitespace(
    source?.conversationId || source?.conversation_id || source?.id || ''
  )
  if (!projectId) {
    await router.push({ name: 'projects', query: { scope: 'inbox' } })
    return
  }
  const projectLabel = normalizeWhitespace(
    source?.projectDisplayLabel || source?.projectLabel || source?.project_label || ''
  )
  const query = { project_id: projectId }
  if (projectLabel) {
    query.project_label = projectLabel
  }
  if (conversationId) {
    query.return_to = 'chat'
    query.conversation_id = conversationId
  }
  await router.push({ name: 'projects', query })
}

const handleTaskSubmit = () => {
  submitPrompt(messageInput.value)
}

const handleComposerSubmit = () => {
  submitPrompt(composerValue.value)
}

const openSearchPanel = () => {
  showSearchPanel.value = true
  if (isSearchModal.value) {
    nextTick(() => {
      searchPanelInput.value?.focus()
    })
  } else {
    nextTick(updateDockedSearchPosition)
  }
}

const resetSearchPanelState = ({ clearQuery = false } = {}) => {
  searchRequestToken += 1
  searchResults.value = []
  lastSearchQuery.value = ''
  isSearchLoading.value = false
  searchError.value = ''
  if (clearQuery) {
    searchQuery.value = ''
  }
}

const closeSearchPanel = () => {
  showSearchPanel.value = false
  resetSearchPanelState({ clearQuery: isSearchModal.value })
}

const handleSearchSelect = async (chat) => {
  await startConversation(chat)
  closeSearchPanel()
}

const handleNewConversation = () => {
  closeSearchPanel()
  resetSearchPanelState({ clearQuery: true })
  resetConversationState()
  submittedTask.value = ''
  isChatActive.value = false
  router.push({ name: 'home' })
}

let searchRequestToken = 0

const runConversationSearch = async () => {
  const query = normalizeWhitespace(searchQuery.value)
  if (!query) {
    resetSearchPanelState()
    return
  }

  const token = searchRequestToken + 1
  searchRequestToken = token
  lastSearchQuery.value = query
  isSearchLoading.value = true
  searchError.value = ''
  searchResults.value = []

  try {
    const response = await fetchProjectConversationSearch({
      q: query,
      scope: 'all',
      pageSize: 20,
    })
    if (token !== searchRequestToken) return
    const items = Array.isArray(response?.items) ? response.items : []
    searchResults.value = items
      .map((item) => normalizeSearchResultRecord(item))
      .filter((item) => item && item.id)
  } catch (error) {
    if (token !== searchRequestToken) return
    searchResults.value = []
    searchError.value = error?.message || t('home.search.error')
    if (shouldHandleSessionExpired(error)) {
      handleSessionExpired()
    }
  } finally {
    if (token === searchRequestToken) {
      isSearchLoading.value = false
    }
  }
}

const handleSearchInputChange = () => {
  const query = normalizeWhitespace(searchQuery.value)
  if (!query || (lastSearchQuery.value && query !== lastSearchQuery.value)) {
    resetSearchPanelState()
  }
}

const handleSearchSubmit = async () => {
  await runConversationSearch()
}

const queryStringValue = (value) => {
  if (Array.isArray(value)) return String(value[0] || '').trim()
  return String(value || '').trim()
}

const routeConversationKey = ref('')
const consumeRouteConversationQuery = async () => {
  if (router.currentRoute.value.name !== 'home') return
  if (!isAuthenticated.value) return
  const query = router.currentRoute.value.query || {}
  const conversationId = queryStringValue(query.conversation_id)
  const composeProjectId = queryStringValue(query.compose_project_id)
  const composeProjectLabel = queryStringValue(query.compose_project_label)

  if (conversationId) {
    if (routeConversationKey.value === conversationId) return
    routeConversationKey.value = conversationId
    try {
      const source = {
        id: conversationId,
        conversationId,
        projectId: queryStringValue(query.project_id) || null,
        projectLabel: queryStringValue(query.project_label) || '',
      }
      await startConversation(source)
    } finally {
      const nextQuery = { ...router.currentRoute.value.query }
      delete nextQuery.conversation_id
      delete nextQuery.project_id
      delete nextQuery.project_label
      delete nextQuery.compose_project_id
      delete nextQuery.compose_project_label
      router.replace({ name: 'home', query: nextQuery }).catch(() => {})
      routeConversationKey.value = ''
    }
    return
  }

  const composeKey = composeProjectId ? `${composeProjectId}|${composeProjectLabel}` : ''
  if (composeKey && routeConversationKey.value === composeKey) return
  if (composeProjectId) {
    routeConversationKey.value = composeKey
    try {
      resetConversationState()
      activeProjectId.value = composeProjectId
      setConversationIdForProject(composeProjectId, null)
      const normalizedComposeLabel = normalizeWhitespace(composeProjectLabel)
      if (normalizedComposeLabel) {
        conversationTitle.value = normalizedComposeLabel
        renameValue.value = normalizedComposeLabel
      }
      isChatActive.value = false
    } finally {
      const nextQuery = { ...router.currentRoute.value.query }
      delete nextQuery.compose_project_id
      delete nextQuery.compose_project_label
      router.replace({ name: 'home', query: nextQuery }).catch(() => {})
      routeConversationKey.value = ''
    }
  }
}

const updateWidth = () => {
  stageWidth.value = initialViewportWidth()
  if (!isCompactSidebar.value) {
    isSidebarCollapsed.value = false
  }
  nextTick(updateDockedSearchPosition)
}

const closeMenuOnOutside = (event) => {
  if (!event.target.closest('[data-menu-root]')) {
    activeMenu.value = null
  }
  if (
    showSearchPanel.value &&
    !isSearchModal.value &&
    !event.target.closest('.search-field') &&
    !event.target.closest('.search-panel')
  ) {
    closeSearchPanel()
  }
  if (
    isCompactSidebar.value &&
    !isSidebarCollapsed.value &&
    !event.target.closest('.sidebar') &&
    !event.target.closest('.top-bar__menu')
  ) {
    isSidebarCollapsed.value = true
  }
}

watch(
  () => router.currentRoute.value.query,
  () => {
    consumeRouteConversationQuery()
  },
  { deep: true, immediate: true }
)

onMounted(() => {
  resetHomeQuoteDestinationPreference()
  updateWidth()
  window.addEventListener('resize', updateWidth)
  document.addEventListener('click', closeMenuOnOutside)
  consumeQuoteChatUiReturnPayload()
    .catch((error) => {
      console.warn('Unable to consume quote ChatUI return payload', error)
    })
    .finally(() => {
      consumeRouteConversationQuery()
    })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateWidth)
  document.removeEventListener('click', closeMenuOnOutside)
  if (snackbarTimer.value) {
    clearTimeout(snackbarTimer.value)
  }
  if (permissionLookupTimer.value) {
    clearTimeout(permissionLookupTimer.value)
  }
  clearComposerAttachments()
})
</script>

<template>
  <LoginLayout
    v-if="!isAuthenticated"
    @login-success="handleLoginSuccess"
  />

  <div
    v-else
    class="app-shell"
    :class="{ 'is-sidebar-collapsed': isSidebarCollapsed, 'is-chat-active': isChatActive }"
  >

    <AppSidebar
      :logo-src="logoMain"
      :nav-items="navItems"
      :icon-images="iconImages"
      :arrow-icon-src="iconArrowIndicator"
      :active-nav-id="activeNavId"
      :side-menu="sideMenu"
      :side-menu-open="sideMenuOpen"
      :aria-label="t('home.aria.main_nav')"
      @logo-click="handleNewConversation"
      @nav-click="setActiveNav"
    />

    <div class="main-stage" :class="{ 'is-chat-active': isChatActive }">

    <AppTopBar
      ref="topBarRef"
      :logo-src="logoMain"
      :is-compact-sidebar="isCompactSidebar"
      :is-sidebar-collapsed="isSidebarCollapsed"
      :hamburger-icon="glyphs.hamburger"
      :menu-aria-label="t('home.aria.toggle_menu')"
      :avatar-aria-label="t('home.aria.open_account_menu')"
      @toggle-sidebar="toggleSidebar"
      @logo-click="handleNewConversation"
    >
      <template #search>
        <label
          v-if="!isTablet"
          class="search-field"
        >
          <span class="search-field__icon" v-html="glyphs.search" aria-hidden="true" />
          <input
            type="search"
            :placeholder="t('home.placeholders.search')"
            v-model="searchQuery"
            @focus="openSearchPanel"
            @input="handleSearchInputChange"
            @keydown.enter.prevent="handleSearchSubmit"
            @keydown.esc="closeSearchPanel"
          />
        </label>
      <button
        v-else
        class="icon-button top-bar__search-button"
        type="button"
        :aria-label="t('home.aria.open_search')"
        @click="openSearchPanel"
      >
          <span v-html="glyphs.search" aria-hidden="true" />
        </button>
      </template>
      <template #command>
        <div class="command-home-panel">
          <section>
            <h3>{{ t('app.command.pinned') }}</h3>
            <button
              v-for="item in pinnedDialogs.slice(0, 4)"
              :key="`command-pinned-${item.id}`"
              type="button"
              class="command-home-panel__item"
              @click="startConversation(item)"
            >
              <span>{{ resolveHistoryInfoLabel(item) }}</span>
              <small>{{ formatDisplayTime(item.updatedAt || item.createdAt) }}</small>
            </button>
            <p v-if="!pinnedDialogs.length" class="command-home-panel__empty">{{ t('app.command.empty') }}</p>
          </section>
          <section>
            <h3>{{ t('app.command.recent') }}</h3>
            <button
              v-for="item in recentDialogs.slice(0, 5)"
              :key="`command-recent-${item.id}`"
              type="button"
              class="command-home-panel__item"
              @click="startConversation(item)"
            >
              <span>{{ resolveHistoryInfoLabel(item) }}</span>
              <small>{{ formatDisplayTime(item.updatedAt || item.createdAt) }}</small>
            </button>
            <p v-if="!recentDialogs.length" class="command-home-panel__empty">{{ t('app.command.empty') }}</p>
          </section>
        </div>
      </template>
    </AppTopBar>

    <input
      ref="uploadFileInput"
      type="file"
      class="composer-file-input"
      multiple
      :accept="uploadAccept"
      @change="handleComposerFilesSelected"
    />


          <TopAdviceBar v-if="isChatActive" ref="topAdviceRef">
      <header class="chat-header">
        <div class="chat-header__title">
          <h2>{{ chatHeaderTitle }}</h2>
        </div>
        <div class="chat-header__controls">
          <button
            class="chat-header__edit"
            type="button"
            :aria-label="t('home.aria.edit_input')"
            :disabled="!activeConversationId"
            @click="openActiveConversationRenameModal"
          >
            <img :src="topPenIcon" alt="" aria-hidden="true" />
          </button>
          <label v-if="showQuoteResultToggle" class="result-toggle">
            <span>{{ t('quote.actions.show_generated') }}</span>
            <input
              type="checkbox"
              v-model="showGeneratedResults"
              @change="handleHomeQuoteResultToggleChange"
            />
          </label>
        </div>
      </header>
    </TopAdviceBar>

      <div
        v-if="showSearchPanel && !isSearchModal"
        class="search-panel is-docked"
        :style="dockedSearchPosition"
      >
        <div class="search-panel__card">
          <button class="search-panel__new" type="button" @click="handleNewConversation">
            + {{ t('home.actions.new_conversation') }}
          </button>
          <p class="search-panel__subtitle">{{ searchPanelSubtitle }}</p>
          <div class="search-panel__list">
            <button
              v-for="chat in searchPanelItems"
              :key="`dock-${chat.id}`"
              type="button"
              class="search-panel__item"
              @click="handleSearchSelect(chat)"
            >
              <span>{{ resolveHistoryInfoLabel(chat) }}</span>
              <p v-if="isSearchResultsMode" class="search-panel__excerpt">
                {{ resolveSearchPanelItemExcerpt(chat) }}
              </p>
              <small>{{ formatDisplayTime(chat.updatedAt || chat.createdAt) }}</small>
            </button>
            <p v-if="!searchPanelItems.length" class="search-panel__empty">
              {{ searchPanelEmptyText }}</p>
          </div>
        </div>
      </div>

      <main class="stage-canvas" :class="[canvasClass, { 'is-chat-active': isChatActive }]">
        <template v-if="!isChatActive">
          <section class="hero-panel">
            <p class="hero-panel__eyebrow">{{ t('home.hero.eyebrow') }}</p>
            <h1>{{ t('home.hero.title') }}</h1>
            <p class="hero-panel__copy">
              {{ t('home.hero.copy') }}
            </p>
          </section>

          <section class="action-rail">
            <ChatComposer
              :class="['action-rail__composer']"
              v-model="messageInput"
              :placeholder="CHAT_COMPOSER_PLACEHOLDER"
              :output-types="outputTypes"
              :selected-output-type="selectedOutputType"
              :output-placeholder="chatOutputPlaceholder"
              :attachments="uploadAttachments"
              :upload-warning="uploadWarning"
              :show-attachments="true"
              :two-row-layout="uploadAttachments.length > 0"
              :send-icon-src="arrowButtonAsset"
              :input-rows="1"
              :upload-aria-label="t('home.aria.upload_file')"
              :send-aria-label="t('home.aria.send_message')"
              @submit="handleTaskSubmit"
              @select-output-type="selectOutputType"
              @upload-click="handleComposerUploadClick"
              @add-urls="handleComposerUrlsAdded"
              @remove-attachment="removeComposerAttachment"
            />
          </section>

          <section class="project-row">
            <header class="section-header">
              <div>
                <h2>{{ t('home.sections.inbox') }}</h2>
              </div>
            </header>
            <p v-if="historyError" class="section-error">{{ historyError }}</p>
            <div v-if="isHistoryLoading" class="section-empty">
              {{ t('home.loading.history') }}
            </div>
            <div v-else-if="!projectRowDialogs.length" class="section-empty">
              {{ t('home.empty.no_inbox') }}
            </div>
            <div v-else class="project-grid">
              <article
                v-for="project in projectRowDialogs"
                :key="project.id"
                class="project-card"
                :class="{ 'is-menu-open': isMenuOpen('card', project.id) }"
                @click="startConversation(project)"
              >
                <div class="project-card__body">
                  <p class="project-card__title">
                    {{ resolveHistoryInfoLabel(project) }}
                  </p>
                  <div class="project-card__meta">
                    <span>{{ formatDisplayTime(project.updatedAt || project.createdAt) }}</span>
                    <span
                      class="project-card__owner"
                      :style="{ background: avatarColor(project.owner) }"
                    >
                      {{ project.owner }}
                    </span>
                    <span
                      class="visibility-badge"
                      :class="resolveVisibilityClass(project.visibility)"
                    >
                      {{ formatVisibilityLabel(project.visibility) }}
                    </span>
                  </div>
                </div>
                <div class="menu-anchor" data-menu-root @click.stop>
                  <button
                    class="icon-button menu-toggle"
                    type="button"
                    :aria-label="t('home.aria.open_actions')"
                    @click.stop="toggleMenu('card', project.id, $event)"
                  >
                    <span v-html="glyphs.more" aria-hidden="true" />
                  </button>
                  <div
                    v-if="isMenuOpen('card', project.id)"
                    class="menu-popover"
                    role="menu"
                  >
                    <button
                      v-for="option in getMenuOptions('card', project)"
                      :key="option.label"
                      class="menu-popover__item"
                      :class="{ 'is-danger': option.danger }"
                      type="button"
                      @click="handleMenuAction(option, project)"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                </div>
              </article>
            </div>
          </section>

          <section class="list-section">
            <header class="section-header">
              <div>
                <h2>{{ t('home.sections.pinned') }}</h2>
              </div>
            </header>
            <div v-if="isHistoryLoading" class="section-empty">
              {{ t('home.loading.history') }}
            </div>
            <div v-else-if="!pinnedDialogs.length" class="section-empty">
              {{ t('home.empty.no_pinned') }}
            </div>
            <div v-else class="selected-list">
              <article
                v-for="item in pinnedDialogs"
                :key="item.id"
                class="selected-row"
                @click="startConversation(item)"
              >
                <div class="selected-row__info">
                  <p class="selected-row__title">
                    {{ resolveHistoryInfoLabel(item) }}
                  </p>
                </div>
                <div class="selected-row__meta">
                  <span
                    class="project-card__owner"
                    :style="{ background: avatarColor(item.owner) }"
                  >
                    {{ item.owner }}
                  </span>
                  <div class="selected-row__timeline">
                    <span class="selected-row__datetime">{{ formatDisplayTime(item.updatedAt || item.createdAt) }}</span>
                    <span class="selected-row__divider" aria-hidden="true"></span>
                    <button
                      type="button"
                      class="selected-row__location selected-row__location-button"
                      @click.stop="openProjectFolderFromHistory(item)"
                    >
                      <img :src="iconImages.folder" alt="" aria-hidden="true" />
                      {{ item.projectDisplayLabel || item.projectLabel || t('home.labels.unnamed_project') }}
                    </button>
                    <span
                      class="visibility-badge"
                      :class="resolveVisibilityClass(item.visibility)"
                    >
                      {{ formatVisibilityLabel(item.visibility) }}
                    </span>
                  </div>
                </div>
                <div class="menu-anchor" data-menu-root @click.stop>
                  <button
                    class="icon-button menu-toggle"
                    type="button"
                    :aria-label="t('home.aria.open_actions')"
                    @click.stop="toggleMenu('pinned', item.id, $event)"
                  >
                    <span v-html="glyphs.more" aria-hidden="true" />
                  </button>
                  <div
                    v-if="isMenuOpen('pinned', item.id)"
                    class="menu-popover"
                  >
                    <button
                      v-for="option in getMenuOptions('pinned', item)"
                      :key="option.label"
                      class="menu-popover__item"
                      :class="{ 'is-danger': option.danger }"
                      type="button"
                      @click="handleMenuAction(option, item)"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                </div>
              </article>
            </div>
          </section>

          <section class="list-section history-section">
            <header class="section-header">
              <div>
                <h2>{{ t('home.sections.history') }}</h2>
              </div>
            </header>
            <div v-if="isHistoryLoading" class="section-empty">
              {{ t('home.loading.history') }}
            </div>
            <div v-else-if="!historyDialogs.length" class="section-empty">
              {{ t('home.empty.no_history') }}
            </div>
            <div v-else class="history-table">
              <article
                v-for="chat in historyDialogs"
                :key="chat.id"
                class="history-row"
                @click="startConversation(chat)"
              >
                <div class="history-row__info">
                  <p class="history-row__title">
                    {{ resolveHistoryInfoLabel(chat) }}
                  </p>
                </div>
                <div class="history-row__meta">
                  <span class="history-row__status">{{ chat.status }}</span>
                  <span
                    class="visibility-badge"
                    :class="resolveVisibilityClass(chat.visibility)"
                  >
                    {{ formatVisibilityLabel(chat.visibility) }}
                  </span>
                  <div class="history-row__data">
                    <span class="history-row__datetime">{{ formatDisplayTime(chat.updatedAt || chat.createdAt) }}</span>
                    <span class="history-row__divider" aria-hidden="true"></span>
                    <button
                      type="button"
                      class="history-row__location history-row__location-button"
                      @click.stop="openProjectFolderFromHistory(chat)"
                    >
                      <img :src="iconImages.folder" alt="" aria-hidden="true" />
                      {{ chat.projectDisplayLabel || chat.projectLabel || t('home.labels.unnamed_project') }}
                    </button>
                  </div>
                </div>
                <div class="menu-anchor" data-menu-root @click.stop>
                  <button
                    class="icon-button menu-toggle"
                    type="button"
                    :aria-label="t('home.aria.open_actions')"
                    @click.stop="toggleMenu('dialog', chat.id, $event)"
                  >
                    <span v-html="glyphs.more" aria-hidden="true" />
                  </button>
                  <div
                    v-if="isMenuOpen('dialog', chat.id)"
                    class="menu-popover"
                  >
                    <button
                      v-for="option in getMenuOptions('dialog', chat)"
                      :key="option.label"
                      class="menu-popover__item"
                      :class="{ 'is-danger': option.danger }"
                      type="button"
                      @click="handleMenuAction(option, chat)"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                </div>
              </article>
            </div>
          </section>
        </template>

        <template v-else>
          <section class="chat-ui">
            <div
              class="chat-thread"
              ref="chatThreadRef"
            >
              <div
                v-if="isConversationLoading"
                class="chat-thread__loading"
              >
                <span class="chat-thread__spinner" aria-hidden="true"></span>
                <p>{{ t('home.loading.conversation') }}</p>
              </div>

              <template v-else-if="chatMessages.length">
                <article
                  v-for="(message, idx) in chatMessages"
                  :key="message.id || idx"
                  :class="['chat-message', message.role === 'assistant' ? 'is-assistant' : 'is-user']"
                >
                  <template v-if="message.role === 'assistant'">
                    <div class="chat-message__avatar" aria-hidden="true">
                      {{ t('home.labels.ai') }}
                    </div>

                    <div
                      v-if="messageShouldUseQuoteRenderer(message)"
                      class="chat-message__bubble is-quote-response"
                    >
                      <QuoteResponseRenderer
                        :quote-ui="getQuoteUiForMessage(message)"
                        :followup-summary="getQuoteFollowupSummaryForMessage(message)"
                        :followup-actions="getQuoteFollowupActionsForMessage(message)"
                        :copy-aria-label="t('home.aria.copy_response')"
                        :share-aria-label="t('home.aria.share_response')"
                        @copy="handleCopyClick(message)"
                        @share="handleShareClick(message)"
                        @action="handleQuoteFollowupActionFromChatUi(message, $event)"
                      >
                        <p
                          v-if="getQuoteUiForMessage(message)?.intro"
                          class="chat-message__quote-paragraph"
                        >
                          {{ getQuoteUiForMessage(message)?.intro }}
                        </p>
                        <ul
                          v-if="getQuoteUiForMessage(message)?.introBullets?.length"
                          class="chat-message__list chat-message__list--quote"
                        >
                          <li
                            v-for="(item, quoteIdx) in getQuoteUiForMessage(message)?.introBullets || []"
                            :key="`${message.id || idx}-quote-intro-${quoteIdx}`"
                          >
                            {{ item }}
                          </li>
                        </ul>

                        <article class="chat-result-card chat-result-card--quote">
                          <div class="chat-result-card__header">
                            <div class="chat-result-card__header-copy">
                              <p class="chat-result-card__title">
                                {{ getQuoteUiForMessage(message)?.title }}
                              </p>
                              <div class="chat-result-card__meta">
                                <span>{{ getQuoteUiForMessage(message)?.generatedAt }}</span>
                                <span
                                  class="chat-result-card__status"
                                  :class="`is-${getQuoteUiForMessage(message)?.statusVariant || 'success'}`"
                                >
                                  <span class="dot" />
                                  {{ getQuoteUiForMessage(message)?.status }}
                                </span>
                              </div>
                            </div>
                            <span
                              class="chat-result-card__check"
                              :class="`is-${getQuoteUiForMessage(message)?.statusVariant || 'success'}`"
                              aria-hidden="true"
                            >
                              ✓
                            </span>
                          </div>
                        </article>

                        <p
                          v-if="getQuoteUiForMessage(message)?.closing"
                          class="chat-message__quote-paragraph"
                        >
                          {{ getQuoteUiForMessage(message)?.closing }}
                        </p>
                        <ul
                          v-if="getQuoteUiForMessage(message)?.closingBullets?.length"
                          class="chat-message__list chat-message__list--quote is-secondary"
                        >
                          <li
                            v-for="(item, quoteIdx) in getQuoteUiForMessage(message)?.closingBullets || []"
                            :key="`${message.id || idx}-quote-closing-${quoteIdx}`"
                          >
                            {{ item }}
                          </li>
                        </ul>

                        <div class="chat-toolbar chat-toolbar--quote">
                          <button
                            type="button"
                            :aria-label="t('home.aria.copy_response')"
                            @click="handleCopyClick(message)"
                          >
                            <img :src="chatToolbarCopy" alt="" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            :aria-label="t('home.aria.share_response')"
                            @click="handleShareClick(message)"
                          >
                            <img :src="chatToolbarShare" alt="" aria-hidden="true" />
                          </button>
                        </div>
                      </QuoteResponseRenderer>
                      <div
                        v-if="message.content"
                        class="chat-message__answer chat-message__answer--quote-detail"
                        v-html="renderMessageContent(message)"
                      />
                    </div>

                    <div v-else class="chat-message__bubble">
                      <div
                        class="chat-message__answer"
                        v-html="renderMessageContent(message)"
                      />

                      <ChatProductCard
                        v-if="messageHasCerpData(message) && getProductCardForMessage(message)"
                        :product="getProductCardForMessage(message)"
                      />
                      <div
                        v-if="messageHasCerpResults(message)"
                        class="chat-cerp-results"
                      >
                        <div class="chat-cerp-results__header">
                          <div>
                            <p class="chat-cerp-results__title">
                              {{ tMessage(message, 'home.cerp_results.title', { count: normalizeCerpResultsForMessage(message).length }) }}
                            </p>
                            <p class="chat-cerp-results__subtitle">
                              {{ tMessage(message, 'home.cerp_results.subtitle') }}
                            </p>
                            <p
                              v-if="getCerpResultLimitSummary(message)"
                              class="chat-cerp-results__subtitle"
                            >
                              {{ getCerpResultLimitSummary(message) }}
                            </p>
                          </div>
                        </div>
                        <div class="chat-cerp-results__scroller">
                          <table class="chat-cerp-results__table">
                            <thead>
                              <tr>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.code') }}</th>
                                <th v-if="messageHasCerpResultCategories(message)">{{ tMessage(message, 'home.cerp_results.columns.category') }}</th>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.producer') }}</th>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.name') }}</th>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.vintage') }}</th>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.stock') }}</th>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.price') }}</th>
                                <th>{{ tMessage(message, 'home.cerp_results.columns.status') }}</th>
                                <th v-if="messageHasCerpResultReasons(message)">{{ tMessage(message, 'home.cerp_results.columns.reason') }}</th>
                              </tr>
                            </thead>
                            <tbody>
                              <template
                                v-for="item in normalizeCerpResultsForMessage(message)"
                                :key="item.key"
                              >
                                <tr>
                                  <td>{{ formatCerpResultValue(item.code, message) }}</td>
                                  <td v-if="messageHasCerpResultCategories(message)">{{ formatCerpResultValue(item.category, message) }}</td>
                                  <td>{{ formatCerpResultValue(item.producer, message) }}</td>
                                  <td>
                                    <span
                                      v-if="item.specialRecommended"
                                      class="chat-cerp-results__special"
                                    >
                                      ★
                                    </span>
                                    {{ formatCerpResultValue(item.name, message) }}
                                  </td>
                                  <td>{{ formatCerpResultValue(item.vintage, message) }}</td>
                                  <td>{{ formatCerpResultStock(item.stock, message) }}</td>
                                  <td>{{ formatCerpResultPrice(item.vipPrice || item.price, message) }}</td>
                                  <td>{{ formatCerpResultValue(item.status, message) }}</td>
                                  <td v-if="messageHasCerpResultReasons(message)">{{ formatCerpResultValue(item.reason, message) }}</td>
                                </tr>
                              </template>
                            </tbody>
                          </table>
                        </div>
                      </div>
                      <div
                        v-if="messageHasStandardFollowup(message)"
                        class="quote-followup"
                      >
                        <p
                          v-if="getQuoteFollowupSummaryForMessage(message)"
                          class="quote-followup__summary"
                        >
                          {{ getQuoteFollowupSummaryForMessage(message) }}
                        </p>
                        <div
                          v-if="getQuoteFollowupActionsForMessage(message)?.length"
                          class="quote-followup__actions"
                        >
                          <button
                            v-for="action in getQuoteFollowupActionsForMessage(message)"
                            :key="`${message.id || idx}-${action.id}`"
                            type="button"
                            class="quote-followup__chip"
                            :class="{ 'is-preferred': action.preferred }"
                            @click="handleQuoteFollowupActionFromChatUi(message, action)"
                          >
                            {{ action.label }}
                          </button>
                        </div>
                      </div>
                      <template v-if="getResultCardForMessage(message)">
                        <div
                          v-if="
                            showAssistantResultSummary &&
                            getResultCardForMessage(message)
                          "
                          class="chat-result-card-list"
                        >
                          <article class="chat-result-card">
                            <div class="chat-result-card__header">
                              <p class="chat-result-card__title">{{ getResultCardForMessage(message).title }}</p>
                              <ul
                                v-if="getResultCardForMessage(message).summaryBullets?.length"
                                class="chat-result-card__summary"
                              >
                                <li
                                  v-for="(item, bulletIdx) in getResultCardForMessage(message).summaryBullets"
                                  :key="`${getResultCardForMessage(message).id}-summary-${bulletIdx}`"
                                >
                                  {{ item }}
                                </li>
                              </ul>
                              <div class="chat-result-card__meta">
                                <span>{{ getResultCardForMessage(message).datetime }}</span>
                                <span class="chat-result-card__status">
                                  <span class="dot" />
                                  {{ getResultCardForMessage(message).status }}
                                </span>
                              </div>
                            </div>
                            <div
                              v-if="getResultCardForMessage(message).references?.length"
                              class="chat-result-card__references-block"
                            >
                              <ul class="chat-result-card__references">
                                <li
                                  v-for="(ref, refIdx) in getVisibleResultCardReferences(message, getResultCardForMessage(message))"
                                  :key="`${getResultCardForMessage(message).id}-${ref.title || refIdx}`"
                                >
                                  <template v-if="ref.kind === 'external'">
                                    <a
                                      class="chat-result-card__reference-link"
                                      :href="ref.url"
                                      target="_blank"
                                      rel="noopener noreferrer"
                                    >
                                      {{ ref.url || ref.title }}
                                    </a>
                                  </template>
                                  <template v-else>
                                    <strong>{{ ref.title }}</strong>
                                    <span
                                      v-if="ref.badge"
                                      class="chat-result-card__badge"
                                    >
                                      {{ ref.badge }}
                                    </span>
                                    <span v-if="ref.location">{{ ref.location }}</span>
                                  </template>
                                </li>
                              </ul>
                              <button
                                v-if="shouldShowResultCardReferenceToggle(getResultCardForMessage(message))"
                                type="button"
                                class="chat-result-card__references-toggle"
                                :aria-expanded="isResultCardReferencesExpanded(message, getResultCardForMessage(message))"
                                @click="toggleResultCardReferences(message, getResultCardForMessage(message))"
                              >
                                {{
                                  isResultCardReferencesExpanded(message, getResultCardForMessage(message))
                                    ? t('home.references.less_references')
                                    : t('home.references.more_references')
                                }}
                              </button>
                            </div>
                            <div
                              v-if="
                                getResultCardForMessage(message).answerMode ||
                                getResultCardForMessage(message).sourceMixRows?.length ||
                                getResultCardForMessage(message).rejectedEvidence?.length
                              "
                              class="chat-result-card__transparency-wrap"
                            >
                              <button
                                type="button"
                                class="chat-result-card__transparency-trigger"
                                :aria-label="resolveTransparencyCopy('title')"
                              >
                                {{ resolveTransparencyCopy('title') }}
                              </button>
                              <div class="chat-result-card__transparency" role="tooltip">
                                <div class="chat-result-card__transparency-row">
                                  <span class="chat-result-card__label">
                                    {{ resolveTransparencyCopy('answerMode') }}
                                  </span>
                                  <span class="chat-result-card__badge is-mode">
                                    {{ getResultCardForMessage(message).answerMode }}
                                  </span>
                                </div>
                                <div
                                  v-if="getResultCardForMessage(message).generalAnswerDisclaimer"
                                  class="chat-result-card__transparency-row"
                                >
                                  <span class="chat-result-card__label">
                                    {{ t('home.transparency.disclaimer') }}
                                  </span>
                                  <span class="chat-result-card__badge is-metric">
                                    {{ getResultCardForMessage(message).generalAnswerDisclaimer }}
                                  </span>
                                </div>
                                <div
                                  v-if="getResultCardForMessage(message).citationValidation?.citation_count != null"
                                  class="chat-result-card__transparency-row"
                                >
                                  <span class="chat-result-card__label">{{ t('home.transparency.citation_validation') }}</span>
                                  <span class="chat-result-card__badge is-metric">
                                    {{ t('home.transparency.citation_metric', {
                                      citations: getResultCardForMessage(message).citationValidation.citation_count,
                                      unmapped: getResultCardForMessage(message).citationValidation.unmapped_citation_count || 0,
                                    }) }}
                                  </span>
                                </div>
                                <div
                                  v-if="getResultCardForMessage(message).officialInventoryBinding?.proof_count != null"
                                  class="chat-result-card__transparency-row"
                                >
                                  <span class="chat-result-card__label">{{ t('home.transparency.cerp_proof') }}</span>
                                  <span class="chat-result-card__badge is-metric">
                                    {{ t('home.transparency.cerp_proof_metric', { count: getResultCardForMessage(message).officialInventoryBinding.proof_count }) }}
                                  </span>
                                </div>
                                <div
                                  v-if="getResultCardForMessage(message).hardErrorFlags?.length"
                                  class="chat-result-card__transparency-row is-column"
                                >
                                  <span class="chat-result-card__label">{{ t('home.transparency.hard_flags') }}</span>
                                  <div class="chat-result-card__badge-list">
                                    <span
                                      v-for="flag in getResultCardForMessage(message).hardErrorFlags"
                                      :key="`${getResultCardForMessage(message).id}-${flag}`"
                                      class="chat-result-card__badge is-rejected"
                                    >
                                      {{ flag }}
                                    </span>
                                  </div>
                                </div>
                                <div
                                  v-if="getResultCardForMessage(message).sourceMixRows?.length"
                                  class="chat-result-card__transparency-row is-column"
                                >
                                  <span class="chat-result-card__label">
                                    {{ resolveTransparencyCopy('sourceMix') }}
                                  </span>
                                  <div class="chat-result-card__badge-list">
                                    <span
                                      v-for="item in getResultCardForMessage(message).sourceMixRows"
                                      :key="item.key"
                                      class="chat-result-card__badge is-metric"
                                    >
                                      {{ item.label }} {{ item.count }} / {{ item.percent }}%
                                    </span>
                                  </div>
                                </div>
                                <div
                                  v-if="getResultCardForMessage(message).rejectedEvidence?.length"
                                  class="chat-result-card__transparency-row is-column"
                                >
                                  <span class="chat-result-card__label">
                                    {{ resolveTransparencyCopy('rejectedEvidence') }}
                                    {{ getResultCardForMessage(message).coverageReport?.rejected_hit_count || getResultCardForMessage(message).rejectedEvidence.length }}
                                  </span>
                                  <ul class="chat-result-card__rejected-list">
                                    <li
                                      v-for="item in getResultCardForMessage(message).rejectedEvidence"
                                      :key="`${getResultCardForMessage(message).id}-${item.id}`"
                                    >
                                      <span class="chat-result-card__badge is-rejected">{{ item.badge }}</span>
                                      <span>{{ item.label || item.id }}</span>
                                      <span v-if="item.reasons">{{ item.reasons }}</span>
                                    </li>
                                  </ul>
                                </div>
                              </div>
                            </div>
                          </article>
                        </div>

                        <div class="chat-toolbar">
                          <button
                            type="button"
                            :aria-label="t('home.aria.copy_response')"
                            @click="handleCopyClick()"
                          >
                            <img :src="chatToolbarCopy" alt="" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            :aria-label="t('home.aria.share_response')"
                            @click="handleShareClick()"
                          >
                            <img :src="chatToolbarShare" alt="" aria-hidden="true" />
                          </button>
                        </div>
                      </template>
                    </div>
                  </template>

                  <template v-else>
                    <div class="chat-message__bubble">
                      <p class="chat-message__text">{{ message.content }}</p>
                    </div>
                    <div class="chat-message__avatar is-user" aria-hidden="true">
                      {{ resolveUserMessageAuthorLabel(message) }}
                    </div>
                  </template>
                </article>
                <article
                  v-if="isAssistantTyping"
                  class="chat-message is-assistant is-typing"
                >
                  <div class="chat-message__avatar" aria-hidden="true">
                    {{ t('home.labels.ai') }}
                  </div>
                  <div class="chat-message__bubble typing-bubble" aria-live="polite">
                    <div class="typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                    <p class="typing-hint">{{ t('home.loading.ai_thinking') }}</p>
                  </div>
                </article>
              </template>

              <template v-else>
                <article class="chat-message is-user">
                  <div class="chat-message__bubble">
                    <p>{{ submittedTask || defaultUserPrompt }}</p>
                  </div>
                  <div class="chat-message__avatar is-user">{{ t('home.labels.you') }}</div>
                </article>
                <article class="chat-message is-assistant">
                  <div class="chat-message__avatar" aria-hidden="true">
                    {{ t('home.labels.ai') }}
                  </div>
                  <div class="chat-message__bubble">
                    <div
                      class="chat-message__answer"
                      v-html="assistantAnswerHtml"
                    />
                  </div>
                </article>
              </template>
            </div>
          </section>
          <section class="chat-composer-dock">
            <p v-if="chatError" class="chat-error" role="alert">
              {{ chatError }}
            </p>
            <ChatComposer
              v-model="composerValue"
              :placeholder="CHAT_COMPOSER_PLACEHOLDER"
              :output-types="outputTypes"
              :selected-output-type="selectedOutputType"
              :output-placeholder="chatOutputPlaceholder"
              :attachments="uploadAttachments"
              :upload-warning="uploadWarning"
              :show-attachments="true"
              :two-row-layout="uploadAttachments.length > 0"
              :send-icon-src="arrowButtonAsset"
              :input-rows="1"
              :upload-aria-label="t('home.aria.upload_file')"
              :send-aria-label="t('home.aria.send_message')"
              @submit="handleComposerSubmit"
              @select-output-type="selectOutputType"
              @upload-click="handleComposerUploadClick"
              @add-urls="handleComposerUrlsAdded"
              @remove-attachment="removeComposerAttachment"
            />
          </section>
        </template>
      </main>
    </div>
  </div>

  <transition name="snackbar-fade">
    <div
      v-if="showSnackbar"
      class="snackbar"
      role="status"
      aria-live="polite"
    >
      <div class="snackbar__icon" aria-hidden="true">
        <span>✓</span>
      </div>
      <span class="snackbar__text">{{ t('home.snackbar.copied') }}</span>
      <button
        class="snackbar__close"
        type="button"
        :aria-label="t('home.aria.close_snackbar')"
        @click="closeSnackbar"
      >?</button>
    </div>
  </transition>

  <div
    v-if="showShareDialog"
    class="share-dialog"
  >
    <div class="share-dialog__backdrop" @click="closeShareDialog" />
    <div
      class="share-dialog__card"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-dialog-title"
    >
      <header class="share-dialog__header">
        <h3 id="share-dialog-title">{{ t('home.share.title') }}</h3>
        <button
          class="share-dialog__close"
          type="button"
          :aria-label="t('home.aria.close_share')"
          @click="closeShareDialog"
        >?</button>
      </header>

      <section class="share-dialog__preview">
        <img :src="chatToolbarShareIc" alt="" aria-hidden="true" />
        <div>
          <p class="share-dialog__preview-title">{{ conversationTitle }}</p>
          <p class="share-dialog__preview-snippet">{{ sharePreviewSnippet }}</p>
        </div>
      </section>

      <div class="share-dialog__form">
        <label class="share-dialog__input">
          <input
            ref="shareInputRef"
            type="email"
            :placeholder="t('home.placeholders.share_email')"
            v-model="shareEmail"
          />
          <button
            type="button"
            :disabled="!shareEmail.trim()"
            @click="handleShareSubmit"
          >{{ t('home.share.submit') }}</button>
        </label>
        <p class="share-dialog__note">{{ t('home.share.note') }}</p>
      </div>
    </div>
  </div>

  <div
    v-if="activeModal === 'permission' && isAuthenticated"
    class="modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="closeModal"
  >
    <article class="modal-card modal-card--permission">
      <header class="modal-card__header modal-card__header--figma">
        <h3>{{ t('home.menu.visibility') }}</h3>
        <button
          class="icon-button"
          type="button"
          :aria-label="t('home.aria.close_modal')"
          @click="closeModal"
        >x</button>
      </header>
      <div class="modal-card__body modal-card__body--permission">
        <div class="permission-target">
          <img
            class="permission-target__icon"
            :src="permissionTargetIconSrc"
            alt=""
            aria-hidden="true"
          />
          <strong>{{ permissionTargetTitle }}</strong>
        </div>

        <div class="permission-section">
          <p class="permission-section__label">
            <span class="required-star">*</span> {{ t('home.permission.visibility_setting') }}
          </p>
          <div class="visibility-switch">
            <label>
              <input v-model="permissionVisibility" type="radio" value="private" />
              {{ t('home.visibility.private') }}
            </label>
            <label>
              <input v-model="permissionVisibility" type="radio" value="public" />
              {{ t('home.visibility.public') }}
            </label>
          </div>
        </div>

        <template v-if="permissionVisibility === 'private'">
          <div class="permission-section">
          <p class="permission-section__label">{{ t('home.permission.invite_members') }}</p>
            <div class="invite-inline">
              <div class="invite-lookup">
                <input
                  v-model="permissionEmail"
                  type="text"
                  autocomplete="off"
                  :placeholder="t('home.permission.lookup_placeholder')"
                  @focus="handlePermissionInviteFocus"
                  @keydown.enter.prevent="addPermissionInvitation"
                />
                <div v-if="permissionLookupOpen" class="invite-suggestions">
                  <button
                    v-for="candidate in permissionSuggestions"
                    :key="candidate.id"
                    type="button"
                    class="invite-suggestion"
                    @click="selectPermissionCandidate(candidate)"
                  >
                    <strong>{{ candidate.label }}</strong>
                    <small>{{ candidate.username }}</small>
                  </button>
                  <p v-if="permissionLookupBusy" class="invite-suggestion-empty">{{ t('home.permission.lookup_loading') }}</p>
                  <p
                    v-else-if="permissionEmail.trim().length >= INVITE_LOOKUP_MIN_LENGTH && !permissionSuggestions.length"
                    class="invite-suggestion-empty"
                  >
                    {{ t('home.permission.lookup_empty') }}
                  </p>
                </div>
              </div>
              <button
                type="button"
                class="invite-submit"
                :disabled="!canSubmitPermissionInvite"
                @click="addPermissionInvitation"
              >
                {{ t('home.permission.invite') }}
              </button>
            </div>
          </div>
          <div class="permission-section">
            <p class="permission-section__label">{{ t('home.permission.current_members') }}</p>
            <div class="invite-list">
              <article
                v-for="access in permissionAccessRows"
                :key="access.id"
                class="invite-item"
              >
                <div class="invite-item__identity">
                  <span class="invite-avatar" aria-hidden="true">{{ access.label.slice(0, 1).toUpperCase() }}</span>
                  <div class="invite-item__text">
                    <strong>{{ access.label }}</strong>
                    <small v-if="access.secondary">{{ access.secondary }}</small>
                  </div>
                </div>
                <div class="invite-item__actions">
                  <small>{{ access.status }}</small>
                  <button
                    v-if="access.revokable"
                    type="button"
                    class="invite-remove"
                    @click="revokePermissionInvitation({ id: access.id })"
                  >
                    {{ t('home.permission.remove') }}
                  </button>
                </div>
              </article>
              <p v-if="!permissionAccessRows.length" class="invite-empty">{{ t('home.permission.empty_members') }}</p>
            </div>
          </div>
        </template>

        <p v-else class="modal-copy">{{ t('home.permission.public_copy') }}</p>

        <p v-if="permissionError" class="modal-card__error">{{ permissionError }}</p>
      </div>
      <footer class="modal-card__actions modal-card__actions--permission">
        <button type="button" class="ghost" @click="closeModal">
          {{ t('home.actions.cancel') }}
        </button>
        <button
          type="button"
          class="primary permission-confirm"
          :disabled="isPermissionBusy"
          @click="confirmPermissionModal"
        >
          {{ isPermissionBusy ? t('home.permission.saving') : t('home.permission.confirm') }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-else-if="activeModal === 'selectFolder' && isAuthenticated"
    class="modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="closeModal"
  >
    <article class="modal-card modal-card--select-folder">
      <header class="modal-card__header">
        <h3>{{ t('home.modals.select_folder.title') }}</h3>
        <button
          class="icon-button"
          type="button"
          :aria-label="t('home.aria.close_modal')"
          @click="closeModal"
        >?</button>
      </header>
      <div class="modal-card__body modal-card__body--select-folder">
        <p class="modal-copy">{{ t('home.modals.select_folder.subtitle') }}</p>
        <label class="form-field form-field--compact">
          <span>{{ t('home.modals.select_folder.search_label') }}</span>
          <input
            v-model="folderPickerQuery"
            type="search"
            :placeholder="t('home.modals.select_folder.search_placeholder')"
          />
        </label>
        <div class="folder-picker-list">
          <div v-if="isFolderPickerLoading" class="folder-picker-state">
            {{ t('home.modals.select_folder.loading') }}
          </div>
          <label
            v-for="item in filteredFolderPickerItems"
            :key="item.id"
            class="folder-picker-item"
          >
            <input v-model="folderPickerSelectedId" type="radio" :value="item.id" />
            <div class="folder-picker-item__text">
              <strong>{{ item.name }}</strong>
              <small>{{ item.visibility === 'public' ? t('home.visibility.public') : t('home.visibility.private') }}</small>
            </div>
          </label>
          <div
            v-if="!isFolderPickerLoading && !filteredFolderPickerItems.length"
            class="folder-picker-state"
          >
            {{ t('home.modals.select_folder.empty') }}
          </div>
        </div>
        <p v-if="folderPickerError" class="modal-card__error">{{ folderPickerError }}</p>
      </div>
      <footer class="modal-card__actions">
        <button type="button" class="ghost" @click="closeModal">
          {{ t('home.actions.cancel') }}
        </button>
        <button
          type="button"
          class="primary"
          :disabled="isFolderPickerSaving || !folderPickerSelectedId"
          @click="submitSelectFolder"
        >
          {{ isFolderPickerSaving ? t('home.modals.select_folder.submitting') : t('home.modals.select_folder.confirm') }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-else-if="modalContent && isAuthenticated"
    class="modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="closeModal"
  >
    <div class="modal-card" :class="modalContent.variant === 'danger' ? 'is-danger' : ''">
      <header class="modal-card__header">
        <h3>{{ modalContent.title }}</h3>
        <button
          class="icon-button"
          type="button"
          :aria-label="t('home.aria.close_modal')"
          @click="closeModal"
        >?</button>
      </header>
      <p class="modal-card__body" v-if="modalContent.body">
        {{ modalContent.body }}
      </p>
      <div v-if="modalContent.hasInput" class="modal-card__field">
        <label for="rename-field">* {{ $t('home.labels.project_name') }}</label>
        <input
          id="rename-field"
          v-model="renameValue"
          type="text"
          :placeholder="t('home.placeholders.rename_project')"
        />
      </div>
      <p v-if="renameError" class="modal-card__error">{{ renameError }}</p>
      <p
        v-if="(activeModal === 'deleteProject' || activeModal === 'deleteConversation') && deleteError"
        class="modal-card__error"
      >
        {{ deleteError }}
      </p>
      <footer class="modal-card__actions">
        <button
          v-if="modalContent.showCancel !== false"
          type="button"
          class="ghost"
          @click="closeModal"
        >
          {{ t('home.actions.cancel') }}
        </button>
        <button
          type="button"
          :class="modalContent.variant === 'danger' ? 'danger' : 'primary'"
          :disabled="(activeModal === 'rename' && isRenaming) || ((activeModal === 'deleteProject' || activeModal === 'deleteConversation') && isDeleting)"
          @click="handleModalConfirm"
        >
          {{ modalContent.confirmLabel }}
        </button>
      </footer>
    </div>
  </div>

  <div
          v-if="showSearchPanel && isSearchModal"
          class="search-panel is-modal"
        >
    <div class="search-panel__backdrop" @click="closeSearchPanel" />
    <div class="search-panel__card">
      <form class="search-panel__form" @submit.prevent="handleSearchSubmit">
        <div class="search-panel__modal-input">
          <span v-html="glyphs.search" aria-hidden="true" />
          <input
            ref="searchPanelInput"
            type="search"
            :placeholder="t('home.placeholders.search')"
            v-model="searchQuery"
            @input="handleSearchInputChange"
          />
          <button
            type="button"
            :aria-label="t('home.aria.close_search')"
            @click="closeSearchPanel"
          >?</button>
        </div>
      </form>
      <button class="search-panel__new" type="button" @click="handleNewConversation">
        + {{ t('home.actions.new_conversation') }}
      </button>
      <p class="search-panel__subtitle">{{ searchPanelSubtitle }}</p>
      <div class="search-panel__list">
        <button
          v-for="chat in searchPanelItems"
          :key="`modal-${chat.id}`"
          type="button"
          class="search-panel__item"
          @click="handleSearchSelect(chat)"
        >
          <span>{{ resolveHistoryInfoLabel(chat) }}</span>
          <p v-if="isSearchResultsMode" class="search-panel__excerpt">
            {{ resolveSearchPanelItemExcerpt(chat) }}
          </p>
          <small>{{ formatDisplayTime(chat.updatedAt || chat.createdAt) }}</small>
        </button>
        <p v-if="!searchPanelItems.length" class="search-panel__empty">
          {{ searchPanelEmptyText }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-header {
  display: none;
}

.section-empty,
.section-error {
  padding: 24px;
  border-radius: 18px;
  text-align: center;
  font-size: 15px;
  line-height: 1.5;
  background: #f5f7fb;
  color: #4b5563;
  margin: 0 0 16px;
}

.section-error {
  background: #ffe9df;
  color: #9c2a1b;
}

.modal-card__error {
  margin: 8px 0 0;
  color: #d64539;
  font-size: 13px;
}

.selected-row__summary,
.history-row__summary {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.4;
}

.visibility-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1;
  margin-left: 8px;
  background: #edf2ff;
  color: #1d3a8a;
}

.visibility-badge.is-public {
  background: #e6f4ef;
  color: #0f6c45;
}

.visibility-badge.is-private {
  background: #f1f5f9;
  color: #475569;
}

.modal-card--permission {
  width: min(624px, 100%);
  padding: 0;
  border-radius: 16px;
  overflow: hidden;
}

.modal-card--select-folder {
  width: min(560px, 100%);
}

.modal-card__header--figma {
  height: 76px;
  padding: 0 24px;
  margin-bottom: 0;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.modal-card__body--permission {
  margin: 0;
  padding: 0 24px 20px;
  display: grid;
  gap: 18px;
  max-height: 70vh;
  overflow: auto;
}

.modal-card__actions--permission {
  padding: 0 24px 20px;
}

.modal-card__body--select-folder {
  display: grid;
  gap: 12px;
}

.folder-picker-list {
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: var(--ys-control-radius, 6px);
  max-height: 280px;
  overflow: auto;
}

.folder-picker-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.16);
}

.folder-picker-item:last-child {
  border-bottom: none;
}

.folder-picker-item input[type='radio'] {
  margin-top: 2px;
}

.folder-picker-item__text {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.folder-picker-item__text strong {
  color: #212b36;
  font-size: 14px;
  line-height: 1.45;
}

.folder-picker-item__text small {
  color: #637381;
  font-size: 12px;
}

.folder-picker-state {
  padding: 18px 14px;
  color: #637381;
  font-size: 13px;
  text-align: center;
}

.permission-confirm {
  background: #55b77f !important;
  color: #fff !important;
}

.permission-confirm:hover:not(:disabled) {
  background: #3f9f6a !important;
}

.permission-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.permission-target {
  min-height: 58px;
  border-radius: var(--ys-control-radius, 6px);
  border: 1px solid rgba(145, 158, 171, 0.24);
  background: #fff;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.permission-target__icon {
  width: 24px;
  height: 24px;
  object-fit: contain;
  display: block;
}

.permission-target strong {
  margin: 0;
  color: #212b36;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
}

.permission-section {
  display: grid;
  gap: 10px;
}

.permission-section__label {
  margin: 0;
  color: #637381;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
}

.required-star {
  color: #ff5630;
  margin-right: 4px;
}

.visibility-switch {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: 10px;
  overflow: hidden;
}

.visibility-switch label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 0 14px;
  font-size: 14px;
  color: #212b36;
  cursor: pointer;
}

.visibility-switch input[type='radio'] {
  margin: 0;
}

.invite-inline {
  display: flex;
  align-items: center;
  gap: 8px;
}

.invite-lookup {
  position: relative;
  flex: 1;
}

.invite-inline input {
  flex: 1;
  min-height: 40px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  padding: 0 12px;
  color: #212b36;
  font-size: 14px;
}

.invite-suggestions {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 8;
  display: grid;
  gap: 0;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.1);
  overflow: hidden;
}

.invite-suggestion {
  border: none;
  background: #fff;
  padding: 10px 12px;
  display: grid;
  gap: 2px;
  text-align: left;
  cursor: pointer;
}

.invite-suggestion:hover {
  background: #f8fafc;
}

.invite-suggestion strong {
  color: #212b36;
  font-size: 14px;
  font-weight: 700;
}

.invite-suggestion small,
.invite-suggestion-empty {
  color: #637381;
  font-size: 12px;
}

.invite-suggestion-empty {
  margin: 0;
  padding: 10px 12px;
}

.invite-submit {
  min-width: 84px;
  min-height: 40px;
  border-radius: var(--ys-control-radius, 6px);
  border: 1px solid rgba(145, 158, 171, 0.32);
  background: #fff;
  color: #212b36;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.invite-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.invite-list {
  display: grid;
  gap: 8px;
}

.invite-item {
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.invite-item__identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.invite-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #edf2f7;
  color: #455468;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.invite-item strong {
  color: #212b36;
  font-size: 14px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.invite-item small {
  color: #637381;
  font-size: 12px;
}

.invite-item__actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.invite-remove {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 1px solid rgba(145, 158, 171, 0.4);
  background: #fff;
  color: #637381;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  cursor: pointer;
}

.invite-remove:hover {
  background: #f4f6f8;
}

.invite-empty {
  margin: 0;
  color: #637381;
  font-size: 13px;
}

.modal-copy {
  margin: 0;
  color: #637381;
  font-size: 14px;
  line-height: 1.6;
}

.chat-message.is-typing .chat-message__bubble {
  background: #f8fafc;
}

.typing-bubble {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.typing-indicator {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  animation: typingPulse 1.2s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.3s;
}

.typing-hint {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}

.cerp-summary-fields {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cerp-summary-fields p {
  margin: 0;
  font-size: 13px;
  color: #111827;
}

.cerp-summary-fields p strong {
  font-weight: 600;
  color: #0f172a;
}

.chat-composer {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-composer__row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
}

.chat-composer__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-dropdown {
  margin-left: 0;
}

.chat-composer__field {
  flex: 1;
  min-width: 320px;
  display: flex;
  align-items: center;
}

.chat-composer__field textarea {
  width: 100%;
  min-height: 54px;
  resize: none;
  display: flex;
  align-items: center;
}

.chat-composer__send {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  cursor: pointer;
  margin-left: auto;
}

.chat-composer__preview-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
  padding: 4px 0;
  height: 80px;
  overflow-y: hidden;
  justify-content: flex-start;
}

.chat-composer__preview-card {
  width: 80px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  height: 80px;
}

@media (max-width: 768px) {
  .chat-composer__preview-card {
    width: 100%;
  }
}

.chat-composer__preview-thumb {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: var(--ys-chat-radius, 6px);
  border: 1px dashed #cbd5f5;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.chat-composer__preview-thumb img {
  width: 72px;
  height: 72px;
  object-fit: cover;
}

.chat-composer__preview-remove {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  cursor: pointer;
  padding: 0;
}

.chat-composer__preview-placeholder {
  font-size: 12px;
  color: #475569;
}

.chat-composer__preview-label {
  margin: 0;
  font-size: 12px;
  color: #475569;
  word-break: break-all;
}

.chat-composer__upload-hint {
  font-size: 12px;
  color: #475569;
  margin: 4px 0 0;
}

.composer-file-input {
  display: none;
}

.command-home-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.command-home-panel section {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  border: 1px solid rgba(27, 45, 41, 0.1);
  border-radius: var(--ys-chat-radius, 6px);
  background: #f7f9f6;
}

.command-home-panel h3 {
  margin: 0 0 4px;
  color: #10241f;
  font-size: 13px;
  font-weight: 900;
}

.command-home-panel__item {
  display: grid;
  gap: 3px;
  min-height: 46px;
  padding: 8px 10px;
  border-radius: var(--ys-chat-radius, 6px);
  color: #1b2d29;
  text-align: left;
  background: #fff;
}

.command-home-panel__item:hover {
  background: #fff3d4;
}

.command-home-panel__item span,
.command-home-panel__item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-home-panel__item span {
  font-weight: 800;
}

.command-home-panel__item small,
.command-home-panel__empty {
  color: #64766f;
  font-size: 12px;
}

.command-home-panel__empty {
  margin: 0;
}

@media (max-width: 720px) {
  .command-home-panel {
    grid-template-columns: 1fr;
  }
}

@keyframes typingPulse {
  0%,
  80%,
  100% {
    opacity: 0.2;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}
</style>
