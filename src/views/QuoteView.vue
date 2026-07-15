<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { useFileUploader } from '../composables/useFileUploader'
import { fetchConversationMessages, sendChatMessage } from '../services/ysApi'
import ChatComposer from '../components/ChatComposer.vue'
import QuoteResponseRenderer from '../components/QuoteResponseRenderer.vue'
import arrowButtonAsset from '../assets/arrow-button.svg'
import logoMain from '../assets/ysLogo_transparent.png'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import iconDrag from '../assets/ic_drag.svg'
import iconUpDown from '../assets/ic-ud.svg'
import glassRed from '../assets/placeholder.png'
import glassWhite from '../assets/placeholder.png'
import glassRose from '../assets/placeholder.png'
import checkmark from '../assets/q-ic_checkmark.png'
import tabShape0 from '../assets/q-tab-shape.svg'
import tabShape0Active from '../assets/q-tab-shape-a.svg'
import tabShape1 from '../assets/q-tab-shape-1.svg'
import tabShape1Active from '../assets/q-tab-shape-1-a.svg'
import tabShape2 from '../assets/q-tab-shape-2.svg'
import tabShape2Active from '../assets/q-tab-shape-2-a.svg'
import tabShape3 from '../assets/q-tab-shape-3.svg'
import tabShape3Active from '../assets/q-tab-shape-3-a.svg'
import iconCopy from '../assets/ic-copy.svg'
import iconMoreVertical from '../assets/ic-more-vertical.svg'
import iconShare from '../assets/ic-share.svg'
import iconStar from '../assets/ic-star.svg'
import { writeClipboard } from '../utils/clipboard'
import { snapshotEdmTableColumns } from '../utils/edmTable'
import {
  assertUsableChatResponse,
  normalizeChatAnswerPayload,
  resolveChatFlowErrorMessage,
} from '../utils/chatFlow'
import { buildQuoteChatRequest } from '../utils/quoteChatRequest'
import { extractFeatureValue } from '../utils/feature'
import { formatUsdInput, formatUsdPrice, parseUsdInput } from '../utils/currency'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import TopAdviceBar from '../components/TopAdviceBar.vue'
import QuoteSortControls from '../components/QuoteSortControls.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'
import { buildUserAvatarLabel } from '../utils/userAvatarLabel'
import {
  buildVisibleUserPrompt,
  buildQuoteFollowupActions,
  buildQuoteFollowupSummary,
  buildQuoteShareText,
  collectStructuredUrlInputs,
  DEFAULT_QUOTE_LANG,
  detectQuoteLanguage,
  extractActionableQuoteRows,
  extractQuoteContinuityPayload,
  hasQuoteContinuity,
  hasQuoteMetadata,
  normalizeQuoteLanguage,
  normalizeQuoteUiPayload,
} from '../utils/quoteUi'
import {
  buildCerpPricingState,
  resolveCerpBundle,
  resolveCerpBundleDisplay,
  resolveCerpColor,
  resolveCerpField,
  resolveCerpProductName,
  resolveCerpBrand,
  resolveCerpFeature,
  resolveCerpStock,
  resolveCerpStockSourceLabel,
  resolveCerpStoreStock,
  resolveCerpSpecification,
  toNullableNumber,
} from '../utils/cerpFields'
import './quote-stage.css'

const router = useRouter()
const route = useRoute()
const { t, tm, te, locale } = useI18n()
const { isAuthenticated, authToken, userProfile } = useAuth()
const QUOTE_STORAGE_KEY = 'ys-quote-items'
const QUOTE_CONTEXT_KEY = 'ys-quote-context'
const QUOTE_PENDING_COMPOSE_KEY = 'ys-quote-pending-compose'
const QUOTE_CHAT_HANDOFF_KEY = 'ys-quote-chat-handoff'
const QUOTE_CHATUI_RETURN_KEY = 'ys-quote-chatui-return'
const QUOTE_SHOW_GENERATED_KEY = 'ys-quote-show-generated'
const QUOTE_TAB_IDS = ['report', 'gallery', 'slides', 'social']
const EDM_ITEMS_KEY = 'ys-edm-items'
const EDM_CONTEXT_KEY = 'ys-edm-context'
const EDM_PREVIEW_STATE_KEY = 'ys-edm-preview-state'
const UNKNOWN_COLOR = t('quote.defaults.color_unknown')

const quoteAdviceTitle = t('quote.advice.title')
const showGeneratedResults = ref(true)
const showBundleColumn = ref(true)

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'quote.nav'))

const iconImages = PRIMARY_NAV_ICON_IMAGES

const activeNavId = ref('')
const searchQuery = ref('')
const composerValue = ref('')
const isSending = ref(false)
const quoteProgressStageIndex = ref(0)
const quoteProgressLanguage = ref(DEFAULT_QUOTE_LANG)
let quoteProgressTimer = null
const QUOTE_PROGRESS_STAGE_KEYS = ['analyzing_prompt', 'retrieving_sources', 'reviewing_evidence', 'composing_answer']
const quoteProgressLocale = computed(() => (quoteProgressLanguage.value === 'en' ? 'en' : 'zh-TW'))
const currentQuoteProgressHint = computed(() => {
  const stageKey = QUOTE_PROGRESS_STAGE_KEYS[quoteProgressStageIndex.value] || QUOTE_PROGRESS_STAGE_KEYS[0]
  return t(`quote.loading.progress.${stageKey}`, {}, { locale: quoteProgressLocale.value })
})
const stopQuoteProgressHints = () => {
  if (quoteProgressTimer) clearInterval(quoteProgressTimer)
  quoteProgressTimer = null
  quoteProgressStageIndex.value = 0
}
const startQuoteProgressHints = (lang = DEFAULT_QUOTE_LANG) => {
  stopQuoteProgressHints()
  quoteProgressLanguage.value = normalizeQuoteLanguage(lang)
  quoteProgressTimer = setInterval(() => {
    quoteProgressStageIndex.value = Math.min(quoteProgressStageIndex.value + 1, QUOTE_PROGRESS_STAGE_KEYS.length - 1)
  }, 9000)
}
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
const quoteThreadRef = ref(null)
const quoteLayoutRef = ref(null)
const quoteLeftPanelRef = ref(null)
const quoteTablePanelRef = ref(null)
const quoteTableViewportRef = ref(null)
const quoteSummaryShellRef = ref(null)
const quoteFiltersPanelRef = ref(null)
const quoteFiltersStackRef = ref(null)
const quoteFilterActionsRef = ref(null)
const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const MOBILE_QUOTE_BREAKPOINT = 720
const initialViewport = typeof window !== 'undefined' ? window.innerWidth : 1440
const stageWidth = ref(initialViewport)
const isSidebarCollapsed = ref(initialViewport <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isTablet = computed(() => stageWidth.value <= 900)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isMobileQuote = computed(() => stageWidth.value <= MOBILE_QUOTE_BREAKPOINT)
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet,
    isSidebarCollapsed,
  })
const reportViewportHeight = ref(null)

let reportViewportResizeObserver = null
let reportViewportAnimationFrame = 0

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7a879c" stroke-width="2"/><path d="M12.5 12.5 16 16" stroke="#7a879c" stroke-width="2" stroke-linecap="round"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#263847" stroke-width="2" stroke-linecap="round"/></svg>',
}

const toggleSidebar = () => {
  if (!isCompactSidebar.value) return
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

const updateWidth = () => {
  stageWidth.value = typeof window !== 'undefined' ? window.innerWidth : stageWidth.value
  if (!isCompactSidebar.value) {
    isSidebarCollapsed.value = false
  }
  scheduleReportViewportUpdate()
}

const setActiveNav = (item) => {
  activeNavId.value = item.id
}

const currentUserNumericId = computed(() => Number(userProfile.value?.id ?? userProfile.value?.user_id))

const createCurrentUserAuthor = () => ({
  authorUserId: Number(userProfile.value?.id ?? userProfile.value?.user_id) || null,
  authorUsername: String(userProfile.value?.username || '').trim(),
  authorName: String(
    userProfile.value?.name || userProfile.value?.username || userProfile.value?.email || ''
  ).trim(),
})

const resolveQuoteAuthorLabel = (message = {}) => {
  if (message.role !== 'user') return t('quote.labels.ai')
  const authorUserId = Number(message.authorUserId)
  if (
    Number.isFinite(authorUserId) &&
    Number.isFinite(currentUserNumericId.value) &&
    authorUserId === currentUserNumericId.value
  ) {
    return t('quote.labels.you')
  }
  return buildUserAvatarLabel({
    authorName: message.authorName,
    authorUsername: message.authorUsername,
    fallback: t('quote.labels.you'),
  })
}

const handleNavClick = (item) => {
  if (item.id === 'permission') {
    handlePermissionNavClick()
    return
  }
  closePermissionMenu()
  setActiveNav(item)
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

const handleLogoClick = () => {
  router.push({ name: 'home' })
}

const chatMessages = ref([])
const chatLoading = ref(false)
const chatError = ref('')
const quoteContext = ref({})

const FALLBACK_CERP_SCHEMA = Object.freeze({
  columns: [
    { key: 'no', label: 'Code', source_keys: ['no', 'code', 'id', 'invn002'], width: 110, default_visible: true },
    {
      key: 'product',
      label: 'Product',
      source_keys: ['product', 'product_name', 'name', 'name_en', 'name_ch', 'invn077', 'invn005', 'title'],
      width: 220,
      default_visible: true,
    },
    { key: 'stock', label: 'Stock', source_keys: ['stock', 'stock_qty', 'total_stock', 'invn045'], width: 80, default_visible: true },
    { key: 'price', label: 'Price', source_keys: ['list_price', 'price', 'amount', 'invn013'], width: 110, default_visible: true },
    { key: 'vip', label: 'VIP Price', source_keys: ['quote_price', 'vip_price', 'display_quote_price', 'vip', 'invn015', 'amount', 'invn013'], width: 110, default_visible: true },
    { key: 'brand', label: 'Brand / Supplier', source_keys: ['brand', 'brand', 'supplier', 'invn006'], width: 130, default_visible: false },
    { key: 'specification', label: 'Spec / Model', source_keys: ['specification', 'spec', 'spec1', 'model', 'model_name', 'model_year', 'invn807', 'invn051', 'size'], width: 130, default_visible: true },
    { key: 'color', label: 'Color', source_keys: ['color', 'invn801'], width: 90, default_visible: false },
    { key: 'feature', label: 'Feature', source_keys: ['feature', 'invn804'], width: 100, default_visible: false },
    { key: 'bundle', label: 'Bundle', source_keys: ['bundle', 'promo', 'invn048'], width: 90, default_visible: false },
  ],
  default_visible_columns: ['no', 'product', 'specification', 'stock', 'price', 'vip'],
  filters: [
    { id: 'stock', field: 'stock', type: 'stock_status' },
    { id: 'price', field: 'price', type: 'range' },
    { id: 'specification', field: 'specification', type: 'option' },
  ],
  sort_fields: ['product', 'specification', 'stock', 'price'],
  price_tiers: [
    { id: 'price', label: 'Price', column: 'price' },
    { id: 'vip', label: 'VIP Price', column: 'vip' },
  ],
})
const cerpSchema = ref(FALLBACK_CERP_SCHEMA)
const normalizeSchemaColumns = (schema) => (Array.isArray(schema?.columns) ? schema.columns : FALLBACK_CERP_SCHEMA.columns)
const schemaColumns = computed(() => normalizeSchemaColumns(cerpSchema.value))
const schemaColumnMap = computed(() =>
  schemaColumns.value.reduce((map, column) => {
    if (column?.key) map[column.key] = column
    return map
  }, {})
)
const schemaFilterFields = computed(
  () => new Set((Array.isArray(cerpSchema.value?.filters) ? cerpSchema.value.filters : []).map((item) => item.field).filter(Boolean))
)
const getSchemaSourceKeys = (key, fallback = []) => schemaColumnMap.value[key]?.source_keys || fallback
const translateKnownKey = (key, fallback = '') => (te(key) ? t(key) : fallback)
const getSchemaColumnLabel = (key, fallback = '') =>
  translateKnownKey(`quote.table.columns.${key}`, fallback || schemaColumnMap.value[key]?.label || key)
const hasSchemaFilter = (field) => schemaFilterFields.value.has(field)

const LEGACY_PRICE_COLUMNS = [
  { key: 'restaurant', label: t('quote.price_types.restaurant'), width: 110 },
  { key: 'dealer', label: t('quote.price_types.dealer'), width: 110 },
  { key: 'promo', label: t('quote.price_types.promo'), width: 110 },
]
const tableColumns = computed(() => [
  ...schemaColumns.value.map((column) => ({
    key: column.key,
    label: getSchemaColumnLabel(column.key, column.label),
    width: column.width || 100,
  })),
  ...LEGACY_PRICE_COLUMNS,
])

const DEFAULT_VISIBLE_COLUMNS = [...FALLBACK_CERP_SCHEMA.default_visible_columns]
const visibleColumns = ref([...DEFAULT_VISIBLE_COLUMNS])

const tableRows = ref([])
const priceTable = ref([])
const selectedQuoteKeys = ref(new Set())

const resolveRowKey = (row, fallback = '') =>
  String(row?.no ?? row?.id ?? fallback)

const isRowSelectable = (row) => Number(row?.stock ?? 0) > 0

const isRowSelected = (row, index) =>
  isRowSelectable(row) && selectedQuoteKeys.value.has(resolveRowKey(row, `row-${index}`))

const galleryCards = computed(() =>
  sortedTableRows.value.map((row, index) => {
    const href = row.link || row.linkHref || row.link_href || row.url
    const label = row.linkLabel || row.link_label || href
    return {
      id: `gallery-${row.id || index}`,
      sku: row.no || row.id || `SKU-${index + 1}`,
      title:
        `${row.brand || ''} ${row.product || ''}`.trim() ||
        t('quote.gallery.default_title'),
      vipPrice: row.vip,
      comparePrice: row.price,
      color: row.color,
      spec: row.spec,
      specification: row.specification,
      feature: row.feature,
      brand: row.brand,
      terroirs: [],
      progress: 100,
      cases: row.stock ?? 0,
      description: row.description || '',
      link: { label: label || t('quote.gallery.default_link'), href: href || '#', external: false },
      photoUrl: row.photoUrl || row.photo_url || '',
      photoText: row.photoText || t('quote.gallery.photo_placeholder'),
    }
  })
)

const storeCards = computed(() =>
  sortedTableRows.value.map((row, index) => ({
    id: `store-${row.id || index}` ,
    sku: row.no || row.id || `SKU-${index + 1}` ,
    title:
      `${row.brand || ''} ${row.product || ''}`.trim() ||
      t('quote.gallery.default_title'),
    vipPrice: row.vip ,
    feature: row.feature ,
    color: row.color ,
    spec: row.spec ,
    specification: row.specification ,
    badges: row.bundle && row.bundle !== '-' ? [row.bundle] : [],
    photoUrl: row.photoUrl || row.photo_url || '',
    photoText: row.photoText || t('quote.gallery.photo_placeholder'),
  }))
)
const quoteMessages = tm('quote.sample_messages') || []
const hasColumnData = (field) =>
  tableRows.value.some((row) => {
    const value = row?.[field]
    return value !== undefined && value !== null && String(value).trim() !== ''
  })
const showColorFilter = computed(() => hasSchemaFilter('color') && hasColumnData('color'))
const showFeatureFilter = computed(() => hasSchemaFilter('feature') && hasColumnData('feature'))
const showSpecificationFilter = computed(() => hasSchemaFilter('specification') && hasColumnData('specification'))
const showBrandFilter = computed(() => hasSchemaFilter('brand') && hasColumnData('brand'))
const showSpecFilter = computed(() => hasSchemaFilter('spec') && hasColumnData('spec'))

const displayedSlideGroups = computed(() =>
  sortedTableRows.value.map((row, idx) => ({
    id: `slide-${row.id || idx}`,
    order: idx + 1,
    title:
      `${row.brand || ''} ${row.product || ''}`.trim() ||
      t('quote.defaults.unnamed'),
    price: row.price,
    vipPrice: row.vip,
    specification: row.specification || t('quote.defaults.non_specification'),
    spec: row.spec || '',
    sku: row.no || row.id || `SKU-${idx + 1}`,
    link: '#',
    notes: [
      t('quote.slide.notes.color', { value: row.color || '-' }),
      t('quote.slide.notes.feature', { value: row.feature || '-' }),
    ],
    brand: row.brand || '',
    village: row.product || '',
    parcel: row.bundle || '-',
  }))
)

const showCopySnackbar = ref(false)
const showSelectionSnackbar = ref(false)
const showShareDialog = ref(false)
let copySnackbarTimer = null
let selectionSnackbarTimer = null

const triggerCopySnackbar = () => {
  showCopySnackbar.value = true
  if (typeof window === 'undefined') return
  window.clearTimeout(copySnackbarTimer)
  copySnackbarTimer = window.setTimeout(() => {
    showCopySnackbar.value = false
  }, 2800)
}

const triggerSelectionSnackbar = () => {
  showSelectionSnackbar.value = true
  if (typeof window === 'undefined') return
  window.clearTimeout(selectionSnackbarTimer)
  selectionSnackbarTimer = window.setTimeout(() => {
    showSelectionSnackbar.value = false
  }, 2800)
}

const openShareDialog = () => {
  showShareDialog.value = true
}

const closeShareDialog = () => {
  showShareDialog.value = false
}

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  window.clearTimeout(copySnackbarTimer)
  window.clearTimeout(selectionSnackbarTimer)
})


