
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import logoMain from '../assets/ysLogo_transparent.png'
import iconFolder from '../assets/ic-folder.svg'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import iconChatProject from '../assets/ic_chat_p.svg'
import emptyTableImage from '../assets/Table No data.svg'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { useAuth } from '../composables/useAuth'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'
import { formatUsdPrice } from '../utils/currency'
import {
  archiveConversation,
  createConversationInvitation,
  createProject,
  createProjectInvitation,
  deleteConversationInvitation,
  deleteProject,
  deleteProjectInvitation,
  fetchConversationInvitations,
  fetchProjectConversations,
  fetchProjectConversationSearch,
  fetchProjectInvitations,
  fetchProjects,
  renameConversation,
  searchInvitationCandidates,
  updateConversationProject,
  updateConversationVisibility,
  updateProject,
} from '../services/ysApi'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const { isAuthenticated, avatarLabel, userProfile } = useAuth()
const debugLog = (...args) => {
  if (import.meta.env.DEV) {
    console.debug('[ProjectView]', ...args)
  }
}

const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const TABLET_BREAKPOINT = 900
const SHOW_PROJECT_PROFILE = false
const INVITE_LOOKUP_MIN_LENGTH = 2

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7A879C" stroke-width="2"/><path d="M12.5 12.5L16 16" stroke="#7A879C" stroke-width="2" stroke-linecap="round"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#0D3357" stroke-width="2" stroke-linecap="round"/></svg>',
  plus:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 3.333V12.667M3.333 8H12.667" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  more:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="3" r="1.25" fill="#98a3b9"/><circle cx="8" cy="8" r="1.25" fill="#98a3b9"/><circle cx="8" cy="13" r="1.25" fill="#98a3b9"/></svg>',
  back:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m9.5 3.5-4 4 4 4" stroke="#637381" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'home.nav'))

const iconImages = PRIMARY_NAV_ICON_IMAGES

const stageWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1440)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isTablet = computed(() => stageWidth.value <= TABLET_BREAKPOINT)
const isSidebarCollapsed = ref(stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const activeNavId = ref('project')
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet,
    isSidebarCollapsed,
  })

const mode = ref('project')
const listScope = ref('all')
const loading = ref(false)
const listError = ref('')
const searchQuery = ref('')
const searchTimer = ref(null)

const projects = ref([])
const projectPage = ref(1)
const projectTotal = ref(0)
const globalSearchConversations = ref([])
const globalSearchConversationTotal = ref(0)

const activeProject = ref(null)
const conversations = ref([])
const conversationPage = ref(1)
const conversationTotal = ref(0)

const pageSize = ref(10)
const isGlobalSearchMode = computed(() => mode.value === 'project' && !!searchQuery.value.trim())
const isInboxScope = computed(() => mode.value === 'project' && listScope.value === 'inbox')
const displayMode = computed(() => {
  if (isInboxScope.value) return 'conversation'
  if (isGlobalSearchMode.value) return 'conversation'
  return mode.value === 'project' ? 'project' : 'conversation'
})
const rows = computed(() => {
  if (displayMode.value === 'project') return projects.value
  if (mode.value === 'conversation') return conversations.value
  return globalSearchConversations.value
})
const total = computed(() => {
  if (displayMode.value === 'project') return projectTotal.value
  if (mode.value === 'conversation') return conversationTotal.value
  return globalSearchConversationTotal.value
})
const currentPage = computed(() => {
  if (displayMode.value === 'project') return projectPage.value
  if (mode.value === 'conversation') return conversationPage.value
  return projectPage.value
})
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const rangeLabel = computed(() => {
  if (!total.value || !rows.value.length) return '0-0 / 0'
  const start = (currentPage.value - 1) * pageSize.value + 1
  const end = Math.min(total.value, start + rows.value.length - 1)
  return `${start}-${end} / ${total.value}`
})
const tableModeClass = computed(() => (displayMode.value === 'project' ? 'table--project' : 'table--conversation'))
const breadcrumbTitle = computed(() => {
  if (activeProject.value) return activeProject.value.name || t('projects.common.project')
  if (isInboxScope.value) return t('projects.common.drafts')
  return t('projects.common.all_projects')
})
const tableSearchPlaceholder = computed(() => {
  if (isInboxScope.value) return t('projects.common.search_drafts')
  if (mode.value === 'conversation') return t('projects.common.search_folder')
  return t('projects.common.search_projects')
})
const selectedScope = ref('project')

const activeMenuId = ref('')
const rowMenuTarget = computed(() =>
  rows.value.find((item) => String(item.id) === String(activeMenuId.value)) || null
)
const isRowMenuOpen = (id) => String(activeMenuId.value) === String(id)

const showCreateModal = ref(false)
const showRenameModal = ref(false)
const showDeleteModal = ref(false)
const showPermissionModal = ref(false)
const showSelectFolderModal = ref(false)
const modalBusy = ref(false)
const modalError = ref('')
const selectedItem = ref(null)

const selectFolderTarget = ref(null)
const folderPickerQuery = ref('')
const folderPickerSelectedId = ref('')
const folderPickerItems = ref([])
const folderPickerError = ref('')
const isFolderPickerLoading = ref(false)
const isFolderPickerSaving = ref(false)

const renameValue = ref('')
const permissionScope = ref('project')
const permissionVisibility = ref('private')
const permissionInvitations = ref([])
const inviteEmail = ref('')
const inviteSuggestions = ref([])
const inviteLookupBusy = ref(false)
const inviteLookupOpen = ref(false)
const selectedInviteCandidate = ref(null)
const inviteLookupTimer = ref(null)

const permissionTargetTitle = computed(() => {
  if (!selectedItem.value) return ''
  if (permissionScope.value === 'project') {
    return selectedItem.value.name || selectedItem.value.project_name || '-'
  }
  return selectedItem.value.title || t('projects.common.untitled_conversation')
})

const permissionTargetIconSrc = computed(() =>
  permissionScope.value === 'project' ? iconFolder : iconChatProject
)

const formatInvitationStatus = (status) => {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'accepted') return t('projects.common.accepted')
  if (normalized === 'pending') return t('projects.common.pending')
  if (normalized === 'rejected') return t('projects.common.rejected')
  if (normalized === 'revoked') return t('projects.common.revoked')
  return normalized || '-'
}

const ownerAccessLabel = computed(() => avatarLabel.value || t('projects.common.me'))
const isProjectOwner = (row) => {
  const ownerId = Number(row?.owner_user_id)
  const selfId = Number(userProfile.value?.id ?? userProfile.value?.user_id)
  if (!Number.isFinite(ownerId) || !Number.isFinite(selfId)) return false
  return ownerId === selfId
}

const canManageSelectedTarget = computed(() => {
  if (!selectedItem.value) return false
  return selectedScope.value === 'project'
    ? isProjectOwner(selectedItem.value)
    : isConversationOwner(selectedItem.value)
})

const canManageRow = (row) =>
  displayMode.value === 'project' ? isProjectOwner(row) : isConversationOwner(row)

const permissionAccessRows = computed(() => {
  const invitationRows = (permissionInvitations.value || []).map((invite) => ({
    id: invite.id,
    label: invite.name || invite.username || invite.email || '-',
    secondary: invite.username || invite.email || '',
    status: formatInvitationStatus(invite.status),
    revokable: invite.status !== 'revoked',
  }))
  invitationRows.push({
    id: 'owner',
    label: ownerAccessLabel.value,
    secondary: String(userProfile.value?.username || '').trim(),
    status: t('projects.common.owner_role'),
    revokable: false,
  })
  return invitationRows
})
const clearInviteLookupState = ({ clearInput = false } = {}) => {
  if (inviteLookupTimer.value) {
    clearTimeout(inviteLookupTimer.value)
    inviteLookupTimer.value = null
  }
  if (clearInput) {
    inviteEmail.value = ''
  }
  inviteSuggestions.value = []
  inviteLookupBusy.value = false
  inviteLookupOpen.value = false
  selectedInviteCandidate.value = null
}

