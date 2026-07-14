<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import logoMain from '../assets/ysLogo_transparent.png'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import iconDrag from '../assets/ic_drag.svg'
import iconMoreVertical from '../assets/ic-more-vertical.svg'
import iconUpDown from '../assets/ic-ud.svg'
import iconFileCsv from '../assets/f-csv.svg'
import iconFileDoc from '../assets/f-doc.svg'
import iconFileDocx from '../assets/f-docx.svg'
import iconFileGenericDoc from '../assets/f-file.svg'
import iconFilePdf from '../assets/f-pdf.svg'
import iconFilePpt from '../assets/f-ppt.svg'
import iconFilePptx from '../assets/f-pptx.svg'
import iconFileTxt from '../assets/f-txt.svg'
import iconFileXls from '../assets/f-xls.svg'
import iconFileXlsx from '../assets/f-xlsx.svg'
import iconFileGeneric from '../assets/ic-file.svg'
import uploadIllustration from '../assets/file-upload-illustration.svg'
import emptyIllustration from '../assets/Table No data.svg'
import AppSidebar from '../components/AppSidebar.vue'
import FileResourceSortControls from '../components/FileResourceSortControls.vue'
import AppTopBar from '../components/AppTopBar.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { useAuth } from '../composables/useAuth'
import { useFileUploader } from '../composables/useFileUploader'
import {
  createDocumentResource,
  createImageResource,
  createWineLabelResource,
  deleteFileResource,
  fetchFileResourceDepartments,
  fetchFileResourceDetail,
  fetchFileResourcePreview,
  fetchFileResources,
  searchCerpProducts,
  updateFileResource,
  updateWineLabelResource,
} from '../services/ysApi'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'

const router = useRouter()
const { t, locale } = useI18n()
const { isAuthenticated, avatarLabel, userProfile } = useAuth()

const TYPE_WINE = 'wine_label'
const TYPE_IMAGE = 'image'
const TYPE_DOCUMENT = 'document'
const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const TABLET_BREAKPOINT = 900
const PAGE_SIZE = 10
const PREVIEW_INFO_STORAGE_KEY = 'ys-file-resources-preview-info-open'
const IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']
const DOCUMENT_EXTS = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'ppt', 'pptx', 'txt']

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7a879c" stroke-width="2"/><path d="M12.5 12.5 16 16" stroke="#7a879c" stroke-width="2" stroke-linecap="round"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#263847" stroke-width="2" stroke-linecap="round"/></svg>',
  plus:
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  chevronDown:
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m5 7.5 5 5 5-5" stroke="#212B36" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  previewPrev:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m12.5 4.5-6 5.5 6 5.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  previewNext:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m7.5 4.5 6 5.5-6 5.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  previewDownload:
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10 3v8m0 0 3-3m-3 3-3-3M4 14.5v.5A2 2 0 0 0 6 17h8a2 2 0 0 0 2-2v-.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  previewEdit:
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m13.8 4.2 2 2M5 15l2.8-.5 7.3-7.3a1.4 1.4 0 0 0 0-2l-.3-.3a1.4 1.4 0 0 0-2 0L5.5 12.2 5 15Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  previewDelete:
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4.5 6h11m-8.5 0V4.8c0-.7.6-1.3 1.3-1.3h3.4c.7 0 1.3.6 1.3 1.3V6m-6.8 0 .5 8.3c0 .7.6 1.2 1.3 1.2h3.4c.7 0 1.3-.5 1.3-1.2L13.5 6m-4.5 3v3.8m3-3v3.8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  previewInfo:
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.7"/><path d="M10 8.2v4.6M10 6.2h.01" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  previewClose:
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
}

const documentIconMap = {
  csv: iconFileCsv,
  doc: iconFileDoc,
  docx: iconFileDocx,
  pdf: iconFilePdf,
  ppt: iconFilePpt,
  pptx: iconFilePptx,
  txt: iconFileTxt,
  xls: iconFileXls,
  xlsx: iconFileXlsx,
}

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'home.nav'))
const iconImages = PRIMARY_NAV_ICON_IMAGES

const stageWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1440)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isTablet = computed(() => stageWidth.value <= TABLET_BREAKPOINT)
const isSidebarCollapsed = ref(stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const activeNavId = ref('file-resources')
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet,
    isSidebarCollapsed,
  })

const searchQuery = ref('')
const debouncedQuery = ref('')
const currentPage = ref(1)
const activeTab = ref(TYPE_WINE)
const sortRules = ref([])
const sortGrouping = ref(false)
const isSortPanelOpen = ref(false)
const resources = ref([])
const total = ref(0)
const isLoading = ref(false)
const loadError = ref('')
const noticeMessage = ref('')
const activeRowMenuId = ref('')
const isUploadMenuOpen = ref(false)
const isUploadModalOpen = ref(false)
const isWinePickerOpen = ref(false)
const isPermissionModalOpen = ref(false)
const isSubmitting = ref(false)
const isDeleting = ref(false)
const formError = ref('')
const uploadSubmitError = ref('')
const deleteError = ref('')
const permissionError = ref('')
const wineSearchQuery = ref('')
const wineResults = ref([])
const isWineSearchLoading = ref(false)
const wineSearchError = ref('')
const selectedWineCandidateId = ref('')
const selectedWine = ref(null)
const familyProducts = ref([])
const previewUrls = ref({})
const previewDetailMap = ref({})
const previewFamilyProducts = ref([])
const modalMode = ref('create')
const editingResource = ref(null)
const deleteTarget = ref(null)
const isDeleteModalOpen = ref(false)
const isPreviewOpen = ref(false)
const activePreviewId = ref('')
const activePreviewIndex = ref(-1)
const isPreviewLoading = ref(false)
const previewLoadError = ref('')
const uploadMenuRef = ref(null)
const uploadMenuButtonRef = ref(null)
const sortControlsRef = ref(null)
const permissionTarget = ref(null)
const uploadType = ref(TYPE_WINE)
const departments = ref([])
let searchTimer = 0
let wineSearchRequestToken = 0
let previewRequestToken = 0
let sortRuleSeed = 0
const libraryDropDepth = ref(0)
const isLibraryDropActive = ref(false)

const uploadMessages = () => ({
  fileTypeNotAllowed: ({ extension, allowed }) =>
    t('fileResources.errors.unsupported_extension', {
      extension: extension || 'unknown',
      allowed: allowed.join(', ').toUpperCase(),
    }),
  fileTooLarge: ({ filename, maxMb }) =>
    t('fileResources.errors.file_too_large', { filename, maxMb }),
  payloadTooLarge: ({ maxMb }) =>
    t('fileResources.errors.upload_too_large', { maxMb }),
  uploadFailed: () => t('fileResources.errors.upload_failed'),
  uploading: ({ filename }) => t('fileResources.states.uploading_file', { filename }),
})

const wineUploader = useFileUploader({
  allowedExtensions: ['jpg', 'jpeg', 'png', 'webp'],
  messages: uploadMessages(),
})
const imageUploader = useFileUploader({
  allowedExtensions: IMAGE_EXTS,
  messages: uploadMessages(),
})
const documentUploader = useFileUploader({
  allowedExtensions: DOCUMENT_EXTS,
  messages: uploadMessages(),
})

const sharedForm = reactive({
  department_role: '',
  visibility: 'public',
})
const permissionForm = reactive({
  department_role: '',
  visibility: 'public',
})

const currentRole = computed(() => String(userProfile.value?.role || '').trim())

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const canGoPrev = computed(() => currentPage.value > 1)
const canGoNext = computed(() => currentPage.value < totalPages.value)
const rangeLabel = computed(() => {
  if (!resources.value.length) return `0-0 / ${total.value}`
  const start = (currentPage.value - 1) * PAGE_SIZE + 1
  const end = start + resources.value.length - 1
  return `${start}-${Math.min(total.value, end)} / ${total.value}`
})

const tabs = computed(() => [
  { key: TYPE_WINE, label: t('fileResources.tabs.wine_label') },
  { key: TYPE_IMAGE, label: t('fileResources.tabs.image') },
  { key: TYPE_DOCUMENT, label: t('fileResources.tabs.document') },
])