const sortFields = computed(() => ({
  [t('quote.sort.fields.product')]: {
    key: 'product',
    directions: [t('quote.sort.directions.a_z'), t('quote.sort.directions.z_a')],
    defaultDirection: t('quote.sort.directions.a_z'),
  },
  [t('quote.sort.fields.spec')]: {
    key: 'spec',
    directions: [t('quote.sort.directions.a_z'), t('quote.sort.directions.z_a')],
    defaultDirection: t('quote.sort.directions.a_z'),
  },
  [t('quote.sort.fields.specification')]: {
    key: 'specification',
    directions: [t('quote.sort.directions.old_new'), t('quote.sort.directions.new_old')],
    defaultDirection: t('quote.sort.directions.old_new'),
  },
  [t('quote.sort.fields.color')]: {
    key: 'color',
    directions: [t('quote.sort.directions.a_z'), t('quote.sort.directions.z_a')],
    defaultDirection: t('quote.sort.directions.a_z'),
  },
  [t('quote.sort.fields.feature')]: {
    key: 'feature',
    directions: [t('quote.sort.directions.high_low'), t('quote.sort.directions.low_high')],
    defaultDirection: t('quote.sort.directions.high_low'),
  },
  [t('quote.sort.fields.stock')]: {
    key: 'stock',
    directions: [t('quote.sort.directions.many_few'), t('quote.sort.directions.few_many')],
    defaultDirection: t('quote.sort.directions.many_few'),
  },
  [t('quote.sort.fields.price')]: {
    key: 'price',
    directions: [t('quote.sort.directions.high_low'), t('quote.sort.directions.low_high')],
    defaultDirection: t('quote.sort.directions.high_low'),
  },
  [t('quote.sort.fields.bundle')]: {
    key: 'bundle',
    directions: [t('quote.sort.directions.many_few'), t('quote.sort.directions.few_many')],
    defaultDirection: t('quote.sort.directions.many_few'),
  },
}))
const sortFieldOptions = computed(() => Object.keys(sortFields.value))
const defaultSortRules = []
const sortRules = ref([...defaultSortRules])
watch(locale, () => {
  sortRules.value = [...defaultSortRules]
})

const sortGrouping = ref(false)
const showSortPanel = ref(false)
const columnOptions = computed(() =>
  tableColumns.value.filter((column) => !['restaurant', 'dealer', 'promo'].includes(column.key))
)

const priceTypeOptions = computed(() => {
  const tiers = Array.isArray(cerpSchema.value?.price_tiers) ? cerpSchema.value.price_tiers : []
  if (tiers.length) {
    return tiers
      .map((tier) => ({
        id: tier.id,
        label: translateKnownKey(`quote.price_types.${tier.id}`, tier.label || tier.id),
        column: tier.column || tier.id,
        optional: tier.optional === true,
      }))
      .filter((tier) => tier.id && tier.column)
  }
  return [
    { id: 'price', label: t('quote.table.columns.price'), column: 'price' },
    { id: 'vip', label: t('quote.price_types.vip'), column: 'vip' },
    { id: 'restaurant', label: t('quote.price_types.restaurant'), column: 'restaurant', optional: true },
    { id: 'dealer', label: t('quote.price_types.dealer'), column: 'dealer', optional: true },
    { id: 'promo', label: t('quote.price_types.promo'), column: 'promo', optional: true },
  ]
})
const defaultPriceTypeIds = computed(() => {
  const required = priceTypeOptions.value.filter((option) => option.optional !== true).map((option) => option.id)
  if (required.length) return required
  return priceTypeOptions.value.slice(0, 1).map((option) => option.id)
})
const selectedPriceTypes = ref(['price', 'vip'])
const showPriceTypeMenu = ref(false)

const selectedSpecifications = ref([])
const selectedBrands = ref([])
const selectedSpecs = ref([])
const showSpecificationMenu = ref(false)
const showBrandMenu = ref(false)
const showSpecMenu = ref(false)
const setSortGrouping = (value) => {
  sortGrouping.value = value
}
const setBundleColumn = (value) => {
  showBundleColumn.value = value
}

const priceBounds = { min: 0, max: 100000 }
const priceRange = ref({ min: 0, max: 100000 })
  const setPriceRange = (partial) => {
    priceRange.value = { ...priceRange.value, ...partial }
  }

  const colorOptions = [
    { id: 'red', label: t('quote.colors.red'), swatch: '#9b0b0b' },
    { id: 'white', label: t('quote.colors.white'), swatch: '#f4f4f0', border: '#c5c3bc' },
    { id: 'rose', label: t('quote.colors.rose'), swatch: '#f5d8d5' },
  ]
  const colorFilters = ref(['red', 'white', 'rose'])

  const getColorDotBorder = (colorId) =>
    colorFilters.value.includes(colorId) ? '#9b0b0b' : '#c5c3bc'

  const featureSteps = (tm('quote.feature.steps') || []).map((step) => String(step))
  const featureRange = ref([0, featureSteps.length - 1])
  const featureStepBounds = [
    { min: 0, max: 84 },
    { min: 85, max: 89 },
    { min: 90, max: 95 },
    { min: 96, max: 100 },
  ]

  const favoriteSpecifications = ref(['2021', '2022', '2023'])
  const additionalSpecification = 5
const inventoryOptions = [
  { id: 'all', label: t('quote.inventory.all') },
  { id: 'store_stock', label: t('quote.inventory.boutique') },
]
const selectedInventory = ref('all')

const filterTabs = computed(() => [
  { id: 'report', label: t('quote.tabs.report'), icon: tabShape0, activeIcon: tabShape0Active },
  { id: 'gallery', label: t('quote.tabs.gallery'), icon: tabShape1, activeIcon: tabShape1Active },
  { id: 'slides', label: t('quote.tabs.slides'), icon: tabShape2, activeIcon: tabShape2Active },
  { id: 'social', label: t('quote.tabs.social'), icon: tabShape3, activeIcon: tabShape3Active },
])
const activeFilterTab = ref('report')
const isSlidesTab = computed(() => activeFilterTab.value === 'slides')
const isConsumingPendingCompose = ref(false)

const activeRowMenu = ref(null)
const rowPendingDelete = ref(null)
const showDeleteModal = ref(false)

const tableColumnsDisplayed = computed(() =>
  tableColumns.value.filter((col) => visibleColumns.value.includes(col.key))
)

const REPORT_GRID_COLUMN_WIDTHS = computed(() =>
  tableColumns.value.reduce((widths, column) => {
    widths[column.key] = column.width || 100
    return widths
  }, {})
)

const REPORT_SELECT_COLUMN_WIDTH = 44
const REPORT_ACTION_COLUMN_WIDTH = 44

const reportGridWidth = computed(
  () =>
    REPORT_SELECT_COLUMN_WIDTH +
    REPORT_ACTION_COLUMN_WIDTH +
    tableColumnsDisplayed.value.reduce(
      (total, column) => total + (REPORT_GRID_COLUMN_WIDTHS.value[column.key] || 100),
      0
    )
)

const reportGridTemplate = computed(() =>
  [
    `${REPORT_SELECT_COLUMN_WIDTH}px`,
    ...tableColumnsDisplayed.value.map(
      (column) => `${REPORT_GRID_COLUMN_WIDTHS.value[column.key] || 100}px`
    ),
    `${REPORT_ACTION_COLUMN_WIDTH}px`,
  ].join(' ')
)

const reportGridStyle = computed(() => ({
  gridTemplateColumns: reportGridTemplate.value,
  width: `${reportGridWidth.value}px`,
}))

const colorIconMap = {
  red: glassRed,
  white: glassWhite,
  rose: glassRose,
}


const featureFilterBounds = computed(() => {
  const lowIndex = featureRange.value[0]
  const highIndex = featureRange.value[1]
  const minBound = featureStepBounds[lowIndex]?.min ?? 0
  const maxBound = featureStepBounds[highIndex]?.max ?? 100
  return { min: minBound, max: maxBound }
})

const filteredTableRows = computed(() => {
  if (!tableRows.value.length) {
    return []
  }
  const activeColors = new Set(colorFilters.value)
  const minPrice = priceRange.value.min
  const maxPrice = priceRange.value.max
  const { min: minFeature, max: maxFeature } = featureFilterBounds.value
  const activeSpecifications = selectedSpecifications.value
  const activeBrands = selectedBrands.value
  const activeSpecs = selectedSpecs.value
  const inventoryFilter = selectedInventory.value
  return tableRows.value.filter((row) => {
    const rowColor = row.color ? row.color.toLowerCase() : ''
    const withinColor =
      !showColorFilter.value || !rowColor || activeColors.has(rowColor) || rowColor === UNKNOWN_COLOR.toLowerCase()
    const withinPrice = row.price >= minPrice && row.price <= maxPrice
    const featureValue = extractFeatureValue(row.feature)
    const withinFeature = !showFeatureFilter.value || (featureValue >= minFeature && featureValue <= maxFeature)
    const withinSpecification =
      !showSpecificationFilter.value || !activeSpecifications.length || activeSpecifications.includes(String(row.specification || '').trim())
    const withinBrand =
      !showBrandFilter.value ||
      !activeBrands.length ||
      activeBrands.includes(String(row.brand || '').trim())
    const withinSpec =
      !showSpecFilter.value || !activeSpecs.length || activeSpecs.includes(String(row.spec || '').trim())
    const withinInventory =
      inventoryFilter !== 'store_stock' || Number(row.store_stock || 0) > 0
    return (
      withinColor &&
      withinPrice &&
      withinFeature &&
      withinSpecification &&
      withinBrand &&
      withinSpec &&
      withinInventory
    )
  })
})

const sortedTableRows = computed(() => applySorting(filteredTableRows.value))
const selectedQuoteItems = computed(() =>
  sortedTableRows.value.filter((row, index) =>
    isRowSelectable(row) && selectedQuoteKeys.value.has(resolveRowKey(row, `row-${index}`))
  )
)
const selectedQuoteCount = computed(() => selectedQuoteItems.value.length)
const INITIAL_RENDER_COUNT = 30
const ROW_BATCH_SIZE = 20
const LOAD_MORE_OFFSET = 240
const APPEND_ROWS_DELAY_MS = 120
const renderedRowCount = ref(INITIAL_RENDER_COUNT)
const isAppendingRows = ref(false)
let appendRowsTimer = null

const visibleReportRows = computed(() =>
  sortedTableRows.value.slice(0, renderedRowCount.value)
)

const hasMoreReportRows = computed(
  () => visibleReportRows.value.length < sortedTableRows.value.length
)

const visibleSelectableRowKeys = computed(() =>
  visibleReportRows.value.reduce((keys, row, index) => {
    if (!isRowSelectable(row)) return keys
    const key = resolveRowKey(row, `row-${index}`)
    if (key) {
      keys.push(key)
    }
    return keys
  }, [])
)

const hasVisibleSelectableRows = computed(() => visibleSelectableRowKeys.value.length > 0)

const allVisibleSelected = computed(() => {
  if (!visibleSelectableRowKeys.value.length) return false
  return visibleSelectableRowKeys.value.every((key) => selectedQuoteKeys.value.has(key))
})