const loadInviteSuggestions = async (keyword) => {
  if (
    !showPermissionModal.value ||
    !selectedItem.value?.id ||
    permissionVisibility.value !== 'private'
  ) {
    clearInviteLookupState()
    return
  }
  const normalizedKeyword = String(keyword || '').trim()
  if (normalizedKeyword.length < INVITE_LOOKUP_MIN_LENGTH) {
    inviteSuggestions.value = []
    inviteLookupOpen.value = false
    inviteLookupBusy.value = false
    return
  }

  inviteLookupBusy.value = true
  try {
    const data = await searchInvitationCandidates({
      query: normalizedKeyword,
      scope: permissionScope.value,
      targetId: selectedItem.value.id,
    })
    const items = (data?.items || []).filter((item) => {
      const username = String(item?.username || '').trim().toLowerCase()
      return username && !invitedIdentifierSet.value.has(username)
    })
    inviteSuggestions.value = items
    inviteLookupOpen.value = true
  } catch (error) {
    inviteSuggestions.value = []
    inviteLookupOpen.value = false
    modalError.value = error?.message || t('projects.common.load_accounts_failed')
  } finally {
    inviteLookupBusy.value = false
  }
}

const selectInviteCandidate = (candidate) => {
  if (!candidate?.username) return
  inviteEmail.value = candidate.username
  selectedInviteCandidate.value = candidate
  inviteSuggestions.value = []
  inviteLookupOpen.value = false
  modalError.value = ''
}

const handleInviteInputFocus = () => {
  if (inviteSuggestions.value.length) {
    inviteLookupOpen.value = true
  }
}
const normalizedInviteQuery = computed(() => String(inviteEmail.value || '').trim().toLowerCase())
const invitedIdentifierSet = computed(
  () =>
    new Set(
      (permissionInvitations.value || [])
        .filter((invite) => String(invite?.status || '').toLowerCase() !== 'revoked')
        .map((invite) => String(invite?.email || '').trim().toLowerCase())
        .filter(Boolean)
    )
)
const canSubmitInvite = computed(() => {
  if (modalBusy.value || permissionVisibility.value !== 'private') return false
  const candidate = selectedInviteCandidate.value
  if (!candidate?.username) return false
  const normalizedUsername = String(candidate.username).trim().toLowerCase()
  if (!normalizedUsername || normalizedUsername !== normalizedInviteQuery.value) return false
  if (invitedIdentifierSet.value.has(normalizedUsername)) return false
  return true
})

const filteredFolderPickerItems = computed(() => {
  const keyword = String(folderPickerQuery.value || '').trim().toLowerCase()
  if (!keyword) return folderPickerItems.value
  return folderPickerItems.value.filter((item) =>
    String(item?.name || '')
      .toLowerCase()
      .includes(keyword)
  )
})

const customerTypeOptions = ['VIP', 'B2B', 'F&B']
const projectForm = ref({
  name: '',
  visibility: 'private',
  customerType: '',
  tradeCount: '',
  lastTradeAt: '',
  avgUnitPrice: '',
  preferenceNote: '',
  region: '',
  hasWineCabinet: false,
})

const profileRows = computed(() => {
  if (!activeProject.value) return []
  const p = activeProject.value.customer_profile || {}
  return [
    { label: t('projects.common.customer_name'), value: activeProject.value.name || '-' },
    { label: t('projects.common.type'), value: p.customer_type || '-' },
    { label: t('projects.common.trade_count'), value: p.trade_count ?? '-' },
    { label: t('projects.common.last_trade_at'), value: formatDateTime(p.last_trade_at) },
    { label: t('projects.common.avg_unit_price'), value: p.avg_unit_price ? formatCurrency(p.avg_unit_price) : '-' },
    { label: t('projects.common.region'), value: p.region || '-' },
    { label: t('projects.common.has_wine_cabinet'), value: p.has_wine_cabinet === true ? t('projects.common.yes') : p.has_wine_cabinet === false ? t('projects.common.no') : '-' },
  ]
})

const profileDescription = computed(() => {
  if (!activeProject.value) return '-'
  const p = activeProject.value.customer_profile || {}
  return p.preference_note || '-'
})

const updateViewport = () => {
  stageWidth.value = typeof window !== 'undefined' ? window.innerWidth : stageWidth.value
  if (!isCompactSidebar.value) {
    isSidebarCollapsed.value = false
  }
}

const toggleSidebar = () => {
  if (!isCompactSidebar.value) return
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

const resetProjectForm = () => {
  projectForm.value = {
    name: '',
    visibility: 'private',
    customerType: '',
    tradeCount: '',
    lastTradeAt: '',
    avgUnitPrice: '',
    preferenceNote: '',
    region: '',
    hasWineCabinet: false,
  }
}

const closeAllModals = () => {
  showCreateModal.value = false
  showRenameModal.value = false
  showDeleteModal.value = false
  showPermissionModal.value = false
  showSelectFolderModal.value = false
  modalError.value = ''
  folderPickerError.value = ''
  folderPickerQuery.value = ''
  folderPickerSelectedId.value = ''
  folderPickerItems.value = []
  selectFolderTarget.value = null
  isFolderPickerLoading.value = false
  isFolderPickerSaving.value = false
  modalBusy.value = false
  clearInviteLookupState({ clearInput: true })
}

const closeRowMenu = () => {
  activeMenuId.value = ''
}

const buildCustomerProfilePayload = () => ({
  customer_type: projectForm.value.customerType || null,
  trade_count: Number.isFinite(Number(projectForm.value.tradeCount)) ? Number(projectForm.value.tradeCount) : null,
  last_trade_at: projectForm.value.lastTradeAt || null,
  avg_unit_price: Number.isFinite(Number(projectForm.value.avgUnitPrice)) ? Number(projectForm.value.avgUnitPrice) : null,
  preference_note: projectForm.value.preferenceNote || null,
  region: projectForm.value.region || null,
  has_wine_cabinet: Boolean(projectForm.value.hasWineCabinet),
})

const formatDateTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const h = String(date.getHours()).padStart(2, '0')
  const min = String(date.getMinutes()).padStart(2, '0')
  return `${y}/${m}/${d} ${h}:${min}`
}

const formatCurrency = (value) => {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '-'
  return formatUsdPrice(amount)
}

const normalizeSummaryText = (value = '') =>
  String(value || '')
    .replace(/\s+/g, ' ')
    .trim()

const truncateSummary = (value = '', maxChars = 20) => {
  const clean = normalizeSummaryText(value)
  if (!clean) return ''
  const glyphs = Array.from(clean)
  if (glyphs.length <= maxChars) return clean
  return `${glyphs.slice(0, maxChars).join('')}...`
}

const resolveConversationDisplayTitle = (row = {}) => {
  const title = normalizeSummaryText(row?.title || '')
  const hasCustomTitle = Boolean(row?.has_custom_title ?? row?.hasCustomTitle)
  if (hasCustomTitle && title) {
    return title
  }
  const question = truncateSummary(row?.last_user_message || row?.lastUserMessage || '', 20)
  if (question) {
    return question
  }
  const summary = truncateSummary(row?.summary || '', 20)
  if (summary) {
    return summary
  }
  return title || t('projects.common.untitled_conversation')
}

const isConversationOwner = (row) => {
  const ownerId = Number(row?.owner_user_id ?? row?.user_id)
  const selfId = Number(userProfile.value?.id ?? userProfile.value?.user_id)
  if (!Number.isFinite(ownerId) || !Number.isFinite(selfId)) return false
  return ownerId === selfId
}

const loadProjects = async () => {
  loading.value = true
  listError.value = ''
  try {
    const query = searchQuery.value.trim()
    if (isInboxScope.value) {
      const data = await fetchProjectConversationSearch({
        q: query,
        scope: 'inbox',
        page: projectPage.value,
        pageSize: pageSize.value,
      })
      globalSearchConversations.value = data?.items || []
      globalSearchConversationTotal.value = Number(data?.total || 0)
      projects.value = []
      projectTotal.value = 0
      return
    }

    if (query) {
      const data = await fetchProjectConversationSearch({
        q: query,
        scope: 'all',
        page: projectPage.value,
        pageSize: pageSize.value,
      })
      globalSearchConversations.value = data?.items || []
      globalSearchConversationTotal.value = Number(data?.total || 0)
      projects.value = []
      projectTotal.value = 0
      return
    }

    const data = await fetchProjects({
      q: '',
      page: projectPage.value,
      pageSize: pageSize.value,
    })
    projects.value = data?.items || []
    projectTotal.value = Number(data?.total || 0)
    globalSearchConversations.value = []
    globalSearchConversationTotal.value = 0
  } catch (error) {
    if (isGlobalSearchMode.value) {
      globalSearchConversations.value = []
      globalSearchConversationTotal.value = 0
    } else {
      projects.value = []
      projectTotal.value = 0
    }
    listError.value = error?.message || t('projects.common.load_projects_failed')
  } finally {
    loading.value = false
  }
}

