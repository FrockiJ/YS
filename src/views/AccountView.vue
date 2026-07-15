<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import logoMain from '../assets/ysLogo_transparent.png'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { useAuth } from '../composables/useAuth'
import { usePasswordUi } from '../composables/usePasswordUi'
import { useSystemBrand } from '../composables/useSystemBrand'
import {
  createProject,
  createRole,
  createUserAccount,
  deleteKnowledgeRagTable,
  fetchProjects,
  fetchKnowledgeCompanyProfile,
  fetchKnowledgeExternalSites,
  fetchKnowledgeRagTables,
  deleteRole,
  deleteUserAccount,
  importKnowledgeRagTable,
  ingestKnowledgeExternalSite,
  listRoles,
  listUsers,
  saveKnowledgeCompanyProfile,
  saveKnowledgeExternalSite,
  sendSetupPasswordEmail,
  updateRole,
  updateUserAccount,
} from '../services/ysApi'
import {
  PERMISSIONS,
  hasPermission,
  canAccessPermissionModule,
  canAccessRolesSection,
  canAccessUsersSection,
  canWriteUsers,
  getFirstAllowedRoute,
  normalizePermissionCodes,
  resolveAccessibleAccountSection,
} from '../utils/accessControl'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const { isAuthenticated, avatarLabel, userProfile } = useAuth()
const { openChangePasswordModal } = usePasswordUi()
const { loadSystemBrand } = useSystemBrand()

const PAGE_SIZE = 10
const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const TABLET_BREAKPOINT = 960
const SECTION_ROLES = 'roles'
const SECTION_USERS = 'users'
const SECTION_SETTINGS = 'settings'
const SETTINGS_PANEL_PASSWORD = 'password'
const VISIBLE_ROLE_CODES = new Set([
  PERMISSIONS.chat,
  PERMISSIONS.projects,
  PERMISSIONS.labels,
  PERMISSIONS.files,
  PERMISSIONS.rolesManage,
  PERMISSIONS.usersRead,
  PERMISSIONS.usersWrite,
  PERMISSIONS.settings,
])

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7A879C" stroke-width="2"/><path d="M12.5 12.5L16 16" stroke="#7A879C" stroke-width="2" stroke-linecap="round"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#0D3357" stroke-width="2" stroke-linecap="round"/></svg>',
  plus:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 3.333V12.667M3.333 8H12.667" stroke="#ffffff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  chevron:
    '<svg width="12" height="8" viewBox="0 0 12 8" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 1.5L6 6L10.5 1.5" stroke="#637381" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  close:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M5.75 5.75L14.25 14.25M14.25 5.75L5.75 14.25" stroke="#637381" stroke-width="1.8" stroke-linecap="round"/></svg>',
  trash:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M6.75 4.5H11.25M4.5 6H13.5M12.75 6L12.2449 12.5662C12.1973 13.1847 11.6817 13.6625 11.0613 13.6625H6.93867C6.31826 13.6625 5.8027 13.1847 5.75513 12.5662L5.25 6M7.5 8.25V11.25M10.5 8.25V11.25" stroke="#FF5A3D" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}

const iconImages = PRIMARY_NAV_ICON_IMAGES

const sectionLabelMap = computed(() => ({
  [SECTION_ROLES]: t('account.sections.roles'),
  [SECTION_USERS]: t('account.sections.users'),
  [SECTION_SETTINGS]: t('account.sections.settings'),
}))

const rolePermissionGroups = computed(() => [
  { id: 'chat', label: t('account.permissions.chat'), codes: [PERMISSIONS.chat] },
  { id: 'projects', label: t('account.permissions.projects'), codes: [PERMISSIONS.projects] },
  { id: 'labels', label: t('account.permissions.labels'), codes: [PERMISSIONS.labels] },
  { id: 'files', label: t('account.permissions.files'), codes: [PERMISSIONS.files] },
  {
    id: 'account',
    label: t('account.permissions.account'),
    children: [
      { id: 'roles', label: t('account.permissions.roles'), codes: [PERMISSIONS.rolesManage] },
      {
        id: 'users',
        label: t('account.permissions.users'),
        codes: [PERMISSIONS.usersRead, PERMISSIONS.usersWrite],
      },
    ],
  },
  { id: 'settings', label: t('account.permissions.settings'), codes: [PERMISSIONS.settings] },
])

const stageWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1440)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isTablet = computed(() => stageWidth.value <= TABLET_BREAKPOINT)
const isSidebarCollapsed = ref(stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const activeNavId = ref('permission')

const roleRecords = ref([])
const roleSearchQuery = ref('')
const rolePage = ref(1)
const roleLoading = ref(false)
const roleError = ref('')

const userRecords = ref([])
const userSearchQuery = ref('')
const userPage = ref(1)
const userLoading = ref(false)
const userError = ref('')

const SETTINGS_FETCH_PAGE_SIZE = 100
const SETTINGS_PAGE_SIZE = 10
const SETTINGS_TAB_PENDING = 'pending'
const SETTINGS_TAB_PROCESSED = 'processed'
const KNOWLEDGE_TAB_RAG = 'rag'
const KNOWLEDGE_TAB_PROFILE = 'profile'
const KNOWLEDGE_TAB_SITES = 'sites'

const settingsProjectRecords = ref([])
const settingsProjectLoading = ref(false)
const settingsProjectError = ref('')
const settingsSearchQuery = ref('')
const settingsActiveTab = ref(SETTINGS_TAB_PENDING)
const settingsPage = ref(1)
const showSettingsCreateProjectModal = ref(false)
const settingsProjectSubmitting = ref(false)
const settingsProjectModalError = ref('')
const settingsProjectForm = ref({
  name: '',
  visibility: 'private',
  customerType: '',
  tradeCount: '',
  lastTradeAt: '',
  avgUnitPrice: '',
  preferenceNote: '',
  region: '',
})

const knowledgeActiveTab = ref(KNOWLEDGE_TAB_RAG)
const knowledgeTables = ref([])
const knowledgeTablesLoading = ref(false)
const knowledgeTablesError = ref('')
const knowledgeImporting = ref(false)
const knowledgeImportStatus = ref('')
const knowledgeImportError = ref('')
const knowledgeRagForm = ref({
  tableName: '',
  sourceName: '',
  language: 'zh-TW',
  tags: '',
  file: null,
})
const companyProfileLoading = ref(false)
const companyProfileSaving = ref(false)
const companyProfileStatus = ref('')
const companyProfileError = ref('')
const companyProfileForm = ref({
  company_name: '',
  industry: '',
  product_categories: '',
  tone: '',
  service_scope: '',
  contact_info: '',
  faq: '',
  policies: '',
  language: 'zh-TW',
})
const externalSites = ref([])
const externalSitesLoading = ref(false)
const externalSitesSaving = ref(false)
const externalSitesIngestingId = ref(null)
const externalSitesStatus = ref('')
const externalSitesError = ref('')
const externalSiteForm = ref({
  url: '',
  name: '',
  category: '',
  language: 'zh-TW',
  trust_level: 'approved',
  enabled: true,
})

const activeModal = ref(null)
const modalBackTarget = ref(null)
const selectedRoleId = ref(null)
const selectedUserId = ref(null)
const roleFormError = ref('')
const userFormError = ref('')
const userSetupStatus = ref('')
const roleSubmitting = ref(false)
const userSubmitting = ref(false)
const setupEmailSubmitting = ref(false)
const roleStatusUpdatingId = ref(null)
const userStatusUpdatingId = ref(null)

const defaultRoleForm = () => ({
  name: '',
  isActive: true,
  conversationVisibility: 'private',
  permissionCodes: [],
  hiddenPermissionCodes: [],
})

const defaultUserForm = () => ({
  name: '',
  username: '',
  email: '',
  password: '',
  role: '',
  isActive: true,
})

const defaultSettingsProjectForm = () => ({
  name: '',
  visibility: 'private',
  customerType: '',
  tradeCount: '',
  lastTradeAt: '',
  avgUnitPrice: '',
  preferenceNote: '',
  region: '',
})

const customerTypeOptions = ['VIP', 'B2B', 'F&B']

const roleForm = ref(defaultRoleForm())
const userForm = ref(defaultUserForm())

const canViewRoles = computed(() => canAccessRolesSection(userProfile.value))
const canViewUsers = computed(() => canAccessUsersSection(userProfile.value))
const canManageUsers = computed(() => canWriteUsers(userProfile.value))
const canViewPermissionModule = computed(() => canAccessPermissionModule(userProfile.value))
const canViewSettings = computed(() => hasPermission(userProfile.value, PERMISSIONS.settings))

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'account.nav'))
const knowledgeTabs = computed(() => [
  { id: KNOWLEDGE_TAB_RAG, label: t('account.knowledge.tabs.rag_tables') },
  { id: KNOWLEDGE_TAB_PROFILE, label: t('account.knowledge.tabs.company_profile') },
  { id: KNOWLEDGE_TAB_SITES, label: t('account.knowledge.tabs.external_sites') },
])

const normalizeSettingsProjectRecord = (project) => ({
  id: project.id,
  name: String(project?.name || '').trim() || t('account.settings_stage.unnamed_project'),
  updatedAt: formatDateTime(project?.updated_at || project?.created_at),
  updatedAtRaw: project?.updated_at || project?.created_at || '',
  conversationCount: Number(project?.conversation_count || 0),
  visibility: String(project?.visibility || 'private'),
  owner: String(project?.owner || ''),
  createdAt: project?.created_at || '',
})
const settingsSummaryText = computed(() =>
  t('account.settings_stage.summary', { count: settingsProjectRecords.value.length })
)
const sortedSettingsProjects = computed(() => {
  return [...settingsProjectRecords.value].sort((left, right) =>
    String(right.updatedAtRaw || '').localeCompare(String(left.updatedAtRaw || ''))
  )
})
const splitSettingsProjectGroups = computed(() => {
  const pending = []
  const processed = []

  sortedSettingsProjects.value.forEach((project) => {
    // DEV fallback: there is no explicit workflow status yet, so projects with
    // at most one conversation are treated as pending and the rest as processed.
    if (project.conversationCount <= 1) {
      pending.push(project)
      return
    }
    processed.push(project)
  })

  return { pending, processed }
})
const activeSettingsItems = computed(() => {
  const base =
    settingsActiveTab.value === SETTINGS_TAB_PROCESSED
      ? splitSettingsProjectGroups.value.processed
      : splitSettingsProjectGroups.value.pending
  const query = settingsSearchQuery.value.trim().toLowerCase()
  if (!query) return base
  return base.filter((project) => project.name.toLowerCase().includes(query))
})
const settingsTotalPages = computed(() =>
  Math.max(1, Math.ceil(activeSettingsItems.value.length / SETTINGS_PAGE_SIZE))
)
const paginatedSettingsItems = computed(() => {
  const start = (settingsPage.value - 1) * SETTINGS_PAGE_SIZE
  return activeSettingsItems.value.slice(start, start + SETTINGS_PAGE_SIZE)
})
const settingsRangeLabel = computed(() => {
  if (!activeSettingsItems.value.length || !paginatedSettingsItems.value.length) {
    return '0-0 / 0'
  }
  const start = (settingsPage.value - 1) * SETTINGS_PAGE_SIZE + 1
  const end = start + paginatedSettingsItems.value.length - 1
  return `${start}-${end} / ${activeSettingsItems.value.length}`
})