const toggleRowSelection = (row, index) => {
  if (!isRowSelectable(row)) return
  const key = resolveRowKey(row, `row-${index}`)
  if (!key) return
  const next = new Set(selectedQuoteKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  selectedQuoteKeys.value = next
}

const toggleSelectAll = () => {
  if (!hasVisibleSelectableRows.value) return
  const next = new Set(selectedQuoteKeys.value)
  const keys = visibleSelectableRowKeys.value
  const shouldClear = keys.every((key) => next.has(key))
  keys.forEach((key) => {
    if (!key) return
    if (shouldClear) {
      next.delete(key)
    } else {
      next.add(key)
    }
  })
  selectedQuoteKeys.value = next
}

const clearSelection = () => {
  selectedQuoteKeys.value = new Set()
}

const resetFilters = () => {
  selectedPriceTypes.value = [...defaultPriceTypeIds.value]
  priceRange.value = { ...priceBounds }
  colorFilters.value = colorOptions.map((option) => option.id)
  featureRange.value = [0, featureSteps.length - 1]
  selectedSpecifications.value = []
  selectedBrands.value = []
  selectedSpecs.value = []
  selectedInventory.value = 'all'
}

const createEdmFromSelection = () => {
  if (!selectedQuoteItems.value.length) {
    triggerSelectionSnackbar()
    return
  }
  try {
    sessionStorage.removeItem(EDM_PREVIEW_STATE_KEY)
    sessionStorage.setItem(EDM_ITEMS_KEY, JSON.stringify(selectedQuoteItems.value))
    sessionStorage.setItem(
      EDM_CONTEXT_KEY,
      JSON.stringify({
        conversation_id: quoteContext.value?.conversation_id || null,
        project: quoteContext.value?.project || null,
        table_columns: snapshotEdmTableColumns(tableColumnsDisplayed.value),
        saved_at: new Date().toISOString(),
      })
    )
  } catch (error) {
    console.warn('Unable to persist EDM selection', error)
  }
  router.push({ name: 'edm' })
}

const reportViewportStyle = computed(() => {
  if (reportViewportHeight.value === null) return {}
  return {
    height: `${reportViewportHeight.value}px`,
    maxHeight: `${reportViewportHeight.value}px`,
  }
})

const clearReportViewportAnimationFrame = () => {
  if (typeof window === 'undefined' || !reportViewportAnimationFrame) return
  window.cancelAnimationFrame(reportViewportAnimationFrame)
  reportViewportAnimationFrame = 0
}

const disconnectReportViewportObserver = () => {
  if (!reportViewportResizeObserver) return
  reportViewportResizeObserver.disconnect()
  reportViewportResizeObserver = null
}

const updateReportViewportHeight = () => {
  const viewportEl = quoteTableViewportRef.value
  const actionsEl = quoteFilterActionsRef.value
  if (!viewportEl || !actionsEl) {
    reportViewportHeight.value = null
    return
  }

  const viewportTop = viewportEl.getBoundingClientRect().top
  const targetBottom = actionsEl.getBoundingClientRect().bottom
  const nextHeight = Math.max(0, Math.round(targetBottom - viewportTop))
  reportViewportHeight.value = nextHeight > 0 ? nextHeight : null
}

const scheduleReportViewportUpdate = () => {
  if (typeof window === 'undefined') return
  if (reportViewportAnimationFrame) return

  reportViewportAnimationFrame = window.requestAnimationFrame(() => {
    reportViewportAnimationFrame = 0
    updateReportViewportHeight()
  })
}

const connectReportViewportObserver = () => {
  disconnectReportViewportObserver()
  if (typeof ResizeObserver === 'undefined') {
    return
  }

  reportViewportResizeObserver = new ResizeObserver(() => {
    scheduleReportViewportUpdate()
  })

  ;[
    quoteSummaryShellRef.value,
    quoteFiltersStackRef.value,
  ].forEach((element) => {
    if (element) {
      reportViewportResizeObserver.observe(element)
    }
  })
}

const resetReportWindow = () => {
  renderedRowCount.value = Math.min(INITIAL_RENDER_COUNT, sortedTableRows.value.length)
  isAppendingRows.value = false
  nextTick(() => {
    if (quoteTableViewportRef.value && activeFilterTab.value === 'report') {
      quoteTableViewportRef.value.scrollTop = 0
    }
  })
}

const appendMoreRows = () => {
  if (isAppendingRows.value || !hasMoreReportRows.value) return
  isAppendingRows.value = true
  if (appendRowsTimer) {
    clearTimeout(appendRowsTimer)
  }
  appendRowsTimer = setTimeout(() => {
    renderedRowCount.value = Math.min(
      renderedRowCount.value + ROW_BATCH_SIZE,
      sortedTableRows.value.length
    )
    isAppendingRows.value = false
    appendRowsTimer = null
    nextTick(() => {
      handleQuoteTableScroll()
    })
  }, APPEND_ROWS_DELAY_MS)
}

const handleQuoteTableScroll = () => {
  const el = quoteTableViewportRef.value
  if (!el || activeFilterTab.value !== 'report') return
  const remaining = el.scrollHeight - el.scrollTop - el.clientHeight
  if (remaining <= LOAD_MORE_OFFSET) {
    appendMoreRows()
  }
}

watch(sortedTableRows, () => {
  resetReportWindow()
})

watch(
  tableRows,
  (rows) => {
    const selectableKeys = new Set(
      rows
        .filter((row) => isRowSelectable(row))
        .map((row, index) => resolveRowKey(row, `row-${index}`))
        .filter(Boolean)
    )
    const next = new Set(
      [...selectedQuoteKeys.value].filter((key) => selectableKeys.has(key))
    )
    if (next.size !== selectedQuoteKeys.value.size) {
      selectedQuoteKeys.value = next
    }
  },
  { deep: true }
)

watch(
  () => activeFilterTab.value,
  (value) => {
    if (value === 'report') {
      resetReportWindow()
    }
    nextTick(() => {
      connectReportViewportObserver()
      scheduleReportViewportUpdate()
    })
  }
)

watch(
  () => isMobileQuote.value,
  (value) => {
    nextTick(() => {
      connectReportViewportObserver()
      scheduleReportViewportUpdate()
      if (value) {
        resetMobileQuoteTrack()
      }
    })
  }
)

const priceFillStyle = computed(() => {
  const minPercent =
    ((priceRange.value.min - priceBounds.min) / (priceBounds.max - priceBounds.min)) * 100
  const maxPercent =
    ((priceRange.value.max - priceBounds.min) / (priceBounds.max - priceBounds.min)) * 100
  return {
    left: `${minPercent}%`,
    width: `${maxPercent - minPercent}%`,
  }
})

const featureFillStyle = computed(() => {
  const total = featureSteps.length - 1
  return {
    left: `${(featureRange.value[0] / total) * 100}%`,
    width: `${((featureRange.value[1] - featureRange.value[0]) / total) * 100}%`,
  }
})

const formatCurrency = (value) => formatUsdPrice(value, value)

const getNumeric = (value) => {
  if (typeof value === 'number') return value
  if (typeof value === 'string') {
    const cleaned = value.replace(/,/g, '').trim()
    const parsed = Number(cleaned)
    return Number.isFinite(parsed) ? parsed : 0
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
const brandDescriptionCache = new Map()

const buildBrandDescription = ({ brand, product, specification, color, feature, stock, price }) => {
  const baseBrand = brand || t('quote.defaults.brand')
  const baseProduct = product || t('quote.defaults.product')
  const baseSpecification = specification || t('quote.defaults.non_specification')
  const baseColor = color || t('quote.defaults.color')
  const baseFeature = feature || t('quote.defaults.feature')
  const stockText =
    typeof stock === 'number' && stock >= 0
      ? t('quote.defaults.stock_bottles', { count: stock })
      : t('quote.defaults.stock_pending')
  const priceText =
    typeof price === 'number' && price > 0
      ? t('quote.defaults.price_estimate', { price })
      : t('quote.defaults.price_pending')
  const sentences = [
    t('quote.brand_description.line1', {
      brand: baseBrand,
      specification: baseSpecification,
      product: baseProduct,
      color: baseColor,
      feature: baseFeature,
    }),
    t('quote.brand_description.line2', { stock: stockText, price: priceText }),
    t('quote.brand_description.line3'),
    t('quote.brand_description.line4'),
  ]
  let text = sentences.join(' ')
  const filler = t('quote.brand_description.filler')
  while (text.length < 250) {
    text += filler
  }
  return text.slice(0, 250)
}

const getBrandDescription = (fields) => {
  const brand = fields.brand || t('quote.defaults.brand')
  if (brandDescriptionCache.has(brand)) return brandDescriptionCache.get(brand)
  const description = buildBrandDescription(fields)
  brandDescriptionCache.set(brand, description)
  return description
}


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
        ...(context || {}),
        surface_origin: context?.surface_origin || 'quote-chat',
        quote_continuity: hasQuoteContinuity(context?.quote_continuity)
          ? extractQuoteContinuityPayload(context?.quote_continuity, {
              conversationId: context?.conversation_id || null,
              project: context?.project || null,
              lang:
                context?.lang ||
                normalizeQuoteLanguage(quoteContext.value?.lang, DEFAULT_QUOTE_LANG),
              surfaceOrigin: context?.surface_origin || 'quote-chat',
            })
          : null,
        lang: normalizeQuoteLanguage(
          context?.lang,
          normalizeQuoteLanguage(quoteContext.value?.lang, DEFAULT_QUOTE_LANG)
        ),
      })
    )
  } catch (error) {
    console.warn('Unable to persist quote context', error)
  }
}

const loadQuoteContext = () => {
  try {
    const raw = localStorage.getItem(QUOTE_CONTEXT_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    return {
      ...parsed,
      quote_continuity: hasQuoteContinuity(parsed?.quote_continuity)
        ? extractQuoteContinuityPayload(parsed.quote_continuity, {
            conversationId: parsed?.conversation_id || null,
            project: parsed?.project || null,
            lang: parsed?.lang || DEFAULT_QUOTE_LANG,
            surfaceOrigin: parsed?.surface_origin || 'quote-chat',
          })
        : null,
      lang: normalizeQuoteLanguage(parsed.lang, DEFAULT_QUOTE_LANG),
    }
  } catch (error) {
    console.warn('Unable to load quote context', error)
    return {}
  }
}

const loadQuoteChatHandoff = () => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(QUOTE_CHAT_HANDOFF_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return {
      conversation_id: parsed.conversation_id || null,
      project: parsed.project && typeof parsed.project === 'object' ? parsed.project : null,
      thread: Array.isArray(parsed.thread) ? parsed.thread : [],
      pending_message: String(parsed.pending_message || '').trim(),
      raw_message: String(parsed.raw_message || parsed.pending_message || '').trim(),
      lang: normalizeQuoteLanguage(parsed.lang, DEFAULT_QUOTE_LANG),
      surface_origin: parsed.surface_origin || 'chat-ui',
      attachment: parsed.attachment && typeof parsed.attachment === 'object' ? parsed.attachment : null,
      url_inputs: Array.isArray(parsed.url_inputs) ? parsed.url_inputs.filter(Boolean) : [],
      followup_action: parsed.followup_action || null,
      followup_action_source: parsed.followup_action_source || null,
      quote_continuity: hasQuoteContinuity(parsed?.quote_continuity)
        ? extractQuoteContinuityPayload(parsed.quote_continuity, {
            conversationId: parsed?.conversation_id || null,
            project: parsed?.project || null,
            lang: parsed?.lang || DEFAULT_QUOTE_LANG,
            surfaceOrigin: parsed?.surface_origin || 'chat-ui',
          })
        : null,
      tab: normalizeQuoteTab(parsed.tab),
      created_at: parsed.created_at || null,
    }
  } catch (error) {
    console.warn('Unable to load quote chat handoff payload', error)
    return null
  }
}

const clearQuoteChatHandoff = () => {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(QUOTE_CHAT_HANDOFF_KEY)
}

const loadQuoteDestinationPreference = () => {
  if (typeof window === 'undefined') return true
  try {
    const raw = window.sessionStorage.getItem(QUOTE_SHOW_GENERATED_KEY)
    if (raw === null) return true
    return raw !== '0'
  } catch (error) {
    console.warn('Unable to load quote destination preference', error)
    return true
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

const resetQuoteDestinationPreference = () => {
  showGeneratedResults.value = true
  persistQuoteDestinationPreference(true)
}

const normalizeQuoteTab = (value) => {
  const tab = String(value || '').trim().toLowerCase()
  return QUOTE_TAB_IDS.includes(tab) ? tab : 'report'
}

const persistQuoteChatUiReturnPayload = (payload) => {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(
      QUOTE_CHATUI_RETURN_KEY,
      JSON.stringify({
        conversation_id: payload?.conversation_id || null,
        project: payload?.project || null,
        user_prompt: payload?.user_prompt || '',
        lang: normalizeQuoteLanguage(payload?.lang, quoteContext.value?.lang || DEFAULT_QUOTE_LANG),
        surface_origin: payload?.surface_origin || 'quote-chat',
        url_inputs: Array.isArray(payload?.url_inputs) ? payload.url_inputs.filter(Boolean) : [],
        quote_continuity: hasQuoteContinuity(payload?.quote_continuity)
          ? extractQuoteContinuityPayload(payload.quote_continuity, {
              conversationId: payload?.conversation_id || null,
              project: payload?.project || null,
              lang: payload?.lang || quoteContext.value?.lang || DEFAULT_QUOTE_LANG,
              surfaceOrigin: payload?.surface_origin || 'quote-chat',
            })
          : null,
        created_at: payload?.created_at || new Date().toISOString(),
        assistant_message: payload?.assistant_message || null,
      })
    )
  } catch (error) {
    console.warn('Unable to persist quote ChatUI return payload', error)
  }
}

const syncFilterTabFromRoute = () => {
  activeFilterTab.value = normalizeQuoteTab(route.query.tab)
}

const scrollToQuotePanel = (panel, behavior = 'smooth') => {
  if (!isMobileQuote.value) return
  const target =
    panel === 'chat'
      ? quoteLeftPanelRef.value
      : panel === 'filters'
        ? quoteFiltersPanelRef.value
        : quoteTablePanelRef.value
  target?.scrollIntoView({ behavior, block: 'nearest', inline: 'start' })
}

const resetMobileQuoteTrack = () => {
  if (!isMobileQuote.value) return
  nextTick(() => {
    scrollToQuotePanel('chat', 'auto')
  })
}

const setActiveFilterTab = (value) => {
  const nextTab = normalizeQuoteTab(value)
  activeFilterTab.value = nextTab
  const nextQuery = { ...route.query }
  if (nextTab === 'report') {
    delete nextQuery.tab
  } else {
    nextQuery.tab = nextTab
  }
  router.replace({ query: nextQuery })
  if (isMobileQuote.value) {
    nextTick(() => {
      scrollToQuotePanel('report')
    })
  }
}

const loadPendingQuoteCompose = () => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(QUOTE_PENDING_COMPOSE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const message = String(parsed.message || '').trim()
    if (!message) return null
    return {
      message,
      display_message: String(parsed.display_message || message).trim(),
      tab: normalizeQuoteTab(parsed.tab),
      project: parsed.project && typeof parsed.project === 'object' ? parsed.project : null,
      conversation_id: parsed.conversation_id || null,
      lang: normalizeQuoteLanguage(parsed.lang, DEFAULT_QUOTE_LANG),
      surface_origin: parsed.surface_origin || 'chat-ui',
      attachment: parsed.attachment && typeof parsed.attachment === 'object' ? parsed.attachment : null,
      url_inputs: Array.isArray(parsed.url_inputs) ? parsed.url_inputs.filter(Boolean) : [],
      followup_action: parsed.followup_action || null,
      followup_action_source: parsed.followup_action_source || null,
      quote_continuity: hasQuoteContinuity(parsed?.quote_continuity)
        ? extractQuoteContinuityPayload(parsed.quote_continuity, {
            conversationId: parsed?.conversation_id || null,
            project: parsed?.project || null,
            lang: parsed?.lang || DEFAULT_QUOTE_LANG,
            surfaceOrigin: parsed?.surface_origin || 'chat-ui',
          })
        : null,
    }
  } catch (error) {
    console.warn('Unable to load pending quote compose payload', error)
    return null
  }
}