const loadConversations = async () => {
  if (!activeProject.value?.id) return { ok: false }
  loading.value = true
  listError.value = ''
  try {
    const data = await fetchProjectConversations(activeProject.value.id, {
      q: searchQuery.value.trim(),
      page: conversationPage.value,
      pageSize: pageSize.value,
    })
    conversations.value = data?.items || []
    conversationTotal.value = Number(data?.total || 0)
    if (data?.project?.id && activeProject.value?.id === data.project.id) {
      activeProject.value = {
        ...activeProject.value,
        name: data.project.name || activeProject.value.name || '',
      }
    }
    return { ok: true, data }
  } catch (error) {
    conversations.value = []
    conversationTotal.value = 0
    listError.value = error?.message || t('projects.common.load_conversations_failed')
    return { ok: false, error }
  } finally {
    loading.value = false
  }
}

const reloadCurrentList = async () => {
  if (mode.value === 'project') {
    await loadProjects()
  } else {
    await loadConversations()
  }
}

const reloadConversationRows = async () => {
  if (mode.value === 'conversation') {
    await loadConversations()
    return
  }
  await loadProjects()
}

const openCreateModal = () => {
  closeRowMenu()
  resetProjectForm()
  showCreateModal.value = true
}

const submitCreateProject = async () => {
  if (modalBusy.value) return
  if (!projectForm.value.name.trim()) {
    modalError.value = t('projects.common.name_required')
    return
  }
  modalBusy.value = true
  modalError.value = ''
  try {
    await createProject({
      name: projectForm.value.name.trim(),
      visibility: projectForm.value.visibility,
      customerProfile: buildCustomerProfilePayload(),
    })
    closeAllModals()
    projectPage.value = 1
    await loadProjects()
  } catch (error) {
    modalError.value = error?.message || t('projects.common.create_failed')
  } finally {
    modalBusy.value = false
  }
}

const openRenameModal = () => {
  const target = rowMenuTarget.value
  if (!target) return
  if (!canManageRow(target)) return
  closeRowMenu()
  selectedItem.value = target
  selectedScope.value = displayMode.value === 'project' ? 'project' : 'conversation'
  renameValue.value = selectedScope.value === 'project' ? target.name || '' : target.title || ''
  modalError.value = ''
  showRenameModal.value = true
}

const submitRename = async () => {
  if (!selectedItem.value || modalBusy.value) return
  const nextName = renameValue.value.trim()
  if (!nextName) {
    modalError.value = t('projects.common.blank_name')
    return
  }

  modalBusy.value = true
  modalError.value = ''
  debugLog('rename:start', { scope: selectedScope.value, id: selectedItem.value?.id, nextName })
  try {
    if (selectedScope.value === 'project') {
      await updateProject(selectedItem.value.id, { name: nextName })
      if (activeProject.value?.id === selectedItem.value.id) {
        activeProject.value = { ...activeProject.value, name: nextName }
      }
      await loadProjects()
    } else {
      await renameConversation(selectedItem.value.id, { label: nextName })
      await reloadConversationRows()
    }
    closeAllModals()
  } catch (error) {
    debugLog('rename:error', error)
    modalError.value = error?.message || t('projects.common.rename_failed')
  } finally {
    modalBusy.value = false
  }
}

const openDeleteModal = () => {
  const target = rowMenuTarget.value
  if (!target) return
  if (!canManageRow(target)) return
  closeRowMenu()
  selectedItem.value = target
  selectedScope.value = displayMode.value === 'project' ? 'project' : 'conversation'
  modalError.value = ''
  showDeleteModal.value = true
}

const openNewConversationFromMenu = () => {
  const target = rowMenuTarget.value
  if (!target) return
  closeRowMenu()
  let projectId = ''
  let projectLabel = ''
  if (displayMode.value === 'project') {
    projectId = String(target.id || '').trim()
    projectLabel = String(target.name || '').trim()
  } else {
    projectId = String(
      target.project_id || target.projectId || target.project?.id || activeProject.value?.id || ''
    ).trim()
    projectLabel = String(
      target.project_name ||
        target.project_label ||
        target.projectLabel ||
        target.project?.label ||
        activeProject.value?.name ||
        ''
    ).trim()
  }
  const query = {}
  if (projectId) {
    query.compose_project_id = projectId
  }
  if (projectLabel) {
    query.compose_project_label = projectLabel
  }
  router.push({ name: 'home', query }).catch(() => {})
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
    folderPickerError.value = error?.message || t('projects.common.load_folders_failed')
  } finally {
    isFolderPickerLoading.value = false
  }
}

const openSelectFolderModal = async () => {
  const target = rowMenuTarget.value
  if (!target) return
  closeRowMenu()
  selectFolderTarget.value = target
  folderPickerQuery.value = ''
  folderPickerError.value = ''
  folderPickerSelectedId.value = String(target?.project_id || target?.projectId || '').trim()
  showSelectFolderModal.value = true
  await loadFolderPickerProjects()
}

const submitSelectFolder = async () => {
  const conversationId = String(
    selectFolderTarget.value?.id ||
      selectFolderTarget.value?.conversationId ||
      selectFolderTarget.value?.conversation_id ||
      ''
  ).trim()
  const projectId = String(folderPickerSelectedId.value || '').trim()
  if (!conversationId) {
    folderPickerError.value = t('projects.common.no_conversation')
    return
  }
  if (!projectId) {
    folderPickerError.value = t('projects.common.select_folder_first')
    return
  }
  isFolderPickerSaving.value = true
  folderPickerError.value = ''
  try {
    await updateConversationProject(conversationId, { projectId })
    closeAllModals()
    await loadProjects()
  } catch (error) {
    folderPickerError.value = error?.message || t('projects.common.move_failed')
  } finally {
    isFolderPickerSaving.value = false
  }
}

const submitDelete = async () => {
  if (!selectedItem.value || modalBusy.value) return
  modalBusy.value = true
  modalError.value = ''
  debugLog('delete:start', { scope: selectedScope.value, id: selectedItem.value?.id })
  try {
    if (selectedScope.value === 'project') {
      await deleteProject(selectedItem.value.id)
      if (activeProject.value?.id === selectedItem.value.id) {
        activeProject.value = null
        mode.value = 'project'
      }
      await loadProjects()
    } else {
      await archiveConversation(selectedItem.value.id)
      await reloadConversationRows()
    }
    closeAllModals()
  } catch (error) {
    debugLog('delete:error', error)
    modalError.value = error?.message || t('projects.common.delete_failed')
  } finally {
    modalBusy.value = false
  }
}

const loadPermissionInvitations = async () => {
  if (!selectedItem.value?.id) {
    permissionInvitations.value = []
    return
  }
  try {
    const data =
      permissionScope.value === 'project'
        ? await fetchProjectInvitations(selectedItem.value.id)
        : await fetchConversationInvitations(selectedItem.value.id)
    permissionInvitations.value = data?.items || []
  } catch (error) {
    permissionInvitations.value = []
    modalError.value = error?.message || t('projects.common.load_permissions_failed')
  }
}

const openPermissionModal = async () => {
  const target = rowMenuTarget.value
  if (!target) return
  if (!canManageRow(target)) return
  closeRowMenu()
  selectedItem.value = target
  permissionScope.value = displayMode.value === 'project' ? 'project' : 'conversation'
  selectedScope.value = permissionScope.value
  permissionVisibility.value = String(target.visibility || 'private').toLowerCase()
  clearInviteLookupState({ clearInput: true })
  modalError.value = ''
  showPermissionModal.value = true
  await loadPermissionInvitations()
}

const submitPermissionVisibility = async () => {
  if (!selectedItem.value || modalBusy.value) return
  modalBusy.value = true
  modalError.value = ''
  debugLog('permission:visibility:start', {
    scope: permissionScope.value,
    id: selectedItem.value?.id,
    visibility: permissionVisibility.value,
  })
  try {
    if (permissionScope.value === 'project') {
      await updateProject(selectedItem.value.id, { visibility: permissionVisibility.value })
      if (activeProject.value?.id === selectedItem.value.id) {
        activeProject.value = { ...activeProject.value, visibility: permissionVisibility.value }
      }
      await loadProjects()
    } else {
      await updateConversationVisibility(selectedItem.value.id, { visibility: permissionVisibility.value })
      await reloadConversationRows()
    }
    await loadPermissionInvitations()
    return true
  } catch (error) {
    debugLog('permission:visibility:error', error)
    modalError.value = error?.message || t('projects.common.update_permissions_failed')
    return false
  } finally {
    modalBusy.value = false
  }
}