const availableSections = computed(() => {
  const sections = []
  if (canViewRoles.value) sections.push({ id: SECTION_ROLES, label: sectionLabelMap.value[SECTION_ROLES] })
  if (canViewUsers.value) sections.push({ id: SECTION_USERS, label: sectionLabelMap.value[SECTION_USERS] })
  if (canViewSettings.value) {
    sections.push({ id: SECTION_SETTINGS, label: sectionLabelMap.value[SECTION_SETTINGS] })
  }
  return sections
})

const currentSection = computed(() => {
  if (route.name === 'settings') return SECTION_SETTINGS
  return resolveAccessibleAccountSection(userProfile.value, route.query.section)
})
const currentSectionLabel = computed(
  () => sectionLabelMap.value[currentSection.value || availableSections.value[0]?.id || SECTION_ROLES]
)
const settingsSummaryRows = computed(() => {
  const profile = userProfile.value || {}
  return [
    {
      id: 'account',
      label: t('account.settings.user_label'),
      value: profile.name || profile.username || profile.email || '-',
    },
    {
      id: 'role',
      label: t('account.settings.role_label'),
      value: profile.role || '-',
    },
    {
      id: 'visibility',
      label: t('account.settings.default_visibility'),
      value: roleVisibilityLabel(profile.conversation_visibility_default),
    },
    {
      id: 'session',
      label: t('account.settings.session_version'),
      value: profile.session_version ?? '-',
    },
  ]
})
const settingsPermissionRows = computed(() => {
  const labels = {
    [PERMISSIONS.chat]: t('account.permissions.chat'),
    [PERMISSIONS.projects]: t('account.permissions.projects'),
    [PERMISSIONS.labels]: t('account.permissions.labels'),
    [PERMISSIONS.files]: t('account.permissions.files'),
    [PERMISSIONS.rolesManage]: t('account.permissions.roles'),
    [PERMISSIONS.usersRead]: t('account.permissions.users'),
    [PERMISSIONS.usersWrite]: t('account.permissions.users'),
    [PERMISSIONS.settings]: t('account.permissions.settings'),
  }
  return Array.from(normalizePermissionCodes(userProfile.value?.permissions))
    .sort()
    .map((code) => ({
      code,
      label: labels[code] || code,
    }))
})

const {
  sideMenu,
  sideMenuOpen,
  closePermissionMenu,
  handlePermissionNavClick,
} = usePermissionSideMenu({
  userProfile,
  isTablet,
  isSidebarCollapsed,
  sectionLabels: sectionLabelMap,
})

const selectedRole = computed(() =>
  roleRecords.value.find((record) => record.id === selectedRoleId.value) || null
)

const selectedUser = computed(() =>
  userRecords.value.find((record) => record.id === selectedUserId.value) || null
)

const assignableRoleOptions = computed(() => {
  const options = roleRecords.value.filter((record) => record.isActive).map((record) => record.name)
  const currentRole = selectedUser.value?.role || userForm.value.role
  if (currentRole && !options.includes(currentRole)) options.push(currentRole)
  return options
})

const filteredRoleRecords = computed(() => {
  const query = roleSearchQuery.value.trim().toLowerCase()
  if (!query) return roleRecords.value
  return roleRecords.value.filter((record) => record.name.toLowerCase().includes(query))
})

const filteredUserRecords = computed(() => {
  const query = userSearchQuery.value.trim().toLowerCase()
  if (!query) return userRecords.value
  return userRecords.value.filter((record) =>
    `${record.name} ${record.username} ${record.role}`.toLowerCase().includes(query)
  )
})

const paginatedRoleRecords = computed(() => {
  const start = (rolePage.value - 1) * PAGE_SIZE
  return filteredRoleRecords.value.slice(start, start + PAGE_SIZE)
})

const paginatedUserRecords = computed(() => {
  const start = (userPage.value - 1) * PAGE_SIZE
  return filteredUserRecords.value.slice(start, start + PAGE_SIZE)
})

const rolePageCount = computed(() => Math.max(1, Math.ceil(filteredRoleRecords.value.length / PAGE_SIZE)))
const userPageCount = computed(() => Math.max(1, Math.ceil(filteredUserRecords.value.length / PAGE_SIZE)))

const buildRangeLabel = (total, currentSize, page) => {
  if (!total || !currentSize) return '0-0 / 0'
  const start = (page - 1) * PAGE_SIZE + 1
  const end = start + currentSize - 1
  return `${start}-${end} / ${total}`
}

const roleRangeLabel = computed(() =>
  buildRangeLabel(filteredRoleRecords.value.length, paginatedRoleRecords.value.length, rolePage.value)
)

const userRangeLabel = computed(() =>
  buildRangeLabel(filteredUserRecords.value.length, paginatedUserRecords.value.length, userPage.value)
)

const isRoleModalOpen = computed(() => activeModal.value === 'role-create' || activeModal.value === 'role-edit')
const isUserModalOpen = computed(() => activeModal.value === 'user-create' || activeModal.value === 'user-edit')
const roleModalTitle = computed(() =>
  activeModal.value === 'role-create'
    ? t('account.modals.role_create.title')
    : t('account.modals.role_edit.title')
)
const roleSubmitLabel = computed(() =>
  activeModal.value === 'role-create' ? t('account.actions.add') : t('account.actions.confirm')
)
const roleNameCount = computed(() => String(roleForm.value.name || '').trim().length)
const isRoleFormValid = computed(() => roleNameCount.value > 0 && roleNameCount.value <= 15)
const isValidEmail = (value) => !String(value || '').trim() || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || '').trim())
const requiresUserPassword = computed(() => activeModal.value === 'user-create' && !String(userForm.value.email || '').trim())
const isUserFormValid = computed(() => {
  const hasBase = userForm.value.name.trim() && userForm.value.username.trim() && userForm.value.role.trim()
  if (!hasBase) return false
  if (!isValidEmail(userForm.value.email)) return false
  if (activeModal.value === 'user-create' && userForm.value.password.trim()) {
    return userForm.value.password.trim().length >= 8
  }
  return !requiresUserPassword.value || userForm.value.password.trim().length >= 8
})
const canSendSetupEmail = computed(() => {
  return Boolean(selectedUser.value?.id && String(userForm.value.email || '').trim() && isValidEmail(userForm.value.email))
})

const roleVisibilityLabel = (value) =>
  String(value || '').toLowerCase() === 'public'
    ? t('account.visibility.public')
    : t('account.visibility.private')