const clearPendingQuoteCompose = () => {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(QUOTE_PENDING_COMPOSE_KEY)
}

const consumePendingQuoteCompose = async () => {
  if (isConsumingPendingCompose.value) return
  const pending = loadPendingQuoteCompose()
  if (!pending) return
  isConsumingPendingCompose.value = true
  try {
    activeFilterTab.value = pending.tab
    composerValue.value = pending.message
    quoteContext.value = {
      ...quoteContext.value,
      ...(pending.project ? { project: pending.project } : {}),
      ...(pending.conversation_id ? { conversation_id: pending.conversation_id } : {}),
      ...(pending.quote_continuity ? { quote_continuity: pending.quote_continuity } : {}),
      surface_origin: pending.surface_origin || quoteContext.value?.surface_origin || 'chat-ui',
      lang: normalizeQuoteLanguage(pending.lang, quoteContext.value?.lang || DEFAULT_QUOTE_LANG),
    }
    await nextTick()
    await submitQuoteChat({
      message: pending.message,
      displayMessage: pending.display_message,
      lang: pending.lang,
      attachment: pending.attachment,
      urlInputs: pending.url_inputs,
      followupAction: pending.followup_action,
      followupActionSource: pending.followup_action_source,
    })
  } finally {
    clearPendingQuoteCompose()
    isConsumingPendingCompose.value = false
  }
}

const mapCERPToQuoteRow = (cerp) => {
  const code = cerp.no || cerp.code || cerp.id || cerp.invn002
  const pricing = buildCerpPricingState(cerp)
  const brand = resolveCerpField(cerp, getSchemaSourceKeys('brand', ['brand', 'brand', 'supplier', 'invn006']), '') || resolveCerpBrand(cerp, '')
  const product = resolveCerpField(
    cerp,
    getSchemaSourceKeys('product', ['product', 'product_name', 'name', 'name_en', 'name_ch', 'invn077', 'invn005', 'title']),
    ''
  ) || resolveCerpProductName(cerp, t('quote.defaults.unnamed'))
  const specification = resolveCerpField(
    cerp,
    getSchemaSourceKeys('specification', ['specification', 'spec', 'spec1', 'model', 'model_name', 'model_year', 'invn807', 'invn051', 'size']),
    ''
  ) || resolveCerpSpecification(cerp, t('quote.defaults.non_specification'))
  const spec = specification
  const color = resolveCerpField(cerp, getSchemaSourceKeys('color', ['color', 'invn801']), '') || resolveCerpColor(cerp, UNKNOWN_COLOR)
  const feature = resolveCerpField(cerp, getSchemaSourceKeys('feature', ['feature', 'invn804']), '') || resolveCerpFeature(cerp, t('quote.defaults.feature'))
  const stock = resolveCerpStock(cerp)
  const storeStock = resolveCerpStoreStock(cerp)
  const stockSourceLabel = resolveCerpStockSourceLabel(
    cerp,
    storeStock > 0 ? t('quote.inventory.boutique') : t('quote.inventory.overall'),
    {
      store_stock: t('quote.inventory.boutique'),
      overall_stock: t('quote.inventory.overall'),
    }
  )
  const price = getNumeric(pricing.list_price)
  const description = getBrandDescription({
    brand,
    product,
    specification,
    color,
    feature,
    stock,
    price,
  })
  const bundle = resolveCerpBundle(cerp, '')
  const bundleDisplay = resolveCerpBundleDisplay(bundle)
  return {
    id: code || cerp.id,
    no: code,
    spec,
    specification,
    brand,
    product,
    color,
    feature,
    stock,
    store_stock: storeStock,
    stock_source: stockSourceLabel,
    price,
    vip: getNumeric(pricing.vip_price),
    restaurant: getNumeric(pricing.fb_price),
    dealer: getNumeric(pricing.wholesale_price),
    promo: cerp.promo || cerp.bundle || '',
    list_price: pricing.list_price,
    vip_price: pricing.vip_price,
    fb_price: pricing.fb_price,
    wholesale_price: pricing.wholesale_price,
    selected_quote_tier: pricing.selected_quote_tier,
    display_quote_price: pricing.display_quote_price,
    bundle: bundleDisplay,
    photoUrl: cerp.photo_url || cerp.photoUrl || '',
    photoText: cerp.photo_placeholder || t('quote.gallery.photo_placeholder'),
    description,

  }
}
const mapCERPToPriceRow = (cerp) => {
  const code = cerp.no || cerp.code || cerp.id || cerp.invn002
  const pricing = buildCerpPricingState(cerp)
  return {
    no: code,
    spec: resolveCerpSpecification(cerp, t('quote.defaults.non_specification')),
    specification: resolveCerpSpecification(cerp, t('quote.defaults.non_specification')),
    brand: resolveCerpBrand(cerp, ''),
    product: resolveCerpProductName(cerp, t('quote.defaults.unnamed')),
    color: resolveCerpColor(cerp, UNKNOWN_COLOR),
    feature: resolveCerpFeature(cerp, t('quote.defaults.feature')),
    list: formatCurrency(getNumeric(pricing.list_price)),
    quote: formatCurrency(getNumeric(pricing.vip_price)),
    restaurant: formatCurrency(getNumeric(pricing.fb_price)),
    dealer: formatCurrency(getNumeric(pricing.wholesale_price)),
    promo: cerp.promo || cerp.bundle || '-',
    bundle: resolveCerpBundleDisplay(cerp),
    quantity: 0,
  }
}

const applyCERPMappings = (items) => {
  const quoteRows = items.map(mapCERPToQuoteRow)
  tableRows.value = quoteRows
  priceTable.value = items.map(mapCERPToPriceRow)
  return quoteRows
}

const filterPriceRange = (cerp) => {
  const price = getNumeric(toNullableNumber(cerp.list_price ?? cerp.invn013 ?? cerp.price))
  return price >= 2000 && price <= 6000
}

const loadQuoteItemsFromStorage = () => {
  try {
    const raw = localStorage.getItem(QUOTE_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch (error) {
    console.warn('Unable to load quote items', error)
    return []
  }
}

const normalizeMetadata = (raw) => {
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      return typeof parsed === 'object' && parsed ? parsed : {}
    } catch (error) {
      console.warn('Unable to parse metadata', error)
    }
  }
  return {}
}

const normalizeMessageQuoteUi = (metadata = {}, createdAt = '') =>
  normalizeQuoteUiPayload(metadata, {
    createdAt,
    language: normalizeQuoteLanguage(
      metadata?.language || metadata?.lang,
      quoteContext.value?.lang || DEFAULT_QUOTE_LANG
    ),
  })

const getQuoteUiForMessage = (message) =>
  message?.quoteUi || normalizeMessageQuoteUi(message?.metadata || {}, message?.timestamp)

const messageHasQuoteUi = (message) => Boolean(getQuoteUiForMessage(message))

const resolveQuoteChatLanguage = (value = '', override = null) =>
  normalizeQuoteLanguage(override || quoteContext.value?.lang, detectQuoteLanguage(value))

const persistQuoteLanguage = (value) => {
  const lang = normalizeQuoteLanguage(value, DEFAULT_QUOTE_LANG)
  quoteContext.value = {
    ...quoteContext.value,
    lang,
  }
  return lang
}

const mapConversationMessage = (record, idx = 0) => {
  const metadata = normalizeMetadata(record.metadata)
  const timestamp = record.created_at || record.createdAt || record.timestamp || ''
  return {
    id: record.id || record.message_id || `msg-${idx}`,
    role: record.role || 'assistant',
    text: record.content || record.text || '',
    timestamp,
    metadata,
    authorUserId: record.author_user_id ?? metadata.author_user_id ?? null,
    authorUsername: record.author_username ?? metadata.author_username ?? '',
    authorName: record.author_name ?? metadata.author_name ?? '',
    quoteUi: normalizeMessageQuoteUi(metadata, timestamp),
  }
}

const buildVisiblePromptForThread = (message = '', urlInputs = []) =>
  buildVisibleUserPrompt(message, urlInputs)

const getStructuredUrlsFromMetadata = (metadata = {}) => collectStructuredUrlInputs(metadata)

const hydrateStructuredUrlsIntoThread = (messages = []) => {
  if (!Array.isArray(messages) || !messages.length) return []
  const hydrated = messages.map((message) => ({ ...message }))
  for (let index = 0; index < hydrated.length; index += 1) {
    const current = hydrated[index]
    if (current?.role !== 'user') continue
    const currentText = String(current?.text || '').trim()
    const nextAssistant = hydrated
      .slice(index + 1)
      .find((entry) => entry?.role === 'assistant' && getStructuredUrlsFromMetadata(entry?.metadata || {}).length)
    if (!nextAssistant) continue
    const urlInputs = getStructuredUrlsFromMetadata(nextAssistant.metadata || {})
    const visibleText = buildVisiblePromptForThread(currentText, urlInputs)
    if (visibleText && visibleText !== currentText) {
      current.text = visibleText
    }
  }
  return hydrated
}

const getActionableQuoteRows = (metadata = {}) => extractActionableQuoteRows(metadata)

const extractQuoteItemsFromMessages = (messages = []) => {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const meta = messages[i]?.metadata || {}
    if (meta && Array.isArray(meta.quote_items) && meta.quote_items.length) {
      return meta.quote_items
    }
  }
  return null
}

const findLatestQuoteAssistantMessage = (messages = []) => {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i]
    if (message?.role !== 'assistant') continue
    if (message?.quoteUi || hasQuoteMetadata(message?.metadata || {})) {
      return message
    }
  }
  return null
}

const latestQuoteAssistantMessage = computed(() =>
  findLatestQuoteAssistantMessage(chatMessages.value)
)

const buildQuoteContinuityFromMessage = (message, options = {}) =>
  extractQuoteContinuityPayload(message?.metadata || {}, {
    conversationId: options.conversationId || quoteContext.value?.conversation_id || null,
    project: options.project || quoteContext.value?.project || null,
    lang: options.lang || quoteContext.value?.lang || DEFAULT_QUOTE_LANG,
    surfaceOrigin: options.surfaceOrigin || 'quote-chat',
    messageId: message?.id || null,
    createdAt: message?.timestamp || null,
  })

const getQuoteFollowupSummaryForMessage = (message) =>
  buildQuoteFollowupSummary(
    buildQuoteContinuityFromMessage(message, {
      conversationId: quoteContext.value?.conversation_id || null,
      project: quoteContext.value?.project || null,
      lang: quoteContext.value?.lang || DEFAULT_QUOTE_LANG,
      surfaceOrigin: 'quote-chat',
    }),
    quoteContext.value?.lang || DEFAULT_QUOTE_LANG
  )

const getQuoteFollowupActionsForMessage = (message) =>
  buildQuoteFollowupActions(
    buildQuoteContinuityFromMessage(message, {
      conversationId: quoteContext.value?.conversation_id || null,
      project: quoteContext.value?.project || null,
      lang: quoteContext.value?.lang || DEFAULT_QUOTE_LANG,
      surfaceOrigin: 'quote-chat',
    }),
    quoteContext.value?.lang || DEFAULT_QUOTE_LANG
  )

const fetchQuoteConversation = async (context, options = {}) => {
  if (!isAuthenticated.value || !authToken.value) return
  const conversationId = context?.conversation_id
  if (!conversationId) return
  const shouldHydrateQuoteItems = options.hydrateQuoteItems !== false
  chatLoading.value = true
  chatError.value = ''
  try {
    const response = await fetchConversationMessages(conversationId, { limit: 200 })
    const records = response?.messages || []
    const normalized = hydrateStructuredUrlsIntoThread(
      records.map((record, idx) => mapConversationMessage(record, idx))
    )
    chatMessages.value = normalized
    const latestAssistant = [...normalized].reverse().find((message) => message?.role === 'assistant')
    if (latestAssistant?.metadata) {
      persistQuoteLanguage(latestAssistant.metadata.language || latestAssistant.metadata.lang)
      const quoteContinuity =
        buildQuoteContinuityFromMessage(latestAssistant, {
          conversationId,
          project: context?.project || quoteContext.value?.project || null,
          lang: latestAssistant.metadata.language || latestAssistant.metadata.lang || context?.lang,
          surfaceOrigin: 'quote-chat',
        }) || null
      if (quoteContinuity) {
        quoteContext.value = {
          ...quoteContext.value,
          ...context,
          quote_continuity: quoteContinuity,
          surface_origin: 'quote-chat',
          lang: normalizeQuoteLanguage(
            latestAssistant.metadata.language || latestAssistant.metadata.lang,
            quoteContext.value?.lang || DEFAULT_QUOTE_LANG
          ),
        }
        persistQuoteContext(quoteContext.value)
      }
    }
    if (shouldHydrateQuoteItems) {
      const latestQuoteMessage = findLatestQuoteAssistantMessage(normalized)
      const quoteItems = getActionableQuoteRows(latestQuoteMessage?.metadata || {})
      if (quoteItems.length) {
        applyCERPMappings(quoteItems)
      } else if (latestQuoteMessage && !tableRows.value.length) {
        tableRows.value = []
        priceTable.value = []
        persistQuoteItems([])
      }
    }
  } catch (error) {
    chatError.value =
      error?.status === 401
        ? t('quote.errors.auth_required')
        : error?.message || t('quote.errors.load_conversation')
  } finally {
    chatLoading.value = false
  }
}

const applyQuoteChatHandoff = (handoff) => {
  if (!handoff) return false
  activeFilterTab.value = handoff.tab
  quoteContext.value = {
    ...(handoff.project ? { project: handoff.project } : {}),
    ...(handoff.conversation_id ? { conversation_id: handoff.conversation_id } : {}),
    ...(handoff.quote_continuity ? { quote_continuity: handoff.quote_continuity } : {}),
    surface_origin: handoff.surface_origin || 'chat-ui',
    lang: normalizeQuoteLanguage(handoff.lang, quoteContext.value?.lang || DEFAULT_QUOTE_LANG),
  }
  chatMessages.value = hydrateStructuredUrlsIntoThread(
    handoff.thread.map((record, index) => mapConversationMessage(record, index))
  )
  return true
}