const addInvitation = async () => {
  if (!selectedItem.value || modalBusy.value) return
  const candidate = selectedInviteCandidate.value
  const selectedIdentifier = String(candidate?.username || '').trim()
  if (!selectedIdentifier || !canSubmitInvite.value) {
    modalError.value = t('projects.common.select_account_first')
    return
  }
  modalBusy.value = true
  modalError.value = ''
  debugLog('permission:invite:start', {
    scope: permissionScope.value,
    id: selectedItem.value?.id,
    identifier: selectedIdentifier,
  })
  try {
    if (permissionScope.value === 'project') {
      await createProjectInvitation(selectedItem.value.id, selectedIdentifier)
    } else {
      await createConversationInvitation(selectedItem.value.id, selectedIdentifier)
    }
    clearInviteLookupState({ clearInput: true })
    await loadPermissionInvitations()
  } catch (error) {
    debugLog('permission:invite:error', error)
    modalError.value = error?.message || t('projects.common.invite_failed')
  } finally {
    modalBusy.value = false
  }
}

const confirmPermissionModal = async () => {
  const success = await submitPermissionVisibility()
  if (success) {
    closeAllModals()
  }
}

const revokeInvitation = async (invitation) => {
  if (!selectedItem.value || !invitation?.id || modalBusy.value) return
  modalBusy.value = true
  modalError.value = ''
  debugLog('permission:revoke:start', {
    scope: permissionScope.value,
    id: selectedItem.value?.id,
    invitationId: invitation?.id,
  })
  try {
    if (permissionScope.value === 'project') {
      await deleteProjectInvitation(selectedItem.value.id, invitation.id)
    } else {
      await deleteConversationInvitation(selectedItem.value.id, invitation.id)
    }
    await loadPermissionInvitations()
  } catch (error) {
    debugLog('permission:revoke:error', error)
    modalError.value = error?.message || t('projects.common.remove_permission_failed')
  } finally {
    modalBusy.value = false
  }
}


const toggleRowMenu = (event, row) => {
  event.stopPropagation()
  const currentId = String(row.id)
  if (activeMenuId.value === currentId) {
    closeRowMenu()
    return
  }
  activeMenuId.value = currentId
}

const enterProject = async (project) => {
  listScope.value = 'all'
  activeProject.value = project
  mode.value = 'conversation'
  searchQuery.value = ''
  globalSearchConversations.value = []
  globalSearchConversationTotal.value = 0
  conversationPage.value = 1
  closeRowMenu()
  await loadConversations()
}

const leaveProject = async () => {
  const chatContext = returnToChatContext.value
  if (chatContext?.conversation_id) {
    await router.push({
      name: 'home',
      query: {
        conversation_id: chatContext.conversation_id,
        project_id: chatContext.project_id || '',
        project_label: chatContext.project_label || '',
      },
    })
    return
  }
  listScope.value = 'all'
  activeProject.value = null
  mode.value = 'project'
  searchQuery.value = ''
  globalSearchConversations.value = []
  globalSearchConversationTotal.value = 0
  closeRowMenu()
  await loadProjects()
}

const setPage = async (next) => {
  if (next < 1 || next > totalPages.value) return
  if (mode.value === 'project') {
    projectPage.value = next
  } else {
    conversationPage.value = next
  }
  await reloadCurrentList()
}

const handleRowClick = async (row) => {
  if (displayMode.value === 'project') {
    await enterProject(row)
    return
  }
  if (mode.value === 'conversation' && !isConversationOwner(row)) {
    return
  }
  await router.push({
    name: 'home',
    query: {
      conversation_id: row.id,
      project_id: row.project_id || activeProject.value?.id || '',
      project_label: activeProject.value?.name || row.project_name || row.project_label || '',
    },
  })
}

const handleNavClick = (item) => {
  if (item.id === 'permission') {
    handlePermissionNavClick()
    return
  }
  closePermissionMenu()
  activeNavId.value = item.id
  if (item.route) {
    const targetRoute = item.routeQuery
      ? { name: item.route, query: { ...item.routeQuery } }
      : { name: item.route }
    if (
      router.currentRoute.value.name !== item.route ||
      JSON.stringify(router.currentRoute.value.query || {}) !== JSON.stringify(targetRoute.query || {})
    ) {
      router.push(targetRoute)
    }
  }
}

const handleDocumentClick = (event) => {
  if (activeMenuId.value && !event.target.closest('[data-menu-root]')) {
    closeRowMenu()
  }
}

const handleDocumentKeydown = (event) => {
  if (event.key === 'Escape') {
    closeRowMenu()
  }
}

const routeProjectKey = ref('')
const returnToChatContext = ref(null)

const fallbackToProjectRoot = async () => {
  listScope.value = 'all'
  activeProject.value = null
  mode.value = 'project'
  conversationPage.value = 1
  conversations.value = []
  conversationTotal.value = 0
  await loadProjects()
}

const consumeRouteProjectQuery = async () => {
  if (route.name !== 'projects') return
  if (!isAuthenticated.value) return

  const scope = String(route.query.scope || '').trim().toLowerCase()
  if (scope === 'inbox') {
    if (routeProjectKey.value === 'scope:inbox') return
    routeProjectKey.value = 'scope:inbox'
    try {
      listScope.value = 'inbox'
      activeProject.value = null
      mode.value = 'project'
      projectPage.value = 1
      conversationPage.value = 1
      globalSearchConversations.value = []
      globalSearchConversationTotal.value = 0
      closeRowMenu()
      await loadProjects()
    } finally {
      routeProjectKey.value = ''
    }
    return
  }

  const projectId = String(route.query.project_id || '').trim()
  if (!projectId) {
    returnToChatContext.value = null
    if (listScope.value === 'inbox' && mode.value === 'project') {
      listScope.value = 'all'
      projectPage.value = 1
      await loadProjects()
    }
    return
  }
  if (routeProjectKey.value === projectId) return

  routeProjectKey.value = projectId
  try {
    const projectLabel = String(route.query.project_label || '').trim()
    const returnTo = String(route.query.return_to || '').trim().toLowerCase()
    const conversationId = String(route.query.conversation_id || '').trim()
    returnToChatContext.value =
      returnTo === 'chat' && conversationId
        ? {
            conversation_id: conversationId,
            project_id: projectId,
            project_label: projectLabel,
          }
        : null
    listScope.value = 'all'
    searchQuery.value = ''
    projectPage.value = 1
    conversationPage.value = 1
    globalSearchConversations.value = []
    globalSearchConversationTotal.value = 0
    mode.value = 'conversation'
    activeProject.value = {
      id: projectId,
      name: projectLabel || '',
      visibility: 'private',
      customer_profile: {},
    }
    closeRowMenu()

    const result = await loadConversations()
    if (!result?.ok) {
      await fallbackToProjectRoot()
    }
  } finally {
    const nextQuery = { ...route.query }
    delete nextQuery.project_id
    delete nextQuery.project_label
    delete nextQuery.return_to
    delete nextQuery.conversation_id
    await router.replace({ name: 'projects', query: nextQuery }).catch(() => {})
    routeProjectKey.value = ''
  }
}

const bootstrap = async () => {
  await loadProjects()
  await consumeRouteProjectQuery()
}

watch(searchQuery, () => {
  if (searchTimer.value) clearTimeout(searchTimer.value)
  searchTimer.value = setTimeout(async () => {
    if (mode.value === 'project') {
      projectPage.value = 1
    } else {
      conversationPage.value = 1
    }
    await reloadCurrentList()
  }, 260)
})