const formatDateTime = (value) => {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  const yyyy = parsed.getFullYear()
  const mm = String(parsed.getMonth() + 1).padStart(2, '0')
  const dd = String(parsed.getDate()).padStart(2, '0')
  const hh = String(parsed.getHours()).padStart(2, '0')
  const mi = String(parsed.getMinutes()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd} ${hh}:${mi}`
}

const splitRolePermissions = (permissions) => {
  const normalized = Array.from(normalizePermissionCodes(permissions))
  return {
    visible: normalized.filter((code) => VISIBLE_ROLE_CODES.has(code)),
    hidden: normalized.filter((code) => !VISIBLE_ROLE_CODES.has(code)),
  }
}

const mapRoleRecord = (role) => {
  const permissions = splitRolePermissions(role?.permissions)
  return {
    id: role.id,
    name: String(role?.name || ''),
    isActive: role?.is_active !== false,
    conversationVisibility:
      String(role?.conversation_visibility_default || 'private').toLowerCase() === 'public'
        ? 'public'
        : 'private',
    memberCount: Number(role?.member_count || 0),
    updatedAt: formatDateTime(role?.updated_at),
    visiblePermissions: permissions.visible,
    hiddenPermissions: permissions.hidden,
  }
}

const mapUserRecord = (user) => ({
  id: user.id,
  name: String(user?.name || user?.username || ''),
  username: String(user?.username || ''),
  email: String(user?.email || ''),
  role: String(user?.role || 'user'),
  isActive: user?.is_active !== false,
  permissions: Array.from(normalizePermissionCodes(user?.permissions)),
  roleActive: user?.role_active !== false,
  updatedAt: formatDateTime(user?.updated_at),
  passwordSetAt: user?.password_set_at || null,
})

const getRowCodes = (item) => (item.children ? item.children.flatMap((child) => child.codes) : item.codes)

const isPermissionSelected = (codes) => {
  const selected = new Set(roleForm.value.permissionCodes)
  return codes.every((code) => selected.has(code))
}

const updatePermissionSelection = (codes, checked) => {
  const next = new Set(roleForm.value.permissionCodes)
  if (checked) codes.forEach((code) => next.add(code))
  else codes.forEach((code) => next.delete(code))
  roleForm.value.permissionCodes = Array.from(next)
}

const togglePermissionRow = (item, event) => {
  const checked = event?.target?.checked ?? !isPermissionSelected(getRowCodes(item))
  updatePermissionSelection(getRowCodes(item), checked)
}

const resetRoleForm = () => {
  roleForm.value = defaultRoleForm()
  selectedRoleId.value = null
  roleFormError.value = ''
}

const resetUserForm = () => {
  userForm.value = defaultUserForm()
  selectedUserId.value = null
  userFormError.value = ''
  userSetupStatus.value = ''
}

const resetSettingsProjectForm = () => {
  settingsProjectForm.value = defaultSettingsProjectForm()
  settingsProjectModalError.value = ''
  settingsProjectSubmitting.value = false
}

const closeSettingsCreateProjectModal = () => {
  showSettingsCreateProjectModal.value = false
  resetSettingsProjectForm()
}

const dismissModal = () => {
  activeModal.value = null
  modalBackTarget.value = null
  roleFormError.value = ''
  userFormError.value = ''
  userSetupStatus.value = ''
}

const closeModal = () => {
  if ((activeModal.value === 'role-delete' || activeModal.value === 'user-delete') && modalBackTarget.value) {
    activeModal.value = modalBackTarget.value
    modalBackTarget.value = null
    roleFormError.value = ''
    userFormError.value = ''
    return
  }
  dismissModal()
}

const updateWidth = () => {
  stageWidth.value = typeof window !== 'undefined' ? window.innerWidth : stageWidth.value
  if (!isCompactSidebar.value) isSidebarCollapsed.value = false
}

const toggleSidebar = () => {
  if (!isCompactSidebar.value) return
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

const handleLogoClick = () => {
  router.push(getFirstAllowedRoute(userProfile.value))
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
    router.push(targetRoute)
  }
}

const buildSectionRoute = (section) => {
  const nextQuery = { ...route.query }
  delete nextQuery.section
  if (section === SECTION_SETTINGS) {
    return { name: 'settings', query: nextQuery }
  }
  return { name: 'account', query: { ...nextQuery, section } }
}

const setSection = (sectionId) => {
  closePermissionMenu()
  if (sectionId !== currentSection.value) router.replace(buildSectionRoute(sectionId))
}

const goToPreviousPage = () => {
  if (currentSection.value === SECTION_ROLES) rolePage.value = Math.max(1, rolePage.value - 1)
  else userPage.value = Math.max(1, userPage.value - 1)
}

const goToNextPage = () => {
  if (currentSection.value === SECTION_ROLES) rolePage.value = Math.min(rolePageCount.value, rolePage.value + 1)
  else userPage.value = Math.min(userPageCount.value, userPage.value + 1)
}

const fetchRoles = async () => {
  roleLoading.value = true
  roleError.value = ''
  try {
    const data = await listRoles()
    roleRecords.value = (data || []).map(mapRoleRecord)
  } catch (error) {
    roleError.value = error?.message || t('account.errors.load_roles')
  } finally {
    roleLoading.value = false
  }
}

const fetchUsers = async () => {
  if (!canViewUsers.value) {
    userRecords.value = []
    return
  }
  userLoading.value = true
  userError.value = ''
  try {
    const data = await listUsers()
    userRecords.value = (data || []).map(mapUserRecord)
  } catch (error) {
    userError.value = error?.message || t('account.errors.load_members')
  } finally {
    userLoading.value = false
  }
}

const buildSettingsProjectPayload = () => ({
  name: settingsProjectForm.value.name.trim(),
  visibility: settingsProjectForm.value.visibility,
  customerProfile: {
    customer_type: settingsProjectForm.value.customerType || null,
    trade_count: Number.isFinite(Number(settingsProjectForm.value.tradeCount))
      ? Number(settingsProjectForm.value.tradeCount)
      : null,
    last_trade_at: settingsProjectForm.value.lastTradeAt || null,
    avg_unit_price: Number.isFinite(Number(settingsProjectForm.value.avgUnitPrice))
      ? Number(settingsProjectForm.value.avgUnitPrice)
      : null,
    preference_note: settingsProjectForm.value.preferenceNote || null,
    region: settingsProjectForm.value.region || null,
  },
})

const fetchSettingsProjects = async () => {
  if (!canViewSettings.value) {
    settingsProjectRecords.value = []
    return
  }

  settingsProjectLoading.value = true
  settingsProjectError.value = ''
  try {
    const data = await fetchProjects({ q: '', page: 1, pageSize: SETTINGS_FETCH_PAGE_SIZE })
    settingsProjectRecords.value = (data?.items || []).map(normalizeSettingsProjectRecord)
  } catch (error) {
    settingsProjectRecords.value = []
    settingsProjectError.value = error?.message || t('account.settings_stage.errors.load')
  } finally {
    settingsProjectLoading.value = false
  }
}

const fetchKnowledgeTables = async () => {
  if (!canViewSettings.value) {
    knowledgeTables.value = []
    return
  }
  knowledgeTablesLoading.value = true
  knowledgeTablesError.value = ''
  try {
    const data = await fetchKnowledgeRagTables()
    knowledgeTables.value = data?.items || []
  } catch (error) {
    knowledgeTables.value = []
    knowledgeTablesError.value = error?.message || t('account.knowledge.errors.load')
  } finally {
    knowledgeTablesLoading.value = false
  }
}

const fetchCompanyProfile = async () => {
  if (!canViewSettings.value) return
  companyProfileLoading.value = true
  companyProfileError.value = ''
  try {
    const data = await fetchKnowledgeCompanyProfile()
    companyProfileForm.value = {
      ...companyProfileForm.value,
      ...(data?.profile || {}),
    }
  } catch (error) {
    companyProfileError.value = error?.message || t('account.knowledge.errors.load_profile')
  } finally {
    companyProfileLoading.value = false
  }
}

const fetchExternalSites = async () => {
  if (!canViewSettings.value) {
    externalSites.value = []
    return
  }
  externalSitesLoading.value = true
  externalSitesError.value = ''
  try {
    const data = await fetchKnowledgeExternalSites()
    externalSites.value = data?.items || []
  } catch (error) {
    externalSites.value = []
    externalSitesError.value = error?.message || t('account.knowledge.errors.load_sites')
  } finally {
    externalSitesLoading.value = false
  }
}

const fetchKnowledgeData = async () => {
  if (!canViewSettings.value) return
  await Promise.all([fetchKnowledgeTables(), fetchCompanyProfile(), fetchExternalSites()])
}

const handleKnowledgeFileSelected = (event) => {
  const [file] = Array.from(event?.target?.files || [])
  knowledgeRagForm.value.file = file || null
  knowledgeImportStatus.value = ''
  knowledgeImportError.value = ''
}

const submitKnowledgeRagTable = async () => {
  if (knowledgeImporting.value) return
  if (!knowledgeRagForm.value.file) {
    knowledgeImportError.value = t('account.knowledge.errors.file_required')
    return
  }
  const formData = new FormData()
  formData.append('file', knowledgeRagForm.value.file)
  formData.append('table_name', knowledgeRagForm.value.tableName)
  formData.append('source_name', knowledgeRagForm.value.sourceName)
  formData.append('language', knowledgeRagForm.value.language)
  formData.append('tags', knowledgeRagForm.value.tags)
  formData.append('replace', 'true')
  knowledgeImporting.value = true
  knowledgeImportError.value = ''
  knowledgeImportStatus.value = ''
  try {
    const data = await importKnowledgeRagTable(formData)
    knowledgeImportStatus.value = t('account.knowledge.rag.import_success', {
      rows: data?.rows || 0,
      chunks: data?.chunks || 0,
    })
    knowledgeRagForm.value.file = null
    await fetchKnowledgeTables()
  } catch (error) {
    knowledgeImportError.value = error?.message || t('account.knowledge.errors.import')
  } finally {
    knowledgeImporting.value = false
  }
}

const removeKnowledgeRagTable = async (item) => {
  if (!item?.id) return
  knowledgeTablesError.value = ''
  try {
    await deleteKnowledgeRagTable(item.id)
    await fetchKnowledgeTables()
  } catch (error) {
    knowledgeTablesError.value = error?.message || t('account.knowledge.errors.delete')
  }
}

const submitCompanyProfile = async () => {
  if (companyProfileSaving.value) return
  companyProfileSaving.value = true
  companyProfileStatus.value = ''
  companyProfileError.value = ''
  try {
    const data = await saveKnowledgeCompanyProfile(companyProfileForm.value)
    companyProfileStatus.value = t('account.knowledge.profile.save_success', { chunks: data?.chunks || 0 })
    await loadSystemBrand({ force: true })
  } catch (error) {
    companyProfileError.value = error?.message || t('account.knowledge.errors.save_profile')
  } finally {
    companyProfileSaving.value = false
  }
}

const submitExternalSite = async () => {
  if (externalSitesSaving.value) return
  externalSitesSaving.value = true
  externalSitesStatus.value = ''
  externalSitesError.value = ''
  try {
    await saveKnowledgeExternalSite(externalSiteForm.value)
    externalSitesStatus.value = t('account.knowledge.sites.save_success')
    externalSiteForm.value = {
      url: '',
      name: '',
      category: '',
      language: 'zh-TW',
      trust_level: 'approved',
      enabled: true,
    }
    await fetchExternalSites()
  } catch (error) {
    externalSitesError.value = error?.message || t('account.knowledge.errors.save_site')
  } finally {
    externalSitesSaving.value = false
  }
}

const ingestExternalSite = async (item) => {
  if (!item?.id || externalSitesIngestingId.value) return
  externalSitesIngestingId.value = item.id
  externalSitesStatus.value = ''
  externalSitesError.value = ''
  try {
    const data = await ingestKnowledgeExternalSite(item.id)
    externalSitesStatus.value = t('account.knowledge.sites.ingest_success', { chunks: data?.chunks || 0 })
    await fetchExternalSites()
  } catch (error) {
    externalSitesError.value = error?.message || t('account.knowledge.errors.ingest_site')
  } finally {
    externalSitesIngestingId.value = null
  }
}

const bootstrapAccountData = async () => {
  const tasks = []
  if (canViewRoles.value || canViewUsers.value) tasks.push(fetchRoles())
  else roleRecords.value = []
  if (canViewUsers.value) tasks.push(fetchUsers())
  else userRecords.value = []
  if (canViewSettings.value) tasks.push(fetchSettingsProjects(), fetchKnowledgeData())
  else {
    settingsProjectRecords.value = []
    knowledgeTables.value = []
    externalSites.value = []
  }
  if (!tasks.length) return
  await Promise.all(tasks)
}

const openRoleCreateModal = () => {
  if (!canViewRoles.value) return
  resetRoleForm()
  activeModal.value = 'role-create'
}

const openRoleEditModal = (record) => {
  if (!canViewRoles.value) return
  selectedRoleId.value = record.id
  roleForm.value = {
    name: record.name,
    isActive: record.isActive,
    conversationVisibility: record.conversationVisibility,
    permissionCodes: [...record.visiblePermissions],
    hiddenPermissionCodes: [...record.hiddenPermissions],
  }
  roleFormError.value = ''
  activeModal.value = 'role-edit'
}

const openRoleDeleteModal = ({ fromEdit = false } = {}) => {
  if (!selectedRole.value) return
  modalBackTarget.value = fromEdit ? 'role-edit' : null
  activeModal.value = 'role-delete'
  roleFormError.value = ''
}

const openUserCreateModal = () => {
  if (!canManageUsers.value) return
  resetUserForm()
  activeModal.value = 'user-create'
}

const openUserEditModal = (record) => {
  if (!canManageUsers.value) return
  selectedUserId.value = record.id
  userForm.value = {
    name: record.name,
    username: record.username,
    email: record.email || '',
    password: '',
    role: record.role,
    isActive: record.isActive,
  }
  userFormError.value = ''
  userSetupStatus.value = ''
  activeModal.value = 'user-edit'
}

const openUserDeleteModal = ({ fromEdit = false } = {}) => {
  if (!selectedUser.value || !canManageUsers.value) return
  modalBackTarget.value = fromEdit ? 'user-edit' : null
  activeModal.value = 'user-delete'
  userFormError.value = ''
}

const openPasswordSettings = () => {
  if (!canViewSettings.value) return
  openChangePasswordModal()
  if (route.query.panel === SETTINGS_PANEL_PASSWORD) {
    const nextQuery = { ...route.query }
    delete nextQuery.panel
    router.replace({ name: route.name === 'settings' ? 'settings' : 'account', query: nextQuery }).catch(() => {})
  }
}

const openSettingsCreateProjectModal = () => {
  if (!canViewSettings.value) return
  resetSettingsProjectForm()
  showSettingsCreateProjectModal.value = true
}

const submitSettingsProject = async () => {
  if (settingsProjectSubmitting.value) return
  if (!settingsProjectForm.value.name.trim()) {
    settingsProjectModalError.value = t('account.settings_stage.modal.errors.name_required')
    return
  }

  settingsProjectSubmitting.value = true
  settingsProjectModalError.value = ''
  try {
    await createProject(buildSettingsProjectPayload())
    closeSettingsCreateProjectModal()
    settingsPage.value = 1
    settingsActiveTab.value = SETTINGS_TAB_PENDING
    await fetchSettingsProjects()
  } catch (error) {
    settingsProjectModalError.value = error?.message || t('account.settings_stage.modal.errors.create')
  } finally {
    settingsProjectSubmitting.value = false
  }
}

const openSettingsProject = (project) => {
  if (!project?.id) return
  router
    .push({
      name: 'projects',
      query: {
        project_id: project.id,
        project_label: project.name || '',
      },
    })
    .catch(() => {})
}

const setSettingsTab = (tabId) => {
  if (tabId !== SETTINGS_TAB_PENDING && tabId !== SETTINGS_TAB_PROCESSED) return
  settingsActiveTab.value = tabId
  settingsPage.value = 1
}

const goToPreviousSettingsPage = () => {
  settingsPage.value = Math.max(1, settingsPage.value - 1)
}

const goToNextSettingsPage = () => {
  settingsPage.value = Math.min(settingsTotalPages.value, settingsPage.value + 1)
}

const prepareUserDelete = (record) => {
  if (!canManageUsers.value) return
  selectedUserId.value = record.id
  userForm.value = {
    name: record.name,
    username: record.username,
    email: record.email || '',
    password: '',
    role: record.role,
    isActive: record.isActive,
  }
  openUserDeleteModal()
}

const buildRolePayload = () => ({
  name: roleForm.value.name.trim(),
  description: null,
  is_active: roleForm.value.isActive,
  conversation_visibility_default: roleForm.value.conversationVisibility,
  permissions: [...roleForm.value.permissionCodes, ...roleForm.value.hiddenPermissionCodes],
})

const submitRoleForm = async () => {
  if (!isRoleFormValid.value || roleSubmitting.value) return
  roleSubmitting.value = true
  roleFormError.value = ''
  try {
    if (activeModal.value === 'role-create') await createRole(buildRolePayload())
    else if (selectedRole.value) await updateRole(selectedRole.value.id, buildRolePayload())
    dismissModal()
    await bootstrapAccountData()
  } catch (error) {
    roleFormError.value = error?.message || t('account.errors.save_role')
  } finally {
    roleSubmitting.value = false
  }
}

const confirmRoleDelete = async () => {
  if (!selectedRole.value || roleSubmitting.value) return
  roleSubmitting.value = true
  roleFormError.value = ''
  try {
    await deleteRole(selectedRole.value.id)
    dismissModal()
    resetRoleForm()
    await bootstrapAccountData()
  } catch (error) {
    roleFormError.value = error?.message || t('account.errors.delete_role')
  } finally {
    roleSubmitting.value = false
  }
}

const toggleRoleStatus = async (record) => {
  if (!record?.id || roleStatusUpdatingId.value === record.id) return
  roleStatusUpdatingId.value = record.id
  roleError.value = ''
  try {
    await updateRole(record.id, { is_active: !record.isActive })
    await bootstrapAccountData()
  } catch (error) {
    roleError.value = error?.message || t('account.errors.update_role_status')
  } finally {
    roleStatusUpdatingId.value = null
  }
}

const submitUserForm = async () => {
  if (!isUserFormValid.value || userSubmitting.value || !canManageUsers.value) return
  userSubmitting.value = true
  userFormError.value = ''
  userSetupStatus.value = ''
  try {
    if (activeModal.value === 'user-create') {
      const payload = {
        name: userForm.value.name.trim(),
        username: userForm.value.username.trim(),
        email: userForm.value.email.trim() || null,
        role: userForm.value.role.trim(),
      }
      if (userForm.value.password.trim()) {
        payload.password = userForm.value.password.trim()
      }
      await createUserAccount(payload)
    } else if (selectedUser.value) {
      const payload = { role: userForm.value.role.trim() }
      if (userForm.value.name.trim() !== selectedUser.value.name) {
        payload.name = userForm.value.name.trim()
      }
      if (userForm.value.username.trim() !== selectedUser.value.username) {
        payload.username = userForm.value.username.trim()
      }
      if ((userForm.value.email.trim() || '') !== (selectedUser.value.email || '')) {
        payload.email = userForm.value.email.trim() || null
      }
      if (userForm.value.password.trim()) {
        payload.password = userForm.value.password.trim()
      }
      await updateUserAccount(selectedUser.value.id, payload)
    }
    dismissModal()
    await fetchUsers()
    await fetchRoles()
  } catch (error) {
    userFormError.value = error?.message || t('account.errors.save_member')
  } finally {
    userSubmitting.value = false
  }
}

const handleSendSetupEmail = async () => {
  if (!selectedUser.value?.id || !canSendSetupEmail.value || setupEmailSubmitting.value) return
  setupEmailSubmitting.value = true
  userFormError.value = ''
  userSetupStatus.value = ''
  try {
    if ((userForm.value.email.trim() || '') !== (selectedUser.value.email || '')) {
      await updateUserAccount(selectedUser.value.id, {
        email: userForm.value.email.trim() || null,
      })
      await fetchUsers()
      const refreshed = userRecords.value.find((record) => record.id === selectedUser.value.id)
      if (refreshed) {
        selectedUserId.value = refreshed.id
        userForm.value.email = refreshed.email || ''
      }
    }
    const response = await sendSetupPasswordEmail(selectedUser.value.id)
    userSetupStatus.value =
      (response?.message_key && t(response.message_key)) ||
      response?.message ||
      t('account.form.setup_email_success')
  } catch (error) {
    userFormError.value = error?.message || t('account.form.setup_email_failed')
  } finally {
    setupEmailSubmitting.value = false
  }
}

const toggleUserStatus = async (record) => {
  if (!record?.id || userStatusUpdatingId.value === record.id || !canManageUsers.value) return
  userStatusUpdatingId.value = record.id
  userError.value = ''
  try {
    await updateUserAccount(record.id, { is_active: !record.isActive })
    await fetchUsers()
  } catch (error) {
    userError.value = error?.message || t('account.errors.update_member_status')
  } finally {
    userStatusUpdatingId.value = null
  }
}

const confirmUserDelete = async () => {
  if (!selectedUser.value || userSubmitting.value || !canManageUsers.value) return
  userSubmitting.value = true
  userFormError.value = ''
  try {
    await deleteUserAccount(selectedUser.value.id)
    dismissModal()
    resetUserForm()
    await fetchUsers()
    await fetchRoles()
  } catch (error) {
    userFormError.value = error?.message || t('account.errors.delete_member')
  } finally {
    userSubmitting.value = false
  }
}

watch(roleSearchQuery, () => {
  rolePage.value = 1
})

watch(userSearchQuery, () => {
  userPage.value = 1
})

watch(filteredRoleRecords, () => {
  if (rolePage.value > rolePageCount.value) rolePage.value = rolePageCount.value
})

watch(filteredUserRecords, () => {
  if (userPage.value > userPageCount.value) userPage.value = userPageCount.value
})

watch(settingsSearchQuery, () => {
  settingsPage.value = 1
})

watch(activeSettingsItems, () => {
  if (settingsPage.value > settingsTotalPages.value) {
    settingsPage.value = settingsTotalPages.value
  }
})

watch(
  currentSection,
  (section) => {
    activeNavId.value = section === SECTION_SETTINGS ? 'settings' : 'permission'
  },
  { immediate: true }
)

watch(
  () => [currentSection.value, route.query.panel],
  ([section, panel]) => {
    if (section === SECTION_SETTINGS && panel === SETTINGS_PANEL_PASSWORD) {
      openPasswordSettings()
    }
  },
  { immediate: true }
)

watch(
  [isAuthenticated, () => route.name, () => route.query.section, canViewRoles, canViewUsers, canViewSettings],
  async ([authed, routeName, requestedSection]) => {
    if (!authed) {
      roleRecords.value = []
      userRecords.value = []
      settingsProjectRecords.value = []
      return
    }
    if (!canViewPermissionModule.value && !canViewSettings.value) {
      router.replace(getFirstAllowedRoute(userProfile.value))
      return
    }
    const resolved =
      routeName === 'settings'
        ? (canViewSettings.value ? SECTION_SETTINGS : null)
        : resolveAccessibleAccountSection(userProfile.value, requestedSection)
    if (!resolved) {
      router.replace(getFirstAllowedRoute(userProfile.value))
      return
    }
    if (routeName === 'account' && resolved === SECTION_SETTINGS) {
      const nextQuery = { ...route.query }
      delete nextQuery.section
      router.replace({ name: 'settings', query: nextQuery })
      return
    }
    if (routeName === 'settings' && resolved !== SECTION_SETTINGS) {
      router.replace(buildSectionRoute(resolved))
      return
    }
    if (routeName !== 'settings' && resolved !== requestedSection) {
      router.replace(buildSectionRoute(resolved))
      return
    }
    await bootstrapAccountData()
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('resize', updateWidth)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateWidth)
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
      :aria-label="t('account.aria.main_nav')"
      @logo-click="handleLogoClick"
      @nav-click="handleNavClick"
    />

    <div class="main-stage account-dev-stage">
      <AppTopBar
        :logo-src="logoMain"
        :is-compact-sidebar="isCompactSidebar"
        :is-sidebar-collapsed="isSidebarCollapsed"
        :hamburger-icon="glyphs.hamburger"
        :menu-aria-label="t('account.aria.toggle_menu')"
        :avatar-label="avatarLabel"
        :avatar-aria-label="t('account.aria.toggle_profile')"
        @toggle-sidebar="toggleSidebar"
        @logo-click="handleLogoClick"
      >
        <template #search>
          <label v-if="!isTablet" class="account-top-search">
            <span class="account-top-search__icon" v-html="glyphs.search" aria-hidden="true" />
            <input type="search" :placeholder="t('account.search.chat_placeholder')" />
          </label>
        </template>
      </AppTopBar>

      <main class="account-dev-main">
        <section class="account-dev-hero">
          <div class="account-dev-hero__copy">
            <h1>{{ currentSection === SECTION_SETTINGS ? t('account.settings_stage.title') : currentSectionLabel }}</h1>
          </div>
          <div v-if="availableSections.length > 1 && isTablet" class="account-dev-tabs">
            <button
              v-for="section in availableSections"
              :key="section.id"
              type="button"
              class="account-dev-tabs__item"
              :class="{ 'is-active': currentSection === section.id }"
              @click="setSection(section.id)"
            >
              {{ section.label }}
            </button>
          </div>
          <button
            v-if="currentSection === SECTION_ROLES"
            type="button"
            class="account-dev-primary"
            @click="openRoleCreateModal"
          >
            <span v-html="glyphs.plus" aria-hidden="true" />
            {{ t('account.actions.add_role') }}
          </button>
          <button
            v-else-if="currentSection === SECTION_USERS && canManageUsers"
            type="button"
            class="account-dev-primary"
            @click="openUserCreateModal"
          >
            <span v-html="glyphs.plus" aria-hidden="true" />
            {{ t('account.actions.add_member') }}
          </button>
        </section>

        <header v-if="currentSection !== SECTION_SETTINGS" class="account-dev-search-bar">
          <label class="account-dev-search">
            <span class="account-dev-search__icon" v-html="glyphs.search" aria-hidden="true" />
            <input
              v-if="currentSection === SECTION_ROLES"
              v-model="roleSearchQuery"
              type="search"
              :placeholder="t('account.search.roles_placeholder')"
            />
            <input
              v-else
              v-model="userSearchQuery"
              type="search"
              :placeholder="t('account.search.members_placeholder')"
            />
          </label>
        </header>

        <section v-if="currentSection === SECTION_SETTINGS" class="settings-stage">
          <header class="settings-stage__hero">
            <p>{{ settingsSummaryText }}</p>
            <button type="button" class="settings-stage__create" @click="openSettingsCreateProjectModal">
              <span v-html="glyphs.plus" aria-hidden="true" />
              {{ t('account.settings_stage.create_project') }}
            </button>
          </header>

          <article class="settings-stage__card knowledge-card">
            <div class="settings-stage__tabs">
              <button
                v-for="tab in knowledgeTabs"
                :key="tab.id"
                type="button"
                class="settings-stage__tab"
                :class="{ 'is-active': knowledgeActiveTab === tab.id }"
                @click="knowledgeActiveTab = tab.id"
              >
                {{ tab.label }}
              </button>
            </div>

            <section v-if="knowledgeActiveTab === KNOWLEDGE_TAB_RAG" class="knowledge-panel">
              <div class="knowledge-panel__form">
                <label>
                  <span>{{ t('account.knowledge.rag.table_name') }}</span>
                  <input v-model="knowledgeRagForm.tableName" type="text" :placeholder="t('account.knowledge.rag.table_name_placeholder')" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.rag.source_name') }}</span>
                  <input v-model="knowledgeRagForm.sourceName" type="text" :placeholder="t('account.knowledge.rag.source_name_placeholder')" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.common.language') }}</span>
                  <select v-model="knowledgeRagForm.language">
                    <option value="zh-TW">繁體中文</option>
                    <option value="en">English</option>
                    <option value="ja">日本語</option>
                  </select>
                </label>
                <label>
                  <span>{{ t('account.knowledge.rag.tags') }}</span>
                  <input v-model="knowledgeRagForm.tags" type="text" :placeholder="t('account.knowledge.rag.tags_placeholder')" />
                </label>
                <label class="knowledge-panel__file">
                  <span>{{ t('account.knowledge.rag.file') }}</span>
                  <input type="file" accept=".csv,.xlsx" @change="handleKnowledgeFileSelected" />
                </label>
                <button type="button" class="settings-stage__create" :disabled="knowledgeImporting" @click="submitKnowledgeRagTable">
                  {{ knowledgeImporting ? t('common.actions.processing') : t('account.knowledge.rag.import') }}
                </button>
              </div>
              <p v-if="knowledgeImportStatus" class="knowledge-panel__status">{{ knowledgeImportStatus }}</p>
              <p v-if="knowledgeImportError" class="knowledge-panel__status is-error">{{ knowledgeImportError }}</p>
              <div class="knowledge-panel__list">
                <p v-if="knowledgeTablesLoading" class="settings-stage__state">{{ t('account.knowledge.common.loading') }}</p>
                <p v-else-if="knowledgeTablesError" class="settings-stage__state is-error">{{ knowledgeTablesError }}</p>
                <div v-else-if="!knowledgeTables.length" class="settings-stage__state">{{ t('account.knowledge.rag.empty') }}</div>
                <div v-for="item in knowledgeTables" v-else :key="item.id" class="knowledge-row">
                  <div>
                    <strong>{{ item.meta?.table_name || item.meta?.source_name || item.filename }}</strong>
                    <small>{{ item.chunk_count || 0 }} {{ t('account.knowledge.common.chunks') }}</small>
                  </div>
                  <button type="button" @click="removeKnowledgeRagTable(item)">{{ t('common.actions.delete') }}</button>
                </div>
              </div>
            </section>

            <section v-else-if="knowledgeActiveTab === KNOWLEDGE_TAB_PROFILE" class="knowledge-panel">
              <div v-if="companyProfileLoading" class="settings-stage__state">{{ t('account.knowledge.common.loading') }}</div>
              <div class="knowledge-panel__form is-wide">
                <label>
                  <span>{{ t('account.knowledge.profile.company_name') }}</span>
                  <input v-model="companyProfileForm.company_name" type="text" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.industry') }}</span>
                  <input v-model="companyProfileForm.industry" type="text" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.product_categories') }}</span>
                  <input v-model="companyProfileForm.product_categories" type="text" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.tone') }}</span>
                  <input v-model="companyProfileForm.tone" type="text" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.service_scope') }}</span>
                  <textarea v-model="companyProfileForm.service_scope" rows="3" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.contact_info') }}</span>
                  <textarea v-model="companyProfileForm.contact_info" rows="3" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.faq') }}</span>
                  <textarea v-model="companyProfileForm.faq" rows="4" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.profile.policies') }}</span>
                  <textarea v-model="companyProfileForm.policies" rows="4" />
                </label>
                <button type="button" class="settings-stage__create" :disabled="companyProfileSaving" @click="submitCompanyProfile">
                  {{ companyProfileSaving ? t('common.actions.processing') : t('account.knowledge.profile.save') }}
                </button>
              </div>
              <p v-if="companyProfileStatus" class="knowledge-panel__status">{{ companyProfileStatus }}</p>
              <p v-if="companyProfileError" class="knowledge-panel__status is-error">{{ companyProfileError }}</p>
            </section>

            <section v-else class="knowledge-panel">
              <div class="knowledge-panel__form">
                <label>
                  <span>{{ t('account.knowledge.sites.url') }}</span>
                  <input v-model="externalSiteForm.url" type="url" placeholder="https://example.com/article" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.sites.name') }}</span>
                  <input v-model="externalSiteForm.name" type="text" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.sites.category') }}</span>
                  <input v-model="externalSiteForm.category" type="text" />
                </label>
                <label>
                  <span>{{ t('account.knowledge.common.language') }}</span>
                  <select v-model="externalSiteForm.language">
                    <option value="zh-TW">繁體中文</option>
                    <option value="en">English</option>
                    <option value="ja">日本語</option>
                  </select>
                </label>
                <label>
                  <span>{{ t('account.knowledge.sites.trust_level') }}</span>
                  <select v-model="externalSiteForm.trust_level">
                    <option value="approved">{{ t('account.knowledge.sites.trust.approved') }}</option>
                    <option value="reference">{{ t('account.knowledge.sites.trust.reference') }}</option>
                    <option value="experimental">{{ t('account.knowledge.sites.trust.experimental') }}</option>
                  </select>
                </label>
                <label class="settings-project-modal__switch">
                  <span>{{ t('account.knowledge.sites.enabled') }}</span>
                  <input v-model="externalSiteForm.enabled" type="checkbox" />
                </label>
                <button type="button" class="settings-stage__create" :disabled="externalSitesSaving" @click="submitExternalSite">
                  {{ externalSitesSaving ? t('common.actions.processing') : t('account.knowledge.sites.add') }}
                </button>
              </div>
              <p v-if="externalSitesStatus" class="knowledge-panel__status">{{ externalSitesStatus }}</p>
              <p v-if="externalSitesError" class="knowledge-panel__status is-error">{{ externalSitesError }}</p>
              <div class="knowledge-panel__list">
                <p v-if="externalSitesLoading" class="settings-stage__state">{{ t('account.knowledge.common.loading') }}</p>
                <div v-for="item in externalSites" v-else :key="item.id" class="knowledge-row">
                  <div>
                    <strong>{{ item.meta?.source_name || item.meta?.url }}</strong>
                    <small>{{ item.meta?.url }} · {{ item.chunk_count || 0 }} {{ t('account.knowledge.common.chunks') }}</small>
                  </div>
                  <button type="button" :disabled="externalSitesIngestingId === item.id" @click="ingestExternalSite(item)">
                    {{ externalSitesIngestingId === item.id ? t('common.actions.processing') : t('account.knowledge.sites.ingest') }}
                  </button>
                </div>
              </div>
            </section>
          </article>

          <article class="settings-stage__card">
            <div class="settings-stage__tabs">
              <button
                type="button"
                class="settings-stage__tab"
                :class="{ 'is-active': settingsActiveTab === SETTINGS_TAB_PENDING }"
                @click="setSettingsTab(SETTINGS_TAB_PENDING)"
              >
                {{ t('account.settings_stage.tabs.pending') }}
              </button>
              <button
                type="button"
                class="settings-stage__tab"
                :class="{ 'is-active': settingsActiveTab === SETTINGS_TAB_PROCESSED }"
                @click="setSettingsTab(SETTINGS_TAB_PROCESSED)"
              >
                {{ t('account.settings_stage.tabs.processed') }}
              </button>
            </div>

            <div class="settings-stage__toolbar">
              <label class="settings-stage__search">
                <span class="settings-stage__search-icon" v-html="glyphs.search" aria-hidden="true" />
                <input
                  v-model="settingsSearchQuery"
                  type="search"
                  :placeholder="t('account.settings_stage.search_placeholder')"
                  autocomplete="off"
                />
              </label>
            </div>

            <div class="settings-stage__table-wrap">
              <div class="settings-stage__head">
                <span>{{ t('account.settings_stage.columns.topic') }}</span>
                <span>{{ t('account.settings_stage.columns.time') }}</span>
              </div>

              <div v-if="settingsProjectLoading" class="settings-stage__state">
                {{ t('account.settings_stage.loading') }}
              </div>
              <div v-else-if="settingsProjectError" class="settings-stage__state is-error">
                {{ settingsProjectError }}
              </div>
              <div v-else-if="!paginatedSettingsItems.length" class="settings-stage__state">
                {{
                  settingsSearchQuery.trim()
                    ? t('account.settings_stage.empty.filtered')
                    : t('account.settings_stage.empty.default')
                }}
              </div>

              <button
                v-for="project in paginatedSettingsItems"
                v-else
                :key="project.id"
                type="button"
                class="settings-stage__row"
                @click="openSettingsProject(project)"
              >
                <span class="settings-stage__topic">{{ project.name }}</span>
                <span class="settings-stage__time">{{ project.updatedAt }}</span>
              </button>
            </div>

            <footer class="settings-stage__footer">
              <div class="settings-stage__page-size">
                {{ t('account.settings_stage.page_size') }}
                <strong>{{ SETTINGS_PAGE_SIZE }}</strong>
                <span v-html="glyphs.chevron" aria-hidden="true" />
              </div>
              <div class="settings-stage__range">{{ settingsRangeLabel }}</div>
              <div class="settings-stage__pager">
                <button
                  type="button"
                  :disabled="settingsPage <= 1"
                  @click="goToPreviousSettingsPage"
                >
                  &lt;
                </button>
                <button
                  type="button"
                  :disabled="settingsPage >= settingsTotalPages"
                  @click="goToNextSettingsPage"
                >
                  &gt;
                </button>
              </div>
            </footer>
          </article>
        </section>

        <div v-else-if="currentSection === SECTION_ROLES" class="account-dev-table">
            <p v-if="roleError" class="account-dev-table__status is-error">{{ roleError }}</p>
            <p v-else-if="roleLoading" class="account-dev-table__status">{{ t('account.loading.roles') }}</p>
            <template v-else>
              <div class="account-role-table__head">
                <span>{{ t('account.table.status') }}</span>
                <span>{{ t('account.table.roles.name') }}</span>
                <span>{{ t('account.table.roles.conversation_visibility') }}</span>
                <span>{{ t('account.table.roles.member_count') }}</span>
                <span>{{ t('account.table.roles.updated_at') }}</span>
              </div>

              <div
                v-for="record in paginatedRoleRecords"
                :key="record.id"
                class="account-role-row"
                role="button"
                tabindex="0"
                @click="openRoleEditModal(record)"
                @keydown.enter.prevent="openRoleEditModal(record)"
                @keydown.space.prevent="openRoleEditModal(record)"
              >
                <div class="account-role-row__status">
                  <button
                    type="button"
                    class="account-role-switch-button"
                    :disabled="roleStatusUpdatingId === record.id"
                    @click.stop="toggleRoleStatus(record)"
                  >
                    <span class="account-role-switch" :class="{ 'is-on': record.isActive }">
                      <span />
                    </span>
                  </button>
                  <span :class="{ 'is-muted': !record.isActive }">
                    {{ record.isActive ? t('account.status.enabled') : t('account.status.disabled') }}
                  </span>
                </div>
                <span>{{ record.name }}</span>
                <span>{{ roleVisibilityLabel(record.conversationVisibility) }}</span>
                <span>{{ record.memberCount }}</span>
                <span>{{ record.updatedAt }}</span>
              </div>

              <p v-if="!paginatedRoleRecords.length" class="account-dev-table__status">{{ t('account.empty.roles') }}</p>
            </template>
          </div>

          <div v-else class="account-dev-table">
            <p v-if="userError" class="account-dev-table__status is-error">{{ userError }}</p>
            <p v-else-if="userLoading" class="account-dev-table__status">{{ t('account.loading.members') }}</p>
            <template v-else>
              <div class="account-user-table__head">
                <span>{{ t('account.table.status') }}</span>
                <span>{{ t('account.table.users.name') }}</span>
                <span>{{ t('account.table.users.role') }}</span>
                <span>{{ t('account.table.users.account') }}</span>
                <span>{{ t('account.table.users.updated_at') }}</span>
              </div>

              <div
                v-for="record in paginatedUserRecords"
                :key="record.id"
                class="account-user-row"
                role="button"
                tabindex="0"
                @click="openUserEditModal(record)"
                @keydown.enter.prevent="openUserEditModal(record)"
                @keydown.space.prevent="openUserEditModal(record)"
              >
                <div class="account-role-row__status">
                  <button
                    type="button"
                    class="account-role-switch-button"
                    :disabled="userStatusUpdatingId === record.id || !canManageUsers"
                    @click.stop="toggleUserStatus(record)"
                  >
                    <span class="account-role-switch" :class="{ 'is-on': record.isActive }">
                      <span />
                    </span>
                  </button>
                  <span :class="{ 'is-muted': !record.isActive }">
                    {{ record.isActive ? t('account.status.enabled') : t('account.status.disabled') }}
                  </span>
                </div>
                <span>{{ record.name }}</span>
                <span>{{ record.role }}</span>
                <span>{{ record.username }}</span>
                <span>{{ record.updatedAt }}</span>
              </div>

              <p v-if="!paginatedUserRecords.length" class="account-dev-table__status">{{ t('account.empty.members') }}</p>
            </template>
          </div>

        <footer v-if="currentSection !== SECTION_SETTINGS" class="account-dev-pagination">
          <div class="account-dev-pagination__size">
            {{ t('account.pagination.per_page') }}
            <strong>{{ PAGE_SIZE }}</strong>
            <span v-html="glyphs.chevron" aria-hidden="true" />
          </div>
          <div class="account-dev-pagination__range">
            {{ currentSection === SECTION_ROLES ? roleRangeLabel : userRangeLabel }}
          </div>
          <div class="account-dev-pagination__nav">
            <button
              type="button"
              :disabled="currentSection === SECTION_ROLES ? rolePage <= 1 : userPage <= 1"
              @click="goToPreviousPage"
            >
              &lt;
            </button>
            <button
              type="button"
              :disabled="currentSection === SECTION_ROLES ? rolePage >= rolePageCount : userPage >= userPageCount"
              @click="goToNextPage"
            >
              &gt;
            </button>
          </div>
        </footer>
      </main>
    </div>
  </div>

  <div v-if="showSettingsCreateProjectModal" class="account-modal-mask" role="dialog" aria-modal="true">
    <div class="account-role-modal settings-project-modal">
      <header class="account-role-modal__header settings-project-modal__header">
        <h3>{{ t('account.settings_stage.modal.title') }}</h3>
        <button type="button" class="account-modal-close" @click="closeSettingsCreateProjectModal">
          <span v-html="glyphs.close" aria-hidden="true" />
        </button>
      </header>
      <div class="account-role-modal__body settings-project-modal__body">
        <label class="account-field">
          <span><em>*</em> {{ t('account.settings_stage.modal.name_label') }}</span>
          <input
            v-model="settingsProjectForm.name"
            type="text"
            :placeholder="t('account.settings_stage.modal.name_placeholder')"
          />
        </label>

        <label class="account-field">
          <span>{{ t('account.settings_stage.modal.visibility_label') }}</span>
          <select v-model="settingsProjectForm.visibility">
            <option value="private">{{ t('account.visibility.private') }}</option>
            <option value="public">{{ t('account.visibility.public') }}</option>
          </select>
        </label>

        <div class="settings-project-modal__grid">
          <label class="account-field">
            <span>{{ t('account.settings_stage.modal.customer_type_label') }}</span>
            <select v-model="settingsProjectForm.customerType">
              <option value="">{{ t('account.settings_stage.modal.type_unset') }}</option>
              <option v-for="type in customerTypeOptions" :key="type" :value="type">{{ type }}</option>
            </select>
          </label>
          <label class="account-field">
            <span>{{ t('account.settings_stage.modal.trade_count_label') }}</span>
            <input v-model="settingsProjectForm.tradeCount" type="number" min="0" placeholder="0" />
          </label>
          <label class="account-field">
            <span>{{ t('account.settings_stage.modal.last_trade_at_label') }}</span>
            <input v-model="settingsProjectForm.lastTradeAt" type="datetime-local" />
          </label>
          <label class="account-field">
            <span>{{ t('account.settings_stage.modal.avg_unit_price_label') }}</span>
            <input v-model="settingsProjectForm.avgUnitPrice" type="number" min="0" placeholder="1800" />
          </label>
          <label class="account-field">
            <span>{{ t('account.settings_stage.modal.region_label') }}</span>
            <input
              v-model="settingsProjectForm.region"
              type="text"
              :placeholder="t('account.settings_stage.modal.region_placeholder')"
            />
          </label>
        </div>

        <label class="account-field">
          <span>{{ t('account.settings_stage.modal.description_label') }}</span>
          <textarea
            v-model="settingsProjectForm.preferenceNote"
            rows="4"
            :placeholder="t('account.settings_stage.modal.description_placeholder')"
          />
        </label>

        <p v-if="settingsProjectModalError" class="account-form-error">{{ settingsProjectModalError }}</p>
      </div>
      <footer class="account-role-modal__footer">
        <div class="account-role-modal__actions">
          <button type="button" class="account-btn account-btn--ghost" @click="closeSettingsCreateProjectModal">
            {{ t('common.actions.cancel') }}
          </button>
          <button
            type="button"
            class="account-btn account-btn--primary"
            :disabled="settingsProjectSubmitting"
            @click="submitSettingsProject"
          >
            {{ settingsProjectSubmitting ? t('common.actions.processing') : t('common.actions.add') }}
          </button>
        </div>
      </footer>
    </div>
  </div>

  <div v-if="isRoleModalOpen" class="account-modal-mask" role="dialog" aria-modal="true">
    <div class="account-role-modal">
      <header class="account-role-modal__header">
        <h3>{{ roleModalTitle }}</h3>
        <button type="button" class="account-modal-close" @click="dismissModal">
          <span v-html="glyphs.close" aria-hidden="true" />
        </button>
      </header>

      <div class="account-role-modal__body">
        <section class="account-role-modal__section">
          <h4>{{ t('account.headings.basic_settings') }}</h4>
          <label class="account-field">
            <span><em>*</em> {{ t('account.form.role_name_label') }}</span>
            <div class="account-field__input-wrap">
              <input v-model="roleForm.name" type="text" maxlength="15" :placeholder="t('account.form.input_placeholder')" />
              <small>{{ roleNameCount }}/15</small>
            </div>
          </label>

          <div class="account-radio-group">
            <span><em>*</em> {{ t('account.headings.default_conversation_access') }}</span>
            <label>
              <input v-model="roleForm.conversationVisibility" type="radio" value="private" />
              <span>{{ t('account.visibility.private') }}</span>
            </label>
            <label>
              <input v-model="roleForm.conversationVisibility" type="radio" value="public" />
              <span>{{ t('account.visibility.public') }}</span>
            </label>
          </div>
        </section>

        <section class="account-role-modal__section">
          <h4>{{ t('account.headings.permission_settings') }}</h4>
          <div class="account-permission-table">
            <div class="account-permission-table__head">{{ t('account.headings.menu_name') }}</div>
            <div
              v-for="item in rolePermissionGroups"
              :key="item.id"
              class="account-permission-row"
            >
              <label class="account-permission-row__label">
                <span v-if="item.children" class="account-permission-row__arrow" v-html="glyphs.chevron" aria-hidden="true" />
                <input
                  type="checkbox"
                  :checked="isPermissionSelected(getRowCodes(item))"
                  @change="togglePermissionRow(item, $event)"
                />
                <span>{{ item.label }}</span>
              </label>

              <div v-if="item.children" class="account-permission-row__children">
                <label
                  v-for="child in item.children"
                  :key="child.id"
                  class="account-permission-row__label is-child"
                >
                  <input
                    type="checkbox"
                    :checked="isPermissionSelected(getRowCodes(child))"
                    @change="togglePermissionRow(child, $event)"
                  />
                  <span>{{ child.label }}</span>
                </label>
              </div>
            </div>
          </div>
          <p v-if="roleFormError" class="account-form-error">{{ roleFormError }}</p>
        </section>
      </div>

      <footer class="account-role-modal__footer">
        <button
          v-if="activeModal === 'role-edit'"
          type="button"
          class="account-link is-danger account-role-modal__delete"
          @click="openRoleDeleteModal({ fromEdit: true })"
        >
          <span v-html="glyphs.trash" aria-hidden="true" />
          {{ t('account.modals.role_delete.title') }}
        </button>
        <div class="account-role-modal__actions">
          <button type="button" class="account-btn account-btn--ghost" @click="dismissModal">{{ t('account.actions.cancel') }}</button>
          <button
            type="button"
            class="account-btn account-btn--primary"
            :disabled="!isRoleFormValid || roleSubmitting"
            @click="submitRoleForm"
          >
            {{ roleSubmitLabel }}
          </button>
        </div>
      </footer>
    </div>
  </div>

  <div v-if="activeModal === 'role-delete' && selectedRole" class="account-modal-mask" role="dialog" aria-modal="true">
    <div class="account-confirm-modal">
      <header class="account-confirm-modal__header">
        <h3>{{ t('account.modals.role_delete.title') }}</h3>
        <button type="button" class="account-modal-close" @click="closeModal">
          <span v-html="glyphs.close" aria-hidden="true" />
        </button>
      </header>
      <p class="account-confirm-modal__body">
        {{ t('account.modals.role_delete.body') }}
      </p>
      <p v-if="roleFormError" class="account-form-error account-confirm-modal__error">{{ roleFormError }}</p>
      <footer class="account-confirm-modal__actions">
        <button type="button" class="account-btn account-btn--ghost" @click="closeModal">{{ t('account.actions.cancel') }}</button>
        <button
          type="button"
          class="account-btn account-btn--danger"
          :disabled="roleSubmitting"
          @click="confirmRoleDelete"
        >
          {{ t('account.actions.delete') }}
        </button>
      </footer>
    </div>
  </div>

  <div v-if="isUserModalOpen" class="account-modal-mask" role="dialog" aria-modal="true">
    <div class="account-user-modal">
      <header class="account-role-modal__header">
        <h3>{{ activeModal === 'user-create' ? t('account.modals.member_create.title') : t('account.modals.member_edit.title') }}</h3>
        <button type="button" class="account-modal-close" @click="dismissModal">
          <span v-html="glyphs.close" aria-hidden="true" />
        </button>
      </header>
      <div class="account-role-modal__body">
        <label class="account-field">
          <span><em>*</em> {{ t('account.form.member_name_label') }}</span>
          <input v-model="userForm.name" type="text" :placeholder="t('account.form.member_name_placeholder')" />
        </label>
        <label class="account-field">
          <span><em>*</em> {{ t('account.form.account_label') }}</span>
          <input v-model="userForm.username" type="text" :placeholder="t('account.form.account_placeholder')" :disabled="activeModal === 'user-edit'" />
        </label>
        <label class="account-field">
          <span>{{ t('account.form.email_label') }}</span>
          <input v-model="userForm.email" type="email" :placeholder="t('account.form.email_placeholder')" />
        </label>
        <label class="account-field">
          <span>{{ activeModal === 'user-create' ? `* ${t('account.form.password_label')}` : t('account.form.new_password_label') }}</span>
          <input
            v-model="userForm.password"
            type="password"
            :placeholder="activeModal === 'user-create' ? t('account.form.password_placeholder') : t('account.form.new_password_placeholder')"
          />
        </label>
        <label class="account-field">
          <span><em>*</em> {{ t('account.form.role_label') }}</span>
          <select v-model="userForm.role">
            <option disabled value="">{{ t('account.form.select_placeholder') }}</option>
            <option v-for="role in assignableRoleOptions" :key="role" :value="role">{{ role }}</option>
          </select>
        </label>
        <p v-if="userSetupStatus" class="account-form-success">{{ userSetupStatus }}</p>
        <p v-if="userFormError" class="account-form-error">{{ userFormError }}</p>
      </div>
      <footer class="account-role-modal__footer">
        <button
          v-if="activeModal === 'user-edit'"
          type="button"
          class="account-link is-danger account-role-modal__delete"
          @click="openUserDeleteModal({ fromEdit: true })"
        >
          <span v-html="glyphs.trash" aria-hidden="true" />
          {{ t('account.modals.member_delete.title') }}
        </button>
        <div class="account-role-modal__actions">
          <button
            v-if="activeModal === 'user-edit'"
            type="button"
            class="account-btn account-btn--ghost"
            :disabled="!canSendSetupEmail || setupEmailSubmitting"
            @click="handleSendSetupEmail"
          >
            {{ setupEmailSubmitting ? t('common.actions.sending') : t('account.form.send_setup_email') }}
          </button>
          <button type="button" class="account-btn account-btn--ghost" @click="dismissModal">{{ t('account.actions.cancel') }}</button>
          <button
            type="button"
            class="account-btn account-btn--primary"
            :disabled="!isUserFormValid || userSubmitting"
            @click="submitUserForm"
          >
            {{ activeModal === 'user-create' ? t('account.actions.add') : t('account.actions.confirm') }}
          </button>
        </div>
      </footer>
    </div>
  </div>

  <div v-if="activeModal === 'user-delete' && selectedUser" class="account-modal-mask" role="dialog" aria-modal="true">
    <div class="account-confirm-modal">
      <header class="account-confirm-modal__header">
        <h3>{{ t('account.modals.member_delete.title') }}</h3>
        <button type="button" class="account-modal-close" @click="closeModal">
          <span v-html="glyphs.close" aria-hidden="true" />
        </button>
      </header>
      <p class="account-confirm-modal__body">
        {{ t('account.modals.member_delete.body') }}
      </p>
      <p v-if="userFormError" class="account-form-error account-confirm-modal__error">{{ userFormError }}</p>
      <footer class="account-confirm-modal__actions">
        <button type="button" class="account-btn account-btn--ghost" @click="closeModal">{{ t('account.actions.cancel') }}</button>
        <button
          type="button"
          class="account-btn account-btn--danger"
          :disabled="userSubmitting"
          @click="confirmUserDelete"
        >
          {{ t('account.actions.delete') }}
        </button>
      </footer>
    </div>
  </div>

</template>

<style scoped>
.account-dev-stage {
  position: relative;
  background:
    radial-gradient(circle at top left, rgba(237, 106, 75, 0.08), transparent 22%),
    linear-gradient(180deg, #f5f7fb 0%, #eff3f8 100%);
}

.account-dev-main {
  padding: 24px 48px 48px;
}

.account-dev-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 6px 0 28px;
}

.account-dev-hero h1 {
  margin: 0;
  font-size: 42px;
  line-height: 1.1;
  color: #1f2937;
}

.account-dev-tabs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.account-dev-tabs__item {
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.24);
  color: #4b5563;
  font-weight: 600;
}

.account-dev-tabs__item.is-active {
  background: #fff4f1;
  border-color: rgba(85, 183, 127, 0.22);
  color: #55b77f;
}

.account-dev-primary {
  min-width: 118px;
  height: 42px;
  padding: 0 16px;
  border-radius: 10px;
  background: #55b77f;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-shadow: 0 6px 16px rgba(85, 183, 127, 0.18);
}

.account-dev-search-bar,
.account-dev-table,
.account-dev-pagination,
.settings-stage {
  width: 1080px;
  max-width: 100%;
  margin: 0 auto;
}

.account-dev-search-bar {
  padding: 0 0 14px;
}

.account-top-search,
.account-dev-search {
  width: min(300px, 100%);
  height: 44px;
  border-radius: var(--ys-control-radius, 6px);
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.22);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
}

.account-top-search__icon,
.account-dev-search__icon {
  display: inline-flex;
}

.account-top-search input,
.account-dev-search input,
.account-field input,
.account-field select {
  width: 100%;
  border: 0;
  background: transparent;
  color: #1f2937;
  font-size: 14px;
  outline: none;
}

.account-dev-table {
  min-height: 340px;
}

.account-role-table__head,
.account-user-table__head,
.account-role-row,
.account-user-row {
  display: grid;
  grid-template-columns: 1.2fr 1.4fr 1fr 0.7fr 1.4fr;
  gap: 16px;
  align-items: center;
  padding: 18px 20px;
}

.account-user-table__head,
.account-user-row {
  grid-template-columns: 1.1fr 1.5fr 1fr 1.3fr 1fr;
}

.account-role-table__head,
.account-user-table__head {
  background: #f3f6fa;
  color: #667085;
  font-size: 13px;
  font-weight: 700;
}

.account-role-row,
.account-user-row {
  width: 100%;
  text-align: left;
  border-bottom: 1px solid #eef2f7;
  background: transparent;
  color: #344054;
  font-size: 14px;
  cursor: pointer;
}

.account-role-row:hover,
.account-user-row:hover {
  background: #fcfdfd;
}

.account-role-row__status {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.account-role-switch {
  width: 26px;
  height: 16px;
  border-radius: 999px;
  background: #d7dde7;
  position: relative;
  flex-shrink: 0;
}

.account-role-switch span {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s ease;
}

.account-role-switch-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.account-role-switch-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.account-role-switch.is-on {
  background: #55b77f;
}

.account-role-switch.is-on span {
  transform: translateX(10px);
}

.is-muted {
  color: #98a2b3;
}

.account-user-row__actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #98a2b3;
}

.account-link {
  color: #344054;
  font-size: 13px;
  font-weight: 600;
}

.account-link.is-danger,
.account-form-error {
  color: #d92d20;
}

.account-form-success {
  color: #0f6c45;
}

.account-link:disabled {
  color: #c0c6d0;
  cursor: not-allowed;
}

.account-dev-table__status {
  padding: 32px 20px;
  color: #667085;
  text-align: center;
}

.account-dev-table__status.is-error {
  color: #d92d20;
}

.account-dev-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 20px;
  padding: 16px 20px 18px;
  color: #667085;
  font-size: 13px;
}

.account-dev-pagination__size {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.account-dev-pagination__nav {
  display: inline-flex;
  gap: 8px;
}

.account-dev-pagination__nav button {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid rgba(148, 163, 184, 0.24);
  color: #667085;
}

.account-dev-pagination__nav button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.account-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.26);
  display: grid;
  place-items: center;
  z-index: 50;
  padding: 20px;
}

.account-role-modal,
.account-user-modal,
.account-confirm-modal {
  width: min(100%, 640px);
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.16);
}

.account-user-modal {
  width: min(100%, 520px);
}

.account-confirm-modal {
  width: min(100%, 680px);
}

.account-role-modal__header,
.account-confirm-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 14px;
  border-bottom: 1px solid #edf1f6;
}

.account-role-modal__header h3,
.account-confirm-modal__header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #212b36;
}

.account-modal-close {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: grid;
  place-items: center;
}

.account-role-modal__body {
  padding: 16px 22px 20px;
  display: grid;
  gap: 16px;
}

.account-role-modal__section h4 {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 700;
  color: #212b36;
}

.account-field {
  display: grid;
  gap: 6px;
}

.account-field > span,
.account-radio-group > span {
  font-size: 12px;
  font-weight: 600;
  color: #7a879c;
}

.account-field em,
.account-radio-group em {
  color: #ed6a4b;
  font-style: normal;
}

.account-field__input-wrap {
  min-height: 40px;
  border: 1px solid #e3e8f1;
  border-radius: var(--ys-control-radius, 6px);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
}

.account-field input,
.account-field select {
  min-height: 40px;
  border: 1px solid #e3e8f1;
  border-radius: var(--ys-control-radius, 6px);
  padding: 0 12px;
}

.account-field__input-wrap input {
  min-height: 0;
  border: 0;
  padding: 0;
}

.account-field__input-wrap small {
  color: #98a2b3;
  font-size: 12px;
}

.account-radio-group {
  display: grid;
  gap: 10px;
}

.account-radio-group input {
  accent-color: #55b77f;
}

.account-radio-group label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-right: 24px;
  color: #344054;
  font-size: 14px;
}

.account-permission-table {
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #edf1f6;
}

.account-permission-table__head {
  padding: 12px 16px;
  background: #f5f7fb;
  color: #7a879c;
  font-size: 12px;
  font-weight: 600;
}

.account-permission-row {
  border-top: 1px solid #edf1f6;
}

.account-permission-row__label {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  color: #344054;
  font-size: 14px;
  font-weight: 500;
}

.account-permission-row__arrow {
  width: 12px;
  display: inline-flex;
}

.account-permission-row__children {
  border-top: 1px solid #edf1f6;
}

.account-permission-row__label.is-child {
  padding-left: 40px;
  border-top: 1px solid #edf1f6;
}

.account-permission-row input[type='checkbox'] {
  accent-color: #55b77f;
}

.account-role-modal__footer,
.account-confirm-modal__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 22px 18px;
}

.account-role-modal__actions,
.account-confirm-modal__actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.account-role-modal__delete {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.account-btn {
  min-width: 76px;
  height: 36px;
  padding: 0 14px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
}

.account-btn--ghost {
  border: 1px solid #d0d5dd;
  color: #344054;
  background: #fff;
}

.account-btn--primary {
  background: #55b77f;
  color: #fff;
}

.account-btn--danger {
  background: #ff5a3d;
  color: #fff;
}

.account-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.account-confirm-modal__body {
  padding: 34px 28px 0;
  margin: 0;
  font-size: 18px;
  line-height: 1.7;
  color: #637381;
}

.account-confirm-modal__error {
  padding: 0 28px;
}

.settings-stage {
  display: grid;
  gap: 18px;
  padding: 8px 0 18px;
  background: transparent;
}

.settings-stage__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.settings-stage__hero p {
  margin: 0;
  color: #7a879c;
  font-size: 13px;
  font-weight: 600;
}

.settings-stage__create {
  min-width: 118px;
  height: 40px;
  padding: 0 16px;
  border-radius: 10px;
  background: #55b77f;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-shadow: 0 6px 16px rgba(85, 183, 127, 0.18);
}

.settings-stage__card {
  border-radius: 26px;
  border: 1px solid #dce4ee;
  background: #fff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.07);
  overflow: hidden;
}

.knowledge-card {
  overflow: visible;
}

.knowledge-panel {
  display: grid;
  gap: 16px;
  padding: 18px 22px 22px;
}

.knowledge-panel__form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: end;
}

.knowledge-panel__form.is-wide {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.knowledge-panel__form label {
  display: grid;
  gap: 6px;
  color: #667085;
  font-size: 12px;
  font-weight: 700;
}

.knowledge-panel__form input,
.knowledge-panel__form select,
.knowledge-panel__form textarea {
  width: 100%;
  border: 1px solid #dce4ee;
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  color: #263847;
  font-size: 14px;
  padding: 10px 12px;
  outline: none;
}

.knowledge-panel__form textarea {
  resize: vertical;
}

.knowledge-panel__file {
  align-self: stretch;
}

.knowledge-panel__status {
  margin: 0;
  color: #0f6c45;
  font-size: 13px;
  font-weight: 700;
}

.knowledge-panel__status.is-error {
  color: #d92d20;
}

.knowledge-panel__list {
  display: grid;
  gap: 10px;
}

.knowledge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 54px;
  padding: 10px 12px;
  border: 1px solid #edf1f6;
  border-radius: 6px;
  background: #f8fbf9;
}

.knowledge-row strong,
.knowledge-row small {
  display: block;
}

.knowledge-row strong {
  color: #263847;
  font-size: 14px;
}

.knowledge-row small {
  margin-top: 3px;
  color: #667085;
  font-size: 12px;
}

.knowledge-row button {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid #dce4ee;
  color: #263847;
  background: #fff;
  font-size: 12px;
  font-weight: 700;
}

.knowledge-row button:disabled,
.settings-stage__create:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.settings-stage__tabs {
  display: flex;
  gap: 30px;
  padding: 0 22px;
  border-bottom: 1px solid #e9eef5;
}

.settings-stage__tab {
  position: relative;
  min-height: 56px;
  padding: 0;
  color: #667085;
  font-size: 14px;
  font-weight: 700;
  background: transparent;
}

.settings-stage__tab::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  border-radius: 999px;
  background: transparent;
}

.settings-stage__tab.is-active {
  color: #212b36;
}

.settings-stage__tab.is-active::after {
  background: #55b77f;
}

.settings-stage__toolbar {
  padding: 14px 22px;
  border-bottom: 1px solid #eef2f7;
}

.settings-stage__search {
  width: min(100%, 230px);
  min-height: 32px;
  border-radius: var(--ys-control-radius, 6px);
  border: 1px solid #dce4ee;
  background: #fff;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
}

.settings-stage__search input {
  width: 100%;
  min-height: 30px;
  border: 0;
  background: transparent;
  color: #344054;
  font-size: 13px;
  outline: none;
}

.settings-stage__search input::placeholder {
  color: #98a2b3;
}

.settings-stage__search-icon {
  display: inline-flex;
}

.settings-stage__table-wrap {
  min-height: 440px;
}

.settings-stage__head,
.settings-stage__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 24px;
  align-items: center;
  padding: 0 22px;
}

.settings-stage__head {
  min-height: 42px;
  background: #f3f5f8;
  color: #667085;
  font-size: 13px;
  font-weight: 700;
}

.settings-stage__row {
  width: 100%;
  min-height: 54px;
  text-align: left;
  border-bottom: 1px solid #eef2f7;
  color: #344054;
  background: transparent;
  transition: background-color 0.18s ease;
}

.settings-stage__row:hover {
  background: #fafbfc;
}

.settings-stage__topic {
  font-size: 14px;
  line-height: 1.5;
}

.settings-stage__time {
  color: #475467;
  font-size: 14px;
}

.settings-stage__state {
  min-height: 320px;
  display: grid;
  place-items: center;
  padding: 24px;
  text-align: center;
  color: #667085;
  font-size: 14px;
}

.settings-stage__state.is-error {
  color: #d92d20;
}

.settings-stage__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 20px;
  min-height: 54px;
  padding: 0 22px;
  color: #667085;
  font-size: 13px;
}

.settings-stage__page-size {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.settings-stage__range {
  min-width: 74px;
  text-align: center;
}

.settings-stage__pager {
  display: inline-flex;
  gap: 8px;
}

.settings-stage__pager button {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: #fff;
  color: #475467;
  font-size: 14px;
}

.settings-stage__pager button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.settings-project-modal {
  width: min(100%, 720px);
}

.settings-project-modal__header h3 {
  font-size: 20px;
}

.settings-project-modal__body {
  gap: 18px;
}

.settings-project-modal__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.settings-project-modal__switch {
  align-content: start;
}

.settings-project-modal__switch input {
  width: 18px;
  min-height: 18px;
  padding: 0;
  border: 0;
  accent-color: #55b77f;
}

.account-field textarea {
  width: 100%;
  min-height: 104px;
  border: 1px solid #e3e8f1;
  border-radius: var(--ys-control-radius, 6px);
  padding: 12px;
  background: #fff;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}

.account-settings-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}

.account-settings-card {
  border: 1px solid #e5e7eb;
  border-radius: 24px;
  background: #f8fafc;
  padding: 24px;
}

.account-settings-card h3 {
  margin: 0 0 12px;
  color: #263847;
  font-size: 20px;
}

.account-settings-card__copy {
  margin: 0;
  color: #637381;
  line-height: 1.7;
}

.account-settings-card__button {
  margin-top: 20px;
}

.account-settings-card__rows {
  display: grid;
  gap: 14px;
}

.account-settings-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #dbe3ed;
  padding-bottom: 12px;
  color: #475467;
}

.account-settings-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.account-settings-row strong {
  color: #0f172a;
}

.account-settings-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.account-settings-chip {
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid #dbe3ed;
  padding: 8px 12px;
  color: #263847;
  font-weight: 600;
}

.account-settings-list {
  margin: 16px 0 0;
  padding-left: 18px;
  color: #475467;
  line-height: 1.8;
}

@media (max-width: 960px) {
  .account-dev-main {
    padding: 20px 18px 28px;
  }

  .account-dev-hero {
    flex-direction: column;
    align-items: stretch;
  }

  .account-role-table__head,
  .account-user-table__head,
  .account-role-row,
  .account-user-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .account-role-table__head,
  .account-user-table__head {
    display: none;
  }

  .account-dev-pagination {
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .settings-stage {
    padding-left: 0;
    padding-right: 0;
  }

  .settings-stage__hero {
    flex-direction: column;
    align-items: stretch;
  }

  .settings-stage__create {
    align-self: flex-end;
  }

  .settings-stage__head,
  .settings-stage__row {
    grid-template-columns: 1fr 150px;
  }

  .settings-project-modal__grid {
    grid-template-columns: 1fr;
  }

  .account-settings-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .account-role-modal,
  .account-user-modal,
  .account-confirm-modal {
    width: 100%;
  }

  .account-role-modal__header,
  .account-confirm-modal__header,
  .account-role-modal__body,
  .account-role-modal__footer,
  .account-confirm-modal__actions {
    padding-left: 20px;
    padding-right: 20px;
  }

  .account-role-modal__header h3,
  .account-confirm-modal__header h3,
  .account-role-modal__section h4 {
    font-size: 24px;
  }

  .settings-stage__tabs {
    gap: 20px;
    padding-left: 16px;
    padding-right: 16px;
  }

  .settings-stage__toolbar,
  .settings-stage__head,
  .settings-stage__row,
  .settings-stage__footer {
    padding-left: 16px;
    padding-right: 16px;
  }

  .settings-stage__head,
  .settings-stage__row {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .settings-stage__footer {
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .settings-stage__create {
    width: 100%;
  }
}
</style>