const applyCerpSchema = (schema) => {
  const columns = normalizeSchemaColumns(schema)
  const visible = Array.isArray(schema?.default_visible_columns)
    ? schema.default_visible_columns
    : columns.filter((column) => column.default_visible).map((column) => column.key)
  cerpSchema.value = {
    ...FALLBACK_CERP_SCHEMA,
    ...(schema && typeof schema === 'object' ? schema : {}),
    columns,
    default_visible_columns: visible.length ? visible : DEFAULT_VISIBLE_COLUMNS,
  }
  visibleColumns.value = reorderVisibleColumns(cerpSchema.value.default_visible_columns)
  selectedPriceTypes.value = Array.isArray(cerpSchema.value.price_tiers)
    ? cerpSchema.value.price_tiers
        .filter((tier) => tier && tier.optional !== true)
        .map((tier) => tier.id)
        .filter(Boolean)
    : [...defaultPriceTypeIds.value]
  if (!selectedPriceTypes.value.length) selectedPriceTypes.value = [...defaultPriceTypeIds.value]
  syncPriceColumnsFromSelection()
}

const loadCerpSchema = async () => {
  try {
    const response = await fetch('/api/cerp/schema')
    if (!response.ok) throw new Error(`CERP schema request failed: ${response.status}`)
    applyCerpSchema(await response.json())
  } catch (error) {
    console.warn('Unable to load CERP schema; using fallback schema', error)
    applyCerpSchema(FALLBACK_CERP_SCHEMA)
  }
}

const bootstrapQuoteView = async () => {
  await loadCerpSchema()
  const handoff = loadQuoteChatHandoff()
  if (handoff) {
    applyQuoteChatHandoff(handoff)
    clearQuoteChatHandoff()
    if (handoff.conversation_id) {
      await fetchQuoteConversation(quoteContext.value, { hydrateQuoteItems: false })
    }
    await consumePendingQuoteCompose()
    return
  }

  const savedQuoteItems = loadQuoteItemsFromStorage()
  if (savedQuoteItems.length) {
    applyCERPMappings(savedQuoteItems)
  } else {
    fetchCERPSample().catch((error) => {
      console.error('Product inventory fetch failed', error)
    })
  }
  const context = loadQuoteContext()
  quoteContext.value = {
    ...context,
    surface_origin: context?.surface_origin || 'quote-chat',
    lang: normalizeQuoteLanguage(context?.lang, DEFAULT_QUOTE_LANG),
  }
  await fetchQuoteConversation(context)
  await consumePendingQuoteCompose()
}

const buildQuoteChatUiReturnPayload = () => {
  const latestQuote = latestQuoteAssistantMessage.value
  if (!latestQuote) return null
  const latestUser = [...chatMessages.value]
    .reverse()
    .find((message) => message?.role === 'user' && String(message?.text || '').trim())
  const quoteContinuity =
    buildQuoteContinuityFromMessage(latestQuote, {
      conversationId: quoteContext.value?.conversation_id || null,
      project: quoteContext.value?.project || null,
      lang: quoteContext.value?.lang || DEFAULT_QUOTE_LANG,
      surfaceOrigin: 'quote-chat',
    }) || null
  return {
    conversation_id: quoteContext.value?.conversation_id || null,
    project: quoteContext.value?.project || null,
    user_prompt: String(latestUser?.text || '').trim(),
    lang: normalizeQuoteLanguage(quoteContext.value?.lang, DEFAULT_QUOTE_LANG),
    surface_origin: 'quote-chat',
    url_inputs: (() => {
      const structuredUrls = getStructuredUrlsFromMetadata(latestQuote?.metadata || {})
      return structuredUrls.length ? structuredUrls : collectComposerUrlInputs()
    })(),
    quote_continuity: quoteContinuity,
    created_at: latestQuote?.timestamp || new Date().toISOString(),
    assistant_message: {
      id: latestQuote.id || null,
      text: latestQuote.text || '',
      created_at: latestQuote.timestamp || new Date().toISOString(),
      metadata: latestQuote.metadata || {},
    },
  }
}

const routeBackToHomeChatUi = async () => {
  const payload = buildQuoteChatUiReturnPayload()
  if (payload) {
    persistQuoteChatUiReturnPayload(payload)
    await router.push({ name: 'home' })
    return
  }
  const conversationId = quoteContext.value?.conversation_id
  if (conversationId) {
    await router.push({ name: 'home', query: { conversation_id: conversationId } })
    return
  }
  await router.push({ name: 'home' })
}

const pushUserMessage = (text, urlInputs = []) => {
  const author = createCurrentUserAuthor()
  const entry = {
    id: `local-user-${Date.now()}`,
    role: 'user',
    text: buildVisiblePromptForThread(text, urlInputs),
    timestamp: new Date().toISOString(),
    ...author,
  }
  chatMessages.value.push(entry)
}

const pushAssistantFromResponse = (response, question) => {
  assertUsableChatResponse(response, t)
  const { answer, metadata: normalizedMetadata, text, language } = normalizeChatAnswerPayload(response, {
    fallbackLanguage: resolveQuoteChatLanguage(question),
    normalizeLanguage: normalizeQuoteLanguage,
  })
  const lang = persistQuoteLanguage(language)
  const assistant = {
    id: answer.message_id || `local-assistant-${Date.now()}`,
    role: 'assistant',
    text,
    timestamp: new Date().toISOString(),
    metadata: normalizedMetadata,
    quoteUi: normalizeMessageQuoteUi(normalizedMetadata, new Date().toISOString()),
  }
  chatMessages.value.push(assistant)
  if (hasQuoteMetadata(normalizedMetadata)) {
    const actionableQuoteRows = getActionableQuoteRows(normalizedMetadata)
    if (actionableQuoteRows.length) {
      const enrichedItems = applyCERPMappings(actionableQuoteRows)
      persistQuoteItems(enrichedItems)
    } else {
      tableRows.value = []
      priceTable.value = []
      persistQuoteItems([])
    }
    persistQuoteContext({
      conversation_id: answer.conversation_id || quoteContext.value?.conversation_id,
      project: response?.project || quoteContext.value?.project,
      lang,
      surface_origin: 'quote-chat',
      quote_continuity: buildQuoteContinuityFromMessage(assistant, {
        conversationId: answer.conversation_id || quoteContext.value?.conversation_id || null,
        project: response?.project || quoteContext.value?.project || null,
        lang,
        surfaceOrigin: 'quote-chat',
      }),
    })
  }
}

const handleQuoteMessageCopy = async (message) => {
  const text = buildQuoteShareText(getQuoteUiForMessage(message), message?.text || '')
  try {
    await writeClipboard(text)
    triggerCopySnackbar()
  } catch (error) {
    console.warn('Clipboard copy failed', error)
  }
}

const handleQuoteMessageShare = async (message) => {
  const text = buildQuoteShareText(getQuoteUiForMessage(message), message?.text || '')
  if (navigator.share) {
    try {
      await navigator.share({
        title: t('quote.share.title'),
        text,
      })
      return
    } catch (error) {
      if (error?.name !== 'AbortError') {
        console.warn('Web Share failed', error)
      }
    }
  }
  try {
    await writeClipboard(text)
    triggerCopySnackbar()
  } catch (error) {
    console.warn('Clipboard share fallback failed', error)
  }
}

const handleQuoteFollowupAction = async (message, action) => {
  const actionId = String(action?.id || '').trim()
  const prompt = String(action?.prompt || '').trim()
  if (!actionId || !prompt || isSending.value) return
  await submitQuoteChat({
    message: prompt,
    lang: quoteContext.value?.lang || DEFAULT_QUOTE_LANG,
    followupAction: actionId,
    followupActionSource: 'button',
  })
}

const scrollQuoteThreadToBottom = async () => {
  await nextTick()
  const el = quoteThreadRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
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

const removeComposerAttachment = (id) => {
  removeUploadAttachment(id)
}

const clearComposerAttachments = () => {
  clearUploadAttachments()
}

const resolveSingleAttachmentMeta = (metas) => {
  if (!Array.isArray(metas) || !metas.length) return null
  return metas[0] || null
}

const collectComposerUrlInputs = () => extractComposerUrlInputs()

const uploadAttachmentMetaIfNeeded = async () => {
  if (!uploadAttachments.value.length) return null
  const metas = await uploadAttachmentsBeforeSend()
  const attachmentMeta = resolveSingleAttachmentMeta(metas)
  if (attachmentMeta) {
    clearUploadFiles()
  }
  return attachmentMeta
}

watch(
  () => [chatMessages.value.length, isSending.value],
  () => {
    scrollQuoteThreadToBottom()
  }
)

const submitQuoteChat = async (options = {}) => {
  const value = (options.message ?? composerValue.value ?? '').trim()
  if (!value || isSending.value) return
  const lang = persistQuoteLanguage(resolveQuoteChatLanguage(value, options.lang))
  persistQuoteContext({
    ...quoteContext.value,
    surface_origin: quoteContext.value?.surface_origin || 'quote-chat',
    lang,
  })
  isSending.value = true
  startQuoteProgressHints(lang)
  chatError.value = ''
  const urlInputs = Array.isArray(options.urlInputs) ? options.urlInputs.filter(Boolean) : collectComposerUrlInputs()
  pushUserMessage(options.displayMessage || value, urlInputs)
  await scrollQuoteThreadToBottom()
  try {
    const attachmentMeta = options.attachment || (await uploadAttachmentMetaIfNeeded())
    const payload = buildQuoteChatRequest({
      message: value,
      conversationId: quoteContext.value?.conversation_id,
      project: quoteContext.value?.project,
      lang,
      followupAction: options.followupAction,
      followupActionSource: options.followupActionSource,
      attachment: attachmentMeta,
      urlInputs,
    })
    const response = await sendChatMessage(payload)
    if (!response?.ok) {
      throw new Error(response?.error || t('quote.errors.submit_failed'))
    }
    pushAssistantFromResponse(response, value)
    if (response?.answer?.conversation_id) {
      quoteContext.value.conversation_id = response.answer.conversation_id
      const latestAssistant = chatMessages.value[chatMessages.value.length - 1]
      if (latestAssistant?.role === 'assistant') {
        quoteContext.value.quote_continuity =
          buildQuoteContinuityFromMessage(latestAssistant, {
            conversationId: response.answer.conversation_id,
            project: response?.project || quoteContext.value?.project || null,
            lang,
            surfaceOrigin: 'quote-chat',
          }) || quoteContext.value.quote_continuity || null
      }
      persistQuoteContext(quoteContext.value)
    }
    composerValue.value = ''
    clearComposerAttachments()
    if (!showGeneratedResults.value) {
      await routeBackToHomeChatUi()
    }
  } catch (error) {
    chatError.value = resolveChatFlowErrorMessage(error, t) || t('quote.errors.submit_failed')
  } finally {
    stopQuoteProgressHints()
    isSending.value = false
  }
}

const handleQuoteResultToggleChange = () => {
  persistQuoteDestinationPreference(showGeneratedResults.value)
  if (!showGeneratedResults.value) {
    routeBackToHomeChatUi().catch((error) => {
      console.warn('Unable to return quote result to ChatUI', error)
    })
  }
}

const fetchCERPSample = async () => {
  const isFakeCerpMode = String(cerpSchema.value?.mode || '').toLowerCase() === 'fake'
  const response = await fetch('/api/cerp/products/info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      custid: '1212266',
      supplier: t('quote.defaults.supplier'),
      compid: '001',
      exprange: 0,
      enrich_product_fields: true,
      perpage: 50,
    }),
  })
  if (!response.ok) {
    throw new Error(t('quote.errors.cerp_failed'))
  }
  const payload = await response.json()
  const rows = payload?.data?.wd4invnas ?? []
  const stockedRows = rows.filter((row) => {
    const quantity = resolveCerpStock(row)
    const price = getNumeric(row.invn013 ?? row.price ?? 0)
    return isFakeCerpMode ? quantity >= 0 : quantity >= 0 && price >= 1000
  }).sort((left, right) => resolveCerpStock(right) - resolveCerpStock(left))
  applyCERPMappings(stockedRows)
  return stockedRows
}

const toggleColor = (color) => {
  const next = new Set(colorFilters.value)
  if (next.has(color)) {
    next.delete(color)
  } else {
    next.add(color)
  }
  colorFilters.value = Array.from(next)
}

const baseColumnOrder = computed(() => tableColumns.value.map((col) => col.key))

const reorderVisibleColumns = (keys) =>
  baseColumnOrder.value.filter((key) => keys.includes(key))

const toggleColumn = (key) => {
  if (key === 'bundle') {
    showBundleColumn.value = !showBundleColumn.value
    return
  }
  const list = new Set(visibleColumns.value)
  if (list.has(key) && list.size > 4) {
    list.delete(key)
  } else if (!list.has(key)) {
    list.add(key)
  }
  visibleColumns.value = reorderVisibleColumns(Array.from(list))
}

const togglePanel = (panel) => {
  if (panel === 'sort') {
    showSortPanel.value = !showSortPanel.value
  } else if (panel === 'priceType') {
    showPriceTypeMenu.value = !showPriceTypeMenu.value
  } else if (panel === 'specification') {
    showSpecificationMenu.value = !showSpecificationMenu.value
  } else if (panel === 'brand') {
    showBrandMenu.value = !showBrandMenu.value
  } else if (panel === 'spec') {
    showSpecMenu.value = !showSpecMenu.value
  }
}

const updatePriceRange = (type, value) => {
  const numeric = typeof value === 'number' ? value : parseUsdInput(value)
  if (numeric === null) return
  if (type === 'min') {
    const nextMin = Math.min(Math.max(priceBounds.min, numeric), priceRange.value.max - 1000)
    setPriceRange({ min: nextMin })
  } else {
    const nextMax = Math.max(
      Math.min(priceBounds.max, numeric),
      priceRange.value.min + 1000
    )
    setPriceRange({ max: nextMax })
  }
}

const handlePriceSlider = (type, event) => {
  const value = Number(event.target.value)
  if (type === 'min') {
    const nextMin = Math.min(value, priceRange.value.max - 1000)
    setPriceRange({ min: nextMin })
  } else {
    const nextMax = Math.max(value, priceRange.value.min + 1000)
    setPriceRange({ max: nextMax })
  }
}

const setFeatureHandle = (type, value) => {
  const next = [...featureRange.value]
  if (type === 'min') {
    next[0] = Math.min(value, next[1])
  } else {
    next[1] = Math.max(value, next[0])
  }
  featureRange.value = next
}

const openRowMenu = (rowId, event) => {
  event.stopPropagation()
  activeRowMenu.value = activeRowMenu.value === rowId ? null : rowId
}

const requestDeleteRow = (row) => {
  rowPendingDelete.value = row
  showDeleteModal.value = true
  activeRowMenu.value = null
}

const confirmDeleteRow = () => {
  if (rowPendingDelete.value) {
    tableRows.value = tableRows.value.filter((row) => row.id !== rowPendingDelete.value.id)
  }
  showDeleteModal.value = false
  rowPendingDelete.value = null
}

const closeDeleteModal = () => {
  showDeleteModal.value = false
  rowPendingDelete.value = null
}