watch(inviteEmail, (value) => {
  const normalizedValue = String(value || '').trim().toLowerCase()
  if (
    selectedInviteCandidate.value &&
    String(selectedInviteCandidate.value.username || '').trim().toLowerCase() !== normalizedValue
  ) {
    selectedInviteCandidate.value = null
  }

  if (inviteLookupTimer.value) {
    clearTimeout(inviteLookupTimer.value)
    inviteLookupTimer.value = null
  }

  if (
    !showPermissionModal.value ||
    permissionVisibility.value !== 'private' ||
    normalizedValue.length < INVITE_LOOKUP_MIN_LENGTH
  ) {
    inviteSuggestions.value = []
    inviteLookupOpen.value = false
    inviteLookupBusy.value = false
    return
  }

  inviteLookupTimer.value = setTimeout(() => {
    loadInviteSuggestions(value)
  }, 240)
})

watch(permissionVisibility, (value) => {
  if (value !== 'private') {
    clearInviteLookupState({ clearInput: true })
  }
})

watch(
  isAuthenticated,
  async (authed) => {
    if (!authed) {
      router.push({ name: 'home', query: { redirect: '/projects' } })
      return
    }
    await bootstrap()
  },
  { immediate: true }
)

watch(
  () => route.query,
  () => {
    consumeRouteProjectQuery()
  },
  { deep: true, immediate: true }
)

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleDocumentKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleDocumentKeydown)
  if (searchTimer.value) clearTimeout(searchTimer.value)
  if (inviteLookupTimer.value) clearTimeout(inviteLookupTimer.value)
})
</script>