const sortConfigByType = computed(() => ({
  [TYPE_WINE]: {
    groupBy: 'producer',
    groupingLabel: t('fileResources.sort.group_by_producer'),
    defaultRules: [{ field: 'uploaded_at', direction: 'desc' }],
    fields: [
      {
        value: 'uploaded_at',
        label: t('fileResources.sort.fields.uploaded_at'),
        directions: {
          asc: t('fileResources.sort.directions.oldest_first'),
          desc: t('fileResources.sort.directions.newest_first'),
        },
      },
      {
        value: 'display_name',
        label: t('fileResources.sort.fields.display_name'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'producer',
        label: t('fileResources.sort.fields.producer'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'cerp_code_full',
        label: t('fileResources.sort.fields.product_code'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
    ],
  },
  [TYPE_IMAGE]: {
    groupBy: 'department_role',
    groupingLabel: t('fileResources.sort.group_by_department'),
    defaultRules: [{ field: 'uploaded_at', direction: 'desc' }],
    fields: [
      {
        value: 'uploaded_at',
        label: t('fileResources.sort.fields.uploaded_at'),
        directions: {
          asc: t('fileResources.sort.directions.oldest_first'),
          desc: t('fileResources.sort.directions.newest_first'),
        },
      },
      {
        value: 'display_name',
        label: t('fileResources.sort.fields.display_name'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'department_role',
        label: t('fileResources.sort.fields.department'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'attachment_mime',
        label: t('fileResources.sort.fields.file_type'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'visibility',
        label: t('fileResources.sort.fields.visibility'),
        directions: {
          asc: t('fileResources.sort.directions.public_private'),
          desc: t('fileResources.sort.directions.private_public'),
        },
      },
    ],
  },
  [TYPE_DOCUMENT]: {
    groupBy: 'department_role',
    groupingLabel: t('fileResources.sort.group_by_department'),
    defaultRules: [{ field: 'uploaded_at', direction: 'desc' }],
    fields: [
      {
        value: 'uploaded_at',
        label: t('fileResources.sort.fields.uploaded_at'),
        directions: {
          asc: t('fileResources.sort.directions.oldest_first'),
          desc: t('fileResources.sort.directions.newest_first'),
        },
      },
      {
        value: 'display_name',
        label: t('fileResources.sort.fields.display_name'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'department_role',
        label: t('fileResources.sort.fields.department'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'attachment_mime',
        label: t('fileResources.sort.fields.file_type'),
        directions: {
          asc: t('fileResources.sort.directions.a_z'),
          desc: t('fileResources.sort.directions.z_a'),
        },
      },
      {
        value: 'visibility',
        label: t('fileResources.sort.fields.visibility'),
        directions: {
          asc: t('fileResources.sort.directions.public_private'),
          desc: t('fileResources.sort.directions.private_public'),
        },
      },
    ],
  },
}))

const activeSortConfig = computed(() => sortConfigByType.value[activeTab.value] || null)
const sortFieldOptions = computed(() => activeSortConfig.value?.fields || [])
const sortGroupLabel = computed(
  () => activeSortConfig.value?.groupingLabel || t('fileResources.sort.placeholder')
)

const createSortRule = (field, direction) => {
  sortRuleSeed += 1
  return {
    id: sortRuleSeed,
    field,
    direction,
  }
}

const cloneSortRules = (rules = []) =>
  rules.map((rule) => createSortRule(rule.field, rule.direction))

const getSortFieldDefinition = (field) =>
  activeSortConfig.value?.fields.find((item) => item.value === field) || null

const resolveDefaultDirection = (field) => {
  if (field === 'uploaded_at') return 'desc'
  return Object.keys(getSortFieldDefinition(field)?.directions || {})[0] || 'asc'
}

const resolveSortFieldLabel = (field) =>
  getSortFieldDefinition(field)?.label || t('fileResources.sort.placeholder')

const resolveDirectionLabel = (field, direction) =>
  getSortFieldDefinition(field)?.directions?.[direction] || t('fileResources.sort.placeholder')

const buildSortToken = (rule) => {
  const field = String(rule?.field || '').trim()
  const direction = String(rule?.direction || '').trim()
  if (!field || !direction) return ''
  if (field === 'uploaded_at') {
    return direction === 'asc' ? 'uploaded_asc' : 'uploaded_desc'
  }
  return `${field}_${direction}`
}

const fallbackSortSummary = computed(() => {
  const fallbackRule = activeSortConfig.value?.defaultRules?.[0]
  if (!fallbackRule) return t('fileResources.sort.placeholder')
  return t('fileResources.sort.single', {
    field: resolveSortFieldLabel(fallbackRule.field),
    direction: resolveDirectionLabel(fallbackRule.field, fallbackRule.direction),
  })
})

const sortSummaryLabel = computed(() => {
  const count = sortRules.value.length
  if (!count) return fallbackSortSummary.value
  if (count === 1) {
    const solo = sortRules.value[0]
    return t('fileResources.sort.single', {
      field: resolveSortFieldLabel(solo.field),
      direction: resolveDirectionLabel(solo.field, solo.direction),
    })
  }
  return t('fileResources.sort.count', { count })
})

const activeSortTokens = computed(() => {
  if (!sortRules.value.length) {
    return activeSortConfig.value?.defaultRules.map(buildSortToken).filter(Boolean) || ['uploaded_desc']
  }
  return sortRules.value.map(buildSortToken).filter(Boolean)
})

const activeGroupBy = computed(() =>
  sortGrouping.value ? activeSortConfig.value?.groupBy || '' : ''
)

const sortRequestKey = computed(() => activeSortTokens.value.join('|'))

const activeUploader = computed(() => {
  if (uploadType.value === TYPE_IMAGE) return imageUploader
  if (uploadType.value === TYPE_DOCUMENT) return documentUploader
  return wineUploader
})
const uploadAttachments = computed(() => activeUploader.value.attachments.value)
const uploadWarning = computed(() => activeUploader.value.warning.value)
const departmentOptions = computed(() => {
  const items = [...departments.value]
  if (currentRole.value && !items.includes(currentRole.value)) {
    items.unshift(currentRole.value)
  }
  return items
})
const selectedAttachment = computed(() => wineUploader.attachments.value.at(-1) || null)
const selectedWineCandidate = computed(
  () => wineResults.value.find((item) => item.no === selectedWineCandidateId.value) || null
)
const isEditMode = computed(() => modalMode.value === 'edit')
const modalAttachmentPreviewUrl = computed(
  () => selectedAttachment.value?.previewUrl || previewUrls.value[editingResource.value?.id] || ''
)
const modalAttachmentFilename = computed(
  () => selectedAttachment.value?.filename || editingResource.value?.attachment_filename || ''
)
const modalAttachmentPresent = computed(
  () => Boolean(selectedAttachment.value?.file || editingResource.value?.id)
)
const selectedWineName = computed(
  () =>
    String(
      selectedWine.value?.name_ch ||
        selectedWine.value?.name ||
        selectedWine.value?.name_en ||
        ''
    ).trim() || '-'
)
const activePreviewSummary = computed(
  () => resources.value.find((item) => item.id === activePreviewId.value) || null
)
const activePreviewResource = computed(
  () => previewDetailMap.value[activePreviewId.value] || activePreviewSummary.value || null
)
const activePreviewImageUrl = computed(() => previewUrls.value[activePreviewId.value] || '')
const previewTitle = computed(() => activePreviewResource.value?.display_name || '-')
const canPreviewPrev = computed(() => activePreviewIndex.value > 0)
const canPreviewNext = computed(
  () => activePreviewIndex.value >= 0 && activePreviewIndex.value < resources.value.length - 1
)
const isPreviewInfoOpen = ref(readPreviewInfoOpen())
const isPreviewModalLayerActive = computed(
  () =>
    isPreviewOpen.value &&
    (isUploadModalOpen.value ||
      isDeleteModalOpen.value ||
      isWinePickerOpen.value ||
      isPermissionModalOpen.value)
)
const uploadDisabled = computed(
  () =>
    !modalAttachmentPresent.value ||
    !selectedWine.value ||
    isSubmitting.value ||
    wineUploader.isUploading.value
)
const canConfirmWineSelection = computed(() => Boolean(selectedWineCandidate.value))
const isLibraryUploadReady = computed(
  () =>
    Boolean(uploadAttachments.value.length) &&
    Boolean(sharedForm.department_role) &&
    !isSubmitting.value &&
    !activeUploader.value.isUploading.value
)
const uploadModalTitle = computed(() => {
  if (uploadType.value === TYPE_IMAGE) return t('fileResources.modal.image_title')
  if (uploadType.value === TYPE_DOCUMENT) return t('fileResources.modal.document_title')
  return isEditMode.value ? t('fileResources.modal.edit_title') : t('fileResources.modal.title')
})
const uploadModalSubtitle = computed(() => {
  if (uploadType.value === TYPE_IMAGE) return t('fileResources.modal.image_subtitle')
  if (uploadType.value === TYPE_DOCUMENT) return t('fileResources.modal.document_subtitle')
  return isEditMode.value ? t('fileResources.modal.edit_subtitle') : t('fileResources.modal.subtitle')
})
const submitButtonLabel = computed(() => {
  if (isSubmitting.value || wineUploader.isUploading.value) return t('fileResources.states.submitting')
  return isEditMode.value ? t('fileResources.actions.save_changes') : t('fileResources.actions.save')
})
const libraryDropzoneTitle = computed(() => t('fileResources.modal.dropzone_title'))
const librarySupportedFormats = computed(() =>
  t(
    uploadType.value === TYPE_IMAGE
      ? 'fileResources.modal.supported_formats_image'
      : 'fileResources.modal.supported_formats_document'
  )
)

const topbarSearchLabel = computed(() => t('home.placeholders.search'))
const libraryPreviewMeta = computed(() => [
  {
    label: t('fileResources.preview.department'),
    value: activePreviewResource.value?.department_role || '-',
  },
  {
    label: t('fileResources.preview.visibility'),
    value: resolveVisibilityLabel(activePreviewResource.value?.visibility),
  },
  {
    label: t('fileResources.preview.uploaded_at'),
    value: formatDateTime(activePreviewResource.value?.created_at),
  },
  {
    label: t('fileResources.preview.updated_at'),
    value: formatDateTime(activePreviewResource.value?.updated_at),
  },
  {
    label: t('fileResources.preview.updated_by'),
    value: activePreviewResource.value?.created_by_username || '-',
  },
])

function readPreviewInfoOpen() {
  if (typeof window === 'undefined') return true
  const raw = window.localStorage.getItem(PREVIEW_INFO_STORAGE_KEY)
  if (raw == null) return true
  return raw === '1' || raw === 'true'
}

const persistPreviewInfoOpen = (value) => {
  isPreviewInfoOpen.value = value
  if (typeof window === 'undefined') return
  window.localStorage.setItem(PREVIEW_INFO_STORAGE_KEY, value ? '1' : '0')
}

const handleLogoClick = () => {
  router.push({ name: 'home' })
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

const toggleSidebar = () => {
  if (!isCompactSidebar.value) return
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

const updateViewport = () => {
  stageWidth.value = typeof window !== 'undefined' ? window.innerWidth : stageWidth.value
  if (!isCompactSidebar.value) {
    isSidebarCollapsed.value = false
  }
}

const formatDateTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat(locale.value === 'en' ? 'en-US' : 'zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

const normalizeVisibility = (value) =>
  String(value || 'public').toLowerCase() === 'private' ? 'private' : 'public'

const resolveVisibilityLabel = (value) =>
  t(`fileResources.visibility.${normalizeVisibility(value)}`)

const formatAttachmentSize = (bytes = 0) => {
  const normalized = Number(bytes || 0)
  if (!normalized) return '0 KB'
  if (normalized < 1024 * 1024) {
    return `${Math.max(1, Math.round(normalized / 1024))} KB`
  }
  const mb = normalized / (1024 * 1024)
  return `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`
}

const resolveFileIcon = (resource = {}) => {
  const filename = resource.attachment_filename || resource.display_name || ''
  const ext = String(filename).split('.').pop()?.toLowerCase() || ''
  return documentIconMap[ext] || iconFileGenericDoc || iconFileGeneric
}

const resolveThumbLabel = (resource = {}) =>
  String(resource.attachment_filename || resource.display_name || '?').slice(0, 1).toUpperCase()

const isPreviewable = (resource = {}) => resource.resource_type !== TYPE_DOCUMENT

const clearPreviewUrls = () => {
  Object.values(previewUrls.value).forEach((url) => {
    if (url) URL.revokeObjectURL(url)
  })
  previewUrls.value = {}
}

const clearPreviewDetails = () => {
  previewDetailMap.value = {}
  previewFamilyProducts.value = []
}

const loadPreviewUrls = async (items = []) => {
  clearPreviewUrls()
  const next = {}
  await Promise.all(
    items.filter(isPreviewable).map(async (item) => {
      try {
        const blob = await fetchFileResourcePreview(item.id)
        next[item.id] = URL.createObjectURL(blob)
      } catch {
        next[item.id] = ''
      }
    })
  )
  previewUrls.value = next
}

const loadDepartments = async () => {
  try {
    const response = await fetchFileResourceDepartments()
    departments.value = Array.isArray(response?.items) ? response.items.filter(Boolean) : []
  } catch {
    departments.value = currentRole.value ? [currentRole.value] : []
  }
}

const loadResources = async () => {
  if (!isAuthenticated.value) {
    resources.value = []
    total.value = 0
    clearPreviewUrls()
    return
  }
  isLoading.value = true
  loadError.value = ''
  noticeMessage.value = ''
  try {
    const response = await fetchFileResources({
      type: activeTab.value,
      q: debouncedQuery.value,
      sorts: activeSortTokens.value,
      groupBy: activeGroupBy.value,
      page: currentPage.value,
      pageSize: PAGE_SIZE,
    })
    resources.value = Array.isArray(response?.items) ? response.items : []
    total.value = Number(response?.total || 0)
    await loadPreviewUrls(resources.value)
  } catch (error) {
    resources.value = []
    total.value = 0
    clearPreviewUrls()
    loadError.value = error?.message || t('fileResources.errors.load')
  } finally {
    isLoading.value = false
  }
}

const closeSortPanel = () => {
  isSortPanelOpen.value = false
}

const resetSortStateForTab = (tabKey) => {
  const config = sortConfigByType.value[tabKey] || sortConfigByType.value[TYPE_WINE]
  sortRules.value = cloneSortRules(config?.defaultRules || [])
  sortGrouping.value = false
}

const toggleSortPanel = () => {
  closeUploadMenu()
  closeRowMenu()
  isSortPanelOpen.value = !isSortPanelOpen.value
}

const toggleSortGrouping = () => {
  sortGrouping.value = !sortGrouping.value
}

const updateSortField = (rule, field) => {
  const nextField = String(field || '').trim()
  const definition = getSortFieldDefinition(nextField)
  if (!definition) return
  rule.field = nextField
  rule.direction = resolveDefaultDirection(nextField)
}

const toggleSortDirection = (rule) => {
  const directionKeys = Object.keys(getSortFieldDefinition(rule.field)?.directions || {})
  if (!directionKeys.length) return
  const currentIndex = directionKeys.indexOf(rule.direction)
  const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % directionKeys.length : 0
  rule.direction = directionKeys[nextIndex]
}

const addSortRule = () => {
  const firstField = sortFieldOptions.value[0]
  if (!firstField) return
  sortRules.value = [
    ...sortRules.value,
    createSortRule(firstField.value, resolveDefaultDirection(firstField.value)),
  ]
}

const removeSortRule = (id) => {
  sortRules.value = sortRules.value.filter((item) => item.id !== id)
}

const resetSortRules = () => {
  sortRules.value = []
  sortGrouping.value = false
}

const draggingSortRuleId = ref(null)

const reorderSortRules = (fromId, toId) => {
  const items = [...sortRules.value]
  const fromIndex = items.findIndex((item) => item.id === fromId)
  const toIndex = items.findIndex((item) => item.id === toId)
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return
  const [moved] = items.splice(fromIndex, 1)
  items.splice(toIndex, 0, moved)
  sortRules.value = items
}

const handleSortDragStart = (rule, event) => {
  draggingSortRuleId.value = rule.id
  if (event?.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(rule.id))
  }
}

const handleSortDragOver = (event) => {
  event.preventDefault()
}

const handleSortDrop = (targetRule) => {
  if (draggingSortRuleId.value !== null) {
    reorderSortRules(draggingSortRuleId.value, targetRule.id)
  }
  draggingSortRuleId.value = null
}

const handleSortDragEnd = () => {
  draggingSortRuleId.value = null
}

const closeUploadMenu = () => {
  isUploadMenuOpen.value = false
}

const closeRowMenu = () => {
  activeRowMenuId.value = ''
}

const closePreview = () => {
  isPreviewOpen.value = false
  activePreviewId.value = ''
  activePreviewIndex.value = -1
  isPreviewLoading.value = false
  previewLoadError.value = ''
  previewFamilyProducts.value = []
}

const extractFamilyPrefix = (value = '') => {
  const normalized = String(value || '').trim().toUpperCase()
  const match = normalized.match(/^(.*)-(\d{3})$/)
  return match ? match[1] : normalized
}

const normalizeWineResult = (item = {}) => ({
  id: item.id || item.no || '',
  no: String(item.no || item.id || '').trim(),
  name: String(item.name || item.name_ch || item.name_en || '').trim(),
  name_ch: String(item.name_ch || item.name || item.name_en || '').trim(),
  name_en: String(item.name_en || item.name_ch || item.name || '').trim(),
  producer: String(item.producer || '').trim(),
  region: String(item.region || '').trim(),
  color: String(item.color || '').trim(),
  vintage: item.vintage ?? '',
})

const resetUploadState = () => {
  wineUploader.clear()
  imageUploader.clear()
  documentUploader.clear()
  formError.value = ''
  uploadSubmitError.value = ''
  wineSearchQuery.value = ''
  wineResults.value = []
  wineSearchError.value = ''
  selectedWineCandidateId.value = ''
  selectedWine.value = null
  familyProducts.value = []
  isWinePickerOpen.value = false
  editingResource.value = null
  modalMode.value = 'create'
  sharedForm.department_role = currentRole.value || departmentOptions.value[0] || ''
  sharedForm.visibility = 'public'
  libraryDropDepth.value = 0
  isLibraryDropActive.value = false
}

const openUploadModal = (type = TYPE_WINE) => {
  closeUploadMenu()
  closeRowMenu()
  closeSortPanel()
  noticeMessage.value = ''
  resetUploadState()
  uploadType.value = type
  isUploadModalOpen.value = true
}

const closeUploadModal = () => {
  isUploadModalOpen.value = false
  resetUploadState()
}

const handleTabClick = (tab) => {
  activeTab.value = tab.key
}

const toggleUploadMenu = () => {
  closeRowMenu()
  closeSortPanel()
  isUploadMenuOpen.value = !isUploadMenuOpen.value
}

const openWinePicker = () => {
  wineSearchError.value = ''
  selectedWineCandidateId.value = selectedWine.value?.no || ''
  if (!wineSearchQuery.value.trim()) {
    wineSearchQuery.value = selectedWine.value?.name_ch || selectedWine.value?.name || ''
  }
  isWinePickerOpen.value = true
}

const closeWinePicker = () => {
  isWinePickerOpen.value = false
  wineSearchError.value = ''
}

const buildFallbackWine = (resource = {}) => {
  if (!resource?.cerp_code_full) return null
  return normalizeWineResult({
    no: resource.cerp_code_full,
    name_ch: resource.display_name,
    name_en: resource.display_name,
    name: resource.display_name,
    producer: resource.producer,
  })
}

const sortFamilyProducts = (items = []) =>
  items
    .slice()
    .sort((left, right) => {
      const leftVintage = Number(left?.vintage || 0)
      const rightVintage = Number(right?.vintage || 0)
      if (rightVintage !== leftVintage) return rightVintage - leftVintage
      return String(left?.no || '').localeCompare(String(right?.no || ''))
    })

const fetchFamilyProductsForCode = async (cerpCode, fallbackWine = null) => {
  const familyPrefix = extractFamilyPrefix(cerpCode)
  if (!familyPrefix) {
    return fallbackWine ? [fallbackWine] : []
  }
  try {
    const response = await searchCerpProducts({
      query: familyPrefix,
      limit: 50,
      lang: locale.value === 'en' ? 'en' : 'zh-TW',
    })
    const items = Array.isArray(response?.items) ? response.items : []
    const normalized = items
      .map(normalizeWineResult)
      .filter((item) => item.no && item.no.startsWith(familyPrefix))
    const deduped = Array.from(
      new Map(
        [...normalized, ...(fallbackWine ? [fallbackWine] : [])].map((item) => [item.no, item])
      ).values()
    )
    return sortFamilyProducts(deduped)
  } catch {
    return fallbackWine ? [fallbackWine] : []
  }
}

const loadFamilyProducts = async (cerpCode) => {
  familyProducts.value = await fetchFamilyProductsForCode(cerpCode, selectedWine.value)
}

const loadPreviewFamilyProducts = async (resource = {}) => {
  const fallbackWine = buildFallbackWine(resource)
  previewFamilyProducts.value = await fetchFamilyProductsForCode(resource?.cerp_code_full, fallbackWine)
}

const hydrateSelectedWine = async (resource = {}) => {
  const fallbackWine = buildFallbackWine(resource)
  if (!resource?.cerp_code_full) {
    selectedWine.value = fallbackWine
    selectedWineCandidateId.value = fallbackWine?.no || ''
    familyProducts.value = fallbackWine ? [fallbackWine] : []
    return
  }
  selectedWine.value = (await fetchExactWineByCode(resource.cerp_code_full)) || fallbackWine
  selectedWineCandidateId.value = selectedWine.value?.no || ''
  wineSearchQuery.value = selectedWine.value?.name_ch || selectedWine.value?.name || resource.display_name || ''
  await loadFamilyProducts(selectedWine.value?.no || resource.cerp_code_full || '')
}

const trimAttachmentsToLatest = () => {
  const current = wineUploader.attachments.value.slice()
  if (current.length <= 1) return
  const keepId = current.at(-1)?.id
  current
    .filter((item) => item.id !== keepId)
    .forEach((item) => wineUploader.removeAttachment(item.id))
}

const handleWineLabelFileChange = (event) => {
  formError.value = ''
  wineUploader.handleFilesSelected(event)
  trimAttachmentsToLatest()
}

const handleLibraryFileChange = (event) => {
  formError.value = ''
  uploadSubmitError.value = ''
  activeUploader.value.handleFilesSelected(event)
}

const handleLibraryDropEnter = (event) => {
  if (uploadType.value === TYPE_WINE) return
  event.preventDefault()
  libraryDropDepth.value += 1
  isLibraryDropActive.value = true
}

const handleLibraryDropOver = (event) => {
  if (uploadType.value === TYPE_WINE) return
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
  isLibraryDropActive.value = true
}

const handleLibraryDropLeave = (event) => {
  if (uploadType.value === TYPE_WINE) return
  event.preventDefault()
  libraryDropDepth.value = Math.max(0, libraryDropDepth.value - 1)
  if (!libraryDropDepth.value) {
    isLibraryDropActive.value = false
  }
}

const handleLibraryDrop = (event) => {
  if (uploadType.value === TYPE_WINE) return
  event.preventDefault()
  libraryDropDepth.value = 0
  isLibraryDropActive.value = false
  formError.value = ''
  uploadSubmitError.value = ''
  activeUploader.value.handleDroppedFiles(event.dataTransfer?.files || [])
}

const toggleRowMenu = (resourceId) => {
  activeRowMenuId.value = activeRowMenuId.value === resourceId ? '' : resourceId
}

const fetchExactWineByCode = async (cerpCode) => {
  const normalizedCode = String(cerpCode || '').trim()
  if (!normalizedCode) return null
  try {
    const response = await searchCerpProducts({
      query: normalizedCode,
      limit: 20,
      lang: locale.value === 'en' ? 'en' : 'zh-TW',
    })
    const items = Array.isArray(response?.items) ? response.items.map(normalizeWineResult) : []
    return items.find((item) => item.no === normalizedCode) || null
  } catch {
    return null
  }
}

const searchWineCandidates = async (query) => {
  const keyword = String(query || '').trim()
  const token = ++wineSearchRequestToken
  if (!keyword) {
    wineResults.value = []
    wineSearchError.value = ''
    isWineSearchLoading.value = false
    return
  }
  isWineSearchLoading.value = true
  wineSearchError.value = ''
  try {
    const response = await searchCerpProducts({
      query: keyword,
      limit: 20,
      lang: locale.value === 'en' ? 'en' : 'zh-TW',
    })
    if (token !== wineSearchRequestToken) return
    wineResults.value = Array.isArray(response?.items) ? response.items.map(normalizeWineResult) : []
    if (!wineResults.value.length) {
      selectedWineCandidateId.value = ''
    } else if (!wineResults.value.some((item) => item.no === selectedWineCandidateId.value)) {
      selectedWineCandidateId.value = ''
    }
  } catch (error) {
    if (token !== wineSearchRequestToken) return
    wineResults.value = []
    wineSearchError.value = error?.message || t('fileResources.errors.search')
  } finally {
    if (token === wineSearchRequestToken) {
      isWineSearchLoading.value = false
    }
  }
}

const handleWineSearchSubmit = () => {
  const trimmed = wineSearchQuery.value.trim()
  if (!trimmed) {
    wineResults.value = []
    wineSearchError.value = ''
    selectedWineCandidateId.value = ''
    isWineSearchLoading.value = false
    return
  }
  if (trimmed.length < 2) {
    wineResults.value = []
    wineSearchError.value = ''
    selectedWineCandidateId.value = ''
    isWineSearchLoading.value = false
    return
  }
  searchWineCandidates(trimmed)
}

const confirmWineSelection = async () => {
  if (!selectedWineCandidate.value) return
  selectedWine.value = selectedWineCandidate.value
  formError.value = ''
  await loadFamilyProducts(selectedWineCandidate.value.no)
  closeWinePicker()
}

const openWineEditModal = async (resourceSummary) => {
  closeRowMenu()
  closeUploadMenu()
  noticeMessage.value = ''
  resetUploadState()
  try {
    const detail = await fetchFileResourceDetail(resourceSummary.id)
    editingResource.value = detail
    modalMode.value = 'edit'
    uploadType.value = TYPE_WINE
    await hydrateSelectedWine(detail)
    isUploadModalOpen.value = true
  } catch (error) {
    loadError.value = error?.message || t('fileResources.errors.detail')
  }
}

const loadPreviewDetail = async (resourceSummary) => {
  const previewId = resourceSummary?.id
  if (!previewId) return
  const token = ++previewRequestToken
  isPreviewLoading.value = true
  previewLoadError.value = ''
  previewFamilyProducts.value = []
  try {
    const detail = await fetchFileResourceDetail(previewId)
    if (token !== previewRequestToken) return
    if (detail.resource_type === TYPE_WINE) {
      const exactWine = detail?.cerp_code_full ? await fetchExactWineByCode(detail.cerp_code_full) : null
      if (token !== previewRequestToken) return
      const enrichedDetail = exactWine
        ? {
            ...detail,
            producer: detail.producer || exactWine.producer || '',
            region: exactWine.region || '',
            color: exactWine.color || '',
          }
        : detail
      previewDetailMap.value = {
        ...previewDetailMap.value,
        [previewId]: enrichedDetail,
      }
      await loadPreviewFamilyProducts(enrichedDetail)
    } else {
      previewDetailMap.value = {
        ...previewDetailMap.value,
        [previewId]: detail,
      }
      if (detail.resource_type === TYPE_IMAGE && !previewUrls.value[previewId]) {
        try {
          const blob = await fetchFileResourcePreview(previewId)
          if (token !== previewRequestToken) return
          previewUrls.value = {
            ...previewUrls.value,
            [previewId]: URL.createObjectURL(blob),
          }
        } catch {
          previewUrls.value = {
            ...previewUrls.value,
            [previewId]: '',
          }
        }
      }
    }
  } catch (error) {
    if (token !== previewRequestToken) return
    previewLoadError.value = error?.message || t('fileResources.errors.detail')
    if (resourceSummary.resource_type === TYPE_WINE) {
      await loadPreviewFamilyProducts(resourceSummary || {})
    }
  } finally {
    if (token === previewRequestToken) {
      isPreviewLoading.value = false
    }
  }
}

const openPreview = async (resourceSummary, providedIndex = -1) => {
  if (!resourceSummary?.id) return
  closeRowMenu()
  closeUploadMenu()
  previewFamilyProducts.value = []
  const index =
    providedIndex >= 0
      ? providedIndex
      : resources.value.findIndex((item) => item.id === resourceSummary.id)
  activePreviewId.value = resourceSummary.id
  activePreviewIndex.value = index
  isPreviewOpen.value = true
  await loadPreviewDetail(resourceSummary)
}

const openPreviewByIndex = async (index) => {
  const target = resources.value[index]
  if (!target) return
  activePreviewIndex.value = index
  await openPreview(target)
}

const stepPreview = async (delta) => {
  const nextIndex = activePreviewIndex.value + delta
  if (nextIndex < 0 || nextIndex >= resources.value.length) return
  await openPreviewByIndex(nextIndex)
}

const togglePreviewInfo = () => {
  persistPreviewInfoOpen(!isPreviewInfoOpen.value)
}

const downloadPreviewResource = async () => {
  if (!activePreviewResource.value) return
  await downloadResource(activePreviewResource.value)
}

const editPreviewResource = async () => {
  if (!activePreviewResource.value) return
  await openWineEditModal(activePreviewResource.value)
}

const deletePreviewResource = () => {
  if (!activePreviewResource.value) return
  openDeleteModal(activePreviewResource.value)
}

const downloadResource = async (item) => {
  closeRowMenu()
  loadError.value = ''
  try {
    const blob = await fetchFileResourcePreview(item.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = item.attachment_filename || `${item.display_name || 'product-label'}.png`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    loadError.value = error?.message || t('fileResources.errors.download')
  }
}

const closePermissionModal = () => {
  isPermissionModalOpen.value = false
  permissionTarget.value = null
  permissionError.value = ''
}

const openPermissionModal = (item) => {
  closeRowMenu()
  permissionTarget.value = item
  permissionForm.department_role = item.department_role || currentRole.value || departmentOptions.value[0] || ''
  permissionForm.visibility = normalizeVisibility(item.visibility)
  permissionError.value = ''
  isPermissionModalOpen.value = true
}

const submitPermission = async () => {
  if (!permissionTarget.value?.id) return
  permissionError.value = ''
  const resourceId = permissionTarget.value.id
  const payload = {
    department_role: permissionForm.department_role,
    visibility: permissionForm.visibility,
  }
  try {
    await updateFileResource(resourceId, payload)
    previewDetailMap.value = {
      ...previewDetailMap.value,
      [resourceId]: {
        ...(previewDetailMap.value[resourceId] || permissionTarget.value || {}),
        ...payload,
      },
    }
    await loadResources()
    closePermissionModal()
    noticeMessage.value = t('fileResources.messages.permissions_updated')
  } catch (error) {
    permissionError.value = error?.message || t('fileResources.errors.permission_update')
  }
}

const openDeleteModal = (item) => {
  closeRowMenu()
  deleteError.value = ''
  deleteTarget.value = item
  isDeleteModalOpen.value = true
}

const closeDeleteModal = (force = false) => {
  if (isDeleting.value && !force) return
  isDeleteModalOpen.value = false
  deleteTarget.value = null
  deleteError.value = ''
}

const handleDocumentPointerDown = (event) => {
  const sortPanelCandidate = sortControlsRef.value?.panelRef || null
  const sortButtonCandidate = sortControlsRef.value?.buttonRef || null
  const sortPanelElement = sortPanelCandidate?.value || sortPanelCandidate || null
  const sortButtonElement = sortButtonCandidate?.value || sortButtonCandidate || null
  if (
    isUploadMenuOpen.value &&
    !uploadMenuRef.value?.contains(event.target) &&
    !uploadMenuButtonRef.value?.contains(event.target)
  ) {
    closeUploadMenu()
  }
  if (activeRowMenuId.value && !event.target?.closest?.('.file-resource-row-menu-anchor')) {
    closeRowMenu()
  }
  if (
    isSortPanelOpen.value &&
    !sortPanelElement?.contains(event.target) &&
    !sortButtonElement?.contains(event.target)
  ) {
    closeSortPanel()
  }
}

const handleDocumentKeydown = (event) => {
  if (event.key !== 'Escape') return
  if (isDeleteModalOpen.value) {
    closeDeleteModal(true)
    return
  }
  if (isPermissionModalOpen.value) {
    closePermissionModal()
    return
  }
  if (isWinePickerOpen.value) {
    closeWinePicker()
    return
  }
  if (isUploadModalOpen.value) {
    closeUploadModal()
    return
  }
  if (isPreviewOpen.value) {
    closePreview()
    return
  }
  if (isSortPanelOpen.value) {
    closeSortPanel()
    return
  }
  closeUploadMenu()
  closeRowMenu()
}

const submitWineLabel = async () => {
  formError.value = ''
  if (!modalAttachmentPresent.value) {
    formError.value = t('fileResources.errors.file_required')
    return
  }
  if (!selectedWine.value?.no) {
    formError.value = t('fileResources.errors.wine_required')
    return
  }
  isSubmitting.value = true
  const editedResourceId = isEditMode.value ? editingResource.value?.id || '' : ''
  try {
    let attachmentPayload = null
    if (selectedAttachment.value?.file) {
      const [uploaded] = await wineUploader.uploadAll()
      if (!uploaded?.path) {
        throw new Error(t('fileResources.errors.upload_failed'))
      }
      attachmentPayload = {
        path: uploaded.path,
        filename: uploaded.filename,
        mime: uploaded.mime,
        size: uploaded.size,
      }
    }
    const isSameWineAsCurrent =
      isEditMode.value &&
      editingResource.value?.cerp_code_full &&
      editingResource.value.cerp_code_full === selectedWine.value.no
    const payload = {
      display_name:
        isEditMode.value && isSameWineAsCurrent
          ? editingResource.value?.display_name || selectedWineName.value
          : selectedWineName.value,
      cerp_code_full: selectedWine.value.no,
    }
    if (attachmentPayload) {
      payload.attachment = attachmentPayload
    }

    if (isEditMode.value && editingResource.value?.id) {
      await updateWineLabelResource(editingResource.value.id, payload)
    } else {
      await createWineLabelResource({
        ...payload,
        attachment: attachmentPayload,
      })
    }
    closeUploadModal()
    currentPage.value = isEditMode.value ? currentPage.value : 1
    await loadResources()
    if (editedResourceId && isPreviewOpen.value && activePreviewId.value === editedResourceId) {
      const refreshedIndex = resources.value.findIndex((item) => item.id === editedResourceId)
      if (refreshedIndex >= 0) {
        await openPreviewByIndex(refreshedIndex)
      }
    }
    noticeMessage.value = t(
      isEditMode.value ? 'fileResources.messages.updated' : 'fileResources.messages.created'
    )
  } catch (error) {
    formError.value =
      error?.message || t(isEditMode.value ? 'fileResources.errors.update' : 'fileResources.errors.create')
  } finally {
    isSubmitting.value = false
  }
}

const submitLibraryUpload = async () => {
  formError.value = ''
  uploadSubmitError.value = ''
  if (!uploadAttachments.value.length) {
    formError.value = t('fileResources.errors.file_required')
    return
  }
  if (!sharedForm.department_role) {
    formError.value = t('fileResources.errors.departments')
    return
  }
  isSubmitting.value = true
  try {
    const uploadedItems = await activeUploader.value.uploadAll()
    if (!uploadedItems.length) {
      throw new Error(t('fileResources.errors.upload_failed'))
    }
    const createResource =
      uploadType.value === TYPE_IMAGE ? createImageResource : createDocumentResource
    currentPage.value = 1
    for (const uploaded of uploadedItems) {
      await createResource({
        department_role: sharedForm.department_role,
        visibility: sharedForm.visibility,
        attachment: uploaded,
      })
    }
    await loadResources()
    closeUploadModal()
    noticeMessage.value = t(
      uploadType.value === TYPE_IMAGE
        ? 'fileResources.messages.images_created'
        : 'fileResources.messages.documents_created'
    )
  } catch (error) {
    uploadSubmitError.value = error?.message || t('fileResources.modal.upload_failed_retry')
  } finally {
    isSubmitting.value = false
  }
}

const submitUpload = async () => {
  if (uploadType.value === TYPE_WINE) {
    await submitWineLabel()
    return
  }
  await submitLibraryUpload()
}

const confirmDelete = async () => {
  if (!deleteTarget.value?.id || isDeleting.value) return
  isDeleting.value = true
  deleteError.value = ''
  const deletingId = deleteTarget.value.id
  const deletingIndex = resources.value.findIndex((item) => item.id === deletingId)
  const fallbackPreviewId =
    isPreviewOpen.value && activePreviewId.value === deletingId
      ? resources.value[deletingIndex + 1]?.id || resources.value[deletingIndex - 1]?.id || ''
      : ''
  try {
    await deleteFileResource(deletingId)
    const remaining = Math.max(0, total.value - 1)
    const nextPage =
      remaining > 0 && currentPage.value > 1 && (currentPage.value - 1) * PAGE_SIZE >= remaining
        ? currentPage.value - 1
        : currentPage.value
    closeDeleteModal(true)
    currentPage.value = nextPage
    await loadResources()
    if (isPreviewOpen.value && activePreviewId.value === deletingId) {
      if (fallbackPreviewId) {
        const nextIndexInPage = resources.value.findIndex((item) => item.id === fallbackPreviewId)
        if (nextIndexInPage >= 0) {
          await openPreviewByIndex(nextIndexInPage)
        } else {
          closePreview()
        }
      } else {
        closePreview()
      }
    }
    noticeMessage.value = t('fileResources.messages.deleted')
  } catch (error) {
    deleteError.value = error?.message || t('fileResources.errors.delete')
  } finally {
    isDeleting.value = false
  }
}

resetSortStateForTab(activeTab.value)

watch(searchQuery, (value) => {
  if (typeof window === 'undefined') {
    debouncedQuery.value = value.trim()
    return
  }
  window.clearTimeout(searchTimer)
  currentPage.value = 1
  searchTimer = window.setTimeout(() => {
    debouncedQuery.value = value.trim()
  }, 250)
})

watch(wineSearchQuery, (value) => {
  if (!isWinePickerOpen.value) return
  const trimmed = value.trim()
  if (!trimmed) {
    wineResults.value = []
    wineSearchError.value = ''
    selectedWineCandidateId.value = ''
    isWineSearchLoading.value = false
  }
})

watch([sortRequestKey, activeGroupBy], () => {
  currentPage.value = 1
})

watch(activeTab, (tabKey) => {
  closeUploadMenu()
  closeSortPanel()
  closeRowMenu()
  closePreview()
  resetSortStateForTab(tabKey)
  currentPage.value = 1
})

watch(
  [isAuthenticated, debouncedQuery, sortRequestKey, activeGroupBy, currentPage, activeTab],
  ([authed]) => {
    if (!authed) return
    loadResources()
  },
  { immediate: true }
)

onMounted(async () => {
  if (typeof window === 'undefined') return
  window.addEventListener('resize', updateViewport)
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
  await loadDepartments()
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateViewport)
    document.removeEventListener('pointerdown', handleDocumentPointerDown)
    document.removeEventListener('keydown', handleDocumentKeydown)
    window.clearTimeout(searchTimer)
  }
  clearPreviewUrls()
  clearPreviewDetails()
  wineUploader.clear()
  imageUploader.clear()
  documentUploader.clear()
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
      :aria-label="t('home.aria.main_nav')"
      @logo-click="handleLogoClick"
      @nav-click="handleNavClick"
    />

    <div class="main-stage file-resource-stage-shell">
      <AppTopBar
        :logo-src="logoMain"
        :is-compact-sidebar="isCompactSidebar"
        :is-sidebar-collapsed="isSidebarCollapsed"
        :hamburger-icon="glyphs.hamburger"
        :menu-aria-label="t('home.aria.toggle_menu')"
        :avatar-label="avatarLabel"
        :avatar-aria-label="t('home.aria.open_account_menu')"
        @toggle-sidebar="toggleSidebar"
        @logo-click="handleLogoClick"
      >
        <template #search>
          <div class="file-topbar-search">
            <span class="file-topbar-search__icon" v-html="glyphs.search" aria-hidden="true" />
            <span class="file-topbar-search__label">{{ topbarSearchLabel }}</span>
          </div>
        </template>
      </AppTopBar>

      <main class="stage-canvas file-resource-stage">
        <div class="file-resource-page">
          <header class="file-resource-page__header">
            <div class="file-resource-page__title-block">
              <h1>{{ t('fileResources.title') }}</h1>
            </div>

            <div class="file-upload-menu-anchor file-resource-page__upload-anchor">
              <button
                ref="uploadMenuButtonRef"
                type="button"
                class="file-upload-trigger"
                @click="toggleUploadMenu"
              >
                <span class="file-upload-trigger__icon" v-html="glyphs.plus" aria-hidden="true" />
                {{ t('fileResources.actions.upload_file') }}
              </button>

              <div v-if="isUploadMenuOpen" ref="uploadMenuRef" class="file-upload-menu">
                <button type="button" class="file-upload-menu__item" @click="openUploadModal(TYPE_WINE)">
                  <strong>{{ t('fileResources.upload_menu.wine_label.title') }}</strong>
                  <small>{{ t('fileResources.upload_menu.wine_label.description') }}</small>
                </button>
                <button type="button" class="file-upload-menu__item" @click="openUploadModal(TYPE_IMAGE)">
                  <strong>{{ t('fileResources.upload_menu.image.title') }}</strong>
                  <small>{{ t('fileResources.upload_menu.image.description') }}</small>
                </button>
                <button type="button" class="file-upload-menu__item" @click="openUploadModal(TYPE_DOCUMENT)">
                  <strong>{{ t('fileResources.upload_menu.document.title') }}</strong>
                  <small>{{ t('fileResources.upload_menu.document.description') }}</small>
                </button>
              </div>
            </div>
          </header>

          <section class="file-resource-card">
            <div class="file-resource-tabs">
              <button
                v-for="tab in tabs"
                :key="tab.key"
                type="button"
                class="file-resource-tab"
                :class="{ 'is-active': activeTab === tab.key }"
                @click="handleTabClick(tab)"
              >
                {{ tab.label }}
              </button>
            </div>

            <div class="file-resource-toolbar">
              <label class="file-resource-search">
                <span class="file-resource-search__icon" v-html="glyphs.search" aria-hidden="true" />
                <input
                  v-model="searchQuery"
                  type="search"
                  :placeholder="t('fileResources.search.placeholder')"
                />
              </label>

              <div class="file-resource-toolbar__actions">
                <FileResourceSortControls
                  ref="sortControlsRef"
                  :summary-label="sortSummaryLabel"
                  :show-panel="isSortPanelOpen"
                  :sort-rules="sortRules"
                  :sort-field-options="sortFieldOptions"
                  :sort-grouping="sortGrouping"
                  :grouping-label="sortGroupLabel"
                  :toggle-panel="toggleSortPanel"
                  :toggle-grouping="toggleSortGrouping"
                  :handle-drag-start="handleSortDragStart"
                  :handle-drag-over="handleSortDragOver"
                  :handle-drop="handleSortDrop"
                  :handle-drag-end="handleSortDragEnd"
                  :update-sort-field="updateSortField"
                  :toggle-direction="toggleSortDirection"
                  :remove-sort-rule="removeSortRule"
                  :add-sort-rule="addSortRule"
                  :reset-sort-rules="resetSortRules"
                  :resolve-direction-label="resolveDirectionLabel"
                  :icon-drag="iconDrag"
                  :icon-up-down="iconUpDown"
                  :add-rule-label="t('fileResources.sort.add_rule')"
                  :reset-rules-label="t('fileResources.sort.reset_rules')"
                  :remove-rule-label="t('fileResources.sort.remove_rule')"
                  class="file-resource-sort-shell"
                />
              </div>
            </div>

            <p v-if="noticeMessage" class="file-resource-notice">{{ noticeMessage }}</p>
            <p v-if="loadError" class="file-resource-error">{{ loadError }}</p>

            <template v-if="activeTab === TYPE_WINE">
              <div class="file-resource-table-wrap">
                <div v-if="isLoading" class="file-resource-state">
                  {{ t('fileResources.states.loading') }}
                </div>
                <div v-else-if="resources.length" class="file-resource-table">
                  <div class="file-resource-table__head">
                    <div>{{ t('fileResources.table.name') }}</div>
                    <div>{{ t('fileResources.table.product_code') }}</div>
                    <div>{{ t('fileResources.table.producer') }}</div>
                    <div>{{ t('fileResources.table.uploaded_at') }}</div>
                    <div />
                  </div>

                  <div
                    v-for="item in resources"
                    :key="item.id"
                    class="file-resource-table__row"
                    role="button"
                    tabindex="0"
                    @click="openPreview(item)"
                    @keydown.enter.prevent="openPreview(item)"
                    @keydown.space.prevent="openPreview(item)"
                  >
                    <div class="file-resource-table__name">
                      <div class="file-resource-thumb">
                        <img v-if="previewUrls[item.id]" :src="previewUrls[item.id]" alt="" />
                        <span v-else class="file-resource-thumb__placeholder">IMG</span>
                      </div>
                      <div class="file-resource-table__meta">
                        <strong>{{ item.display_name }}</strong>
                        <small>{{ item.attachment_filename }}</small>
                      </div>
                    </div>
                    <div class="file-resource-table__cell">
                      {{ item.cerp_code_full || '-' }}
                    </div>
                    <div class="file-resource-table__cell">
                      {{ item.producer || '-' }}
                    </div>
                    <div class="file-resource-table__cell">
                      {{ formatDateTime(item.created_at) }}
                    </div>
                    <div class="file-resource-table__placeholder">
                      <div class="file-resource-row-menu-anchor" @click.stop>
                        <button
                          type="button"
                          class="file-resource-row-menu-toggle"
                          :aria-label="t('quote.aria.open_actions')"
                          @click.stop="toggleRowMenu(item.id)"
                        >
                          <img :src="iconMoreVertical" alt="" aria-hidden="true" />
                        </button>
                        <div v-if="activeRowMenuId === item.id" class="file-resource-row-menu">
                          <button type="button" class="file-resource-row-menu__item" @click="openWineEditModal(item)">
                            {{ t('fileResources.actions.edit') }}
                          </button>
                          <button type="button" class="file-resource-row-menu__item" @click="downloadResource(item)">
                            {{ t('fileResources.actions.download') }}
                          </button>
                          <button
                            type="button"
                            class="file-resource-row-menu__item file-resource-row-menu__item--danger"
                            @click="openDeleteModal(item)"
                          >
                            {{ t('fileResources.actions.delete') }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="file-resource-empty">
                  <img :src="emptyIllustration" alt="" />
                  <p>{{ t('fileResources.states.empty') }}</p>
                </div>
              </div>

              <footer class="file-resource-footer">
                <div>{{ t('fileResources.pagination.per_page') }} <strong>{{ PAGE_SIZE }}</strong></div>
                <div>{{ rangeLabel }}</div>
                <div class="file-resource-footer__pager">
                  <button type="button" :disabled="!canGoPrev" @click="currentPage -= 1">&lt;</button>
                  <button type="button" :disabled="!canGoNext" @click="currentPage += 1">&gt;</button>
                </div>
              </footer>
            </template>

            <template v-else>
              <div class="file-resource-table-wrap file-library-table-wrap">
                <div v-if="isLoading" class="file-resource-state">
                  {{ t('fileResources.states.loading') }}
                </div>
                <div v-else-if="resources.length" class="file-library-table">
                  <div class="file-library-table__head">
                    <div>{{ t('fileResources.table.name') }}</div>
                    <div>{{ t('fileResources.table.department') }}</div>
                    <div>{{ t('fileResources.table.visibility') }}</div>
                    <div>{{ t('fileResources.table.uploaded_at') }}</div>
                    <div />
                  </div>

                  <div
                    v-for="(item, index) in resources"
                    :key="item.id"
                    class="file-library-table__row"
                  >
                    <button type="button" class="file-library-table__name" @click="openPreview(item, index)">
                      <span
                        class="file-library-table__thumb"
                        :class="{ 'is-document': item.resource_type === TYPE_DOCUMENT }"
                      >
                        <img
                          v-if="item.resource_type === TYPE_IMAGE && previewUrls[item.id]"
                          :src="previewUrls[item.id]"
                          alt=""
                        />
                        <img
                          v-else-if="item.resource_type === TYPE_DOCUMENT"
                          :src="resolveFileIcon(item)"
                          alt=""
                          class="file-library-table__file-icon"
                        />
                        <span v-else>{{ resolveThumbLabel(item) }}</span>
                      </span>
                      <span class="file-library-table__meta">
                        <strong>{{ item.display_name }}</strong>
                        <small>{{ item.attachment_filename }}</small>
                      </span>
                    </button>
                    <div class="file-library-table__cell">{{ item.department_role || '-' }}</div>
                    <div class="file-library-table__cell">{{ resolveVisibilityLabel(item.visibility) }}</div>
                    <div class="file-library-table__cell">{{ formatDateTime(item.created_at) }}</div>
                    <div class="file-library-table__actions">
                      <div class="file-resource-row-menu-anchor" @click.stop>
                        <button
                          type="button"
                          class="file-resource-row-menu-toggle"
                          :aria-label="t('quote.aria.open_actions')"
                          @click.stop="toggleRowMenu(item.id)"
                        >
                          <img :src="iconMoreVertical" alt="" aria-hidden="true" />
                        </button>
                        <div v-if="activeRowMenuId === item.id" class="file-resource-row-menu">
                          <button type="button" class="file-resource-row-menu__item" @click="openPermissionModal(item)">
                            {{ t('fileResources.actions.permission') }}
                          </button>
                          <button type="button" class="file-resource-row-menu__item" @click="downloadResource(item)">
                            {{ t('fileResources.actions.download') }}
                          </button>
                          <button
                            type="button"
                            class="file-resource-row-menu__item file-resource-row-menu__item--danger"
                            @click="openDeleteModal(item)"
                          >
                            {{ t('fileResources.actions.delete') }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="file-resource-empty">
                  <img :src="emptyIllustration" alt="" />
                  <p>{{ t('fileResources.states.empty') }}</p>
                </div>
              </div>

              <footer class="file-resource-footer file-library-footer">
                <div>{{ t('fileResources.pagination.per_page') }} <strong>{{ PAGE_SIZE }}</strong></div>
                <div>{{ rangeLabel }}</div>
                <div class="file-resource-footer__pager">
                  <button type="button" :disabled="!canGoPrev" @click="currentPage -= 1">&lt;</button>
                  <button type="button" :disabled="!canGoNext" @click="currentPage += 1">&gt;</button>
                </div>
              </footer>
            </template>
          </section>
        </div>
      </main>
    </div>
  </div>

  <template v-if="isPreviewOpen && activePreviewResource">
    <div
      v-if="activePreviewResource.resource_type === TYPE_WINE"
      class="file-resource-preview"
      role="dialog"
      aria-modal="true"
      @click.self="closePreview"
    >
      <div
        class="file-resource-preview__layout"
        :class="{ 'is-dimmed': isPreviewModalLayerActive, 'is-info-open': isPreviewInfoOpen }"
      >
        <section class="file-resource-preview__stage">
          <header class="file-resource-preview__topbar">
            <div class="file-resource-preview__title">
              <button
                type="button"
                class="file-resource-preview__toolbar-button file-resource-preview__toolbar-button--ghost"
                :aria-label="t('fileResources.preview.close')"
                @click="closePreview"
              >
                <span v-html="glyphs.previewClose" aria-hidden="true" />
              </button>
              <strong>{{ previewTitle }}</strong>
            </div>

            <div class="file-resource-preview__toolbar">
              <button
                type="button"
                class="file-resource-preview__toolbar-button"
                :aria-label="t('fileResources.actions.download')"
                @click="downloadPreviewResource"
              >
                <span v-html="glyphs.previewDownload" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-resource-preview__toolbar-button"
                :aria-label="t('fileResources.actions.edit')"
                @click="editPreviewResource"
              >
                <span v-html="glyphs.previewEdit" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-resource-preview__toolbar-button"
                :aria-label="t('fileResources.actions.delete')"
                @click="deletePreviewResource"
              >
                <span v-html="glyphs.previewDelete" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-resource-preview__toolbar-button"
                :class="{ 'is-active': isPreviewInfoOpen }"
                :aria-label="t('fileResources.preview.toggle_info')"
                @click="togglePreviewInfo"
              >
                <span v-html="glyphs.previewInfo" aria-hidden="true" />
              </button>
            </div>
          </header>

          <div class="file-resource-preview__canvas">
            <button
              type="button"
              class="file-resource-preview__nav"
              :class="'file-resource-preview__nav--prev'"
              :disabled="!canPreviewPrev"
              :aria-label="t('fileResources.preview.previous')"
              @click="stepPreview(-1)"
            >
              <span v-html="glyphs.previewPrev" aria-hidden="true" />
            </button>

            <div class="file-resource-preview__image-shell">
              <div v-if="isPreviewLoading" class="file-resource-preview__state">
                {{ t('fileResources.preview.loading') }}
              </div>
              <div
                v-else-if="previewLoadError"
                class="file-resource-preview__state file-resource-preview__state--error"
              >
                {{ previewLoadError }}
              </div>
              <img
                v-else-if="activePreviewImageUrl"
                class="file-resource-preview__image"
                :src="activePreviewImageUrl"
                :alt="previewTitle"
              />
              <div v-else class="file-resource-preview__state">
                {{ t('fileResources.preview.no_image') }}
              </div>
            </div>

            <button
              type="button"
              class="file-resource-preview__nav"
              :class="'file-resource-preview__nav--next'"
              :disabled="!canPreviewNext"
              :aria-label="t('fileResources.preview.next')"
              @click="stepPreview(1)"
            >
              <span v-html="glyphs.previewNext" aria-hidden="true" />
            </button>
          </div>
        </section>

        <aside v-if="isPreviewInfoOpen" class="file-resource-preview__info">
          <header class="file-resource-preview__info-header">
            <h2>{{ t('fileResources.preview.info_title') }}</h2>
            <button
              type="button"
              class="file-resource-preview__info-close"
              :aria-label="t('fileResources.preview.toggle_info')"
              @click="togglePreviewInfo"
            >
              <span v-html="glyphs.previewClose" aria-hidden="true" />
            </button>
          </header>

          <section class="file-resource-preview__panel">
            <h3>{{ t('fileResources.preview.product_section') }}</h3>
            <div class="file-resource-preview__card">
              <strong>{{ activePreviewResource.display_name }}</strong>
              <dl class="file-resource-preview__meta">
                <div>
                  <dt>{{ t('fileResources.modal.fields.producer') }}</dt>
                  <dd>{{ activePreviewResource.producer || '-' }}</dd>
                </div>
                <div>
                  <dt>{{ t('fileResources.modal.fields.region') }}</dt>
                  <dd>{{ activePreviewResource.region || '-' }}</dd>
                </div>
                <div>
                  <dt>{{ t('fileResources.modal.fields.color') }}</dt>
                  <dd>{{ activePreviewResource.color || '-' }}</dd>
                </div>
              </dl>
            </div>
          </section>

          <section class="file-resource-preview__panel">
            <h3>{{ t('fileResources.preview.related_section') }}</h3>
            <div class="file-resource-preview__related">
              <div class="file-resource-preview__related-head">
                <span>{{ t('fileResources.modal.related_code') }}</span>
                <span>{{ t('fileResources.modal.related_vintage') }}</span>
              </div>
              <div
                v-for="item in previewFamilyProducts"
                :key="item.no"
                class="file-resource-preview__related-row"
              >
                <span>{{ item.no }}</span>
                <span>{{ item.vintage || '-' }}</span>
              </div>
            </div>
          </section>

          <section class="file-resource-preview__panel">
            <h3>{{ t('fileResources.preview.basic_section') }}</h3>
            <div class="file-resource-preview__card">
              <dl class="file-resource-preview__meta file-resource-preview__meta--stacked">
                <div>
                  <dt>{{ t('fileResources.preview.uploaded_at') }}</dt>
                  <dd>{{ formatDateTime(activePreviewResource.created_at) }}</dd>
                </div>
                <div>
                  <dt>{{ t('fileResources.preview.updated_at') }}</dt>
                  <dd>{{ formatDateTime(activePreviewResource.updated_at) }}</dd>
                </div>
                <div>
                  <dt>{{ t('fileResources.preview.updated_by') }}</dt>
                  <dd>{{ activePreviewResource.created_by_username || '-' }}</dd>
                </div>
              </dl>
            </div>
          </section>
        </aside>
      </div>
    </div>

    <div
      v-else
      class="file-library-preview"
      role="dialog"
      aria-modal="true"
      @click.self="closePreview"
    >
      <div
        class="file-library-preview__layout"
        :class="{ 'is-dimmed': isPreviewModalLayerActive, 'is-info-open': isPreviewInfoOpen }"
      >
        <section class="file-library-preview__stage">
          <header class="file-library-preview__topbar">
            <div class="file-library-preview__title">
              <strong>{{ previewTitle }}</strong>
              <small>{{ activePreviewResource.attachment_filename || previewTitle }}</small>
            </div>

            <div class="file-library-preview__toolbar">
              <button
                type="button"
                class="file-library-preview__toolbar-button"
                :aria-label="t('fileResources.actions.download')"
                @click="downloadPreviewResource"
              >
                <span v-html="glyphs.previewDownload" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-library-preview__toolbar-button"
                :aria-label="t('fileResources.actions.permission')"
                @click="openPermissionModal(activePreviewResource)"
              >
                <span v-html="glyphs.previewInfo" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-library-preview__toolbar-button"
                :aria-label="t('fileResources.actions.delete')"
                @click="deletePreviewResource"
              >
                <span v-html="glyphs.previewDelete" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-library-preview__toolbar-button"
                :class="{ 'is-active': isPreviewInfoOpen }"
                :aria-label="t('fileResources.preview.toggle_info')"
                @click="togglePreviewInfo"
              >
                <span v-html="glyphs.previewInfo" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="file-library-preview__toolbar-button file-library-preview__toolbar-button--ghost"
                :aria-label="t('fileResources.preview.close')"
                @click="closePreview"
              >
                <span v-html="glyphs.previewClose" aria-hidden="true" />
              </button>
            </div>
          </header>

          <div class="file-library-preview__canvas">
            <button
              type="button"
              class="file-library-preview__nav"
              :class="'file-library-preview__nav--prev'"
              :disabled="!canPreviewPrev"
              :aria-label="t('fileResources.preview.previous')"
              @click="stepPreview(-1)"
            >
              <span v-html="glyphs.previewPrev" aria-hidden="true" />
            </button>

            <div class="file-library-preview__content">
              <div v-if="isPreviewLoading" class="file-library-preview__state">
                {{ t('fileResources.preview.loading') }}
              </div>
              <div
                v-else-if="previewLoadError"
                class="file-library-preview__state file-library-preview__state--error"
              >
                {{ previewLoadError }}
              </div>
              <img
                v-else-if="activePreviewResource.resource_type === TYPE_IMAGE && activePreviewImageUrl"
                class="file-library-preview__image"
                :src="activePreviewImageUrl"
                :alt="previewTitle"
              />
              <div v-else class="file-library-preview__document-state">
                <img
                  :src="resolveFileIcon(activePreviewResource)"
                  alt=""
                  class="file-library-preview__document-icon"
                />
                <strong>{{ t('fileResources.preview.unsupported_title') }}</strong>
                <p>{{ t('fileResources.preview.unsupported_body') }}</p>
                <button
                  type="button"
                  class="file-library-preview__download"
                  @click="downloadPreviewResource"
                >
                  {{ t('fileResources.actions.download') }}
                </button>
              </div>
            </div>

            <button
              type="button"
              class="file-library-preview__nav"
              :class="'file-library-preview__nav--next'"
              :disabled="!canPreviewNext"
              :aria-label="t('fileResources.preview.next')"
              @click="stepPreview(1)"
            >
              <span v-html="glyphs.previewNext" aria-hidden="true" />
            </button>
          </div>
        </section>

        <aside v-if="isPreviewInfoOpen" class="file-library-preview__info">
          <header class="file-library-preview__info-header">
            <h2>{{ t('fileResources.preview.info_title') }}</h2>
            <button
              type="button"
              class="file-library-preview__info-close"
              :aria-label="t('fileResources.preview.toggle_info')"
              @click="togglePreviewInfo"
            >
              <span v-html="glyphs.previewClose" aria-hidden="true" />
            </button>
          </header>

          <div class="file-library-preview__info-body">
            <div class="file-library-preview__summary">
              <span class="file-library-preview__summary-icon">
                <img
                  v-if="activePreviewResource.resource_type === TYPE_DOCUMENT"
                  :src="resolveFileIcon(activePreviewResource)"
                  alt=""
                />
                <img v-else-if="activePreviewImageUrl" :src="activePreviewImageUrl" alt="" />
                <span v-else>{{ resolveThumbLabel(activePreviewResource) }}</span>
              </span>
              <div>
                <strong>{{ activePreviewResource.display_name }}</strong>
                <small>{{ activePreviewResource.attachment_filename || '-' }}</small>
              </div>
            </div>

            <dl class="file-library-preview__meta">
              <div v-for="item in libraryPreviewMeta" :key="item.label">
                <dt>{{ item.label }}</dt>
                <dd>{{ item.value }}</dd>
              </div>
            </dl>
          </div>
        </aside>
      </div>
    </div>
  </template>

  <div
    v-if="isUploadModalOpen && uploadType === TYPE_WINE"
    class="modal-mask"
    :class="{ 'modal-mask--preview': isPreviewOpen }"
    role="dialog"
    aria-modal="true"
    @click.self="closeUploadModal"
  >
    <article class="file-upload-modal">
      <header class="file-upload-modal__header">
        <div>
          <h2>{{ uploadModalTitle }}</h2>
          <p>{{ uploadModalSubtitle }}</p>
        </div>
        <button type="button" class="file-upload-modal__close" @click="closeUploadModal">×</button>
      </header>

      <div class="file-upload-modal__body">
        <input
          :ref="(el) => { wineUploader.fileInputRef.value = el }"
          class="composer-file-input"
          type="file"
          :accept="wineUploader.accept"
          @change="handleWineLabelFileChange"
        />
        <section class="file-upload-step">
          <header class="file-upload-step__header">
            <span class="file-upload-step__index">Step 1</span>
            <div>
              <h3>{{ t('fileResources.modal.step_image_title') }}</h3>
              <p>{{ t('fileResources.modal.step_image_hint') }}</p>
            </div>
          </header>

          <button type="button" class="file-upload-dropzone" @click="wineUploader.triggerSelect">
            <div v-if="modalAttachmentPreviewUrl" class="file-upload-dropzone__preview">
              <img :src="modalAttachmentPreviewUrl" alt="" />
              <small>{{ modalAttachmentFilename }}</small>
            </div>
            <div v-else class="file-upload-dropzone__placeholder">
              <span class="file-upload-dropzone__icon">＋</span>
              <strong>{{ t('fileResources.modal.select_image') }}</strong>
            </div>
          </button>
          <p class="file-upload-dropzone__hint">{{ t('fileResources.modal.image_size_hint') }}</p>
        </section>

        <section class="file-upload-step">
          <header class="file-upload-step__header">
            <span class="file-upload-step__index">Step 2</span>
            <div>
              <h3>{{ t('fileResources.modal.step_wine_title') }}</h3>
              <p>{{ t('fileResources.modal.step_wine_hint') }}</p>
            </div>
          </header>

          <div v-if="selectedWine" class="file-upload-selection-card">
            <div class="file-upload-selection-card__top">
              <div>
                <strong>{{ selectedWineName }}</strong>
                <small>{{ selectedWine.no }}</small>
              </div>
              <button type="button" class="file-upload-link" @click="openWinePicker">
                {{ t('fileResources.actions.reselect') }}
              </button>
            </div>

            <dl class="file-upload-selection-grid">
              <div>
                <dt>{{ t('fileResources.modal.fields.producer') }}</dt>
                <dd>{{ selectedWine.producer || '-' }}</dd>
              </div>
              <div>
                <dt>{{ t('fileResources.modal.fields.region') }}</dt>
                <dd>{{ selectedWine.region || '-' }}</dd>
              </div>
              <div>
                <dt>{{ t('fileResources.modal.fields.color') }}</dt>
                <dd>{{ selectedWine.color || '-' }}</dd>
              </div>
            </dl>

            <div class="file-upload-related">
              <div class="file-upload-related__title">{{ t('fileResources.modal.related_title') }}</div>
              <div class="file-upload-related__table">
                <div class="file-upload-related__head">
                  <span>{{ t('fileResources.modal.related_code') }}</span>
                  <span>{{ t('fileResources.modal.related_vintage') }}</span>
                </div>
                <div
                  v-for="item in familyProducts"
                  :key="item.no"
                  class="file-upload-related__row"
                >
                  <span>{{ item.no }}</span>
                  <span>{{ item.vintage || '-' }}</span>
                </div>
              </div>
            </div>
          </div>

          <button
            v-else
            type="button"
            class="file-upload-wine-empty"
            @click="openWinePicker"
          >
            <span class="file-upload-wine-empty__icon">＋</span>
            <strong>{{ t('fileResources.modal.select_wine') }}</strong>
          </button>
        </section>
      </div>

      <p v-if="uploadWarning" class="file-resource-error" data-testid="wine-upload-warning">{{ uploadWarning }}</p>
      <p v-if="formError" class="file-resource-error" data-testid="wine-upload-error">{{ formError }}</p>

      <footer class="file-upload-modal__footer">
        <button type="button" class="file-upload-button file-upload-button--ghost" @click="closeUploadModal">
          {{ t('fileResources.actions.cancel') }}
        </button>
        <button
          type="button"
          class="file-upload-button file-upload-button--primary"
          data-testid="wine-upload-submit"
          :disabled="uploadDisabled"
          @click="submitUpload"
        >
          {{ submitButtonLabel }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-if="isUploadModalOpen && uploadType !== TYPE_WINE"
    class="modal-mask"
    :class="{ 'modal-mask--preview': isPreviewOpen }"
    role="dialog"
    aria-modal="true"
    @click.self="closeUploadModal"
  >
    <article class="file-library-upload file-library-upload--figma">
      <header class="file-library-upload__header">
        <h2>{{ uploadModalTitle }}</h2>
        <button type="button" class="file-upload-modal__close" @click="closeUploadModal">×</button>
      </header>

      <div v-if="uploadSubmitError" class="file-library-upload__error-banner" role="alert">
        <span class="file-library-upload__error-icon" aria-hidden="true">!</span>
        <span>{{ uploadSubmitError }}</span>
      </div>

      <div class="file-library-upload__body file-library-upload__body--figma">
        <section class="file-library-upload__settings-panel">
          <label class="file-library-upload__field file-library-upload__field--figma">
            <span class="file-library-upload__field-label">
              <span class="file-library-upload__required" aria-hidden="true">*</span>
              {{ t('fileResources.modal.department') }}
            </span>
            <span class="file-library-upload__select-wrap">
              <select v-model="sharedForm.department_role" class="file-library-upload__select">
                <option v-for="item in departmentOptions" :key="item" :value="item">{{ item }}</option>
              </select>
              <span class="file-library-upload__select-icon" v-html="glyphs.chevronDown" aria-hidden="true" />
            </span>
          </label>

          <fieldset class="file-library-upload__visibility file-library-upload__visibility--figma">
            <legend class="file-library-upload__field-label">
              <span class="file-library-upload__required" aria-hidden="true">*</span>
              {{ t('fileResources.modal.visibility') }}
            </legend>
            <div class="file-library-upload__visibility-options">
              <label class="file-library-upload__radio">
                <input v-model="sharedForm.visibility" type="radio" value="private" />
                <span class="file-library-upload__radio-mark" aria-hidden="true"></span>
                <span class="file-library-upload__radio-text">{{ t('fileResources.visibility.private') }}</span>
              </label>
              <label class="file-library-upload__radio">
                <input v-model="sharedForm.visibility" type="radio" value="public" />
                <span class="file-library-upload__radio-mark" aria-hidden="true"></span>
                <span class="file-library-upload__radio-text">{{ t('fileResources.visibility.public') }}</span>
              </label>
            </div>
          </fieldset>
        </section>

        <section class="file-library-upload__stage file-library-upload__stage--figma">
          <input
            v-if="uploadType === TYPE_IMAGE"
            :ref="(el) => { imageUploader.fileInputRef.value = el }"
            class="composer-file-input"
            type="file"
            :accept="imageUploader.accept"
            multiple
            @change="handleLibraryFileChange"
          />
          <input
            v-else
            :ref="(el) => { documentUploader.fileInputRef.value = el }"
            class="composer-file-input"
            type="file"
            :accept="documentUploader.accept"
            multiple
            @change="handleLibraryFileChange"
          />

          <div
            class="file-library-upload__dropzone file-library-upload__dropzone--figma"
            :class="{ 'is-drag-active': isLibraryDropActive }"
            role="button"
            tabindex="0"
            @click="activeUploader.triggerSelect"
            @keydown.enter.prevent="activeUploader.triggerSelect"
            @keydown.space.prevent="activeUploader.triggerSelect"
            @dragenter="handleLibraryDropEnter"
            @dragover="handleLibraryDropOver"
            @dragleave="handleLibraryDropLeave"
            @drop="handleLibraryDrop"
          >
            <img class="file-library-upload__illustration" :src="uploadIllustration" alt="" />
            <div class="file-library-upload__dropzone-copy">
              <strong>{{ libraryDropzoneTitle }}</strong>
              <p>
                {{ t('fileResources.modal.dropzone_copy_prefix') }}
                <button
                  type="button"
                  class="file-library-upload__dropzone-link"
                  @click.stop="activeUploader.triggerSelect"
                >
                  {{ t('fileResources.modal.choose_files') }}
                </button>
              </p>
              <small>{{ librarySupportedFormats }}</small>
            </div>
          </div>

          <div
            v-if="uploadWarning || formError"
            class="file-library-upload__inline-message"
            :class="{ 'is-error': Boolean(uploadWarning || formError) }"
            role="status"
          >
            {{ uploadWarning || formError }}
          </div>

          <section v-if="uploadAttachments.length" class="file-library-upload__queue file-library-upload__queue--figma">
            <div class="file-library-upload__queue-list">
              <article
                v-for="item in uploadAttachments"
                :key="item.id"
                class="file-library-upload__queue-item file-library-upload__queue-item--figma"
              >
                <span class="file-library-upload__queue-thumb">
                  <img
                    v-if="uploadType === TYPE_IMAGE && item.previewUrl"
                    :src="item.previewUrl"
                    alt=""
                  />
                  <img
                    v-else
                    :src="resolveFileIcon({ attachment_filename: item.filename })"
                    alt=""
                  />
                </span>
                <div class="file-library-upload__queue-copy">
                  <strong>{{ item.filename }}</strong>
                  <small>{{ formatAttachmentSize(item.size) }}</small>
                </div>
                <button
                  type="button"
                  class="file-library-upload__queue-remove"
                  :aria-label="t('fileResources.actions.delete')"
                  @click="activeUploader.removeAttachment(item.id)"
                >
                  ×
                </button>
              </article>
            </div>
          </section>
        </section>
      </div>

      <footer class="file-library-upload__footer">
        <button type="button" class="file-upload-button file-upload-button--ghost" @click="closeUploadModal">
          {{ t('fileResources.actions.cancel') }}
        </button>
        <button
          type="button"
          class="file-upload-button file-upload-button--primary"
          :disabled="!isLibraryUploadReady"
          @click="submitUpload"
        >
          {{
            isSubmitting
              ? t('fileResources.states.submitting')
              : t('fileResources.actions.start_upload')
          }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-if="isDeleteModalOpen && deleteTarget && deleteTarget.resource_type === TYPE_WINE"
    class="modal-mask"
    :class="{ 'modal-mask--preview': isPreviewOpen }"
    role="dialog"
    aria-modal="true"
    @click.self="closeDeleteModal"
  >
    <article class="file-resource-delete-modal">
      <header class="file-resource-delete-modal__header">
        <h2>{{ t('fileResources.delete_modal.wine_label_title') }}</h2>
        <button type="button" class="file-upload-modal__close" @click="closeDeleteModal">×</button>
      </header>
      <div class="file-resource-delete-modal__body">
        <p class="file-resource-delete-modal__copy">{{ t('fileResources.delete_modal.wine_label_body') }}</p>
        <p v-if="deleteError" class="file-resource-error file-resource-delete-modal__error">{{ deleteError }}</p>
      </div>
      <footer class="file-resource-delete-modal__footer">
        <button type="button" class="file-upload-button file-upload-button--ghost" @click="closeDeleteModal">
          {{ t('fileResources.actions.cancel') }}
        </button>
        <button
          type="button"
          class="file-upload-button file-upload-button--danger"
          :disabled="isDeleting"
          @click="confirmDelete"
        >
          {{ isDeleting ? t('fileResources.states.deleting') : t('fileResources.actions.delete') }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-if="isDeleteModalOpen && deleteTarget && deleteTarget.resource_type !== TYPE_WINE"
    class="modal-mask"
    :class="{ 'modal-mask--preview': isPreviewOpen }"
    role="dialog"
    aria-modal="true"
    @click.self="closeDeleteModal"
  >
    <article class="file-resource-setting-modal file-resource-setting-modal--delete">
      <header class="file-resource-setting-modal__header">
        <h2>
          {{
            t(
              deleteTarget.resource_type === TYPE_IMAGE
                ? 'fileResources.delete_modal.image_title'
                : 'fileResources.delete_modal.document_title'
            )
          }}
        </h2>
        <button type="button" class="file-upload-modal__close" @click="closeDeleteModal">×</button>
      </header>
      <div class="file-resource-setting-modal__body">
        <p class="file-resource-setting-modal__copy">
          {{
            t(
              deleteTarget.resource_type === TYPE_IMAGE
                ? 'fileResources.delete_modal.image_body'
                : 'fileResources.delete_modal.document_body'
            )
          }}
        </p>
        <p v-if="deleteError" class="file-resource-error">{{ deleteError }}</p>
      </div>
      <footer class="file-resource-setting-modal__footer">
        <button type="button" class="file-upload-button file-upload-button--ghost" @click="closeDeleteModal">
          {{ t('fileResources.actions.cancel') }}
        </button>
        <button
          type="button"
          class="file-upload-button file-upload-button--danger"
          :disabled="isDeleting"
          @click="confirmDelete"
        >
          {{ isDeleting ? t('fileResources.states.deleting') : t('fileResources.actions.delete') }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-if="isPermissionModalOpen && permissionTarget"
    class="modal-mask"
    :class="{ 'modal-mask--preview': isPreviewOpen, 'modal-mask--permission': true }"
    role="dialog"
    aria-modal="true"
    @click.self="closePermissionModal"
  >
    <article class="file-resource-setting-modal file-resource-setting-modal--permission">
      <header class="file-resource-setting-modal__header">
        <h2>{{ t('fileResources.permission_modal.title') }}</h2>
        <button type="button" class="file-upload-modal__close" @click="closePermissionModal">×</button>
      </header>
      <div class="file-resource-setting-modal__resource">
        <span class="file-resource-setting-modal__resource-icon">
          <img
            v-if="permissionTarget.resource_type === TYPE_DOCUMENT"
            :src="resolveFileIcon(permissionTarget)"
            alt=""
          />
          <img
            v-else-if="previewUrls[permissionTarget.id]"
            :src="previewUrls[permissionTarget.id]"
            alt=""
          />
          <span v-else>{{ resolveThumbLabel(permissionTarget) }}</span>
        </span>
        <strong>{{ permissionTarget.attachment_filename || permissionTarget.display_name || '-' }}</strong>
      </div>
      <div class="file-resource-setting-modal__body file-resource-setting-modal__body--permission">
        <label class="file-resource-setting-modal__field">
          <span class="file-resource-setting-modal__field-label">
            <span class="file-resource-setting-modal__required" aria-hidden="true">*</span>
            {{ t('fileResources.permission_modal.department') }}
          </span>
          <span class="file-resource-setting-modal__select-wrap">
            <select v-model="permissionForm.department_role" class="file-resource-setting-modal__select">
              <option v-for="item in departmentOptions" :key="item" :value="item">{{ item }}</option>
            </select>
            <span class="file-resource-setting-modal__select-icon" v-html="glyphs.chevronDown" aria-hidden="true" />
          </span>
        </label>

        <fieldset class="file-resource-setting-modal__visibility">
          <legend class="file-resource-setting-modal__field-label">
            <span class="file-resource-setting-modal__required" aria-hidden="true">*</span>
            {{ t('fileResources.permission_modal.visibility') }}
          </legend>
          <div class="file-resource-setting-modal__visibility-options">
            <label class="file-resource-setting-modal__radio">
              <input v-model="permissionForm.visibility" type="radio" value="private" />
              <span class="file-resource-setting-modal__radio-mark" aria-hidden="true"></span>
              <span class="file-resource-setting-modal__radio-text">
                {{ t('fileResources.visibility.private') }}
              </span>
            </label>
            <label class="file-resource-setting-modal__radio">
              <input v-model="permissionForm.visibility" type="radio" value="public" />
              <span class="file-resource-setting-modal__radio-mark" aria-hidden="true"></span>
              <span class="file-resource-setting-modal__radio-text">
                {{ t('fileResources.visibility.public') }}
              </span>
            </label>
          </div>
        </fieldset>

        <p v-if="permissionError" class="file-resource-error file-resource-setting-modal__error">{{ permissionError }}</p>
      </div>
      <footer class="file-resource-setting-modal__footer file-resource-setting-modal__footer--permission">
        <button
          type="button"
          class="file-upload-button file-upload-button--ghost file-resource-setting-modal__action file-resource-setting-modal__action--ghost"
          @click="closePermissionModal"
        >
          {{ t('fileResources.actions.cancel') }}
        </button>
        <button
          type="button"
          class="file-upload-button file-upload-button--primary file-resource-setting-modal__action"
          @click="submitPermission"
        >
          {{ t('fileResources.actions.save') }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-if="isWinePickerOpen"
    class="modal-mask"
    :class="{ 'modal-mask--preview': isPreviewOpen }"
    role="dialog"
    aria-modal="true"
    @click.self="closeWinePicker"
  >
    <article class="file-picker-modal">
      <header class="file-picker-modal__header">
        <h2>{{ t('fileResources.picker.title') }}</h2>
        <button type="button" class="file-upload-modal__close" @click="closeWinePicker">×</button>
      </header>

      <div class="file-picker-modal__body">
        <label class="file-picker-search">
          <span class="file-picker-search__icon" v-html="glyphs.search" aria-hidden="true" />
          <input
            v-model="wineSearchQuery"
            type="search"
            :placeholder="t('fileResources.picker.search_placeholder')"
            @keydown.enter.prevent="handleWineSearchSubmit"
          />
        </label>

        <div class="file-picker-section-title">{{ t('fileResources.picker.results_title') }}</div>
        <p v-if="wineSearchError" class="file-resource-error file-picker-modal__error">{{ wineSearchError }}</p>

        <div v-if="isWineSearchLoading" class="file-picker-state">
          {{ t('fileResources.states.searching') }}
        </div>
        <div v-else-if="wineResults.length" class="file-picker-results">
          <label
            v-for="item in wineResults"
            :key="item.no"
            class="file-picker-result"
            :class="{ 'is-selected': selectedWineCandidateId === item.no }"
          >
            <input
              v-model="selectedWineCandidateId"
              type="radio"
              name="wine-selection"
              :value="item.no"
            />
            <div class="file-picker-result__content">
              <strong>{{ item.name_ch || item.name }}</strong>
              <span>{{ item.no }}</span>
              <small>{{ item.producer || '-' }}</small>
            </div>
          </label>
        </div>
        <div v-else class="file-picker-state">
          {{ t('fileResources.picker.empty') }}
        </div>
      </div>

      <footer class="file-picker-modal__footer">
        <button type="button" class="file-upload-button file-upload-button--ghost" @click="closeWinePicker">
          {{ t('fileResources.actions.cancel') }}
        </button>
        <button
          type="button"
          class="file-upload-button file-upload-button--primary"
          :disabled="!canConfirmWineSelection"
          @click="confirmWineSelection"
        >
          {{ t('fileResources.actions.confirm') }}
        </button>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.file-resource-stage-shell {
  background: #f4f6f8;
}

.file-topbar-search {
  width: min(300px, 100%);
  height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: var(--ys-control-radius, 6px);
  background: #f4f6f8;
  padding: 8px 14px;
}

.file-topbar-search__label {
  color: #919eab;
  font-size: 16px;
  line-height: 24px;
}

.file-resource-stage {
  width: 100%;
  max-width: 1280px;
  padding: 32px 24px 48px;
}

.file-resource-page {
  width: min(1080px, 100%);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.file-resource-page__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.file-resource-page__title-block {
  min-width: 0;
}

.file-resource-page__header h1 {
  margin: 0;
  color: #212b36;
  font-size: 32px;
  line-height: 48px;
  font-weight: 700;
}

.file-resource-card {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 0 2px rgba(145, 158, 171, 0.18), 0 6px 14px -4px rgba(145, 158, 171, 0.1);
  overflow: hidden;
}

.file-resource-tabs {
  display: flex;
  gap: 8px;
  padding: 0 24px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.file-resource-tab {
  min-width: 112px;
  height: 64px;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #637381;
  border-bottom: 2px solid transparent;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
}

.file-resource-tab small {
  font-size: 10px;
  line-height: 16px;
  font-weight: 600;
}

.file-resource-tab.is-active {
  color: #55b77f;
  border-bottom-color: #55b77f;
}

.file-resource-tab.is-disabled {
  color: #919eab;
}

.file-resource-toolbar {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.file-resource-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-resource-search {
  position: relative;
  width: min(320px, 100%);
}

.file-resource-search__icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
}

.file-resource-search input,
.file-upload-field input {
  width: 100%;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.file-resource-search input {
  height: 40px;
  padding: 8px 14px 8px 44px;
}

.file-resource-sort-shell {
  position: relative;
  flex-shrink: 0;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__trigger) {
  min-width: 212px;
  min-height: 40px;
  border-radius: var(--ys-control-radius, 6px);
  justify-content: space-between;
  padding: 8px 16px;
  color: #0d223d;
  border-color: rgba(99, 115, 129, 0.48);
  box-shadow: none;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__caret) {
  color: #7a879c;
  font-size: 14px;
  transition: transform 0.2s ease;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__caret.is-open) {
  transform: rotate(180deg);
}

.file-resource-sort-shell :deep(.file-resource-sort-control__panel) {
  left: auto;
  right: 0;
  width: 368px;
  margin-top: 8px;
  padding: 0;
  gap: 0;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 22px rgba(33, 43, 54, 0.13);
  border: 1px solid rgba(145, 158, 171, 0.24);
}

.file-resource-sort-shell :deep(.file-resource-sort-control__switch) {
  min-height: 40px;
  padding: 12px 16px;
  color: #637381;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.file-resource-sort-shell :deep(.file-resource-sort-control__switch input) {
  accent-color: #55b77f;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__row) {
  min-height: 68px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.16);
}

.file-resource-sort-shell :deep(.file-resource-sort-control__field) {
  gap: 10px;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__select) {
  min-width: 156px;
  height: 42px;
  border-radius: var(--ys-control-radius, 6px);
  border: 1px solid rgba(145, 158, 171, 0.32);
  box-shadow: none;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__direction) {
  min-width: 132px;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__direction-btn) {
  min-width: 132px;
  height: 42px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  color: #212b36;
  justify-content: center;
  padding: 0 12px;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__remove) {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  color: #919eab;
  font-size: 18px;
  line-height: 1;
}

.file-resource-sort-shell :deep(.file-resource-sort-control__actions) {
  padding: 12px 16px;
  align-items: center;
}

.file-resource-sort-shell :deep(.quote-link) {
  color: #3366ff;
  font-size: 14px;
  line-height: 22px;
}

.file-resource-sort-shell :deep(.quote-link:last-child) {
  color: #637381;
}

.file-upload-menu-anchor {
  position: relative;
}

.file-upload-trigger,
.file-upload-button {
  min-width: 132px;
  height: 40px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
}

.file-upload-trigger,
.file-upload-button--primary {
  background: #55b77f;
  color: #fff;
}

.file-upload-button--ghost {
  background: #fff;
  color: #212b36;
  border: 1px solid rgba(145, 158, 171, 0.32);
}

.file-upload-button--danger {
  background: #ff5630;
  color: #fff;
}

.file-upload-trigger:disabled,
.file-upload-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.file-upload-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 10px);
  width: 312px;
  padding: 10px;
  background: #fff;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 12px;
  box-shadow: 0 7px 18px rgba(16, 24, 40, 0.13);
  display: grid;
  gap: 8px;
  z-index: 20;
}

.file-upload-menu__item {
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 12px;
  background: #fff;
  padding: 14px 16px;
  display: grid;
  gap: 4px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.file-upload-menu__item:not(.is-disabled):hover,
.file-upload-menu__item:not(.is-disabled):focus-visible {
  border-color: rgba(33, 43, 54, 0.72);
  box-shadow: inset 0 0 0 1px rgba(33, 43, 54, 0.2);
  outline: none;
}

.file-upload-menu__item strong {
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
}

.file-upload-menu__item small {
  color: #637381;
  font-size: 13px;
  line-height: 20px;
}

.file-upload-menu__item.is-disabled {
  background: #f9fafb;
  cursor: not-allowed;
}

.file-resource-notice,
.file-resource-error {
  margin: 0;
  padding: 0 24px 12px;
  font-size: 14px;
  line-height: 22px;
}

.file-resource-notice {
  color: #637381;
}

.file-resource-error {
  color: #b42318;
}

.file-resource-table-wrap {
  min-height: 560px;
}

.file-resource-table {
  display: flex;
  flex-direction: column;
}

.file-resource-table__head,
.file-resource-table__row {
  display: grid;
  grid-template-columns: minmax(320px, 1.5fr) minmax(220px, 1fr) minmax(160px, 0.8fr) minmax(180px, 0.8fr) 66px;
  align-items: center;
}

.file-resource-table__head {
  min-height: 56px;
  background: #f4f6f8;
}

.file-resource-table__head > div {
  padding: 16px 14px 16px 12px;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
}

.file-resource-table__row {
  min-height: 68px;
  background: #fff;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  cursor: pointer;
  transition: background 0.2s ease, box-shadow 0.2s ease;
}

.file-resource-table__row:hover {
  background: #fcf8f8;
}

.file-resource-table__row:focus-visible {
  outline: 2px solid #55b77f;
  outline-offset: -2px;
}

.file-resource-table__name,
.file-resource-table__cell,
.file-resource-table__placeholder {
  padding: 16px 14px 16px 12px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.file-resource-table__name {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-resource-thumb {
  width: 36px;
  height: 36px;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 4px;
  overflow: hidden;
  background: #fff;
  flex-shrink: 0;
}

.file-resource-thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center;
  display: block;
}

.file-resource-thumb__placeholder {
  width: 100%;
  height: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #919eab;
  font-size: 10px;
  font-weight: 700;
}

.file-resource-table__meta {
  min-width: 0;
  display: grid;
}

.file-resource-table__meta strong,
.file-resource-table__meta small {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-resource-table__meta small {
  color: #637381;
}

.file-resource-table__placeholder {
  display: flex;
  justify-content: center;
}

.file-resource-row-menu-anchor {
  position: relative;
}

.file-resource-row-menu-toggle {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-resource-row-menu-toggle:hover {
  background: rgba(145, 158, 171, 0.12);
}

.file-resource-row-menu-toggle img {
  width: 20px;
  height: 20px;
}

.file-resource-row-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: 180px;
  padding: 8px;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.13);
  display: grid;
  gap: 2px;
  z-index: 15;
}

.file-resource-row-menu__item {
  min-height: 44px;
  border-radius: 12px;
  padding: 10px 14px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
  text-align: left;
}

.file-resource-row-menu__item:hover {
  background: #f4f6f8;
}

.file-resource-row-menu__item--danger {
  margin-top: 4px;
  padding-top: 14px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  color: #d92d20;
}

.file-resource-preview {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: rgba(18, 23, 30, 0.96);
}

.file-resource-preview__layout {
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  position: relative;
  isolation: isolate;
}

.file-resource-preview__layout.is-info-open {
  grid-template-columns: minmax(0, 1fr) 300px;
}

.file-resource-preview__layout::after,
.file-library-preview__layout::after {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease, background 0.2s ease;
  z-index: 6;
}

.file-resource-preview__layout.is-dimmed::after,
.file-library-preview__layout.is-dimmed::after {
  background: rgba(0, 0, 0, 0.46);
  opacity: 1;
  pointer-events: auto;
}

.file-resource-preview__stage {
  min-width: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 16px;
  padding: 20px 24px 24px;
  position: relative;
  z-index: 1;
}

.file-resource-preview__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.file-resource-preview__title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  color: #fff;
}

.file-resource-preview__title strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
}

.file-resource-preview__toolbar,
.file-library-preview__toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-resource-preview__toolbar-button,
.file-library-preview__toolbar-button {
  width: 40px;
  height: 40px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.92);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.file-resource-preview__toolbar-button:hover,
.file-library-preview__toolbar-button:hover {
  background: rgba(255, 255, 255, 0.16);
  border-color: rgba(255, 255, 255, 0.18);
}

.file-resource-preview__toolbar-button.is-active,
.file-library-preview__toolbar-button.is-active {
  background: rgba(85, 183, 127, 0.28);
  border-color: rgba(85, 183, 127, 0.5);
}

.file-resource-preview__toolbar-button:disabled,
.file-library-preview__toolbar-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.file-resource-preview__toolbar-button span,
.file-library-preview__toolbar-button span {
  display: inline-flex;
}

.file-resource-preview__toolbar-button--ghost,
.file-library-preview__toolbar-button--ghost {
  background: rgba(255, 255, 255, 0.06);
}

.file-resource-preview__canvas {
  min-height: 0;
  position: relative;
  display: block;
  height: 100%;
}

.file-resource-preview__nav,
.file-library-preview__nav {
  position: absolute;
  top: 50%;
  z-index: 2;
  transform: translateY(-50%);
  width: 44px;
  height: 44px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.file-resource-preview__nav--prev,
.file-library-preview__nav--prev {
  left: 16px;
}

.file-resource-preview__nav--next,
.file-library-preview__nav--next {
  right: 16px;
}

.file-resource-preview__nav:hover:not(:disabled),
.file-library-preview__nav:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.56);
}

.file-resource-preview__nav:disabled,
.file-library-preview__nav:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}

.file-resource-preview__image-shell {
  min-width: 0;
  min-height: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.file-resource-preview__image {
  max-width: 100%;
  max-height: calc(100vh - 140px);
  object-fit: contain;
}

.file-resource-preview__state,
.file-library-preview__state {
  color: rgba(255, 255, 255, 0.72);
  font-size: 15px;
  line-height: 24px;
  text-align: center;
}

.file-resource-preview__state--error,
.file-library-preview__state--error {
  color: #ffb4a8;
}

.file-resource-preview__info {
  background: #fff;
  height: 100%;
  border-left: 1px solid rgba(145, 158, 171, 0.24);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: auto;
  position: relative;
  z-index: 1;
}

.modal-mask--preview {
  z-index: 1300;
}

.file-resource-preview__info-header {
  padding: 20px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.file-resource-preview__info-header h2 {
  margin: 0;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  font-weight: 700;
}

.file-resource-preview__info-close,
.file-library-preview__info-close {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #637381;
}

.file-resource-preview__info-close:hover,
.file-library-preview__info-close:hover {
  background: rgba(145, 158, 171, 0.12);
}

.file-resource-preview__panel {
  padding: 20px 16px 0;
}

.file-resource-preview__panel h3 {
  margin: 0 0 12px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
}

.file-resource-preview__card,
.file-resource-preview__related {
  background: #f8fafc;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 12px;
}

.file-resource-preview__card {
  padding: 16px;
}

.file-resource-preview__card > strong {
  display: block;
  margin-bottom: 12px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
}

.file-resource-preview__meta {
  margin: 0;
  display: grid;
  gap: 10px;
}

.file-resource-preview__meta div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 12px;
}

.file-resource-preview__meta dt {
  color: #637381;
  font-size: 12px;
  line-height: 18px;
}

.file-resource-preview__meta dd {
  margin: 0;
  color: #212b36;
  font-size: 13px;
  line-height: 20px;
  text-align: right;
}

.file-resource-preview__meta--stacked div {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.file-resource-preview__related {
  overflow: hidden;
}

.file-resource-preview__related-head,
.file-resource-preview__related-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px;
  gap: 12px;
  padding: 12px 16px;
}

.file-resource-preview__related-head {
  background: #f4f6f8;
  color: #637381;
  font-size: 12px;
  line-height: 18px;
  font-weight: 700;
}

.file-resource-preview__related-row {
  border-top: 1px solid rgba(145, 158, 171, 0.18);
  color: #212b36;
  font-size: 13px;
  line-height: 20px;
}

.file-resource-state,
.file-resource-empty {
  min-height: 500px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 14px;
  color: #637381;
  padding: 24px;
  text-align: center;
}

.file-resource-empty img {
  width: 220px;
  max-width: 100%;
}

.file-resource-footer {
  min-height: 58px;
  padding: 10px 8px 10px 24px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 24px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.file-resource-footer__pager {
  display: inline-flex;
  gap: 8px;
}

.file-resource-footer__pager button {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  color: #212b36;
  font-size: 20px;
  line-height: 1;
}

.file-resource-footer__pager button:disabled {
  color: rgba(145, 158, 171, 0.8);
}

.file-upload-modal {
  width: min(1040px, calc(100vw - 48px));
  background: #fff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.file-upload-modal__header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.file-upload-modal__header h2 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
}

.file-upload-modal__header p {
  margin: 8px 0 0;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
}

.file-upload-modal__close {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  color: #637381;
  font-size: 0;
  line-height: 1;
  flex-shrink: 0;
}

.file-upload-modal__close::before {
  content: '×';
  font-size: 24px;
  line-height: 1;
}

.file-upload-modal__close:hover {
  background: rgba(145, 158, 171, 0.12);
}

.file-upload-modal__body {
  display: grid;
  grid-template-columns: minmax(0, 414px) minmax(0, 1fr);
  gap: 24px;
  padding: 24px;
}

.file-upload-step {
  display: grid;
  gap: 16px;
  align-content: start;
}

.file-upload-step__header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.file-upload-step__index {
  color: #55b77f;
  font-size: 12px;
  line-height: 18px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.file-upload-step__header h3 {
  margin: 0;
  color: #212b36;
  font-size: 20px;
  line-height: 30px;
  font-weight: 700;
}

.file-upload-step__header p {
  margin: 4px 0 0;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
}

.file-upload-dropzone {
  width: 100%;
  min-height: 520px;
  border: 1px dashed rgba(145, 158, 171, 0.64);
  border-radius: 16px;
  background: #f9fbfc;
  padding: 24px;
}

.file-upload-dropzone__placeholder,
.file-upload-dropzone__preview {
  width: 100%;
  min-height: 460px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
}

.file-upload-dropzone__placeholder strong {
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
}

.file-upload-dropzone__icon,
.file-upload-wine-empty__icon {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(145, 158, 171, 0.16);
  color: #637381;
  font-size: 0;
  line-height: 1;
  font-weight: 700;
}

.file-upload-dropzone__icon::before,
.file-upload-wine-empty__icon::before {
  content: '+';
  font-size: 24px;
  line-height: 1;
}

.file-upload-dropzone__preview img {
  width: 100%;
  max-height: 420px;
  object-fit: contain;
  border-radius: 12px;
}

.file-upload-dropzone__preview small,
.file-upload-dropzone__hint {
  margin: 0;
  color: #637381;
  font-size: 13px;
  line-height: 20px;
}

.file-upload-wine-empty {
  min-height: 520px;
  border: 1px dashed rgba(145, 158, 171, 0.64);
  border-radius: 16px;
  background: #f9fbfc;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
}

.file-upload-selection-card {
  min-height: 520px;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 16px;
  background: #fff;
  padding: 24px;
  display: grid;
  gap: 20px;
}

.file-upload-selection-card__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.file-upload-selection-card__top strong {
  display: block;
  color: #212b36;
  font-size: 20px;
  line-height: 30px;
  font-weight: 700;
}

.file-upload-selection-card__top small {
  display: block;
  margin-top: 4px;
  color: #637381;
  font-size: 13px;
  line-height: 20px;
}

.file-upload-link {
  color: #55b77f;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
  white-space: nowrap;
}

.file-upload-selection-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.file-upload-selection-grid dt {
  color: #637381;
  font-size: 12px;
  line-height: 18px;
  margin: 0 0 6px;
}

.file-upload-selection-grid dd {
  margin: 0;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
}

.file-upload-related {
  display: grid;
  gap: 12px;
}

.file-upload-related__title {
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  font-weight: 700;
}

.file-upload-related__table {
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 14px;
  overflow: hidden;
}

.file-upload-related__head,
.file-upload-related__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 92px;
  gap: 16px;
  padding: 12px 16px;
}

.file-upload-related__head {
  background: #f4f6f8;
  color: #637381;
  font-size: 12px;
  line-height: 18px;
  font-weight: 700;
}

.file-upload-related__row {
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.file-picker-modal {
  width: min(760px, calc(100vw - 48px));
  background: #fff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.file-picker-modal__header,
.file-picker-modal__footer {
  padding: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.file-picker-modal__header {
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.file-picker-modal__header h2 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
}

.file-picker-modal__footer {
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  justify-content: flex-end;
}

.file-picker-modal__body {
  padding: 24px;
  display: grid;
  gap: 16px;
}

.file-picker-search {
  position: relative;
}

.file-picker-search__icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
}

.file-picker-search input {
  width: 100%;
  height: 44px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 14px 10px 44px;
  background: #fff;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.file-picker-section-title {
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
}

.file-picker-results {
  max-height: 420px;
  overflow: auto;
  display: grid;
  gap: 10px;
}

.file-picker-result {
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 14px;
  padding: 16px;
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.file-picker-result input {
  margin-top: 5px;
}

.file-picker-result.is-selected {
  border-color: #55b77f;
  background: rgba(139, 216, 168, 0.10);
}

.file-picker-result__content {
  display: grid;
  gap: 4px;
}

.file-picker-result__content strong {
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  font-weight: 700;
}

.file-picker-result__content span,
.file-picker-result__content small {
  color: #637381;
  font-size: 13px;
  line-height: 20px;
}

.file-picker-state {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #637381;
  text-align: center;
  padding: 24px;
}

.file-picker-modal__error,
.file-resource-error {
  padding-inline: 24px;
}

.file-upload-modal__footer {
  padding: 0 24px 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.file-resource-delete-modal {
  width: 480px;
  min-height: 208px;
  background: #fff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.file-resource-delete-modal__header,
.file-resource-delete-modal__footer {
  padding: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.file-resource-delete-modal__header {
  padding-bottom: 8px;
}

.file-resource-delete-modal__header h2 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 36px;
  font-weight: 700;
}

.file-resource-delete-modal__body {
  padding: 24px;
}

.file-resource-delete-modal__copy {
  margin: 0;
  color: #637381;
  font-size: 16px;
  line-height: 44px;
}

.file-resource-delete-modal__error {
  padding: 16px 0 0;
}

.file-resource-delete-modal__footer {
  justify-content: flex-end;
}

.file-resource-page__upload-anchor {
  margin-left: auto;
  flex-shrink: 0;
  align-self: flex-start;
}

.file-upload-trigger {
  min-width: 132px;
  gap: 8px;
}

.file-upload-trigger__icon {
  display: inline-flex;
}

.file-library-table-wrap {
  padding-bottom: 0;
}

.file-library-table {
  display: grid;
}

.file-library-table__head,
.file-library-table__row {
  display: grid;
  grid-template-columns: minmax(0, 2.5fr) 1fr 1fr 1fr 56px;
  align-items: center;
  padding-inline: 16px;
}

.file-library-table__head {
  min-height: 52px;
  margin-inline: 24px;
  background: #f4f6f8;
  color: #637381;
  font-size: 12px;
  line-height: 18px;
  font-weight: 700;
}

.file-library-table__head > div,
.file-library-table__cell,
.file-library-table__actions {
  padding: 0 12px;
}

.file-library-table__row {
  min-height: 56px;
  margin-inline: 24px;
  border-top: 1px solid rgba(145, 158, 171, 0.2);
}

.file-library-table__name {
  min-width: 0;
  height: 100%;
  padding: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}

.file-library-table__thumb {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
  background: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-library-table__thumb.is-document {
  width: 18px;
  height: 22px;
  border-radius: 0;
}

.file-library-table__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.file-library-table__file-icon {
  object-fit: contain !important;
}

.file-library-table__meta {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.file-library-table__meta strong {
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 400;
}

.file-library-table__meta small,
.file-library-table__cell {
  color: #637381;
  font-size: 14px;
  line-height: 22px;
}

.file-library-table__actions {
  display: flex;
  justify-content: center;
}

.file-library-preview {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: #1f2731;
}

.file-library-preview__layout {
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  position: relative;
  isolation: isolate;
}

.file-library-preview__layout.is-info-open {
  grid-template-columns: minmax(0, 1fr) 300px;
}

.file-library-preview__stage {
  min-width: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 24px;
  padding: 24px;
  position: relative;
  z-index: 1;
}

.file-library-preview__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.file-library-preview__title {
  min-width: 0;
  display: grid;
  gap: 6px;
  color: #fff;
}

.file-library-preview__title strong {
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
}

.file-library-preview__title small {
  color: rgba(255, 255, 255, 0.65);
  font-size: 13px;
  line-height: 20px;
}

.file-library-preview__canvas {
  min-height: 0;
  position: relative;
  display: block;
  height: 100%;
}

.file-library-preview__content {
  min-height: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.file-library-preview__image {
  max-width: 100%;
  max-height: calc(100vh - 176px);
  object-fit: contain;
}

.file-library-preview__document-state {
  display: grid;
  justify-items: center;
  gap: 16px;
  text-align: center;
  color: #fff;
}

.file-library-preview__document-state strong {
  font-size: 18px;
  line-height: 26px;
  font-weight: 700;
}

.file-library-preview__document-state p {
  margin: 0;
  color: rgba(255, 255, 255, 0.7);
  font-size: 14px;
  line-height: 22px;
}

.file-library-preview__document-icon {
  width: 84px;
  height: 102px;
  object-fit: contain;
}

.file-library-preview__download {
  min-width: 96px;
  height: 32px;
  border-radius: 6px;
  background: #55b77f;
  color: #fff;
  padding: 0 14px;
  font-size: 13px;
  line-height: 20px;
  font-weight: 700;
}

.file-library-preview__info {
  background: #fff;
  border-left: 1px solid rgba(145, 158, 171, 0.24);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: auto;
  position: relative;
  z-index: 1;
}

.file-library-preview__info-header {
  padding: 20px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.file-library-preview__info-header h2 {
  margin: 0;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  font-weight: 700;
}

.file-library-preview__info-body {
  padding: 20px;
  display: grid;
  gap: 20px;
  align-content: start;
}

.file-library-preview__summary {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-library-preview__summary-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  overflow: hidden;
  background: #f4f6f8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.file-library-preview__summary-icon img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-library-preview__summary strong {
  display: block;
  color: #212b36;
  font-size: 15px;
  line-height: 22px;
  font-weight: 700;
}

.file-library-preview__summary small {
  display: block;
  margin-top: 2px;
  color: #637381;
  font-size: 12px;
  line-height: 18px;
}

.file-library-preview__meta {
  margin: 0;
  display: grid;
  gap: 14px;
}

.file-library-preview__meta div {
  display: grid;
  gap: 6px;
}

.file-library-preview__meta dt {
  color: #919eab;
  font-size: 12px;
  line-height: 18px;
}

.file-library-preview__meta dd {
  margin: 0;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.file-library-upload {
  width: min(760px, calc(100vw - 48px));
  background: #fff;
  border-radius: 24px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.file-library-upload__header,
.file-resource-setting-modal__header {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.file-library-upload__header h2,
.file-resource-setting-modal__header h2 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
}

.file-library-upload__header {
  align-items: center;
  padding: 24px 28px;
}

.file-library-upload__header h2 {
  font-size: 20px;
  line-height: 30px;
}

.file-library-upload__body--figma {
  padding: 20px 28px 0;
  display: grid;
  gap: 20px;
}

.file-library-upload__error-banner {
  margin: 20px 28px 0;
  min-height: 40px;
  border: 1px solid #ffd5cc;
  border-radius: 10px;
  background: #fff2ef;
  color: #b42318;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
}

.file-library-upload__error-icon {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: #ff5630;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  line-height: 1;
  font-weight: 700;
  flex-shrink: 0;
}

.file-library-upload__settings-panel {
  background: #f4f6f8;
  border-radius: 12px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 24px;
  padding: 22px 24px;
}

.file-library-upload__stage--figma {
  display: grid;
  align-content: start;
  gap: 16px;
}

.file-library-upload__field--figma,
.file-library-upload__visibility--figma {
  margin: 0;
  padding: 0;
  border: 0;
  display: grid;
  gap: 12px;
}

.file-library-upload__field-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
}

.file-library-upload__required {
  color: #ff5630;
  font-size: 16px;
  line-height: 1;
}

.file-library-upload__select-wrap {
  position: relative;
  display: block;
}

.file-library-upload__select {
  width: 100%;
  min-height: 44px;
  padding: 0 44px 0 16px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  appearance: none;
}

.file-library-upload__select:focus {
  outline: none;
  border-color: rgba(33, 43, 54, 0.42);
  box-shadow: 0 0 0 3px rgba(33, 43, 54, 0.08);
}

.file-library-upload__select-icon {
  position: absolute;
  top: 50%;
  right: 14px;
  transform: translateY(-50%);
  color: #637381;
  pointer-events: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-library-upload__select-icon :deep(svg) {
  display: block;
}

.file-library-upload__visibility-options {
  display: flex;
  align-items: center;
  gap: 28px;
  min-height: 44px;
  flex-wrap: wrap;
}

.file-library-upload__radio {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  font-weight: 600;
  cursor: pointer;
}

.file-library-upload__radio input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.file-library-upload__radio-mark {
  position: relative;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  border: 2px solid #637381;
  background: #fff;
  flex-shrink: 0;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.file-library-upload__radio-mark::after {
  content: '';
  position: absolute;
  inset: 0;
  width: 10px;
  height: 10px;
  margin: auto;
  border-radius: 999px;
  background: #b00000;
  transform: scale(0);
  transition: transform 0.18s ease;
}

.file-library-upload__radio input:checked + .file-library-upload__radio-mark {
  border-color: #b00000;
}

.file-library-upload__radio input:checked + .file-library-upload__radio-mark::after {
  transform: scale(1);
}

.file-library-upload__radio input:focus-visible + .file-library-upload__radio-mark {
  box-shadow: 0 0 0 4px rgba(176, 0, 0, 0.12);
}

.file-library-upload__dropzone--figma {
  min-height: 220px;
  border: 1px dashed rgba(145, 158, 171, 0.4);
  border-radius: 16px;
  background: #f7f9fc;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  align-items: center;
  gap: 18px;
  padding: 26px 34px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease;
}

.file-library-upload__dropzone--figma:focus-visible {
  outline: none;
  border-color: rgba(51, 102, 255, 0.45);
  box-shadow: 0 0 0 4px rgba(51, 102, 255, 0.12);
}

.file-library-upload__dropzone--figma.is-drag-active {
  border-color: rgba(85, 183, 127, 0.45);
  background: #fff7f5;
  box-shadow: inset 0 0 0 1px rgba(139, 216, 168, 0.18);
}

.file-library-upload__illustration {
  width: min(100%, 250px);
  justify-self: center;
}

.file-library-upload__dropzone-copy {
  display: grid;
  gap: 8px;
}

.file-library-upload__dropzone-copy strong {
  color: #212b36;
  font-size: 18px;
  line-height: 28px;
  font-weight: 700;
}

.file-library-upload__dropzone-copy p,
.file-library-upload__dropzone-copy small {
  margin: 0;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
}

.file-library-upload__dropzone-link {
  padding: 0;
  background: transparent;
  color: #3366ff;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
  text-decoration: none;
}

.file-library-upload__dropzone-link:hover {
  text-decoration: underline;
}

.file-library-upload__inline-message {
  color: #b42318;
  font-size: 14px;
  line-height: 22px;
}

.file-library-upload__queue--figma {
  border: 0;
  background: transparent;
}

.file-library-upload__queue-list {
  max-height: none;
  overflow: visible;
  display: grid;
  gap: 12px;
}

.file-library-upload__queue-item--figma {
  padding: 10px 12px;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 24px;
  gap: 14px;
  align-items: center;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 10px;
  background: #fff;
}

.file-library-upload__queue-item + .file-library-upload__queue-item {
  border-top: 0;
}

.file-library-upload__queue-thumb {
  width: 44px;
  height: 44px;
  border-radius: 8px;
  overflow: hidden;
  background: #f4f6f8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-library-upload__queue-thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.file-library-upload__queue-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.file-library-upload__queue-copy strong {
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-library-upload__queue-copy small {
  color: #637381;
  font-size: 12px;
  line-height: 18px;
}

.file-library-upload__queue-remove {
  width: 24px;
  height: 24px;
  border-radius: 999px;
  color: #919eab;
  font-size: 22px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-library-upload__queue-remove:hover {
  background: rgba(145, 158, 171, 0.14);
}

.file-library-upload__footer,
.file-resource-setting-modal__footer {
  padding: 0 24px 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.file-library-upload__footer {
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  padding: 18px 28px 24px;
}

.file-resource-setting-modal {
  width: min(480px, calc(100vw - 48px));
  background: #fff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.file-resource-setting-modal__body {
  padding: 20px 24px 24px;
  display: grid;
  gap: 16px;
}

.modal-mask--permission {
  background: rgba(16, 24, 40, 0.76);
}

.file-resource-setting-modal--permission {
  width: min(636px, calc(100vw - 48px));
  border-radius: 24px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.2);
}

.file-resource-setting-modal--permission .file-resource-setting-modal__header {
  padding: 32px 32px 26px;
  align-items: center;
}

.file-resource-setting-modal--permission .file-resource-setting-modal__header h2 {
  font-size: 20px;
  line-height: 30px;
}

.file-resource-setting-modal--permission .file-upload-modal__close {
  width: 28px;
  height: 28px;
  color: #637381;
}

.file-resource-setting-modal--permission .file-upload-modal__close::before {
  font-size: 20px;
}

.file-resource-setting-modal--permission .file-upload-modal__close:hover {
  background: rgba(145, 158, 171, 0.16);
}

.file-resource-setting-modal__resource {
  padding: 22px 32px;
  background: #f4f6f8;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: center;
  gap: 16px;
}

.file-resource-setting-modal__resource-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.file-resource-setting-modal__resource-icon img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-resource-setting-modal__resource-icon span {
  color: #637381;
  font-size: 11px;
  line-height: 1;
  font-weight: 700;
  text-transform: uppercase;
}

.file-resource-setting-modal__resource strong {
  min-width: 0;
  color: #637381;
  font-size: 18px;
  line-height: 28px;
  font-weight: 700;
  word-break: break-word;
}

.file-resource-setting-modal__body--permission {
  padding: 32px;
  gap: 28px;
}

.file-resource-setting-modal__field,
.file-resource-setting-modal__visibility {
  margin: 0;
  display: grid;
  gap: 14px;
  border: 0;
  padding: 0;
}

.file-resource-setting-modal__field-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
}

.file-resource-setting-modal__required {
  color: #ff5630;
  font-size: 16px;
  line-height: 1;
}

.file-resource-setting-modal__select-wrap {
  position: relative;
  display: block;
}

.file-resource-setting-modal__select {
  width: 100%;
  min-height: 52px;
  padding: 0 52px 0 16px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  appearance: none;
}

.file-resource-setting-modal__select:focus {
  outline: none;
  border-color: rgba(33, 43, 54, 0.42);
  box-shadow: 0 0 0 3px rgba(33, 43, 54, 0.08);
}

.file-resource-setting-modal__select-icon {
  position: absolute;
  top: 50%;
  right: 16px;
  transform: translateY(-50%);
  color: #637381;
  pointer-events: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-resource-setting-modal__select-icon :deep(svg) {
  display: block;
}

.file-resource-setting-modal__visibility-options {
  display: flex;
  align-items: center;
  gap: 36px;
  flex-wrap: wrap;
}

.file-resource-setting-modal__radio {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
  font-weight: 600;
  cursor: pointer;
}

.file-resource-setting-modal__radio input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.file-resource-setting-modal__radio-mark {
  position: relative;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  border: 2px solid #637381;
  background: #fff;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
  flex-shrink: 0;
}

.file-resource-setting-modal__radio-mark::after {
  content: '';
  position: absolute;
  inset: 0;
  width: 12px;
  height: 12px;
  margin: auto;
  border-radius: 999px;
  background: #b00000;
  transform: scale(0);
  transition: transform 0.18s ease;
}

.file-resource-setting-modal__radio input:checked + .file-resource-setting-modal__radio-mark {
  border-color: #b00000;
}

.file-resource-setting-modal__radio input:checked + .file-resource-setting-modal__radio-mark::after {
  transform: scale(1);
}

.file-resource-setting-modal__radio input:focus-visible + .file-resource-setting-modal__radio-mark {
  box-shadow: 0 0 0 4px rgba(176, 0, 0, 0.12);
}

.file-resource-setting-modal__radio-text {
  white-space: nowrap;
}

.file-resource-setting-modal__footer--permission {
  padding: 20px 32px 32px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
}

.file-resource-setting-modal__action {
  min-width: 80px;
  height: 48px;
  padding: 0 20px;
  border-radius: 14px;
  font-size: 16px;
  line-height: 24px;
}

.file-resource-setting-modal__action--ghost {
  border-color: rgba(145, 158, 171, 0.42);
}

.file-resource-setting-modal__copy {
  margin: 0;
  color: #637381;
  font-size: 14px;
  line-height: 22px;
}

.file-resource-setting-modal__error {
  padding: 0;
}

.composer-file-input {
  display: none;
}

@media (max-width: 1100px) {
  .file-resource-stage {
    padding: 24px 16px 40px;
  }

  .file-resource-preview__layout,
  .file-library-preview__layout {
    grid-template-columns: minmax(0, 1fr) 280px;
  }

  .file-resource-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .file-resource-toolbar__actions {
    width: 100%;
    justify-content: space-between;
  }

  .file-upload-modal {
    width: min(920px, calc(100vw - 32px));
  }

  .file-library-upload__settings-panel {
    grid-template-columns: 1fr;
    gap: 18px;
  }
}

@media (max-width: 900px) {
  .file-resource-stage {
    padding: 20px 12px 32px;
  }

  .file-topbar-search {
    width: 100%;
  }

  .file-resource-page__header,
  .file-resource-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .file-resource-page__upload-anchor {
    align-self: flex-end;
  }

  .file-resource-table__head,
  .file-library-table__head {
    display: none;
  }

  .file-resource-table__row,
  .file-library-table__row {
    grid-template-columns: 1fr 40px;
    gap: 10px 12px;
    padding: 14px 16px;
    margin-inline: 0;
  }

  .file-resource-table__name,
  .file-resource-table__cell,
  .file-resource-table__placeholder,
  .file-library-table__name,
  .file-library-table__cell,
  .file-library-table__actions {
    padding: 0;
  }

  .file-resource-table__name,
  .file-library-table__name {
    grid-column: 1 / 2;
  }

  .file-resource-table__cell:nth-child(2),
  .file-resource-table__cell:nth-child(3),
  .file-resource-table__cell:nth-child(4),
  .file-library-table__cell {
    grid-column: 1 / 2;
    color: #637381;
    font-size: 13px;
    line-height: 20px;
  }

  .file-resource-table__placeholder,
  .file-library-table__actions {
    grid-column: 2 / 3;
    grid-row: 1 / span 4;
    align-self: start;
  }

  .file-resource-footer {
    flex-wrap: wrap;
    justify-content: space-between;
    padding-inline: 16px;
  }

  .file-upload-modal__body,
  .file-library-upload__body {
    grid-template-columns: 1fr;
  }

  .file-library-upload__body--figma {
    padding-left: 20px;
    padding-right: 20px;
  }

  .file-library-upload__settings-panel {
    grid-template-columns: 1fr;
    gap: 18px;
    padding: 18px 20px;
  }

  .file-library-upload__dropzone--figma {
    grid-template-columns: 1fr;
    justify-items: center;
    text-align: center;
    padding: 24px 20px;
  }

  .file-library-upload__dropzone-copy {
    justify-items: center;
  }

  .file-upload-dropzone,
  .file-upload-wine-empty,
  .file-upload-selection-card {
    min-height: 320px;
  }

  .file-upload-dropzone__placeholder,
  .file-upload-dropzone__preview {
    min-height: 260px;
  }

  .file-upload-selection-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .file-resource-preview__layout,
  .file-library-preview__layout {
    grid-template-columns: 1fr;
  }

  .file-resource-preview__layout.is-info-open,
  .file-library-preview__layout.is-info-open {
    grid-template-columns: 1fr;
  }

  .file-resource-preview__stage,
  .file-library-preview__stage {
    padding: 16px;
  }

  .file-resource-preview__canvas,
  .file-library-preview__canvas {
    min-height: 0;
  }

  .file-resource-preview__nav--prev,
  .file-library-preview__nav--prev {
    left: 8px;
  }

  .file-resource-preview__nav--next,
  .file-library-preview__nav--next {
    right: 8px;
  }

  .file-resource-preview__title strong,
  .file-library-preview__title strong {
    font-size: 18px;
    line-height: 26px;
  }

  .file-resource-preview__info,
  .file-library-preview__info {
    position: absolute;
    inset: 72px 0 0 auto;
    width: min(300px, 82vw);
    box-shadow: -16px 0 32px rgba(0, 0, 0, 0.22);
  }

  .file-resource-toolbar__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .file-resource-sort-shell,
  .file-upload-trigger {
    width: 100%;
  }

  .file-upload-trigger {
    min-width: 0;
  }

  .file-resource-sort-shell :deep(.file-resource-sort-control__trigger) {
    min-width: 0;
    width: 100%;
  }

  .file-resource-sort-shell :deep(.file-resource-sort-control__panel) {
    left: 0;
    right: 0;
    width: auto;
  }

  .file-upload-menu {
    left: 0;
    right: 0;
    width: auto;
  }

  .file-upload-modal__header,
  .file-library-upload__header,
  .file-picker-modal__header,
  .file-picker-modal__footer,
  .file-resource-setting-modal__header,
  .file-resource-setting-modal__footer {
    padding: 20px;
  }

  .file-upload-modal__body,
  .file-library-upload__body,
  .file-picker-modal__body,
  .file-resource-setting-modal__body {
    padding: 20px;
  }

  .file-library-upload {
    width: min(760px, calc(100vw - 24px));
  }

  .file-library-upload__error-banner {
    margin-left: 20px;
    margin-right: 20px;
  }

  .file-library-upload__footer {
    padding-left: 20px;
    padding-right: 20px;
  }

  .file-resource-setting-modal--permission {
    width: min(636px, calc(100vw - 24px));
  }

  .file-resource-setting-modal--permission .file-resource-setting-modal__header {
    padding: 24px 24px 20px;
  }

  .file-resource-setting-modal__resource,
  .file-resource-setting-modal__footer--permission {
    padding-left: 24px;
    padding-right: 24px;
  }

  .file-resource-setting-modal__resource {
    padding-top: 18px;
    padding-bottom: 18px;
  }

  .file-resource-setting-modal__body--permission {
    gap: 24px;
  }

  .file-resource-setting-modal__visibility-options {
    gap: 20px;
  }

  .file-upload-selection-card__top {
    flex-direction: column;
  }
}
</style>