const closePanels = (event) => {
  if (!event.target.closest('[data-quote-panel="sort"]')) {
    showSortPanel.value = false
  }
  if (!event.target.closest('[data-quote-panel="priceType"]')) {
    showPriceTypeMenu.value = false
  }
    if (!event.target.closest('[data-quote-panel="specification"]')) {
    showSpecificationMenu.value = false
  }
  if (!event.target.closest('[data-quote-panel="brand"]')) {
    showBrandMenu.value = false
  }
  if (!event.target.closest('[data-quote-panel="spec"]')) {
    showSpecMenu.value = false
  }
  if (!event.target.closest('[data-quote-row-menu]')) {
    activeRowMenu.value = null
  }
}

const syncBundleColumn = () => {
  const hasBundle = visibleColumns.value.includes('bundle')
  if (showBundleColumn.value && !hasBundle) {
    const next = new Set([...visibleColumns.value, 'bundle'])
    visibleColumns.value = reorderVisibleColumns(Array.from(next))
  } else if (!showBundleColumn.value && hasBundle) {
    visibleColumns.value = visibleColumns.value.filter((key) => key !== 'bundle')
  }
}

watch(showBundleColumn, syncBundleColumn)

const priceTypeColumnKeys = computed(() =>
  priceTypeOptions.value
    .map((option) => option.column)
    .filter(Boolean)
)

const selectedPriceColumnKeys = computed(() => {
  const optionMap = priceTypeOptions.value.reduce((map, option) => {
    map[option.id] = option.column
    return map
  }, {})
  return selectedPriceTypes.value.map((key) => optionMap[key]).filter(Boolean)
})

const syncPriceColumnsFromSelection = () => {
  const selectedColumns = new Set(selectedPriceColumnKeys.value)
  const managedColumns = new Set(priceTypeColumnKeys.value)
  let nextColumns = visibleColumns.value.filter(
    (key) => !managedColumns.has(key) || selectedColumns.has(key)
  )
  priceTypeColumnKeys.value.forEach((columnKey) => {
    if (selectedColumns.has(columnKey) && !nextColumns.includes(columnKey)) {
      nextColumns.push(columnKey)
    }
  })
  visibleColumns.value = reorderVisibleColumns(nextColumns)
}

watch(selectedPriceTypes, syncPriceColumnsFromSelection, { deep: true })
syncPriceColumnsFromSelection()

const toggleSpecification = (value) => {
  const set = new Set(selectedSpecifications.value)
  const key = String(value || '').trim()
  if (!key) return
  set.has(key) ? set.delete(key) : set.add(key)
  selectedSpecifications.value = Array.from(set)
}

const toggleBrand = (value) => {
  const set = new Set(selectedBrands.value)
  const key = String(value || '').trim()
  if (!key) return
  set.has(key) ? set.delete(key) : set.add(key)
  selectedBrands.value = Array.from(set)
}

const toggleSpec = (value) => {
  const set = new Set(selectedSpecs.value)
  const key = String(value || '').trim()
  if (!key) return
  set.has(key) ? set.delete(key) : set.add(key)
  selectedSpecs.value = Array.from(set)
}

const specOptions = computed(() => {
  const bucket = new Set()
  tableRows.value.forEach((row) => {
    const val = String(row.spec || '').trim()
    if (val) bucket.add(val)
  })
  return Array.from(bucket).sort((a, b) => a.localeCompare(b))
})

const specificationOptions = computed(() => {
  const bucket = new Set()
  tableRows.value.forEach((row) => {
    const val = String(row.specification || '').trim()
    if (val) bucket.add(val)
  })
  return Array.from(bucket).sort()
})

const brandOptions = computed(() => {
  const bucket = new Set()
  tableRows.value.forEach((row) => {
    const val = String(row.brand || '').trim()
    if (val) bucket.add(val)
  })
  return Array.from(bucket).sort((a, b) => a.localeCompare(b))
})

const updateSortField = (rule, field) => {
  rule.field = field
  const config = sortFields.value[field]
  if (config) {
    rule.direction = config.defaultDirection
  }
}

const updateSortDirection = (rule, direction) => {
  rule.direction = direction
}

const addSortRule = () => {
  const nextId = sortRules.value.length
    ? Math.max(...sortRules.value.map((item) => item.id)) + 1
    : 1
  const firstField = sortFieldOptions.value[0]
  if (!firstField) return
  sortRules.value = [
    ...sortRules.value,
    { id: nextId, field: firstField, direction: sortFields.value[firstField].defaultDirection },
  ]
}

const removeSortRule = (id) => {
  sortRules.value = sortRules.value.filter((item) => item.id !== id)
}

const resetSortRules = () => {
  sortRules.value = []
}

const getDirectionOptions = (field) => sortFields.value[field]?.directions || []

const toggleDirection = (rule) => {
  const options = getDirectionOptions(rule.field)
  if (!options.length) return
  const idx = options.indexOf(rule.direction)
  const next = idx >= 0 ? options[(idx + 1) % options.length] : options[0]
  rule.direction = next
}

const selectedPriceTypeLabel = computed(() => {
  if (!selectedPriceTypes.value.length) return t('quote.filters.price_type.placeholder')
  if (selectedPriceTypes.value.length === 1) {
    const only = selectedPriceTypes.value[0]
    return (
      priceTypeOptions.value.find((opt) => opt.id === only)?.label ||
      t('quote.filters.price_type.placeholder')
    )
  }
  return t('quote.filters.price_type.selected', {
    count: selectedPriceTypes.value.length,
  })
})

const togglePriceType = (id) => {
  const set = new Set(selectedPriceTypes.value)
  if (set.has(id)) {
    set.delete(id)
  } else {
    set.add(id)
  }
  selectedPriceTypes.value = Array.from(set)
  syncPriceColumnsFromSelection()
}

const sortRuleCountLabel = computed(() => {
  const count = sortRules.value.length
  if (count === 1) {
    const solo = sortRules.value[0]
    return t('quote.sort.single', { field: solo.field, direction: solo.direction })
  }
  return count
    ? t('quote.sort.count', { count })
    : t('quote.sort.placeholder')
})

const getSpecificationValue = (value) => {
  const num = Number(value)
  if (Number.isFinite(num)) return num
  return Number.POSITIVE_INFINITY
}

const getBundleWeight = (value) => {
  if (!value) return 0
  if (typeof value === 'number') return value
  return 1
}

const reorderRules = (fromId, toId) => {
  const items = [...sortRules.value]
  const fromIndex = items.findIndex((item) => item.id === fromId)
  const toIndex = items.findIndex((item) => item.id === toId)
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return
  const [moved] = items.splice(fromIndex, 1)
  items.splice(toIndex, 0, moved)
  sortRules.value = items
}

const draggingRuleId = ref(null)

const handleDragStart = (rule, event) => {
  draggingRuleId.value = rule.id
  if (event?.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(rule.id))
  }
}

const handleDragOver = (event) => {
  event.preventDefault()
}

const handleDrop = (targetRule) => {
  if (draggingRuleId.value !== null) {
    reorderRules(draggingRuleId.value, targetRule.id)
  }
  draggingRuleId.value = null
}

const handleDragEnd = () => {
  draggingRuleId.value = null
}

function applySorting(rows) {
  const indexed = rows.map((row, index) => ({ row, index }))

  const comparators = []

  if (sortGrouping.value) {
    comparators.push((a, b) => {
      const pa = (a.brand || '').toString().toLowerCase()
      const pb = (b.brand || '').toString().toLowerCase()
      return pa.localeCompare(pb)
    })
  }

  comparators.push(
    ...sortRules.value
      .map((rule) => {
        const config = sortFields.value[rule.field]
        if (!config) return null
        const key = config.key
        const primaryDirection = config.directions?.[0] || config.defaultDirection
        const direction =
          rule.direction && config.directions?.includes(rule.direction)
            ? rule.direction
            : config.defaultDirection

        return (a, b) => {
          switch (key) {
            case 'specification': {
              const diff = getSpecificationValue(a[key]) - getSpecificationValue(b[key])
              if (diff !== 0) return direction === primaryDirection ? diff : -diff
              return 0
            }
            case 'product':
            case 'spec':
            case 'color': {
              const ca = (a[key] || '').toString().toLowerCase()
              const cb = (b[key] || '').toString().toLowerCase()
              const cmp = ca.localeCompare(cb)
              if (cmp !== 0) return direction === primaryDirection ? cmp : -cmp
              return 0
            }
            case 'feature': {
              const ra = extractFeatureValue(a.feature)
              const rb = extractFeatureValue(b.feature)
              if (ra !== rb) return direction === primaryDirection ? rb - ra : ra - rb
              const cmp = (a.feature || '').toString().localeCompare((b.feature || '').toString())
              if (cmp !== 0) return cmp
              return 0
            }
            case 'stock': {
              const diff = (Number(a.stock) || 0) - (Number(b.stock) || 0)
              if (diff !== 0) return direction === primaryDirection ? -diff : diff
              return 0
            }
            case 'price': {
              const diff = (Number(a.price) || 0) - (Number(b.price) || 0)
              if (diff !== 0) return direction === primaryDirection ? -diff : diff
              return 0
            }
            case 'bundle': {
              const diff = getBundleWeight(a.bundle) - getBundleWeight(b.bundle)
              if (diff !== 0) return direction === primaryDirection ? -diff : diff
              return 0
            }
            default:
              return 0
          }
        }
      })
      .filter(Boolean)
  )

  indexed.sort((a, b) => {
    for (const compare of comparators) {
      const result = compare(a.row, b.row)
      if (result !== 0) return result
    }
    // Stable fallback
    return a.index - b.index
  })

  return indexed.map((item) => item.row)
}

watch(
  () => route.query.tab,
  () => {
    syncFilterTabFromRoute()
    consumePendingQuoteCompose()
  }
)

onMounted(() => {
  document.addEventListener('click', closePanels)
  if (typeof window !== 'undefined') {
    window.addEventListener('resize', updateWidth)
  }
  resetQuoteDestinationPreference()
  syncFilterTabFromRoute()
  syncBundleColumn()
  bootstrapQuoteView()
  nextTick(() => {
    connectReportViewportObserver()
    scheduleReportViewportUpdate()
    resetMobileQuoteTrack()
  })
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closePanels)
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateWidth)
  }
  stopQuoteProgressHints()
  disconnectReportViewportObserver()
  clearReportViewportAnimationFrame()
  if (appendRowsTimer) {
    clearTimeout(appendRowsTimer)
    appendRowsTimer = null
  }
})
</script>

<template>
  <div
    class="app-shell quote-view-shell"
    :class="{ 'is-sidebar-collapsed': isSidebarCollapsed }"
  >

<AppSidebar
  :logo-src="logoMain"
  :nav-items="navItems"
  :icon-images="iconImages"
  :arrow-icon-src="iconArrowIndicator"
  :active-nav-id="activeNavId"
  :side-menu="sideMenu"
  :side-menu-open="sideMenuOpen"
  :aria-label="t('quote.aria.main_nav')"
  @logo-click="handleLogoClick"
  @nav-click="handleNavClick"
/>

    <div class="main-stage">

<AppTopBar
  :logo-src="logoMain"
  :is-compact-sidebar="isCompactSidebar"
  :is-sidebar-collapsed="isSidebarCollapsed"
  :hamburger-icon="glyphs.hamburger"
  :menu-aria-label="t('quote.aria.toggle_menu')"
  :avatar-aria-label="t('quote.aria.toggle_profile')"
  @toggle-sidebar="toggleSidebar"
  @logo-click="handleLogoClick"
>
  <template #search>
          <label v-if="!isTablet" class="search-field">
            <span class="search-field__icon" v-html="glyphs.search" aria-hidden="true" />
            <input
              type="search"
              :placeholder="t('quote.placeholders.search_chat')"
              v-model="searchQuery"
            />
          </label>
    <button
      v-else
      class="icon-button top-bar__search-button"
      type="button"
      :aria-label="t('quote.aria.search_chat')"
    >
      <span v-html="glyphs.search" aria-hidden="true" />
    </button>
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


<TopAdviceBar class="quote-advice">
  <div class="quote-advice__inner">
    <h2>{{ quoteAdviceTitle }}</h2>
  </div>
  <div class="chat-header__controls quote-advice__controls">
    <label class="result-toggle">
      <span>{{ t('quote.actions.show_generated') }}</span>
      <input type="checkbox" v-model="showGeneratedResults" @change="handleQuoteResultToggleChange" />
    </label>
  </div>