<template>
  <div class="app-shell" :class="{ 'is-sidebar-collapsed': isSidebarCollapsed }">
    <AppSidebar
      :logo-src="logoMain"
      :nav-items="navItems"
      :icon-images="iconImages"
      :arrow-icon-src="iconArrowIndicator"
      :active-nav-id="activeNavId"
      :side-menu="sideMenu"
      :side-menu-open="sideMenuOpen"
      :aria-label="t('projects.common.main_nav')"
      @logo-click="() => router.push({ name: 'home' })"
      @nav-click="handleNavClick"
    />

    <div class="main-stage project-stage">
      <AppTopBar
        :logo-src="logoMain"
        :is-compact-sidebar="isCompactSidebar"
        :is-sidebar-collapsed="isSidebarCollapsed"
        :hamburger-icon="glyphs.hamburger"
        :menu-aria-label="t('projects.common.toggle_menu')"
        :avatar-label="avatarLabel"
        :avatar-aria-label="t('projects.common.account_menu')"
        @toggle-sidebar="toggleSidebar"
        @logo-click="() => router.push({ name: 'home' })"
      >
        <template #search>
          <label v-if="!isTablet" class="search-field search-field--top">
            <span class="search-field__icon" v-html="glyphs.search" aria-hidden="true" />
            <input type="search" :placeholder="t('projects.common.search')" disabled />
          </label>
          <button v-else class="icon-button top-bar__search-button" type="button" :aria-label="t('projects.common.search')">
            <span v-html="glyphs.search" aria-hidden="true" />
          </button>
        </template>
      </AppTopBar>

      <main class="stage-canvas">
        <section class="project-page-header">
          <div class="project-page-header__left">
            <h1>{{ t('projects.common.projects') }}</h1>
            <div class="project-breadcrumb">
              <button
                v-if="activeProject"
                class="project-breadcrumb__back"
                type="button"
                @click="leaveProject"
              >
                <span v-html="glyphs.back" aria-hidden="true" />
                {{ t('projects.common.project') }}
              </button>
              <span v-if="activeProject" class="project-breadcrumb__separator">/</span>
              <span>{{ breadcrumbTitle }}</span>
            </div>
          </div>
          <button class="project-new-button" type="button" @click="openCreateModal">
            <span v-html="glyphs.plus" aria-hidden="true" />
            {{ t('projects.common.new_project') }}
          </button>
        </section>

        <section v-if="SHOW_PROJECT_PROFILE && mode === 'conversation' && activeProject" class="project-profile-card">
          <header class="project-profile-card__header">
            <h3>{{ t('projects.common.customer_profile') }}</h3>
            <span>{{ activeProject.visibility === 'public' ? t('projects.common.public') : t('projects.common.private') }}</span>
          </header>
          <div class="project-profile-card__grid">
            <div v-for="entry in profileRows" :key="entry.label" class="project-profile-card__row">
              <span>{{ entry.label }}</span>
              <strong>{{ entry.value || '-' }}</strong>
            </div>
            <div class="project-profile-card__row project-profile-card__row--full">
              <span>{{ t('projects.common.description') }}</span>
              <strong>{{ profileDescription }}</strong>
            </div>
          </div>
        </section>

        <section class="table-card" :class="tableModeClass">
          <header class="table-card__toolbar">
            <label class="search-field">
              <span class="search-field__icon" v-html="glyphs.search" aria-hidden="true" />
              <input
                v-model="searchQuery"
                type="search"
                :placeholder="tableSearchPlaceholder"
                autocomplete="off"
                autocorrect="off"
                autocapitalize="none"
                spellcheck="false"
              />
            </label>
            <div class="table-card__toolbar-meta">
              <span>{{ t('projects.common.total', { count: total }) }}</span>
            </div>
          </header>

          <div class="table-card__table-wrap">
            <div class="table-head">
              <span class="table-head__name">{{ t('projects.common.name') }}</span>
              <span class="table-head__owner">{{ t('projects.common.owner') }}</span>
              <span class="table-head__updated">{{ t('projects.common.last_updated') }}</span>
              <span class="table-head__actions" aria-hidden="true" />
            </div>

            <div v-if="loading" class="table-state">{{ t('projects.common.loading') }}</div>
            <div v-else-if="listError" class="table-state table-state--error">{{ listError }}</div>

            <template v-else-if="rows.length">
              <article
                v-for="row in rows"
                :key="row.id"
                class="table-row"
                :class="{
                  'table-row--clickable': true,
                  'table-row--readonly': mode === 'conversation' && !isConversationOwner(row),
                }"
                @click="handleRowClick(row)"
              >
                <div class="table-cell table-cell--name">
                  <img
                    v-if="displayMode === 'project'"
                    :src="iconFolder"
                    alt=""
                    class="table-cell__icon"
                    aria-hidden="true"
                  />
                  <img
                    v-else
                    :src="iconChatProject"
                    alt=""
                    class="table-cell__icon table-cell__icon--chat"
                    aria-hidden="true"
                  />
                  <div class="table-cell__name-wrap">
                    <strong>{{
                      displayMode === 'project' ? row.name : resolveConversationDisplayTitle(row)
                    }}</strong>
                    <small>
                      <template v-if="displayMode === 'project'">
                        {{ row.visibility === 'public' ? t('projects.common.public') : t('projects.common.private') }}
                        ・{{ t('projects.common.conversation_count', { count: row.conversation_count || 0 }) }}
                      </template>
                      <template v-else>
                        {{ row.visibility === 'public' ? t('projects.common.public') : t('projects.common.private') }}
                        <span v-if="mode === 'project' && row.project_name">・{{ row.project_name }}</span>
                        <span v-else-if="isInboxScope">・{{ t('projects.common.drafts') }}</span>
                        <span v-if="row.customer_id">・{{ t('projects.common.customer_id', { id: row.customer_id }) }}</span>
                      </template>
                    </small>
                  </div>
                </div>
                <div class="table-cell table-cell--owner">{{ row.owner || '-' }}</div>
                <div class="table-cell table-cell--updated">{{ formatDateTime(row.updated_at) }}</div>
                <div
                  v-if="canManageRow(row)"
                  class="table-cell table-cell--actions"
                >
                  <div class="menu-anchor" data-menu-root @click.stop>
                    <button
                      class="icon-button menu-toggle"
                      type="button"
                      :aria-label="t('projects.common.more')"
                      @click.stop="toggleRowMenu($event, row)"
                    >
                      <span v-html="glyphs.more" aria-hidden="true" />
                    </button>
                    <div
                      v-if="isRowMenuOpen(row.id)"
                      class="menu-popover"
                    >
                      <button
                        v-if="isInboxScope"
                        type="button"
                        class="menu-popover__item"
                        @click="openSelectFolderModal"
                      >
                        {{ t('projects.common.select_folder') }}
                      </button>
                      <button
                        v-else-if="mode !== 'conversation'"
                        type="button"
                        class="menu-popover__item"
                        @click="openNewConversationFromMenu"
                      >
                        {{ t('projects.common.new_conversation') }}
                      </button>
                      <button
                        type="button"
                        class="menu-popover__item"
                        @click="openPermissionModal"
                      >
                        {{ t('projects.common.permissions') }}
                      </button>
                      <button
                        type="button"
                        class="menu-popover__item"
                        @click="openRenameModal"
                      >
                        {{ t('projects.common.rename') }}
                      </button>
                      <button
                        type="button"
                        class="menu-popover__item is-danger"
                        @click="openDeleteModal"
                      >
                        {{ t('projects.common.delete_file') }}
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            </template>

            <div v-else class="table-empty">
              <img :src="emptyTableImage" alt="No data" />
              <p>{{ searchQuery.trim() ? t('projects.common.no_match') : t('projects.common.empty') }}</p>
            </div>
          </div>

          <footer class="table-card__footer">
            <div class="table-card__page-size">{{ t('projects.common.per_page', { count: pageSize }) }}</div>
            <div class="table-card__range">{{ rangeLabel }}</div>
            <div class="table-card__pager">
              <button type="button" :disabled="currentPage <= 1" @click="setPage(currentPage - 1)">{{ t('projects.common.prev') }}</button>
              <button type="button" :disabled="currentPage >= totalPages" @click="setPage(currentPage + 1)">{{ t('projects.common.next') }}</button>
            </div>
          </footer>
        </section>
      </main>
    </div>
  </div>

  <div v-if="showCreateModal" class="modal-overlay" @click.self="closeAllModals">
    <article class="modal-card modal-card--create">
      <header class="modal-card__header">
        <h2>{{ t('projects.common.new_project') }}</h2>
        <button type="button" @click="closeAllModals">×</button>
      </header>
      <div class="modal-card__body">
        <label class="form-field">
          <span>{{ t('projects.common.customer_name') }}</span>
          <input v-model="projectForm.name" type="text" :placeholder="t('projects.common.example_customer')" />
        </label>

        <label class="form-field">
          <span>{{ t('projects.common.visibility') }}</span>
          <select v-model="projectForm.visibility">
            <option value="private">{{ t('projects.common.private') }}</option>
            <option value="public">{{ t('projects.common.public') }}</option>
          </select>
        </label>

        <div class="form-grid">
          <label class="form-field">
            <span>{{ t('projects.common.type') }}</span>
            <select v-model="projectForm.customerType">
              <option value="">{{ t('projects.common.unset') }}</option>
              <option v-for="type in customerTypeOptions" :key="type" :value="type">{{ type }}</option>
            </select>
          </label>
          <label class="form-field">
            <span>{{ t('projects.common.trade_count') }}</span>
            <input v-model="projectForm.tradeCount" type="number" min="0" placeholder="0" />
          </label>
          <label class="form-field">
            <span>{{ t('projects.common.last_trade_at') }}</span>
            <input v-model="projectForm.lastTradeAt" type="datetime-local" />
          </label>
          <label class="form-field">
            <span>{{ t('projects.common.avg_unit_price') }}</span>
            <input v-model="projectForm.avgUnitPrice" type="number" min="0" placeholder="1800" />
          </label>
          <label class="form-field">
            <span>{{ t('projects.common.region') }}</span>
            <input v-model="projectForm.region" type="text" placeholder="Hiking Gear" />
          </label>
          <label class="form-field form-field--switch">
            <span>{{ t('projects.common.has_wine_cabinet') }}</span>
            <input v-model="projectForm.hasWineCabinet" type="checkbox" />
          </label>
        </div>

        <label class="form-field">
          <span>{{ t('projects.common.description') }}</span>
          <textarea v-model="projectForm.preferenceNote" rows="4" :placeholder="t('projects.common.preference_placeholder')" />
        </label>

        <p v-if="modalError" class="modal-error">{{ modalError }}</p>
      </div>
      <footer class="modal-card__footer">
        <button type="button" class="label-button label-button--outline" @click="closeAllModals">{{ t('projects.common.cancel') }}</button>
        <button type="button" class="label-button label-button--primary" :disabled="modalBusy" @click="submitCreateProject">
          {{ modalBusy ? t('projects.common.processing') : t('projects.common.new_project') }}
        </button>
      </footer>
    </article>
  </div>

  <div v-if="showRenameModal" class="modal-overlay" @click.self="closeAllModals">
    <article class="modal-card modal-card--rename">
      <header class="modal-card__header modal-card__header--figma">
        <h2>{{ t('projects.common.rename') }}</h2>
        <button type="button" @click="closeAllModals">×</button>
      </header>
      <div class="modal-card__body modal-card__body--rename">
        <label class="form-field form-field--required">
          <span>{{ t('projects.common.name') }}</span>
          <input v-model="renameValue" type="text" />
        </label>
        <p v-if="modalError" class="modal-error">{{ modalError }}</p>
      </div>
      <footer class="modal-card__footer">
        <button type="button" class="label-button label-button--outline" @click="closeAllModals">{{ t('projects.common.cancel') }}</button>
        <button type="button" class="label-button label-button--primary" :disabled="modalBusy" @click="submitRename">
          {{ modalBusy ? t('projects.common.processing') : t('projects.common.confirm') }}
        </button>
      </footer>
    </article>
  </div>

  <div v-if="showDeleteModal" class="modal-overlay" @click.self="closeAllModals">
    <article class="modal-card modal-card--sm">
      <header class="modal-card__header">
        <h2>{{ selectedScope === 'project' ? t('projects.common.delete_project') : t('projects.common.delete_conversation') }}</h2>
        <button type="button" @click="closeAllModals">×</button>
      </header>
      <div class="modal-card__body">
        <p class="modal-copy">
          {{ selectedScope === 'project' ? t('projects.common.delete_project_copy') : t('projects.common.delete_conversation_copy') }}
        </p>
        <p v-if="modalError" class="modal-error">{{ modalError }}</p>
      </div>
      <footer class="modal-card__footer">
        <button type="button" class="label-button label-button--outline" @click="closeAllModals">{{ t('projects.common.cancel') }}</button>
        <button type="button" class="label-button label-button--danger" :disabled="modalBusy" @click="submitDelete">
          {{ modalBusy ? t('projects.common.processing') : t('projects.common.confirm_delete') }}
        </button>
      </footer>
    </article>
  </div>

  <div v-if="showPermissionModal" class="modal-overlay" @click.self="closeAllModals">
    <article class="modal-card modal-card--permission">
      <header class="modal-card__header modal-card__header--figma">
        <h2>{{ t('projects.common.permissions') }}</h2>
        <button type="button" @click="closeAllModals">×</button>
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
            <span class="required-star">*</span> {{ t('projects.common.visibility_setting') }}
          </p>
          <div class="visibility-switch">
            <label>
              <input v-model="permissionVisibility" type="radio" value="private" />
              {{ t('projects.common.private') }}
            </label>
            <label>
              <input v-model="permissionVisibility" type="radio" value="public" />
              {{ t('projects.common.public') }}
            </label>
          </div>
        </div>

        <template v-if="permissionVisibility === 'private'">
          <div class="permission-section">
            <p class="permission-section__label">{{ t('projects.common.select_account') }}</p>
            <div class="invite-inline">
              <div class="invite-lookup">
                <input
                  v-model="inviteEmail"
                  type="text"
                  autocomplete="off"
                  :placeholder="t('projects.common.search_account')"
                  @focus="handleInviteInputFocus"
                  @keydown.enter.prevent="addInvitation"
                />
                <div v-if="inviteLookupOpen" class="invite-suggestions">
                  <button
                    v-for="candidate in inviteSuggestions"
                    :key="candidate.id"
                    type="button"
                    class="invite-suggestion"
                    @click="selectInviteCandidate(candidate)"
                  >
                    <strong>{{ candidate.label }}</strong>
                    <small>{{ candidate.username }}</small>
                  </button>
                  <p v-if="inviteLookupBusy" class="invite-suggestion-empty">{{ t('projects.common.searching') }}</p>
                  <p
                    v-else-if="inviteEmail.trim().length >= INVITE_LOOKUP_MIN_LENGTH && !inviteSuggestions.length"
                    class="invite-suggestion-empty"
                  >
                    {{ t('projects.common.no_account') }}
                  </p>
                </div>
              </div>
              <button
                type="button"
                class="label-button label-button--outline"
                :disabled="!canSubmitInvite"
                @click="addInvitation"
              >
                {{ t('projects.common.add') }}
              </button>
            </div>
          </div>
          <div class="permission-section">
            <p class="permission-section__label">{{ t('projects.common.authorized_users') }}</p>
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
                    @click="revokeInvitation({ id: access.id })"
                  >
                    ×
                  </button>
                </div>
              </article>
              <p v-if="!permissionAccessRows.length" class="invite-empty">{{ t('projects.common.no_authorized_users') }}</p>
            </div>
          </div>
        </template>

        <p v-else class="modal-copy">{{ t('projects.common.public_permission_copy') }}</p>

        <p v-if="modalError" class="modal-error">{{ modalError }}</p>
      </div>
      <footer class="modal-card__footer modal-card__footer--figma">
        <button type="button" class="label-button label-button--outline" @click="closeAllModals">{{ t('projects.common.cancel') }}</button>
        <button type="button" class="label-button label-button--primary" :disabled="modalBusy" @click="confirmPermissionModal">
          {{ modalBusy ? t('projects.common.processing') : t('projects.common.confirm') }}
        </button>
      </footer>
    </article>
  </div>

  <div v-if="showSelectFolderModal" class="modal-overlay" @click.self="closeAllModals">
    <article class="modal-card modal-card--select-folder">
      <header class="modal-card__header modal-card__header--figma">
        <h2>{{ t('projects.common.select_folder') }}</h2>
        <button type="button" @click="closeAllModals">×</button>
      </header>
      <div class="modal-card__body modal-card__body--select-folder">
        <p class="modal-copy">{{ t('projects.common.move_folder_copy') }}</p>
        <label class="form-field form-field--compact">
          <span>{{ t('projects.common.search_folder_label') }}</span>
          <input
            v-model="folderPickerQuery"
            type="search"
            :placeholder="t('projects.common.search_folder_placeholder')"
          />
        </label>
        <div class="folder-picker-list">
          <div v-if="isFolderPickerLoading" class="folder-picker-state">{{ t('projects.common.loading') }}</div>
          <label
            v-for="item in filteredFolderPickerItems"
            :key="item.id"
            class="folder-picker-item"
          >
            <input v-model="folderPickerSelectedId" type="radio" :value="item.id" />
            <div class="folder-picker-item__text">
              <strong>{{ item.name }}</strong>
              <small>{{ item.visibility === 'public' ? t('projects.common.public') : t('projects.common.private') }}</small>
            </div>
          </label>
          <div
            v-if="!isFolderPickerLoading && !filteredFolderPickerItems.length"
            class="folder-picker-state"
          >
            {{ t('projects.common.no_selectable_folder') }}
          </div>
        </div>
        <p v-if="folderPickerError" class="modal-error">{{ folderPickerError }}</p>
      </div>
      <footer class="modal-card__footer modal-card__footer--figma">
        <button type="button" class="label-button label-button--outline" @click="closeAllModals">{{ t('projects.common.cancel') }}</button>
        <button
          type="button"
          class="label-button label-button--primary"
          :disabled="isFolderPickerSaving || !folderPickerSelectedId"
          @click="submitSelectFolder"
        >
          {{ isFolderPickerSaving ? t('projects.common.processing') : t('projects.common.confirm') }}
        </button>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: #f4f6f8;
}

.main-stage {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  margin-left: 88px;
}

.app-shell.is-sidebar-collapsed .main-stage {
  margin-left: 0;
}

.stage-canvas {
  width: min(1440px, calc(100% - 32px));
  margin: 0 auto;
  padding: 32px 0 40px;
}

.project-page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.project-page-header__left h1 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 36px;
  font-weight: 700;
}

.project-breadcrumb {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #637381;
  font-size: 14px;
}

.project-breadcrumb__back {
  border: none;
  background: transparent;
  color: #637381;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  cursor: pointer;
}

.project-new-button {
  height: 36px;
  border: none;
  border-radius: 8px;
  padding: 0 16px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #55b77f;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}

.project-new-button:hover {
  background: #7b0000;
}

.project-pending-strip {
  background: #ffffff;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
  padding: 14px 16px;
  margin-bottom: 16px;
}

.project-pending-strip > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.project-pending-strip > header h2 {
  margin: 0;
  font-size: 16px;
  color: #212b36;
}

.project-pending-strip__list {
  display: grid;
  gap: 10px;
}

.pending-item {
  border: 1px solid rgba(145, 158, 171, 0.28);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.pending-item__meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}

.pending-item__meta strong {
  color: #212b36;
  font-size: 13px;
}

.pending-item__meta span {
  color: #637381;
  font-size: 13px;
  word-break: break-word;
}

.pending-item__actions {
  display: inline-flex;
  gap: 8px;
}

.pending-item__actions button {
  height: 30px;
  border-radius: 8px;
  border: 1px solid #d6dce2;
  background: #fff;
  padding: 0 12px;
  cursor: pointer;
}

.pending-item__actions .is-primary {
  border-color: #55b77f;
  background: #55b77f;
  color: #fff;
}

.project-profile-card {
  margin-bottom: 16px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid rgba(145, 158, 171, 0.24);
  box-shadow: 0 8px 24px rgba(145, 158, 171, 0.12);
  padding: 16px;
}

.project-profile-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.project-profile-card__header h3 {
  margin: 0;
  color: #212b36;
  font-size: 16px;
}

.project-profile-card__header span {
  font-size: 13px;
  color: #637381;
}

.project-profile-card__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.project-profile-card__row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  background: #f9fafb;
}

.project-profile-card__row span {
  color: #637381;
  font-size: 12px;
}

.project-profile-card__row strong {
  color: #212b36;
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}

.project-profile-card__row--full {
  grid-column: 1 / -1;
}

.table-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 6px 14px rgba(145, 158, 171, 0.1), 0 1px 2px rgba(145, 158, 171, 0.2);
  overflow: hidden;
  border: 1px solid rgba(145, 158, 171, 0.24);
}

.table-card__toolbar {
  min-height: 80px;
  padding: 20px 24px;
  background: #ffffff;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.table-card__toolbar-meta {
  color: #637381;
  font-size: 14px;
}

.search-field {
  position: relative;
  width: min(360px, 100%);
}

.search-field--top {
  width: 420px;
}

.search-field__icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.search-field input {
  width: 100%;
  height: 40px;
  border: 1px solid #dce2e8;
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  padding: 0 12px 0 38px;
  color: #212b36;
  font-size: 14px;
}

.table-card__table-wrap {
  min-height: 480px;
}

.table-head,
.table-row {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) 140px 220px 56px;
  column-gap: 16px;
  align-items: center;
  padding: 0 24px;
}

.table-head {
  height: 56px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  background: #f9fafb;
  color: #637381;
  font-size: 13px;
  font-weight: 600;
}

.table-row {
  min-height: 72px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  background: #fff;
}

.table-row--clickable {
  cursor: pointer;
}

.table-row--clickable:hover {
  background: #fbfcfd;
}

.table-row--readonly {
  cursor: default;
}

.table-row--readonly:hover {
  background: #fff;
}

.table-cell {
  min-width: 0;
  color: #212b36;
  font-size: 14px;
}

.table-cell--name {
  display: flex;
  align-items: center;
  gap: 12px;
}

.table-cell__icon {
  width: 20px;
  height: 20px;
  flex: none;
}

.table-cell__icon--chat {
  width: 22px;
  height: 22px;
}