</TopAdviceBar>

      <main class="stage-canvas quote-stage" :class="{ 'is-mobile-quote': isMobileQuote }">
        <div class="quote-page">
          <div class="quote-layout" ref="quoteLayoutRef">
            <section class="quote-panel quote-panel--left" ref="quoteLeftPanelRef">
              <section class="quote-chat">
                <div class="quote-thread" ref="quoteThreadRef">
                  <div v-if="chatLoading" class="quote-thread__loading">
                    <span class="quote-thread__spinner" aria-hidden="true"></span>
                    <p>{{ t('quote.loading.conversation') }}</p>
                  </div>
                  <p v-else-if="chatError" class="quote-thread__error">{{ chatError }}</p>
                  <template v-else>
                    <div
                      v-for="message in chatMessages"
                      :key="message.id"
                      class="quote-thread__bubble"
                      :class="{
                        'is-user': message.role === 'user',
                        'is-assistant': message.role === 'assistant',
                        'is-quote-response': message.role === 'assistant' && messageHasQuoteUi(message),
                      }"
                    >
                      <div class="quote-thread__meta">
                        <span class="quote-thread__avatar">
                          {{ resolveQuoteAuthorLabel(message) }}
                        </span>
                        <small v-if="message.timestamp">{{ message.timestamp }}</small>
                      </div>
                      <QuoteResponseRenderer
                        v-if="message.role === 'assistant' && messageHasQuoteUi(message)"
                        class="quote-thread__quote-response chat-message__bubble is-quote-response"
                        :quote-ui="getQuoteUiForMessage(message)"
                        :followup-summary="getQuoteFollowupSummaryForMessage(message)"
                        :followup-actions="getQuoteFollowupActionsForMessage(message)"
                        :copy-aria-label="t('quote.aria.copy')"
                        :share-aria-label="t('quote.aria.share')"
                        @copy="handleQuoteMessageCopy(message)"
                        @share="handleQuoteMessageShare(message)"
                        @action="handleQuoteFollowupAction(message, $event)"
                      />
                      <p v-else class="quote-thread__text">{{ message.text }}</p>
                    </div>
                    <div
                      v-if="isSending"
                      class="quote-thread__bubble is-assistant is-typing"
                    >
                      <div class="quote-thread__meta">
                        <span class="quote-thread__avatar">{{ t('quote.labels.ai') }}</span>
                      </div>
                      <div class="quote-thread__typing" aria-live="polite">
                        <span></span>
                        <span></span>
                        <span></span>
                      </div>
                      <p class="quote-thread__typing-hint">{{ currentQuoteProgressHint }}</p>
                    </div>
                  </template>
                </div>

                <ChatComposer
                  v-model="composerValue"
                  :attachments="uploadAttachments"
                  :upload-warning="uploadWarning"
                  :show-attachments="true"
                  :send-icon-src="arrowButtonAsset"
                  :two-row-layout="uploadAttachments.length > 0"
                  :placeholder="t('quote.placeholders.compose')"
                  :send-aria-label="t('quote.aria.send_message')"
                  @submit="submitQuoteChat"
                  @upload-click="handleComposerUploadClick"
                  @add-urls="handleComposerUrlsAdded"
                  @remove-attachment="removeComposerAttachment"
                />
              </section>
            </section>

            <section
              ref="quoteTablePanelRef"
              class="quote-panel quote-panel--table is-slides"
              :class="[`is-${activeFilterTab}`]"
            >
              <template v-if="activeFilterTab === 'report'">
                <div class="quote-report-shell">
                  <div ref="quoteSummaryShellRef" class="quote-summary-shell">
                    <QuoteSortControls
                      :sort-rule-count-label="sortRuleCountLabel"
                      :sort-rules="sortRules"
                      :sort-field-options="sortFieldOptions"
                      :sort-grouping="sortGrouping"
                      :show-sort-panel="showSortPanel"
                      :show-bundle-column="showBundleColumn"
                      :toggle-panel="togglePanel"
                      :handle-drag-start="handleDragStart"
                      :handle-drag-over="handleDragOver"
                      :handle-drop="handleDrop"
                      :handle-drag-end="handleDragEnd"
                      :update-sort-field="updateSortField"
                      :toggle-direction="toggleDirection"
                      :remove-sort-rule="removeSortRule"
                      :add-sort-rule="addSortRule"
                      :reset-sort-rules="resetSortRules"
                      :set-sort-grouping="setSortGrouping"
                      :set-bundle-column="setBundleColumn"
                      :icon-drag="iconDrag"
                      :icon-up-down="iconUpDown"
                    />
                  </div>

                  <div
                    ref="quoteTableViewportRef"
                    class="quote-table-viewport"
                    :style="reportViewportStyle"
                    @scroll.passive="handleQuoteTableScroll"
                  >
                    <div class="quote-table-viewport__content">
                      <div class="quote-table">
                        <div class="quote-table__header" :style="reportGridStyle">
                          <div class="quote-table__cell is-select">
                            <input
                              type="checkbox"
                              :checked="allVisibleSelected"
                              :disabled="!hasVisibleSelectableRows"
                              :aria-label="t('quote.table.select_all')"
                              @change="toggleSelectAll"
                            />
                          </div>
                          <div
                            v-for="column in tableColumnsDisplayed"
                            :key="column.key"
                            class="quote-table__cell"
                            :data-column="column.key"
                          >
                            {{ column.label }}
                          </div>
                          <div class="quote-table__cell is-action">{{ t('quote.table.actions') }}</div>
                        </div>

                        <div class="quote-table__body">
                          <article
                            v-for="(row, index) in visibleReportRows"
                            :key="row.id || row.no || index"
                            class="quote-row"
                            :style="reportGridStyle"
                          >
                            <div class="quote-table__cell is-select">
                              <input
                                type="checkbox"
                                :checked="isRowSelected(row, index)"
                                :disabled="!isRowSelectable(row)"
                                :aria-label="t('quote.table.select_row')"
                                @change="toggleRowSelection(row, index)"
                              />
                            </div>
                            <div
                              v-for="column in tableColumnsDisplayed"
                              :key="`${row.id}-${column.key}`"
                              class="quote-table__cell"
                              :data-column="column.key"
                              :class="{
                                'quote-product': column.key === 'product',
                                'quote-color': column.key === 'color',
                              }"
                            >
                              <template v-if="column.key === 'product'">
                                <a href="#" role="button">{{ row.product }}</a>
                              </template>
                              <template v-else-if="column.key === 'color'">
                                <img
                                  :src="colorIconMap[String(row.color || '').toLowerCase()] || glassRed"
                                  :alt="row.color"
                                />
                                <span>{{ row.color }}</span>
                              </template>
                              <template
                                v-else-if="['price', 'vip', 'restaurant', 'dealer'].includes(column.key)"
                              >
                                {{
                                  formatCurrency(
                                    column.key === 'price'
                                      ? row.price
                                      : column.key === 'vip'
                                        ? row.vip
                                        : column.key === 'restaurant'
                                          ? row.restaurant
                                          : row.dealer
                                  )
                                }}
                              </template>
                              <template v-else-if="column.key === 'promo'">
                                {{ row.promo || '-' }}
                              </template>
                              <template v-else>
                                {{ row[column.key] }}
                              </template>
                            </div>
                            <div class="quote-table__cell is-action" data-quote-row-menu>
                              <button
                                type="button"
                                class="quote-row__menu"
                                :aria-label="t('quote.aria.open_actions')"
                                @click="openRowMenu(row.id, $event)"
                              >
                                <img :src="iconMoreVertical" alt="" aria-hidden="true" />
                              </button>
                              <div v-if="activeRowMenu === row.id" class="quote-row__popover">
                                <button type="button">{{ t('quote.actions.swap_recommendation') }}</button>
                                <button
                                  type="button"
                                  class="is-danger"
                                  @click="requestDeleteRow(row)"
                                >
                                  {{ t('quote.actions.delete') }}
                                </button>
                              </div>
                            </div>
                          </article>
                          <div
                            v-if="isAppendingRows"
                            class="quote-table__load-more"
                            :style="reportGridStyle"
                          >
                            <span class="quote-table__load-more-cell">
                              {{ t('quote.table.loading') }}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>

              <template v-else-if="activeFilterTab === 'gallery'">
                <div class="quote-report-shell quote-report-shell--tab">
                  <div ref="quoteSummaryShellRef" class="quote-summary-shell">
                    <QuoteSortControls
                      :sort-rule-count-label="sortRuleCountLabel"
                      :sort-rules="sortRules"
                      :sort-field-options="sortFieldOptions"
                      :sort-grouping="sortGrouping"
                      :show-sort-panel="showSortPanel"
                      :show-bundle-column="showBundleColumn"
                      :toggle-panel="togglePanel"
                      :handle-drag-start="handleDragStart"
                      :handle-drag-over="handleDragOver"
                      :handle-drop="handleDrop"
                      :handle-drag-end="handleDragEnd"
                      :update-sort-field="updateSortField"
                      :toggle-direction="toggleDirection"
                      :remove-sort-rule="removeSortRule"
                      :add-sort-rule="addSortRule"
                      :reset-sort-rules="resetSortRules"
                      :set-sort-grouping="setSortGrouping"
                      :set-bundle-column="setBundleColumn"
                      :icon-drag="iconDrag"
                      :icon-up-down="iconUpDown"
                    />
                  </div>

                  <div
                    ref="quoteTableViewportRef"
                    class="quote-table-viewport"
                    :style="reportViewportStyle"
                  >
                    <div class="quote-table-viewport__content">
                      <div class="quote-tab-shell quote-tab-shell--gallery">
                        <div class="quote-gallery">
                          <article
                            v-for="card in galleryCards"
                            :key="card.id"
                            class="quote-gallery-card"
                          >
                            <div class="quote-gallery-card__media">
                              <div class="quote-gallery-card__bottle" aria-hidden="true">
                                <img v-if="card.photoUrl" :src="card.photoUrl" :alt="card.title" />
                                <span v-else>{{ card.photoText }}</span>
                              </div>
                              <small>SKU {{ card.sku }}</small>
                            </div>
                            <div class="quote-gallery-card__body">
                              <header class="quote-gallery-card__header">
                                <span class="quote-gallery-card__sku">{{ card.sku }}</span>
                                <button
                                  type="button"
                                  :aria-label="t('quote.aria.open_card_menu')"
                                  class="quote-gallery-card__menu"
                                >
                                  ...
                                </button>
                              </header>
                              <p class="quote-gallery-card__title">{{ card.title }}</p>
                              <div class="quote-gallery-card__pricing">
                                <span class="is-vip">{{ t('quote.labels.vip') }} {{ formatCurrency(card.vipPrice) }}</span>
                                <span class="is-compare">{{ formatCurrency(card.comparePrice) }}</span>
                              </div>
                              <ul class="quote-gallery-card__stats">
                                <li>
                                  <label>{{ getSchemaColumnLabel('spec', 'Spec / Model') }}</label>
                                  <span>{{ card.spec || '-' }}</span>
                                </li>
                                <li v-if="card.color">
                                  <label>{{ getSchemaColumnLabel('color', t('quote.table.columns.color')) }}</label>
                                  <span>{{ card.color }}</span>
                                </li>
                                <li v-if="card.specification">
                                  <label>{{ t('quote.table.columns.specification') }}</label>
                                  <span>{{ card.specification }}</span>
                                </li>
                                <li v-if="card.feature">
                                  <label>{{ t('quote.table.columns.feature') }}</label>
                                  <span>{{ card.feature }}</span>
                                </li>
                                <li v-if="card.brand">
                                  <label>{{ getSchemaColumnLabel('brand', t('quote.table.columns.brand')) }}</label>
                                  <span>{{ card.brand }}</span>
                                </li>
                              </ul>
                              <p class="quote-gallery-card__description">
                                {{ card.description }}
                              </p>
                              <p v-if="card.link?.href" class="quote-gallery-card__link">
                                <a
                                  :href="card.link.href"
                                  target="_blank"
                                  rel="noopener"
                                >
                                  {{ card.link.label || t('quote.gallery.more_info') }}
                                  <span aria-hidden="true">?</span>
                                </a>
                              </p>
                              <div class="quote-gallery-card__footer">
                                <div class="quote-gallery-card__tags">
                                  <span v-for="terroir in card.terroirs" :key="terroir">{{ terroir }}</span>
                                </div>
                                <div class="quote-gallery-card__status">
                                  <strong>{{ card.progress }}%</strong>
                                  <span>{{ t('quote.gallery.cases', { count: card.cases }) }}</span>
                                </div>
                              </div>
                            </div>
                          </article>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>

              <template v-else-if="activeFilterTab === 'slides'">
                <div class="quote-report-shell quote-report-shell--tab">
                  <div ref="quoteSummaryShellRef" class="quote-summary-shell quote-summary-shell--slides">
                    <div class="quote-summary-shell__row">
                      <QuoteSortControls
                        :sort-rule-count-label="sortRuleCountLabel"
                        :sort-rules="sortRules"
                        :sort-field-options="sortFieldOptions"
                        :sort-grouping="sortGrouping"
                        :show-sort-panel="showSortPanel"
                        :show-bundle-column="showBundleColumn"
                        :toggle-panel="togglePanel"
                        :handle-drag-start="handleDragStart"
                        :handle-drag-over="handleDragOver"
                        :handle-drop="handleDrop"
                        :handle-drag-end="handleDragEnd"
                        :update-sort-field="updateSortField"
                        :toggle-direction="toggleDirection"
                        :remove-sort-rule="removeSortRule"
                        :add-sort-rule="addSortRule"
                        :reset-sort-rules="resetSortRules"
                        :set-sort-grouping="setSortGrouping"
                        :set-bundle-column="setBundleColumn"
                        :icon-drag="iconDrag"
                        :icon-up-down="iconUpDown"
                      />
                      <p class="quote-slides__count">
                        {{ t('quote.slides.count', { count: displayedSlideGroups.length }) }}
                      </p>
                    </div>
                  </div>
                  <div
                    ref="quoteTableViewportRef"
                    class="quote-table-viewport"
                    :style="reportViewportStyle"
                  >
                    <div class="quote-table-viewport__content">
                      <section class="quote-tab-shell quote-tab-shell--slides quote-slides">

                  <article class="quote-slide-card">
                    <div
                      v-for="(group, index) in displayedSlideGroups"
                      :key="group.id"
                      class="quote-slide-card__group"
                    >
                      <header class="quote-slide-card__header">
                        <span class="quote-slide-card__order">({{ group.order }})</span>
                        <h3>{{ group.title }}</h3>
                      </header>
                      <div class="quote-slide-card__meta">
                        <div class="quote-slide-card__meta-row">
                          <span class="quote-slide-card__meta-icon" aria-hidden="true">💰</span>
                          <span class="quote-slide-card__meta-label">{{ t('quote.slides.meta.price') }}</span>
                          <strong>{{ formatCurrency(group.price) }}</strong>
                        </div>
                        <div class="quote-slide-card__meta-row">
                          <span class="quote-slide-card__meta-icon" aria-hidden="true">🏅</span>
                          <span class="quote-slide-card__meta-label">{{ t('quote.slides.meta.specification') }}</span>
                          <strong>{{ group.specification }}</strong>
                        </div>
                        <div class="quote-slide-card__meta-row">
                          <span class="quote-slide-card__meta-icon" aria-hidden="true">🔢</span>
                          <span class="quote-slide-card__meta-label">{{ t('quote.slides.meta.sku') }}</span>
                          <strong>{{ group.sku }}</strong>
                        </div>
                        <div class="quote-slide-card__meta-row">
                          <span class="quote-slide-card__meta-icon" aria-hidden="true">🔗</span>
                          <span class="quote-slide-card__meta-label">{{ t('quote.slides.meta.link') }}</span>
                          <a
                            class="quote-slide-card__meta-link"
                            :href="group.link"
                            target="_blank"
                            rel="noopener"
                          >
                            {{ group.link }}
                          </a>
                        </div>
                      </div>
                      <div class="quote-slide-card__description">
                        <p
                          v-for="(note, index) in group.notes"
                          :key="`${group.id}-note-${index}`"
                        >
                          {{ note }}
                        </p>
                      </div>
                      <div class="quote-slide-card__details">
                        <span>{{ group.brand }}</span>
                        <span>{{ group.village }}</span>
                        <span>{{ t('quote.slides.meta.area', { value: group.parcel }) }}</span>
                      </div>
                      <div
                        v-if="index < displayedSlideGroups.length - 1"
                        class="quote-slide-card__divider"
                        aria-hidden="true"
                      ></div>
                    </div>
                  </article>
                  <div class="quote-slide-card__actions">
                    <button
                      type="button"
                      class="quote-slide-card__action"
                      :aria-label="t('quote.aria.copy')"
                      @click="triggerCopySnackbar"
                    >
                      <img :src="iconCopy" :alt="t('quote.aria.copy')" />
                    </button>
                    <button
                      type="button"
                      class="quote-slide-card__action"
                      :aria-label="t('quote.aria.share')"
                      @click="openShareDialog"
                    >
                      <img :src="iconShare" :alt="t('quote.aria.share')" />
                    </button>
                    <button
                      type="button"
                      class="quote-slide-card__action"
                      :aria-label="t('quote.aria.favorite')"
                    >
                      <img :src="iconStar" :alt="t('quote.aria.favorite')" />
                    </button>
                  </div>
                      </section>
                    </div>
                  </div>
                </div>
              </template>

              <template v-else>
                <div class="quote-report-shell quote-report-shell--tab">
                  <div ref="quoteSummaryShellRef" class="quote-summary-shell">
                    <QuoteSortControls
                      :sort-rule-count-label="sortRuleCountLabel"
                      :sort-rules="sortRules"
                      :sort-field-options="sortFieldOptions"
                      :sort-grouping="sortGrouping"
                      :show-sort-panel="showSortPanel"
                      :show-bundle-column="showBundleColumn"
                      :toggle-panel="togglePanel"
                      :handle-drag-start="handleDragStart"
                      :handle-drag-over="handleDragOver"
                      :handle-drop="handleDrop"
                      :handle-drag-end="handleDragEnd"
                      :update-sort-field="updateSortField"
                      :toggle-direction="toggleDirection"
                      :remove-sort-rule="removeSortRule"
                      :add-sort-rule="addSortRule"
                      :reset-sort-rules="resetSortRules"
                      :set-sort-grouping="setSortGrouping"
                      :set-bundle-column="setBundleColumn"
                      :icon-drag="iconDrag"
                      :icon-up-down="iconUpDown"
                    />
                  </div>
                  <div
                    ref="quoteTableViewportRef"
                    class="quote-table-viewport"
                    :style="reportViewportStyle"
                  >
                    <div class="quote-table-viewport__content">
                      <div class="quote-tab-shell quote-tab-shell--social">
                        <div class="quote-store">
                  <article
                    v-for="card in storeCards"
                    :key="card.id"
                    class="quote-store-card"
                  >
                    <header class="quote-store-card__header">
                      <span>{{ card.sku }}</span>
                      <button type="button">...</button>
                    </header>
                    <div class="quote-store-card__thumb" aria-hidden="true">
                      <img v-if="card.photoUrl" :src="card.photoUrl" :alt="card.title" />
                      <span v-else>{{ card.photoText }}</span>
                    </div>
                    <h3>{{ card.title }}</h3>
                    <p class="quote-store-card__price">
                      {{ t('quote.labels.vip') }} {{ formatCurrency(card.vipPrice) }}
                    </p>
                    <ul class="quote-store-card__specs">
                      <li>
                        <label>{{ t('quote.table.columns.feature') }}</label>
                        <span>{{ card.feature }}</span>
                      </li>
                      <li>
                        <label>{{ t('quote.table.columns.color') }}</label>
                        <span>{{ card.color }}</span>
                      </li>
                      <li>
                        <label>{{ t('quote.table.columns.specification') }}</label>
                        <span>{{ card.specification }}</span>
                      </li>
                    </ul>
                    <div class="quote-store-card__checklist">
                      <span
                        v-for="badge in card.badges"
                        :key="`${card.id}-${badge}`"
                      >
                        {{ badge }}
                      </span>
                    </div>
                  </article>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </section>

          <aside
            ref="quoteFiltersPanelRef"
            class="quote-panel quote-panel--filters"
          >
            <div ref="quoteFiltersStackRef" class="quote-filter__stack">
            <header class="quote-filter__header">
              <p>{{ t('quote.filters.output_type') }}</p>
              <div class="quote-filter__tabs">
                <button
                  v-for="tab in filterTabs"
                  :key="tab.id"
                  type="button"
                  :class="['quote-filter__tab', { 'is-active': tab.id === activeFilterTab }]"
                  @click="setActiveFilterTab(tab.id)"
                >
                  <img :src="tab.id === activeFilterTab ? tab.activeIcon : tab.icon" alt="" aria-hidden="true" />
                  <span>{{ tab.label }}</span>
                </button>
              </div>
            </header>

            <section class="quote-filter__section" data-quote-panel="priceType">
              <div class="quote-filter__row">
                <p>{{ t('quote.filters.price_type.label') }}</p>
                <button type="button" class="quote-filter__dropdown" @click.stop="togglePanel('priceType')">
                  <span>{{ selectedPriceTypeLabel }}</span>
                  <span class="quote-filter__caret">⌄</span>
                </button>
              </div>
              <div v-if="showPriceTypeMenu" class="quote-filter__menu">
                <button
                  v-for="option in priceTypeOptions"
                  :key="option.id"
                  type="button"
                  :class="['quote-filter__menu-item', { 'is-active': selectedPriceTypes.includes(option.id) }]"
                  @click="togglePriceType(option.id)"
                >
                  <span class="quote-filter__check" aria-hidden="true">
                    {{ selectedPriceTypes.includes(option.id) ? '✓' : '' }}
                  </span>
                  <span>{{ option.label }}</span>
                </button>
              </div>
            </section>

            <section v-if="showColorFilter" class="quote-filter__section">
              <p>{{ t('quote.filters.price_range') }}</p>
              <div class="quote-slider">
                <div class="quote-slider__track">
                  <div class="quote-slider__fill" :style="priceFillStyle" />
                  <input
                    type="range"
                    :min="priceBounds.min"
                    :max="priceBounds.max"
                    :value="priceRange.min"
                    @input="handlePriceSlider('min', $event)"
                  />
                  <input
                    type="range"
                    :min="priceBounds.min"
                    :max="priceBounds.max"
                    :value="priceRange.max"
                    @input="handlePriceSlider('max', $event)"
                  />
                </div>
                <div class="quote-slider__inputs">
                  <label>
                    <input
                      type="text"
                      inputmode="numeric"
                      :value="formatUsdInput(priceRange.min)"
                      @input="updatePriceRange('min', parseUsdInput($event.target.value))"
                    />
                  </label>
                  <span class="quote-slider__dash">—</span>
                  <label>
                    <input
                      type="text"
                      inputmode="numeric"
                      :value="formatUsdInput(priceRange.max)"
                      @input="updatePriceRange('max', parseUsdInput($event.target.value))"
                    />
                  </label>
                </div>
              </div>
            </section>

            <section v-if="showFeatureFilter" class="quote-filter__section">
              <p>{{ t('quote.filters.color') }}</p>
              <div class="quote-color__list">
                <label
                  v-for="option in colorOptions"
                  :key="option.id"
                  class="quote-color__pill"
                  :class="{ 'is-active': colorFilters.includes(option.id) }"
                >
                  <span
                    class="quote-color__dot"
                    :style="{
                      background: option.swatch,
                      borderColor: getColorDotBorder(option.id),
                    }"
                  />
                  <input
                    type="checkbox"
                    :value="option.id"
                    :checked="colorFilters.includes(option.id)"
                    @change="toggleColor(option.id)"
                  />
                  {{ option.label }}
                </label>
              </div>
            </section>

            <section class="quote-filter__section">
              <p>{{ t('quote.filters.feature') }}</p>
              <div class="quote-feature">
                <div class="quote-slider__track is-feature">
                  <div class="quote-slider__fill" :style="featureFillStyle" />
                  <input
                    type="range"
                    min="0"
                    :max="featureSteps.length - 1"
                    :value="featureRange[0]"
                    step="1"
                    @input="setFeatureHandle('min', Number($event.target.value))"
                  />
                  <input
                    type="range"
                    min="0"
                    :max="featureSteps.length - 1"
                    :value="featureRange[1]"
                    step="1"
                    @input="setFeatureHandle('max', Number($event.target.value))"
                  />
                </div>
                <div class="quote-feature__labels">
                  <span v-for="step in featureSteps" :key="step">{{ step }}</span>
                </div>
              </div>
            </section>

            

            <section v-if="showSpecFilter" class="quote-filter__section" data-quote-panel="spec">
              <p>{{ getSchemaColumnLabel('spec', 'Spec / Model') }}</p>
              <div class="quote-autocomplete" @click.stop="togglePanel('spec')">
                <div class="quote-autocomplete__field">
                  <div class="quote-autocomplete__chips">
                    <span
                      v-for="chip in selectedSpecs"
                      :key="chip"
                      class="quote-chip"
                    >
                      {{ chip }}
                      <button type="button" @click.stop="toggleSpec(chip)">×</button>
                    </span>
                    <span v-if="!selectedSpecs.length" class="quote-autocomplete__placeholder">
                      {{ t('quote.filters.all') }}
                    </span>
                  </div>
                  <span class="quote-filter__caret">⌄</span>
                </div>
              </div>
              <div v-if="showSpecMenu" class="quote-filter__menu">
                <button
                  v-for="option in specOptions"
                  :key="option"
                  type="button"
                  :class="['quote-filter__menu-item', { 'is-active': selectedSpecs.includes(option) }]"
                  @click.stop="toggleSpec(option)"
                >
                  <span class="quote-filter__check" aria-hidden="true">
                    {{ selectedSpecs.includes(option) ? '✓' : '' }}
                  </span>
                  <span>{{ option }}</span>
                </button>
              </div>
            </section>

            <section v-if="showSpecificationFilter" class="quote-filter__section" data-quote-panel="specification">
              <p>{{ t('quote.filters.specification') }}</p>
              <div class="quote-autocomplete" @click.stop="togglePanel('specification')">
                <div class="quote-autocomplete__field">
                  <div class="quote-autocomplete__chips">
                    <span
                      v-for="chip in selectedSpecifications"
                      :key="chip"
                      class="quote-chip"
                    >
                      {{ chip }}
                      <button type="button" @click.stop="toggleSpecification(chip)">×</button>
                    </span>
                    <span v-if="!selectedSpecifications.length" class="quote-autocomplete__placeholder">
                      {{ t('quote.filters.all') }}
                    </span>
                  </div>
                  <span class="quote-filter__caret">⌄</span>
                </div>
              </div>
              <div v-if="showSpecificationMenu" class="quote-filter__menu">
                <button
                  v-for="option in specificationOptions"
                  :key="option"
                  type="button"
                  :class="['quote-filter__menu-item', { 'is-active': selectedSpecifications.includes(option) }]"
                  @click.stop="toggleSpecification(option)"
                >
                  <span class="quote-filter__check" aria-hidden="true">
                    {{ selectedSpecifications.includes(option) ? '✓' : '' }}
                  </span>
                  <span>{{ option }}</span>
                </button>
              </div>
            </section>

            <section v-if="showBrandFilter" class="quote-filter__section" data-quote-panel="brand">
              <p>{{ t('quote.filters.brand') }}</p>
              <div class="quote-autocomplete" @click.stop="togglePanel('brand')">
                <div class="quote-autocomplete__field">
                  <div class="quote-autocomplete__chips">
                    <span
                      v-for="chip in selectedBrands"
                      :key="chip"
                      class="quote-chip"
                    >
                      {{ chip }}
                      <button type="button" @click.stop="toggleBrand(chip)">×</button>
                    </span>
                    <span v-if="!selectedBrands.length" class="quote-autocomplete__placeholder">
                      {{ t('quote.filters.all') }}
                    </span>
                  </div>
                  <span class="quote-filter__caret">⌄</span>
                </div>
              </div>
              <div v-if="showBrandMenu" class="quote-filter__menu">
                <button
                  v-for="option in brandOptions"
                  :key="option"
                  type="button"
                  :class="['quote-filter__menu-item', { 'is-active': selectedBrands.includes(option) }]"
                  @click.stop="toggleBrand(option)"
                >
                  <span class="quote-filter__check" aria-hidden="true">
                    {{ selectedBrands.includes(option) ? '✓' : '' }}
                  </span>
                  <span>{{ option }}</span>
                </button>
              </div>
            </section>

            <section class="quote-filter__section">
              <p>{{ t('quote.filters.inventory') }}</p>
              <div class="quote-radio">
                <label
                  v-for="option in inventoryOptions"
                  :key="option.id"
                  :class="['quote-radio__item', { 'is-active': option.id === selectedInventory }]"
                >
                  <input
                    type="radio"
                    name="inventory"
                    :value="option.id"
                    v-model="selectedInventory"
                  />
                  <span>{{ option.label }}</span>
                </label>
              </div>
            </section>

            </div>

            <div
              ref="quoteFilterActionsRef"
              :class="['quote-filter__actions', { 'is-single': isSlidesTab }]"
            >
              <button type="button" class="quote-ghost" @click="resetFilters">{{ t('quote.actions.reset_filters') }}</button>
              <button
                v-if="!isSlidesTab"
                type="button"
                class="quote-primary"
                @click="createEdmFromSelection"
              >
                {{ t('quote.actions.create_edm', { count: selectedQuoteCount }) }}
              </button>
            </div>
          </aside>

          </div>
        </div>
      </main>
    </div>
  </div>

  <div
    v-if="showDeleteModal"
    class="quote-modal-mask"
    role="dialog"
    aria-modal="true"
  >
    <div class="quote-modal">
      <header>
        <h3>{{ t('quote.modals.delete.title') }}</h3>
        <button type="button" @click="closeDeleteModal">✕</button>
      </header>
      <p>{{ t('quote.modals.delete.body') }}</p>
      <footer>
        <button type="button" class="quote-ghost" @click="closeDeleteModal">
          {{ t('quote.actions.cancel') }}
        </button>
        <button type="button" class="quote-primary" @click="confirmDeleteRow">
          {{ t('quote.actions.delete') }}
        </button>
      </footer>
    </div>
  </div>

  <div v-if="showCopySnackbar" class="quote-snackbar" role="status">
    <div class="quote-snackbar__body">
      <div class="quote-snackbar__icon" aria-hidden="true">✔︎</div>
      <div class="quote-snackbar__text">
        <strong>{{ t('quote.snackbar.copied_title') }}</strong>
        <p>{{ t('quote.snackbar.copied_body') }}</p>
      </div>
    </div>
  </div>
  <div v-if="showSelectionSnackbar" class="quote-snackbar" role="status">
    <div class="quote-snackbar__body">
      <div class="quote-snackbar__icon" aria-hidden="true">!</div>
      <div class="quote-snackbar__text">
        <strong>{{ t('quote.snackbar.select_items_title') }}</strong>
        <p>{{ t('quote.snackbar.select_items_body') }}</p>
      </div>
    </div>
  </div>

  <div
    v-if="showShareDialog"
    class="quote-share-dialog"
    role="dialog"
    aria-modal="true"
  >
    <div class="quote-share-dialog__card">
      <header class="quote-share-dialog__header">
        <h3>{{ t('quote.share.title') }}</h3>
        <button type="button" class="quote-share-dialog__close" @click="closeShareDialog">×</button>
      </header>
      <section class="quote-share-dialog__content">
        <div class="quote-share-dialog__icon" aria-hidden="true">💬</div>
        <div class="quote-share-dialog__copy">
          <p class="quote-share-dialog__lead">
            {{ t('quote.share.lead') }}
          </p>
          <p class="quote-share-dialog__text">
            {{ t('quote.share.body') }}
          </p>
        </div>
      </section>
      <form class="quote-share-dialog__form" @submit.prevent="closeShareDialog">
        <input
          type="email"
          :placeholder="t('quote.share.email_placeholder')"
          :aria-label="t('quote.share.email_aria')"
        />
        <button type="submit" class="quote-primary">{{ t('quote.actions.send') }}</button>
      </form>
      <p class="quote-share-dialog__hint">
        {{ t('quote.share.hint') }}
      </p>
    </div>
  </div>
</template>