.table-cell__name-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.table-cell__name-wrap strong {
  color: #212b36;
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-cell__name-wrap small {
  color: #637381;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-cell--actions {
  display: flex;
  justify-content: flex-end;
  position: relative;
}

.menu-anchor {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.menu-toggle {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
}

.menu-toggle:hover {
  border-color: rgba(145, 158, 171, 0.32);
  background: #f4f6f8;
}

.menu-popover {
  position: absolute;
  top: 38px;
  right: 0;
  width: 188px;
  border: 1px solid rgba(145, 158, 171, 0.3);
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 7px 18px rgba(16, 24, 40, 0.13);
  padding: 6px;
  display: grid;
  gap: 4px;
  z-index: 30;
}

.menu-popover__item {
  border: none;
  border-radius: 8px;
  background: #fff;
  color: #212b36;
  font-size: 14px;
  text-align: left;
  padding: 8px 10px;
  cursor: pointer;
}

.menu-popover__item:hover {
  background: #f4f6f8;
}

.menu-popover__item.is-danger {
  color: #b71d18;
}

.table-state,
.table-empty {
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  color: #637381;
  font-size: 14px;
  padding: 24px;
}

.table-state--error {
  color: #b71d18;
}

.table-empty img {
  width: 220px;
  max-width: 100%;
  opacity: 0.85;
}

.table-card__footer {
  min-height: 58px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  color: #637381;
  font-size: 13px;
}

.table-card__pager {
  display: inline-flex;
  gap: 8px;
}

.table-card__pager button {
  height: 30px;
  border-radius: 8px;
  border: 1px solid #dce2e8;
  background: #fff;
  color: #212b36;
  padding: 0 12px;
  cursor: pointer;
}

.table-card__pager button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(9, 23, 40, 0.38);
  display: grid;
  place-items: center;
  padding: 24px;
}

.modal-card {
  width: min(760px, 100%);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(16, 24, 40, 0.18);
  overflow: hidden;
}

.modal-card--create {
  width: min(760px, 100%);
}

.modal-card--permission {
  width: min(624px, 100%);
}

.modal-card--rename {
  width: min(1024px, 100%);
}

.modal-card--sm {
  width: min(480px, 100%);
}

.modal-card--select-folder {
  width: min(640px, 100%);
}

.modal-card__header {
  height: 64px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
  margin-bottom: 0;
}

.modal-card__header h2 {
  margin: 0;
  color: #212b36;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

.modal-card__header button {
  border: none;
  background: transparent;
  color: #637381;
  font-size: 32px;
  line-height: 1;
  cursor: pointer;
}

.modal-card__header--figma {
  height: 76px;
  padding: 0 24px;
  margin-bottom: 0;
}

.modal-card__header--figma h2 {
  font-size: 24px;
  line-height: 1.3;
}

.modal-card__body {
  padding: 20px;
  display: grid;
  gap: 12px;
  max-height: 70vh;
  overflow: auto;
}

.modal-card__body--rename {
  padding: 28px 44px 44px;
  min-height: 176px;
}

.modal-card__body--permission {
  padding: 0 24px 20px;
  gap: 18px;
}

.modal-card__body--select-folder {
  padding: 20px 24px 24px;
  gap: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.form-field {
  display: grid;
  gap: 6px;
}

.form-field span {
  color: #637381;
  font-size: 13px;
}

.form-field--required span::before {
  content: '*';
  color: #ff5630;
  margin-right: 4px;
}

.form-field--compact input {
  min-height: 44px;
}

.form-field input,
.form-field select,
.form-field textarea {
  width: 100%;
  min-height: 40px;
  border: 1px solid #d7dee5;
  border-radius: var(--ys-control-radius, 6px);
  padding: 8px 10px;
  font-size: 14px;
  color: #212b36;
  background: #fff;
}

.modal-card--rename .form-field input {
  min-height: 56px;
  border: 2px solid #c4cdd5;
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 20px;
  font-size: 16px;
}

.form-field textarea {
  min-height: 90px;
  resize: vertical;
}

.form-field--switch {
  align-content: end;
}

.form-field--switch input {
  width: 18px;
  min-height: 18px;
}

.modal-error {
  margin: 0;
  color: #b71d18;
  font-size: 14px;
}

.modal-copy {
  margin: 0;
  color: #637381;
  font-size: 15px;
  line-height: 1.7;
}

.modal-card__footer {
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  padding: 12px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.modal-card__footer--figma {
  padding: 16px 24px;
}

.label-button {
  height: 36px;
  border-radius: 8px;
  padding: 0 16px;
  border: 1px solid transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
}

.modal-card--rename .label-button,
.modal-card--permission .label-button {
  height: 46px;
  border-radius: 14px;
  padding: 0 24px;
  font-size: 16px;
}

.label-button--outline {
  background: #fff;
  border-color: #c4cdd5;
  color: #212b36;
}

.label-button--primary {
  background: #55b77f;
  border-color: #55b77f;
  color: #fff;
}

.label-button--danger {
  background: #de3618;
  border-color: #de3618;
  color: #fff;
}

.permission-target {
  margin: 16px -24px 0;
  min-height: 64px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f4f6f8;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.permission-target__icon {
  width: 24px;
  height: 24px;
  display: block;
  object-fit: contain;
}

.permission-target strong {
  margin: 0;
  color: #637381;
  font-size: 20px;
  font-weight: 700;
}

.permission-section {
  display: grid;
  gap: 10px;
}

.permission-section__label {
  margin: 0;
  color: #637381;
  font-size: 16px;
  font-weight: 700;
}

.required-star {
  color: #ff5630;
}

.visibility-switch {
  display: flex;
  align-items: center;
  gap: 34px;
}

.visibility-switch label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #212b36;
  font-size: 16px;
  font-weight: 700;
}

.visibility-switch input[type='radio'] {
  width: 24px;
  height: 24px;
  accent-color: #55b77f;
}

.invite-inline {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
}

.invite-lookup {
  position: relative;
}

.invite-inline input {
  width: 100%;
  min-height: 52px;
  border: 1px solid #c4cdd5;
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 12px;
  font-size: 16px;
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
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.1);
  overflow: hidden;
}

.invite-suggestion {
  border: none;
  background: #fff;
  padding: 12px;
  text-align: left;
  display: grid;
  gap: 2px;
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
  font-size: 13px;
}

.invite-suggestion-empty {
  margin: 0;
  padding: 12px;
}

.invite-inline .label-button {
  min-width: 102px;
  font-size: 16px;
  padding: 0 24px;
}

.invite-list {
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  display: grid;
  gap: 0;
}

.invite-item {
  min-height: 64px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.invite-item__identity {
  display: flex;
  align-items: center;
  gap: 10px;
}

.invite-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #006c4f;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}

.invite-item strong {
  color: #212b36;
  font-size: 16px;
  font-weight: 700;
}

.invite-item small {
  color: #637381;
  font-size: 14px;
  font-weight: 700;
}

.invite-item__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.invite-remove {
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: #637381;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.invite-remove:hover {
  background: #475467;
}

.invite-empty {
  margin: 16px 0;
  text-align: left;
  color: #919eab;
  font-size: 14px;
}

.folder-picker-list {
  max-height: 280px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: 12px;
  overflow: auto;
  background: #fff;
}

.folder-picker-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 56px;
  padding: 0 14px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.2);
}

.folder-picker-item:last-of-type {
  border-bottom: none;
}

.folder-picker-item input[type='radio'] {
  width: 18px;
  height: 18px;
  accent-color: #55b77f;
}

.folder-picker-item__text {
  display: grid;
  gap: 2px;
}

.folder-picker-item__text strong {
  color: #212b36;
  font-size: 15px;
  font-weight: 700;
}

.folder-picker-item__text small {
  color: #637381;
  font-size: 12px;
}

.folder-picker-state {
  min-height: 120px;
  display: grid;
  place-items: center;
  color: #637381;
  font-size: 14px;
}

@media (max-width: 1439px) {
  .stage-canvas {
    width: calc(100% - 24px);
    padding-top: 24px;
  }

  .table-head,
  .table-row {
    grid-template-columns: minmax(320px, 1fr) 120px 180px 56px;
  }
}

@media (max-width: 1199px) {
  .project-profile-card__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .table-card__toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .search-field {
    width: 100%;
  }

  .table-head,
  .table-row {
    grid-template-columns: minmax(260px, 1fr) 120px 150px 56px;
  }
}

@media (max-width: 991px) {
  .main-stage {
    margin-left: 0;
  }

  .project-page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .project-new-button {
    align-self: flex-start;
  }

  .table-head {
    display: none;
  }

  .table-row {
    grid-template-columns: 1fr 40px;
    row-gap: 4px;
    padding: 12px 14px;
    min-height: 96px;
  }

  .table-cell--name {
    grid-column: 1 / 2;
  }

  .table-cell--owner,
  .table-cell--updated {
    grid-column: 1 / 2;
    font-size: 12px;
    color: #637381;
  }

  .table-cell--actions {
    grid-column: 2 / 3;
    grid-row: 1 / span 3;
    align-self: start;
  }

  .table-card__footer {
    flex-wrap: wrap;
    gap: 8px;
  }

  .project-profile-card__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .stage-canvas {
    width: calc(100% - 16px);
    padding-top: 16px;
  }

  .modal-overlay {
    padding: 12px;
  }

  .modal-card__header h2 {
    font-size: 22px;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .pending-item {
    flex-direction: column;
    align-items: flex-start;
  }

  .pending-item__actions {
    width: 100%;
  }
}
</style>



