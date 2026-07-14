<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import * as XLSX from 'xlsx'
import { useAuth } from '../composables/useAuth'
import logoMain from '../assets/ysLogo_transparent.png'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import emptyIllustration from '../assets/label_illustration_empty_content.svg'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import PageHeader from '../components/PageHeader.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'
import { renderPrintDocumentHtml as renderLabelPrintDocumentHtml } from '../print/labelPrintTemplate'
import {
  fetchLabelDescription,
  addPrintListItem,
  fetchPrintListCount,
  fetchPrintList,
  deletePrintListItem,
  resetPrintList,
  regenerateLabelDescription,
  searchCerpProducts,
  updatePrintListItemPrice,
  updateLabelDescription,
  importPrintListItems,
} from '../services/ysApi'

const router = useRouter()
const { t } = useI18n()
const { isAuthenticated, userProfile } = useAuth()

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'home.nav'))

const iconImages = PRIMARY_NAV_ICON_IMAGES

const activeNavId = ref('showcase')
const searchQuery = ref('')
const selectedSize = ref('')
const labelSearchQuery = ref('')
const searchResults = ref([])
const isSearchOpen = ref(false)
const isSearchLoading = ref(false)
const searchError = ref('')
const hasSearchAttempted = ref(false)
const lastSubmittedQuery = ref('')
const selectedProduct = ref(null)
const descriptionText = ref('')
const isDescriptionLoading = ref(false)
const sizePriceOverrides = ref({ small: null, medium: null, large: null })
const isEditModalOpen = ref(false)
const editPrice = ref('')
const editDescription = ref('')
const editInstruction = ref('')
const editModalMode = ref('full')
const isRegenerating = ref(false)
const isSaving = ref(false)
const printListCount = ref(0)
const showSnackbar = ref(false)
const snackbarMessage = ref('')
const isPrintModalOpen = ref(false)
const isPrintLoading = ref(false)
const isPrintConfirmModalOpen = ref(false)
const isResetConfirmModalOpen = ref(false)
const isImportResultModalOpen = ref(false)
const isPrinting = ref(false)
const isResettingPrintList = ref(false)
const isImporting = ref(false)
const printItems = ref([])
const editItem = ref(null)
const importResult = ref(null)
const searchWrapperRef = ref(null)
const searchInputRef = ref(null)
const importFileInputRef = ref(null)
const LABEL_LANG = 'zh-TW'
const MAX_DESC = 220
const PRINT_PANEL_CAPACITY = { small: 8, medium: 4, large: 2 }
const PRINT_PANEL_ORDER = ['small', 'medium', 'large']
const IMPORT_TEMPLATE_HEADERS = ['產品編號', '品名', 'Brand', 'Model Year', '價格', '大尺寸', '中尺寸', '小尺寸']

const createEmptySizePriceOverrides = () => ({ small: null, medium: null, large: null })
const normalizeSizeKey = (size) => {
  const key = String(size || '').toLowerCase()
  return PRINT_PANEL_ORDER.includes(key) ? key : 'large'
}
const resolveSizePriceOverride = (size) => {
  const key = normalizeSizeKey(size)
  const value = sizePriceOverrides.value[key]
  return typeof value === 'number' && value > 0 ? value : null
}
const setSizePriceOverride = (size, value) => {
  const key = normalizeSizeKey(size)
  const number = Number(value)
  sizePriceOverrides.value = {
    ...sizePriceOverrides.value,
    [key]: Number.isNaN(number) || number <= 0 ? null : number,
  }
}
const resetSizePriceOverrides = () => {
  sizePriceOverrides.value = createEmptySizePriceOverrides()
}

let activeSearchController = null
let suppressSearch = false
let snackbarTimer = null
let searchDebounceTimer = null
const SEARCH_DEBOUNCE_MS = 250
let printIframeRef = null
let printCleanupTimer = null

const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const initialViewport = typeof window !== 'undefined' ? window.innerWidth : 1440
const stageWidth = ref(initialViewport)
const isSidebarCollapsed = ref(initialViewport <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isTablet = computed(() => stageWidth.value <= 900)
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet,
    isSidebarCollapsed,
  })
const hasProduct = computed(() => !!selectedProduct.value)
const canEditStep2 = computed(() => hasProduct.value && !!selectedSize.value)
const importErrorRows = computed(() =>
  Array.isArray(importResult.value?.error_rows) ? importResult.value.error_rows : []
)
const printPanelsBySize = computed(() => {
  const grouped = { small: [], medium: [], large: [] }
  for (const item of printItems.value) {
    if (!PRINT_PANEL_ORDER.includes(item?.size)) continue
    grouped[item.size].push(item)
  }

  return PRINT_PANEL_ORDER
    .map((size) => {
      const expanded = grouped[size].flatMap((item) => expandByQuantity(item))
      const panels = chunkItems(expanded, size)
      return {
        size,
        title: getPrintPanelTitle(size),
        capacity: PRINT_PANEL_CAPACITY[size],
        panels,
      }
    })
    .filter((section) => section.panels.length > 0)
})
const printLabelCountBySize = computed(() => {
  const counts = { small: 0, medium: 0, large: 0 }
  for (const section of printPanelsBySize.value) {
    counts[section.size] = section.panels.reduce((sum, panel) => sum + panel.length, 0)
  }
  return counts
})
const printSheetCountBySize = computed(() => {
  const counts = { small: 0, medium: 0, large: 0 }
  for (const section of printPanelsBySize.value) {
    counts[section.size] = section.panels.length
  }
  return counts
})
const totalSheets = computed(() =>
  PRINT_PANEL_ORDER.reduce((sum, size) => sum + (printSheetCountBySize.value[size] || 0), 0)
)

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
  if (item?.route) {
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

const handleFabClick = () => {
  if (!isAuthenticated.value) return
  openPrintModal()
}

const resolveProductCode = (product) =>
  (product?.no || product?.id || product?.invn002 || '').toString().trim()

const resolveProductName = (product) =>
  (
    product?.name_en ||
    product?.name_ch ||
    product?.name ||
    product?.invn005 ||
    product?.title ||
    ''
  ).toString().trim()

const resolveProducer = (product) =>
  (product?.producer || product?.invn006 || '').toString().trim()

const resolveVintage = (product) => {
  const raw = (product?.vintage || product?.invn051 || '').toString().trim()
  return raw || 'NV'
}

const resolveRegion = (product) =>
  (product?.region || product?.invn030 || '').toString().trim()

const resolveRating = (product) =>
  (product?.rating || product?.invn804 || product?.invn805 || '').toString().trim()

const resolvePrintProduct = (item) => item?.product_snapshot || {}

const resolvePrintCode = (item) => (item?.code || '').toString().trim()

const resolvePrintName = (item) => {
  const product = resolvePrintProduct(item)
  return resolveProductName(product)
}

const resolvePrintProducer = (item) => {
  const product = resolvePrintProduct(item)
  return resolveProducer(product)
}

const resolvePrintVintage = (item) => {
  const product = resolvePrintProduct(item)
  return resolveVintage(product)
}

const resolvePrintRegion = (item) => {
  const product = resolvePrintProduct(item)
  return resolveRegion(product)
}

const resolvePrintRating = (item) => {
  const product = resolvePrintProduct(item)
  return resolveRating(product)
}

const getPrintPanelTitle = (size) => {
  if (size === 'small') return t('labelPrint.smallPanelTitle')
  if (size === 'medium') return t('labelPrint.mediumPanelTitle')
  return t('labelPrint.largePanelTitle')
}

const resolvePrintCodeLabel = (item) => {
  const code = resolvePrintCode(item)
  return code ? `No. ${code}` : 'No. -'
}

const normalizeItemQuantity = (item) => {
  const parsed = Number(item?.quantity)
  if (Number.isNaN(parsed) || parsed <= 0) return 1
  return Math.floor(parsed)
}

const expandByQuantity = (item) => {
  const qty = normalizeItemQuantity(item)
  const baseKey = item?.id || resolvePrintCode(item) || 'item'
  return Array.from({ length: qty }, (_, index) => ({
    ...item,
    __panelCopyIndex: index,
    __panelCopyKey: `${baseKey}-${index}`,
  }))
}

const chunkItems = (items, size) => {
  const capacity = PRINT_PANEL_CAPACITY[size] || 1
  if (!items.length) return []
  const chunks = []
  for (let index = 0; index < items.length; index += capacity) {
    chunks.push(items.slice(index, index + capacity))
  }
  return chunks
}

const formatPrice = (value) => {
  const number = Number(String(value ?? '').replace(/,/g, ''))
  if (Number.isNaN(number) || number <= 0) return ''
  return `$${number.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

const resolveBasePriceValue = (product) => {
  const listPrice = product?.list_price ?? product?.invn013
  const fallbackPrice = product?.price ?? product?.invn015
  const raw = listPrice ?? fallbackPrice
  const number = Number(String(raw ?? '').replace(/,/g, ''))
  if (Number.isNaN(number) || number <= 0) return null
  return number
}

const resolvePriceText = (product, size) => {
  const overrideValue = resolveSizePriceOverride(size)
  if (overrideValue) return formatPrice(overrideValue)
  const listPrice = product?.list_price ?? product?.invn013
  const fallbackPrice = product?.price ?? product?.invn015
  return formatPrice(listPrice ?? fallbackPrice)
}

const resolvePrintBasePriceValue = (item) =>
  resolveBasePriceValue(resolvePrintProduct(item))

const resolvePrintPriceText = (item) => {
  if (item?.price_override && item.price_override > 0) {
    return formatPrice(item.price_override)
  }
  const product = resolvePrintProduct(item)
  const listPrice = product?.list_price ?? product?.invn013
  const fallbackPrice = product?.price ?? product?.invn015
  return formatPrice(listPrice ?? fallbackPrice)
}

const buildPrintTemplatePanels = () =>
  printPanelsBySize.value.map((section) => ({
    size: section.size,
    panels: section.panels.map((panelItems) =>
      panelItems.map((item) => ({
        producer: resolvePrintProducer(item),
        name: resolvePrintName(item),
        price: resolvePrintPriceText(item),
        rating: resolvePrintRating(item) || '-',
        vintage: resolvePrintVintage(item),
        region: resolvePrintRegion(item) || '-',
        description: (item.description || '').slice(0, MAX_DESC),
      }))
    ),
  }))

const cleanupPrintIframe = (resetPrinting = true) => {
  if (printCleanupTimer) {
    clearTimeout(printCleanupTimer)
    printCleanupTimer = null
  }
  if (printIframeRef?.parentNode) {
    printIframeRef.parentNode.removeChild(printIframeRef)
  }
  printIframeRef = null
  if (resetPrinting) {
    isPrinting.value = false
  }
}

const createPrintIframe = () => {
  if (typeof window === 'undefined') return null
  cleanupPrintIframe(false)
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.opacity = '0'
  iframe.style.pointerEvents = 'none'
  iframe.style.border = '0'
  document.body.appendChild(iframe)
  printIframeRef = iframe
  return iframe
}

const normalizePriceInput = (value) => {
  const raw = String(value ?? '').replace(/[^\d]/g, '')
  if (!raw) return null
  const number = Number(raw)
  if (Number.isNaN(number) || number <= 0) return null
  return number
}

const formatImportRowValue = (entry) => {
  const raw = entry?.raw_row || {}
  return [
    raw['產品編號'],
    raw['品名'],
    raw['Brand'] ?? raw['Producer'],
    raw['Model Year'] ?? raw['年份'],
    raw['價格'],
    raw['大尺寸'],
    raw['中尺寸'],
    raw['小尺寸'],
  ]
    .filter((value) => value !== null && value !== undefined && String(value).trim())
    .map((value) => String(value).trim())
    .join(' / ')
}

const openSnackbar = (message) => {
  snackbarMessage.value = message
  showSnackbar.value = true
  if (snackbarTimer) {
    clearTimeout(snackbarTimer)
  }
  snackbarTimer = setTimeout(() => {
    showSnackbar.value = false
    snackbarTimer = null
  }, 3000)
}

const buildSampleWorkbook = () => {
  const sampleRows = [
    IMPORT_TEMPLATE_HEADERS,
    ['ODR-HK0-JKT0001-24', '', '', '', 1280, 'Y', '', ''],
    ['', 'Alpine Rain Shell', 'TrailForge', '2025', '', '', 'Y', ''],
    ['', 'Carbon Trekking Pole', 'PeakRiver', '2024', '', 'Y', '', 'Y'],
  ]
  const guideRows = [
    [t('labelSettings.sampleGuideTitle')],
    [t('labelSettings.sampleGuideLine1')],
    [t('labelSettings.sampleGuideLine2')],
    [t('labelSettings.sampleGuideLine3')],
    [t('labelSettings.sampleGuideLine4')],
    [t('labelSettings.sampleGuideLine5')],
  ]
  const dataSheet = XLSX.utils.aoa_to_sheet(sampleRows)
  dataSheet['!cols'] = [
    { wch: 10 },
    { wch: 22 },
    { wch: 18 },
    { wch: 10 },
    { wch: 10 },
    { wch: 12 },
    { wch: 10 },
    { wch: 10 },
  ]
  const guideSheet = XLSX.utils.aoa_to_sheet(guideRows)
  guideSheet['!cols'] = [{ wch: 90 }]
  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, dataSheet, t('labelSettings.sampleSheetName'))
  XLSX.utils.book_append_sheet(workbook, guideSheet, t('labelSettings.sampleGuideSheetName'))
  return workbook
}

const downloadSampleWorkbook = () => {
  const workbook = buildSampleWorkbook()
  XLSX.writeFile(workbook, t('labelSettings.sampleFileName'))
  openSnackbar(t('labelSettings.snackbarSampleDownloaded'))
}

const triggerImportPicker = () => {
  if (isImporting.value) return
  importFileInputRef.value?.click()
}

const closeImportResultModal = () => {
  isImportResultModalOpen.value = false
}

const downloadFailedRowsWorkbook = () => {
  if (!importErrorRows.value.length) return
  const exportRows = [
    [...IMPORT_TEMPLATE_HEADERS, '錯誤代碼', '錯誤訊息', '原始列號'],
    ...importErrorRows.value.map((entry) => [
      entry?.raw_row?.['產品編號'] ?? '',
      entry?.raw_row?.['品名'] ?? '',
      entry?.raw_row?.['Brand'] ?? entry?.raw_row?.['Producer'] ?? '',
      entry?.raw_row?.['Model Year'] ?? entry?.raw_row?.['年份'] ?? '',
      entry?.raw_row?.['價格'] ?? '',
      entry?.raw_row?.['大尺寸'] ?? '',
      entry?.raw_row?.['中尺寸'] ?? '',
      entry?.raw_row?.['小尺寸'] ?? '',
      entry?.reason_code ?? '',
      entry?.message ?? '',
      entry?.row_number ?? '',
    ]),
  ]
  const worksheet = XLSX.utils.aoa_to_sheet(exportRows)
  worksheet['!cols'] = [
    { wch: 34 },
    { wch: 22 },
    { wch: 10 },
    { wch: 12 },
    { wch: 10 },
    { wch: 10 },
    { wch: 10 },
    { wch: 10 },
    { wch: 16 },
    { wch: 48 },
    { wch: 12 },
  ]
  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, t('labelSettings.sampleSheetName'))
  XLSX.writeFile(workbook, 'product-label-import-errors.xlsx')
}

const handleImportFileChange = async (event) => {
  const [file] = event?.target?.files || []
  if (!file) return
  try {
    isImporting.value = true
    const response = await importPrintListItems(file, LABEL_LANG)
    importResult.value = response || null
    printListCount.value = response?.total_quantity ?? printListCount.value
    if (isPrintModalOpen.value) {
      await loadPrintList()
    }
    if (Array.isArray(response?.error_rows) && response.error_rows.length) {
      isImportResultModalOpen.value = true
      openSnackbar(t('labelSettings.snackbarImportPartial'))
    } else {
      isImportResultModalOpen.value = false
      openSnackbar(t('labelSettings.snackbarImportSuccess'))
    }
  } catch (error) {
    console.error('Batch import failed', error)
    openSnackbar(error?.message || t('labelSettings.searchEmpty'))
  } finally {
    isImporting.value = false
    if (event?.target) {
      event.target.value = ''
    }
  }
}

const openSearch = () => {
  if (!labelSearchQuery.value.trim()) return
  if (!isSearchLoading.value && !searchResults.value.length) return
  isSearchOpen.value = true
}

const closeSearch = () => {
  isSearchOpen.value = false
}

const clearSearch = () => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
    searchDebounceTimer = null
  }
  if (activeSearchController) {
    activeSearchController.abort()
    activeSearchController = null
  }
  labelSearchQuery.value = ''
  searchResults.value = []
  isSearchOpen.value = false
  isSearchLoading.value = false
  searchError.value = ''
  hasSearchAttempted.value = false
  lastSubmittedQuery.value = ''
  selectedProduct.value = null
  descriptionText.value = ''
  resetSizePriceOverrides()
  selectedSize.value = ''
}

const selectProduct = (product) => {
  if (!product) return
  const currentCode = resolveProductCode(selectedProduct.value)
  const nextCode = resolveProductCode(product)
  if (nextCode && nextCode !== currentCode) {
    selectedSize.value = ''
    resetSizePriceOverrides()
    descriptionText.value = ''
  }
  selectedProduct.value = product
  suppressSearch = true
  labelSearchQuery.value = resolveProductName(product)
  searchResults.value = []
  isSearchOpen.value = false
  hasSearchAttempted.value = false
  searchError.value = ''
  lastSubmittedQuery.value = ''
}

const performSearch = async (query) => {
  const trimmed = query.trim()
  if (!trimmed) {
    searchResults.value = []
    isSearchOpen.value = false
    isSearchLoading.value = false
    return
  }

  if (activeSearchController) {
    activeSearchController.abort()
  }
  const controller = new AbortController()
  activeSearchController = controller
  isSearchLoading.value = true
  isSearchOpen.value = true
  searchResults.value = []
  searchError.value = ''

  try {
    const response = await searchCerpProducts({
      query: trimmed,
      limit: 20,
      lang: LABEL_LANG,
      signal: controller.signal,
    })
    if (activeSearchController !== controller) return
    searchResults.value = response?.items || []
    isSearchOpen.value = true
  } catch (error) {
    if (error?.name !== 'AbortError') {
      console.error('Label search failed', error)
      searchError.value = '目前無法搜尋產品，請稍後再試'
      isSearchOpen.value = true
    }
  } finally {
    if (activeSearchController === controller) {
      isSearchLoading.value = false
      activeSearchController = null
    }
  }
}

const handleSearchSubmit = () => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
    searchDebounceTimer = null
  }
  const trimmed = labelSearchQuery.value.trim()
  if (!trimmed) {
    searchResults.value = []
    isSearchOpen.value = false
    isSearchLoading.value = false
    searchError.value = ''
    hasSearchAttempted.value = false
    lastSubmittedQuery.value = ''
    return
  }
  if (trimmed.length < 2) {
    searchResults.value = []
    isSearchLoading.value = false
    isSearchOpen.value = true
    hasSearchAttempted.value = true
    lastSubmittedQuery.value = trimmed
    return
  }
  if (trimmed === lastSubmittedQuery.value && hasSearchAttempted.value && !isSearchLoading.value) {
    isSearchOpen.value = true
    return
  }
  hasSearchAttempted.value = true
  lastSubmittedQuery.value = trimmed
  performSearch(trimmed)
}

watch(labelSearchQuery, (value) => {
  if (suppressSearch) {
    suppressSearch = false
    return
  }
  if (selectedProduct.value && value !== resolveProductName(selectedProduct.value)) {
    selectedProduct.value = null
    descriptionText.value = ''
    resetSizePriceOverrides()
    selectedSize.value = ''
  }
  const trimmed = value.trim()
  if (!trimmed) {
    if (activeSearchController) {
      activeSearchController.abort()
      activeSearchController = null
    }
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer)
      searchDebounceTimer = null
    }
    searchResults.value = []
    isSearchOpen.value = false
    isSearchLoading.value = false
    searchError.value = ''
    hasSearchAttempted.value = false
    lastSubmittedQuery.value = ''
    return
  }
  if (activeSearchController) {
    activeSearchController.abort()
    activeSearchController = null
  }
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
    searchDebounceTimer = null
  }
  searchResults.value = []
  searchError.value = ''
  if (trimmed.length < 2) {
    isSearchOpen.value = false
    isSearchLoading.value = false
    return
  }
  isSearchOpen.value = true
  isSearchLoading.value = true
  hasSearchAttempted.value = true
  lastSubmittedQuery.value = trimmed
  searchDebounceTimer = setTimeout(() => {
    searchDebounceTimer = null
    if (labelSearchQuery.value.trim() === trimmed) {
      performSearch(trimmed)
    }
  }, SEARCH_DEBOUNCE_MS)
})

watch(selectedProduct, async (product) => {
  if (!product) {
    descriptionText.value = ''
    isDescriptionLoading.value = false
    resetSizePriceOverrides()
    selectedSize.value = ''
    return
  }
  const code = resolveProductCode(product)
  if (!code) {
    descriptionText.value = ''
    isDescriptionLoading.value = false
    resetSizePriceOverrides()
    selectedSize.value = ''
    return
  }
  isDescriptionLoading.value = true
  try {
    const response = await fetchLabelDescription(code, LABEL_LANG)
    const raw = response?.description || ''
    descriptionText.value = raw.slice(0, MAX_DESC)
    resetSizePriceOverrides()
    setSizePriceOverride('large', response?.price_override ?? null)
  } catch (error) {
    console.error('Fetch label description failed', error)
    descriptionText.value = ''
    resetSizePriceOverrides()
  } finally {
    isDescriptionLoading.value = false
  }
})

const selectSize = (size) => {
  if (!hasProduct.value) return
  selectedSize.value = size
}

const openEditModal = () => {
  if (editItem.value) return
  if (!canEditStep2.value || !selectedProduct.value) return
  const targetSize = normalizeSizeKey(selectedSize.value)
  editModalMode.value = targetSize === 'large' ? 'full' : 'priceOnly'
  const basePrice = resolveBasePriceValue(selectedProduct.value)
  const overridePrice = resolveSizePriceOverride(targetSize)
  const initialPrice = overridePrice || basePrice
  editPrice.value = initialPrice ? formatPrice(initialPrice) : ''
  editDescription.value = (descriptionText.value || '').slice(0, MAX_DESC)
  editInstruction.value = ''
  isEditModalOpen.value = true
}

const openEditModalForItem = (item) => {
  if (!item) return
  const itemSize = (item?.size || '').toLowerCase()
  editModalMode.value = itemSize === 'small' || itemSize === 'medium' ? 'priceOnly' : 'full'
  editItem.value = item
  const basePrice = resolvePrintBasePriceValue(item)
  const initialPrice = item?.price_override && item.price_override > 0 ? item.price_override : basePrice
  editPrice.value = initialPrice ? formatPrice(initialPrice) : ''
  editDescription.value = (item.description || '').slice(0, MAX_DESC)
  editInstruction.value = ''
  isEditModalOpen.value = true
}

const closeEditModal = () => {
  if (isSaving.value) return
  isEditModalOpen.value = false
  editItem.value = null
  editModalMode.value = 'full'
}

const handleRegenerate = async () => {
  if (editModalMode.value !== 'full') return
  if (isRegenerating.value) return
  const instruction = editInstruction.value.trim()
  if (!instruction) return
  const code = editItem.value ? resolvePrintCode(editItem.value) : resolveProductCode(selectedProduct.value)
  if (!code) return
  const parsedPrice = normalizePriceInput(editPrice.value)
  const fallbackPrice = editItem.value
    ? resolvePrintBasePriceValue(editItem.value)
    : resolveBasePriceValue(selectedProduct.value)
  const priceValue = parsedPrice || fallbackPrice
  if (!priceValue) {
    return
  }
  if (!parsedPrice) {
    editPrice.value = formatPrice(priceValue)
  }
  isRegenerating.value = true
  try {
    const response = await regenerateLabelDescription({
      code,
      lang: LABEL_LANG,
      instruction,
      priceOverride: priceValue,
    })
    const raw = response?.description || ''
    editDescription.value = raw.slice(0, MAX_DESC)
    editInstruction.value = ''
  } catch (error) {
    console.error('Regenerate label description failed', error)
  } finally {
    isRegenerating.value = false
  }
}

const handleConfirmEdit = async () => {
  if (isSaving.value) return
  const code = editItem.value ? resolvePrintCode(editItem.value) : resolveProductCode(selectedProduct.value)
  if (!code) return
  const parsedPrice = normalizePriceInput(editPrice.value)
  const targetSize = editItem.value ? normalizeSizeKey(editItem.value?.size) : normalizeSizeKey(selectedSize.value)
  const fallbackPrice = editItem.value
    ? resolvePrintBasePriceValue(editItem.value)
    : resolveBasePriceValue(selectedProduct.value)
  if (!parsedPrice) {
    if (editItem.value) {
      const revertValue = editItem.value?.price_override && editItem.value.price_override > 0
        ? editItem.value.price_override
        : fallbackPrice
      editPrice.value = revertValue ? formatPrice(revertValue) : ''
      return
    }
    const revertValue = resolveSizePriceOverride(targetSize) || fallbackPrice
    editPrice.value = revertValue ? formatPrice(revertValue) : ''
    return
  }
  const nextDescription = (editDescription.value || descriptionText.value || '').slice(0, MAX_DESC)
  isSaving.value = true
  try {
    if (editItem.value) {
      let updatedDescription = nextDescription
      if (editModalMode.value === 'full') {
        const descriptionResponse = await updateLabelDescription({
          code,
          lang: LABEL_LANG,
          description: nextDescription,
        })
        updatedDescription = (descriptionResponse?.description || nextDescription).slice(0, MAX_DESC)
      }
      const priceResponse = await updatePrintListItemPrice(editItem.value.id, {
        priceOverride: parsedPrice,
      })
      const updatedPrice = priceResponse?.price_override ?? parsedPrice
      const updatedItem = {
        ...editItem.value,
        description: updatedDescription,
        price_override: updatedPrice,
      }
      printItems.value = printItems.value.map((item) =>
        item.id === updatedItem.id ? updatedItem : item
      )
      if (selectedProduct.value && resolveProductCode(selectedProduct.value) === code) {
        if (targetSize === 'large') {
          descriptionText.value = updatedDescription
        }
        setSizePriceOverride(targetSize, updatedPrice)
      }
      editItem.value = null
    } else {
      const response = await updateLabelDescription({
        code,
        lang: LABEL_LANG,
        description: nextDescription,
        priceOverride: parsedPrice,
      })
      const updatedDescription = (response?.description || nextDescription).slice(0, MAX_DESC)
      const updatedPrice = response?.price_override ?? parsedPrice
      if (targetSize === 'large') {
        descriptionText.value = updatedDescription
      }
      setSizePriceOverride(targetSize, updatedPrice)
    }
    isEditModalOpen.value = false
  } catch (error) {
    console.error('Update label description failed', error)
  } finally {
    isSaving.value = false
  }
}

async function loadPrintListCount() {
  if (!isAuthenticated.value) {
    printListCount.value = 0
    return
  }
  try {
    const response = await fetchPrintListCount()
    printListCount.value = response?.total_quantity || 0
  } catch (error) {
    console.error('Fetch print list failed', error)
  }
}

watch(
  isAuthenticated,
  (value) => {
    if (value) {
      loadPrintListCount()
      return
    }
    printListCount.value = 0
    router.replace({ name: 'home' })
  },
  { immediate: true }
)

const handleAddToPrintList = async () => {
  if (!selectedProduct.value || !selectedSize.value || !isAuthenticated.value) return
  const code = resolveProductCode(selectedProduct.value)
  if (!code) return
  try {
    const response = await addPrintListItem({
      code,
      size: selectedSize.value,
      productSnapshot: selectedProduct.value,
    })
    printListCount.value = response?.total_quantity ?? printListCount.value
    if (isPrintModalOpen.value) {
      await loadPrintList()
    }
    openSnackbar(t('labelSettings.snackbarAdded'))
  } catch (error) {
    console.error('Add to print list failed', error)
  }
}

const loadPrintList = async () => {
  if (!isAuthenticated.value) {
    printItems.value = []
    printListCount.value = 0
    return
  }
  isPrintLoading.value = true
  try {
    const response = await fetchPrintList(LABEL_LANG)
    printItems.value = response?.items || []
    printListCount.value = response?.total_quantity || 0
  } catch (error) {
    console.error('Fetch print list failed', error)
  } finally {
    isPrintLoading.value = false
  }
}

const openPrintModal = () => {
  if (!isAuthenticated.value) return
  isPrintModalOpen.value = true
  isPrintConfirmModalOpen.value = false
  isResetConfirmModalOpen.value = false
  loadPrintList()
}

const closePrintModal = () => {
  isPrintModalOpen.value = false
  isPrintConfirmModalOpen.value = false
  isResetConfirmModalOpen.value = false
}

const handleDeletePrintItem = async (item) => {
  if (!item?.id) return
  try {
    await deletePrintListItem(item.id)
    await loadPrintList()
  } catch (error) {
    console.error('Delete print item failed', error)
  }
}

const openResetConfirmModal = () => {
  if (!printItems.value.length || isResettingPrintList.value) return
  isResetConfirmModalOpen.value = true
}

const closeResetConfirmModal = () => {
  if (isResettingPrintList.value) return
  isResetConfirmModalOpen.value = false
}

const confirmResetPrintList = async () => {
  if (!isAuthenticated.value) return
  if (isResettingPrintList.value) return
  isResettingPrintList.value = true
  try {
    await resetPrintList()
    printItems.value = []
    printListCount.value = 0
    isResetConfirmModalOpen.value = false
  } catch (error) {
    console.error('Reset print list failed', error)
  } finally {
    isResettingPrintList.value = false
  }
}

const openPrintConfirmModal = () => {
  if (!printItems.value.length || isPrinting.value) return
  isPrintConfirmModalOpen.value = true
}

const closePrintConfirmModal = () => {
  if (isPrinting.value) return
  isPrintConfirmModalOpen.value = false
}

const startPrintFromModal = async () => {
  if (!isPrintModalOpen.value || !printItems.value.length || isPrinting.value) return
  const iframe = createPrintIframe()
  if (!iframe?.contentWindow) {
    console.error('Unable to create print iframe')
    return
  }
  isPrinting.value = true
  isPrintConfirmModalOpen.value = false
  try {
    const html = renderLabelPrintDocumentHtml(buildPrintTemplatePanels(), {
      title: t('labelPrint.title'),
    })
    const doc = iframe.contentDocument || iframe.contentWindow.document
    if (!doc) {
      throw new Error('Print iframe document not available')
    }

    await new Promise((resolve) => {
      let resolved = false
      const done = () => {
        if (resolved) return
        resolved = true
        resolve()
      }
      const onLoad = () => done()
      iframe.addEventListener('load', onLoad, { once: true })
      doc.open()
      doc.write(html)
      doc.close()
      setTimeout(done, 300)
    })

    iframe.contentWindow.onafterprint = () => {
      cleanupPrintIframe(true)
    }

    printCleanupTimer = setTimeout(() => {
      if (isPrinting.value) {
        cleanupPrintIframe(true)
      }
    }, 15000)

    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    iframe.contentWindow.focus()
    iframe.contentWindow.print()
  } catch (error) {
    console.error('Print labels failed', error)
    cleanupPrintIframe(true)
  }
}

const handleDocumentClick = (event) => {
  if (!searchWrapperRef.value) return
  if (!searchWrapperRef.value.contains(event.target)) {
    closeSearch()
  }
}

onMounted(() => {
  if (typeof window === 'undefined') return
  window.addEventListener('resize', updateWidth)
  document.addEventListener('click', handleDocumentClick)
  loadPrintListCount()
})

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener('resize', updateWidth)
  document.removeEventListener('click', handleDocumentClick)
  if (activeSearchController) {
    activeSearchController.abort()
    activeSearchController = null
  }
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
    searchDebounceTimer = null
  }
  if (snackbarTimer) {
    clearTimeout(snackbarTimer)
  }
  cleanupPrintIframe(false)
})
</script>

<template>
  <div
    class="app-shell"
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
      :aria-label="t('home.aria.main_nav')"
      @logo-click="handleLogoClick"
      @nav-click="handleNavClick"
    />

    <div class="main-stage">
      <AppTopBar
        :logo-src="logoMain"
        :is-compact-sidebar="isCompactSidebar"
        :is-sidebar-collapsed="isSidebarCollapsed"
        :hamburger-icon="glyphs.hamburger"
        :menu-aria-label="t('home.aria.toggle_menu')"
        :avatar-aria-label="t('home.aria.open_account_menu')"
        @toggle-sidebar="toggleSidebar"
        @logo-click="handleLogoClick"
      >
        <template #search>
          <label v-if="!isTablet" class="search-field">
            <span class="search-field__icon" v-html="glyphs.search" aria-hidden="true" />
            <input
              type="search"
              :placeholder="t('home.placeholders.search')"
              v-model="searchQuery"
            />
          </label>
          <button
            v-else
            class="icon-button top-bar__search-button"
            type="button"
            :aria-label="t('home.aria.open_search')"
          >
            <span v-html="glyphs.search" aria-hidden="true" />
          </button>
        </template>
      </AppTopBar>

      <main class="stage-canvas label-settings-stage">
        <div class="label-settings__content">
          <PageHeader :title="t('labelSettings.title')" class="label-settings__header" />

          <section class="label-card label-card--s1">
            <div class="label-card__header">
              <span class="label-chip">{{ t('labelSettings.step1') }}</span>
              <span class="label-category">{{ t('labelSettings.selectWines') }}</span>
            </div>
            <div class="label-card__row">
              <div
                ref="searchWrapperRef"
                class="label-search"
                role="combobox"
                :aria-expanded="isSearchOpen"
                @click.stop
              >
                <svg class="label-search__icon" viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="2" />
                  <path d="M16.5 16.5L20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
                </svg>
                <input
                  ref="searchInputRef"
                  v-model="labelSearchQuery"
                  type="text"
                  :placeholder="t('labelSettings.searchPlaceholder')"
                  :aria-label="t('labelSettings.searchPlaceholder')"
                  @focus="openSearch"
                  @keydown.enter.prevent="handleSearchSubmit"
                />
                <button
                  v-if="labelSearchQuery"
                  class="label-search__clear"
                  type="button"
                  :aria-label="t('labelSettings.searchClear')"
                  @click.stop="clearSearch"
                >
                  ×
                </button>
                <button
                  class="label-search__submit"
                  type="button"
                  :disabled="labelSearchQuery.trim().length < 2 || isSearchLoading"
                  :aria-label="t('labelSettings.searchPlaceholder')"
                  @click.stop="handleSearchSubmit"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 12 3 3 7-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
                </button>
                <div v-if="isSearchOpen" class="label-search__dropdown" @click.stop>
                  <div v-if="isSearchLoading" class="label-search__status">
                    {{ t('labelSettings.searchLoading') }}
                  </div>
                  <button
                    v-for="item in searchResults"
                    :key="resolveProductCode(item) || resolveProductName(item)"
                    type="button"
                    class="label-search__option"
                    :class="{ 'is-selected': resolveProductCode(item) === resolveProductCode(selectedProduct) }"
                    @click.stop="selectProduct(item)"
                  >
                    <span class="label-search__option-title">{{ resolveProductName(item) }}</span>
                    <span class="label-search__option-sub">
                      {{ resolveProductCode(item) }}
                      <span v-if="resolveProducer(item)"> · {{ resolveProducer(item) }}</span>
                    </span>
                  </button>
                  <div
                    v-if="!isSearchLoading && searchError"
                    class="label-search__status label-search__status--error"
                  >
                    {{ searchError }}
                  </div>
                  <div
                    v-else-if="!isSearchLoading && hasSearchAttempted && !searchResults.length"
                    class="label-search__status"
                  >
                    {{ t('labelSettings.searchEmpty') }}
                  </div>
                </div>
              </div>
              <div class="label-card__footer-actions">
                <input
                  ref="importFileInputRef"
                  type="file"
                  accept=".xlsx"
                  class="label-import-input"
                  @change="handleImportFileChange"
                />
                <button
                  class="label-button label-button--primary"
                  type="button"
                  :disabled="isImporting"
                  @click="triggerImportPicker"
                >
                  {{ isImporting ? t('labelSettings.importing') : t('labelSettings.importExcel') }}
                </button>
                <button class="label-button label-button--link" type="button" @click="downloadSampleWorkbook">
                  {{ t('labelSettings.downloadSample') }}
                </button>
              </div>
            </div>
          </section>

          <section class="label-card label-card--s2">
            <div class="label-card__header">
              <span class="label-chip">{{ t('labelSettings.step2') }}</span>
              <span class="label-category">{{ t('labelSettings.selectSize') }}</span>
            </div>
            <div class="label-size-grid">
              <div class="label-size label-size--small">
                <div class="label-radio">
                  <button
                    class="label-radio__icon"
                    :class="{ 'is-selected': selectedSize === 'small' }"
                    type="button"
                    role="radio"
                    :aria-checked="selectedSize === 'small'"
                    :disabled="!hasProduct"
                    @click="selectSize('small')"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="radio-ring" cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
                      <circle v-if="selectedSize === 'small'" class="radio-dot" cx="12" cy="12" r="6" />
                    </svg>
                  </button>
                  <span class="label-radio__label">{{ t('labelSettings.sizeSmall') }}</span>
                </div>
                <div class="label-size__preview" :class="{ 'has-preview': selectedProduct }">
                  <div v-if="selectedProduct" class="label-preview label-preview--small">
                    <div class="label-preview__bar"></div>
                    <div class="label-preview__body">
                      <div class="label-preview__producer">{{ resolveProducer(selectedProduct) }}</div>
                      <div class="label-preview__name">{{ resolveProductName(selectedProduct) }}</div>
                    </div>
                    <div class="label-preview__meta">
                      <div>• {{ resolveVintage(selectedProduct) }}</div>
                      <div>• {{ resolveRegion(selectedProduct) || '-' }}</div>
                    </div>
                    <div class="label-preview__price">{{ resolvePriceText(selectedProduct, 'small') }}</div>
                  </div>
                  <div v-else class="label-size__text">
                    <div class="label-size__value">{{ t('labelSettings.sizeSmallValue') }}</div>
                    <div class="label-size__desc">{{ t('labelSettings.sizeSmall') }}</div>
                  </div>
                </div>
              </div>
              <div class="label-size label-size--medium">
                <div class="label-radio">
                  <button
                    class="label-radio__icon"
                    :class="{ 'is-selected': selectedSize === 'medium' }"
                    type="button"
                    role="radio"
                    :aria-checked="selectedSize === 'medium'"
                    :disabled="!hasProduct"
                    @click="selectSize('medium')"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="radio-ring" cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
                      <circle v-if="selectedSize === 'medium'" class="radio-dot" cx="12" cy="12" r="6" />
                    </svg>
                  </button>
                  <span class="label-radio__label">{{ t('labelSettings.sizeMedium') }}</span>
                </div>
                <div class="label-size__preview" :class="{ 'has-preview': selectedProduct }">
                  <div v-if="selectedProduct" class="label-preview label-preview--medium">
                    <div class="label-preview__bar"></div>
                    <div class="label-preview__body">
                      <div class="label-preview__producer">{{ resolveProducer(selectedProduct) }}</div>
                      <div class="label-preview__name">{{ resolveProductName(selectedProduct) }}</div>
                    </div>
                    <div class="label-preview__meta">
                      <div>• {{ resolveRating(selectedProduct) || '-' }}</div>
                      <div>• {{ resolveVintage(selectedProduct) }}</div>
                      <div>• {{ resolveRegion(selectedProduct) || '-' }}</div>
                    </div>
                    <div class="label-preview__price">{{ resolvePriceText(selectedProduct, 'medium') }}</div>
                  </div>
                  <div v-else class="label-size__text">
                    <div class="label-size__value">{{ t('labelSettings.sizeMediumValue') }}</div>
                    <div class="label-size__desc">{{ t('labelSettings.sizeMedium') }}</div>
                  </div>
                </div>
              </div>
              <div class="label-size label-size--large">
                <div class="label-radio">
                  <button
                    class="label-radio__icon"
                    :class="{ 'is-selected': selectedSize === 'large' }"
                    type="button"
                    role="radio"
                    :aria-checked="selectedSize === 'large'"
                    :disabled="!hasProduct"
                    @click="selectSize('large')"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="radio-ring" cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
                      <circle v-if="selectedSize === 'large'" class="radio-dot" cx="12" cy="12" r="6" />
                    </svg>
                  </button>
                  <span class="label-radio__label">{{ t('labelSettings.sizeLarge') }}</span>
                </div>
                <div class="label-size__preview" :class="{ 'has-preview': selectedProduct }">
                  <div v-if="selectedProduct" class="label-preview label-preview--large">
                    <div class="label-preview__bar"></div>
                    <div class="label-preview__price">{{ resolvePriceText(selectedProduct, 'large') }}</div>
                    <div class="label-preview__body">
                      <div class="label-preview__producer">{{ resolveProducer(selectedProduct) }}</div>
                      <div class="label-preview__name">{{ resolveProductName(selectedProduct) }}</div>
                    </div>
                    <div class="label-preview__details">
                      <span class="label-preview__detail label-preview__detail--rating">
                        {{ resolveRating(selectedProduct) || '-' }}
                      </span>
                      <div class="label-preview__details-group">
                        <span class="label-preview__divider"></span>
                        <span class="label-preview__detail label-preview__detail--vintage">
                          {{ resolveVintage(selectedProduct) }}
                        </span>
                        <span class="label-preview__divider"></span>
                        <span class="label-preview__detail label-preview__detail--region">
                          {{ resolveRegion(selectedProduct) || '-' }}
                        </span>
                      </div>
                    </div>
                    <div class="label-preview__description">
                      <span v-if="isDescriptionLoading">
                        {{ t('labelSettings.descriptionLoading') }}
                      </span>
                      <span v-else-if="descriptionText">
                        {{ descriptionText }}
                      </span>
                      <span v-else>
                        {{ t('labelSettings.descriptionEmpty') }}
                      </span>
                    </div>
                  </div>
                  <div v-else class="label-size__text">
                    <div class="label-size__value">{{ t('labelSettings.sizeLargeValue') }}</div>
                    <div class="label-size__desc">{{ t('labelSettings.sizeLarge') }}</div>
                  </div>
                </div>
              </div>
            </div>
            <div class="label-card__actions">
              <button
                class="label-button label-button--outline"
                type="button"
                :disabled="!canEditStep2"
                @click="openEditModal"
              >
                {{ t('labelSettings.editLabel') }}
              </button>
              <button
                class="label-button label-button--outline"
                type="button"
                :disabled="!hasProduct || !selectedSize || !isAuthenticated"
                @click="handleAddToPrintList"
              >
                {{ t('labelSettings.addToPrint') }}
              </button>
            </div>
          </section>
        </div>

        <div v-if="isPrintModalOpen" class="label-print-modal">
          <div class="label-print-modal__backdrop" @click="closePrintModal"></div>
          <div class="label-print-modal__card" role="dialog" aria-modal="true">
            <header class="label-print-modal__header">
              <h3>{{ t('labelPrint.title') }}</h3>
              <button class="label-print-modal__close" type="button" @click="closePrintModal">×</button>
            </header>
            <div class="label-print-modal__divider"></div>
            <section
              class="label-print-modal__body"
              :class="{ 'is-empty': !isPrintLoading && !printItems.length }"
            >
              <div v-if="!isPrintLoading && printItems.length" class="label-print-modal__summary">
                <span class="label-print-modal__summary-label">{{ t('labelPrint.total') }}</span>
                <span class="label-print-modal__summary-value">{{ printListCount }}</span>
              </div>

              <div v-if="isPrintLoading" class="label-print__loading">
                {{ t('labelPrint.loading') }}
              </div>
              <div v-else-if="!printItems.length" class="label-print__empty">
                <img :src="emptyIllustration" alt="" />
                <p>{{ t('labelPrint.empty') }}</p>
              </div>
              <div v-else class="label-print__panels">
                <section v-for="section in printPanelsBySize" :key="section.size" class="label-print-section">
                  <h4 class="label-print-section__title">{{ section.title }}</h4>
                  <div class="label-print-section__panels">
                    <div
                      v-for="(panelItems, panelIndex) in section.panels"
                      :key="`${section.size}-${panelIndex}`"
                      class="label-print-panel"
                      :class="`label-print-panel--${section.size}`"
                    >
                      <div class="label-print-panel__grid" :class="`label-print-panel__grid--${section.size}`">
                        <article
                          v-for="item in panelItems"
                          :key="item.__panelCopyKey || item.id"
                          class="label-print-card"
                          :class="`label-print-card--${section.size}`"
                        >
                          <div class="label-print-card__header">
                            <div class="label-print-card__title">
                              <span class="label-print-card__code">{{ resolvePrintCodeLabel(item) }}</span>
                            </div>
                            <div class="label-print-card__actions">
                              <button type="button" @click="openEditModalForItem(item)" aria-label="Edit">
                                <svg viewBox="0 0 20 20" aria-hidden="true">
                                  <path
                                    fill-rule="evenodd"
                                    clip-rule="evenodd"
                                    d="M13.8836 3.83371L16.1669 6.11704C16.8052 6.72518 16.8313 7.73509 16.2253 8.37537L8.72525 15.8754C8.45361 16.1447 8.09758 16.3125 7.71692 16.3504L4.24192 16.667H4.16692C3.94542 16.6683 3.73252 16.5814 3.57525 16.4254C3.39945 16.2502 3.31086 16.0058 3.33358 15.7587L3.69192 12.2837C3.72984 11.903 3.89756 11.547 4.16692 11.2754L11.6669 3.77537C12.3134 3.22916 13.2667 3.25425 13.8836 3.83371ZM11.1003 6.66715L13.3336 8.90049L15.0003 7.27549L12.7253 5.00049L11.1003 6.66715Z"
                                    fill="#637381"
                                  />
                                </svg>
                              </button>
                              <button type="button" @click="handleDeletePrintItem(item)" aria-label="Delete">
                                <svg viewBox="0 0 20 20" aria-hidden="true">
                                  <path
                                    d="M15.5003 5.0005H13.3337V3.60883C13.3141 3.07535 13.0838 2.57138 12.6933 2.20741C12.3028 1.84344 11.7839 1.64916 11.2503 1.66716H8.75033C8.21684 1.64916 7.69794 1.84344 7.30737 2.20741C6.9168 2.57138 6.68654 3.07535 6.66699 3.60883V5.0005H4.50033C4.27932 5.0005 4.06735 5.0883 3.91107 5.24458C3.75479 5.40086 3.66699 5.61282 3.66699 5.83383C3.66699 6.05484 3.75479 6.26681 3.91107 6.42309C4.06735 6.57937 4.27932 6.66716 4.50033 6.66716H5.33366V15.8338C5.33366 16.4969 5.59705 17.1328 6.06588 17.6016C6.53472 18.0704 7.17062 18.3338 7.83366 18.3338H12.167C12.83 18.3338 13.4659 18.0704 13.9348 17.6016C14.4036 17.1328 14.667 16.4969 14.667 15.8338V6.66716H15.5003C15.7213 6.66716 15.9333 6.57937 16.0896 6.42309C16.2459 6.26681 16.3337 6.05484 16.3337 5.83383C16.3337 5.61282 16.2459 5.40086 16.0896 5.24458C15.9333 5.0883 15.7213 5.0005 15.5003 5.0005ZM8.33366 3.60883C8.33366 3.4755 8.50866 3.33383 8.75033 3.33383H11.2503C11.492 3.33383 11.667 3.4755 11.667 3.60883V5.0005H8.33366V3.60883ZM13.0003 15.8338C13.0003 16.0548 12.9125 16.2668 12.7562 16.4231C12.6 16.5794 12.388 16.6672 12.167 16.6672H7.83366C7.61265 16.6672 7.40068 16.5794 7.2444 16.4231C7.08812 16.2668 7.00033 16.0548 7.00033 15.8338V6.66716H13.0003V15.8338Z"
                                    fill="#637381"
                                  />
                                </svg>
                              </button>
                            </div>
                          </div>
                          <div class="label-print-card__preview">
                            <div class="label-preview" :class="`label-preview--${item.size}`">
                              <div class="label-preview__bar"></div>
                              <div class="label-preview__price">{{ resolvePrintPriceText(item) }}</div>
                              <div class="label-preview__body">
                                <div class="label-preview__producer">{{ resolvePrintProducer(item) }}</div>
                                <div class="label-preview__name">{{ resolvePrintName(item) }}</div>
                              </div>
                              <div v-if="item.size === 'small'" class="label-preview__meta">
                                <div>• {{ resolvePrintVintage(item) }}</div>
                                <div>• {{ resolvePrintRegion(item) || '-' }}</div>
                              </div>
                              <div v-else-if="item.size === 'medium'" class="label-preview__meta">
                                <div>• {{ resolvePrintRating(item) || '-' }}</div>
                                <div>• {{ resolvePrintVintage(item) }}</div>
                                <div>• {{ resolvePrintRegion(item) || '-' }}</div>
                              </div>
                              <div v-else class="label-preview__details">
                                <span class="label-preview__detail label-preview__detail--rating">
                                  {{ resolvePrintRating(item) || '-' }}
                                </span>
                                <div class="label-preview__details-group">
                                  <span class="label-preview__divider"></span>
                                  <span class="label-preview__detail label-preview__detail--vintage">
                                    {{ resolvePrintVintage(item) }}
                                  </span>
                                  <span class="label-preview__divider"></span>
                                  <span class="label-preview__detail label-preview__detail--region">
                                    {{ resolvePrintRegion(item) || '-' }}
                                  </span>
                                </div>
                              </div>
                              <div v-if="item.size === 'large'" class="label-preview__description">
                                {{ (item.description || '').slice(0, MAX_DESC) }}
                              </div>
                            </div>
                          </div>
                        </article>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            </section>
            <div v-if="printItems.length" class="label-print-modal__footer">
              <button class="label-button label-button--outline" type="button" @click="openResetConfirmModal">
                {{ t('labelPrint.reset') }}
              </button>
              <button class="label-button label-button--primary" type="button" @click="openPrintConfirmModal">
                {{ t('labelPrint.print') }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="isPrintConfirmModalOpen" class="label-confirm-modal">
          <div class="label-confirm-modal__backdrop" @click="closePrintConfirmModal"></div>
          <div class="label-confirm-modal__card" role="dialog" aria-modal="true">
            <header class="label-confirm-modal__header">
              <h3>{{ t('labelPrint.printConfirmTitle') }}</h3>
              <button class="label-confirm-modal__close" type="button" @click="closePrintConfirmModal">×</button>
            </header>
            <section class="label-confirm-modal__body">
              <div class="label-confirm-modal__section">
                <p class="label-confirm-modal__intro">{{ t('labelPrint.printConfirmIntro') }}</p>
                <ul class="label-confirm-modal__list label-confirm-modal__list--plain">
                  <li>{{ t('labelPrint.sizeCountSmall', { count: printLabelCountBySize.small }) }}</li>
                  <li>{{ t('labelPrint.sizeCountMedium', { count: printLabelCountBySize.medium }) }}</li>
                  <li>{{ t('labelPrint.sizeCountLarge', { count: printLabelCountBySize.large }) }}</li>
                </ul>
              </div>
              <div class="label-confirm-modal__section">
                <p class="label-confirm-modal__intro">{{ t('labelPrint.paperTitle') }}</p>
                <p class="label-confirm-modal__paper">
                  {{ t('labelPrint.paperRequired', { count: totalSheets }) }}
                </p>
              </div>
              <div class="label-confirm-modal__section">
                <p class="label-confirm-modal__intro">{{ t('labelPrint.preflightTitle') }}</p>
                <ul class="label-confirm-modal__list label-confirm-modal__checklist">
                  <li>{{ t('labelPrint.preflightPrinter') }}</li>
                  <li>{{ t('labelPrint.preflightPaper') }}</li>
                  <li>{{ t('labelPrint.preflightDirection') }}</li>
                </ul>
              </div>
              <p class="label-confirm-modal__hint">{{ t('labelPrint.printFinalHint') }}</p>
            </section>
            <footer class="label-confirm-modal__footer">
              <button class="label-button label-button--ghost" type="button" @click="closePrintConfirmModal">
                {{ t('labelSettings.editCancel') }}
              </button>
              <button class="label-button label-button--primary" type="button" :disabled="isPrinting" @click="startPrintFromModal">
                {{ t('labelPrint.startPrint') }}
              </button>
            </footer>
          </div>
        </div>

        <div v-if="isResetConfirmModalOpen" class="label-confirm-modal">
          <div class="label-confirm-modal__backdrop" @click="closeResetConfirmModal"></div>
          <div class="label-confirm-modal__card label-confirm-modal__card--reset" role="dialog" aria-modal="true">
            <header class="label-confirm-modal__header">
              <h3>{{ t('labelPrint.resetConfirmTitle') }}</h3>
              <button class="label-confirm-modal__close" type="button" @click="closeResetConfirmModal">×</button>
            </header>
            <section class="label-confirm-modal__body">
              <p class="label-confirm-modal__message">{{ t('labelPrint.resetConfirmMessage') }}</p>
            </section>
            <footer class="label-confirm-modal__footer">
              <button class="label-button label-button--ghost" type="button" @click="closeResetConfirmModal">
                {{ t('labelSettings.editCancel') }}
              </button>
              <button class="label-button label-button--primary" type="button" :disabled="isResettingPrintList" @click="confirmResetPrintList">
                {{ t('labelPrint.confirmReset') }}
              </button>
            </footer>
          </div>
        </div>

        <div v-if="isImportResultModalOpen" class="label-confirm-modal">
          <div class="label-confirm-modal__backdrop" @click="closeImportResultModal"></div>
          <div class="label-confirm-modal__card label-import-result-modal" role="dialog" aria-modal="true">
            <header class="label-confirm-modal__header">
              <h3>{{ t('labelSettings.importResultTitle') }}</h3>
              <button class="label-confirm-modal__close" type="button" @click="closeImportResultModal">×</button>
            </header>
            <section class="label-confirm-modal__body">
              <div class="label-confirm-modal__section">
                <p class="label-confirm-modal__intro">{{ t('labelSettings.importSummaryTitle') }}</p>
                <ul class="label-confirm-modal__list label-confirm-modal__list--plain">
                  <li>{{ t('labelSettings.importSummaryTotalRows') }}: {{ importResult?.total_rows || 0 }}</li>
                  <li>{{ t('labelSettings.importSummaryImported') }}: {{ importResult?.imported_rows || 0 }}</li>
                  <li>{{ t('labelSettings.importSummaryCreated') }}: {{ importResult?.created_items || 0 }}</li>
                  <li>{{ t('labelSettings.importSummaryMerged') }}: {{ importResult?.merged_rows || 0 }}</li>
                  <li>{{ t('labelSettings.importSummaryAddedQty') }}: {{ importResult?.added_quantity || 0 }}</li>
                  <li>{{ t('labelSettings.importSummaryErrors') }}: {{ importErrorRows.length }}</li>
                </ul>
              </div>
              <div class="label-confirm-modal__section">
                <p v-if="!importErrorRows.length" class="label-confirm-modal__message">
                  {{ t('labelSettings.importNoErrors') }}
                </p>
                <div v-else class="label-import-result-table">
                  <table>
                    <thead>
                      <tr>
                        <th>{{ t('labelSettings.importErrorTableRow') }}</th>
                        <th>{{ t('labelSettings.importErrorTableReason') }}</th>
                        <th>{{ t('labelSettings.importErrorTableMessage') }}</th>
                        <th>{{ t('labelSettings.importErrorTableValue') }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="entry in importErrorRows" :key="`${entry.row_number}-${entry.reason_code}`">
                        <td>{{ entry.row_number }}</td>
                        <td>{{ entry.reason_code }}</td>
                        <td>{{ entry.message }}</td>
                        <td>{{ formatImportRowValue(entry) || '-' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
            <footer class="label-confirm-modal__footer">
              <button
                v-if="importErrorRows.length"
                class="label-button label-button--outline"
                type="button"
                @click="downloadFailedRowsWorkbook"
              >
                {{ t('labelSettings.downloadFailedRows') }}
              </button>
              <button class="label-button label-button--primary" type="button" @click="closeImportResultModal">
                {{ t('labelSettings.closeImportResult') }}
              </button>
            </footer>
          </div>
        </div>

        <div v-if="isEditModalOpen" class="label-edit-modal">
          <div class="label-edit-modal__backdrop" @click="closeEditModal"></div>
          <div
            class="label-edit-modal__card"
            :class="{ 'label-edit-modal__card--price-only': editModalMode === 'priceOnly' }"
            role="dialog"
            aria-modal="true"
            :aria-label="t('labelSettings.editDialogTitle')"
          >
            <header class="label-edit-modal__header">
              <h3>{{ t('labelSettings.editDialogTitle') }}</h3>
              <button class="label-edit-modal__close" type="button" @click="closeEditModal">×</button>
            </header>
            <div class="label-edit-modal__divider"></div>
            <section
              class="label-edit-modal__body"
              :class="{ 'label-edit-modal__body--price-only': editModalMode === 'priceOnly' }"
            >
              <div class="label-edit-modal__field label-edit-modal__field--price">
                <label class="label-edit-modal__label">{{ t('labelSettings.priceLabel') }}</label>
                <div class="label-edit-modal__price">
                  <span class="label-edit-modal__currency">NT$</span>
                  <input
                    type="text"
                    v-model="editPrice"
                    :placeholder="t('labelSettings.editPlaceholder')"
                  />
                </div>
              </div>

              <div v-if="editModalMode === 'full'" class="label-edit-modal__field label-edit-modal__field--description">
                <label class="label-edit-modal__label">{{ t('labelSettings.descriptionLabel') }}</label>
                <div class="label-edit-modal__description-stack">
                  <div class="label-edit-modal__textarea">
                    <textarea readonly :value="editDescription"></textarea>
                    <div class="label-edit-modal__counter">{{ editDescription.length }}/{{ MAX_DESC }}</div>
                  </div>
                  <div class="label-edit-modal__chat">
                    <input
                      type="text"
                      v-model="editInstruction"
                      :placeholder="t('labelSettings.editInstructionPlaceholder')"
                    />
                    <button
                      type="button"
                      class="label-edit-modal__send"
                      :disabled="!editInstruction.trim() || isRegenerating"
                      @click="handleRegenerate"
                    >
                      <span v-if="isRegenerating" class="label-edit-modal__send-spinner" aria-hidden="true"></span>
                      <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                        <path
                          d="M4 4L20 12L4 20L8 12L4 4Z"
                          fill="currentColor"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </section>
            <div class="label-edit-modal__divider"></div>
            <footer class="label-edit-modal__footer">
              <button class="label-button label-button--ghost" type="button" @click="closeEditModal">
                {{ t('labelSettings.editCancel') }}
              </button>
              <button
                class="label-button label-button--primary"
                type="button"
                :disabled="isSaving"
                @click="handleConfirmEdit"
              >
                {{ t('labelSettings.editConfirm') }}
              </button>
            </footer>
          </div>
        </div>

        <div v-if="showSnackbar" class="label-snackbar" role="status">
          <span class="label-snackbar__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path
                fill-rule="evenodd"
                clip-rule="evenodd"
                d="M2 12C2 6.47715 6.47715 2 12 2C14.6522 2 17.1957 3.05357 19.0711 4.92893C20.9464 6.8043 22 9.34784 22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12ZM11.73 15.61L16.3 9.61V9.58C16.5179 9.29419 16.5668 8.91382 16.4283 8.58218C16.2897 8.25054 15.9848 8.01801 15.6283 7.97218C15.2718 7.92635 14.9179 8.07419 14.7 8.36L10.92 13.36L9.29 11.28C9.07028 10.9978 8.71668 10.8542 8.36239 10.9033C8.00811 10.9525 7.70696 11.1869 7.57239 11.5183C7.43783 11.8497 7.49028 12.2278 7.71 12.51L10.15 15.62C10.3408 15.8615 10.6322 16.0017 10.94 16C11.2495 15.9993 11.5412 15.8552 11.73 15.61Z"
                fill="#36B37E"
              />
            </svg>
          </span>
          <span class="label-snackbar__text">{{ snackbarMessage }}</span>
        </div>

        <button
          class="label-fab"
          type="button"
          aria-label="Print"
          :disabled="!isAuthenticated"
          @click="handleFabClick"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M19.36 7H18V5C18.0217 4.49233 17.8413 3.99675 17.4983 3.62186C17.1553 3.24698 16.6776 3.02335 16.17 3H7.83002C7.32242 3.02335 6.84478 3.24698 6.50175 3.62186C6.15873 3.99675 5.97831 4.49233 6.00002 5V7H4.64002C3.93628 7.00529 3.26331 7.28924 2.7685 7.78968C2.27369 8.29011 1.99735 8.96625 2.00002 9.67V16.33C1.99735 17.0338 2.27369 17.7099 2.7685 18.2103C3.26331 18.7108 3.93628 18.9947 4.64002 19H5.50002C5.50002 19.5304 5.71073 20.0391 6.08581 20.4142C6.46088 20.7893 6.96959 21 7.50002 21H16.5C17.0305 21 17.5392 20.7893 17.9142 20.4142C18.2893 20.0391 18.5 19.5304 18.5 19H19.36C20.0638 18.9947 20.7367 18.7108 21.2315 18.2103C21.7264 17.7099 22.0027 17.0338 22 16.33V9.67C22.0027 8.96625 21.7264 8.29011 21.2315 7.78968C20.7367 7.28924 20.0638 7.00529 19.36 7ZM8.00002 5H16V7H8.00002V5ZM7.50002 19V15H16.5V19H7.50002Z"
            />
          </svg>
          <span v-if="printListCount > 0" class="label-fab__badge">{{ printListCount }}</span>
        </button>
      </main>
    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Public+Sans:wght@400;600;700&display=swap');

.label-settings-stage {
  max-width: 100%;
  width: 100%;
  padding: 32px 40px 80px;
  gap: 24px;
  font-family: 'Public Sans', 'Noto Sans TC', sans-serif;
  --label-grid-width: calc(304px + 390px + 600px + 40px);
  --label-content-width: calc(var(--label-grid-width) + 50px);
}

.label-settings__content {
  width: var(--label-content-width);
  max-width: 100%;
  align-self: center;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.label-settings__header h1 {
  margin: 0;
  font-size: 24px;
  line-height: 36px;
  font-weight: 700;
  color: #212b36;
}

.label-card {
  background: #ffffff;
  box-shadow: 0 6px 14px -4px rgba(145, 158, 171, 0.1), 0 0 2px rgba(145, 158, 171, 0.18);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
}

.label-card--s1 {
  padding: 24px;
}

.label-card--s2 {
  padding: 24px;
  gap: 22px;
  min-height: 616px;
}

.label-card__header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.label-chip {
  height: 24px;
  padding: 3px 6px;
  background: #55b77f;
  border: 1px solid #55b77f;
  border-radius: 50px;
  color: #ffffff;
  font-size: 13px;
  line-height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 59px;
}

.label-category {
  font-size: 16px;
  line-height: 24px;
  font-weight: 600;
  color: #212b36;
}

.label-card__row {
  display: flex;
  align-items: center;
  gap: 16px 24px;
}

.label-search {
  flex: 1 1 320px;
  max-width: 714px;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 14px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  background: #ffffff;
  position: relative;
}

.label-search__icon {
  width: 24px;
  height: 24px;
  color: #919eab;
}

.label-search input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 16px;
  line-height: 24px;
  color: #212b36;
  width: 100%;
  flex: 1;
  padding-right: 28px;
}

.label-search input::placeholder {
  color: #919eab;
}

.label-search__clear {
  border: none;
  background: transparent;
  color: #919eab;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}

.label-search__submit {
  display: inline-grid;
  width: 30px;
  height: 30px;
  place-items: center;
  flex: 0 0 auto;
  border: 0;
  border-radius: 8px;
  background: #e7f2eb;
  color: #1c6a43;
  cursor: pointer;
}

.label-search__submit:disabled { opacity: .45; cursor: not-allowed; }
.label-search__submit svg { width: 17px; height: 17px; }

.label-search__dropdown {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  background: #ffffff;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: var(--ys-control-radius, 6px);
  box-shadow: 0 8px 22px -8px rgba(145, 158, 171, 0.22);
  padding: 8px 0;
  z-index: 20;
  max-height: 280px;
  overflow-y: auto;
}

.label-search__option {
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
}

.label-search__option:hover,
.label-search__option.is-selected {
  background: rgba(145, 158, 171, 0.08);
}

.label-search__option-title {
  font-size: 14px;
  line-height: 20px;
  font-weight: 600;
  color: #212b36;
}

.label-search__option-sub {
  font-size: 12px;
  line-height: 18px;
  color: #637381;
}

.label-search__status {
  padding: 12px 16px;
  font-size: 13px;
  line-height: 20px;
  color: #919eab;
}

.label-search__status--error { color: #b42318; }

.label-card__footer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: flex-end;
  margin-left: auto;
}

.label-import-input {
  display: none;
}

.label-button {
  height: 36px;
  padding: 6px 16px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 14px;
  line-height: 24px;
  font-weight: 600;
  background: transparent;
  color: #212b36;
}

.label-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.label-button--outline {
  border: 1px solid rgba(145, 158, 171, 0.32);
  background: #ffffff;
  font-weight: 400;
}

.label-button--primary {
  width: 138px;
  background: #55b77f;
  color: #ffffff;
  font-weight: 700;
}

.label-button--link {
  min-width: 140px;
  width: auto;
  padding: 6px 8px;
  color: #1939b7;
  font-weight: 400;
  white-space: nowrap;
}

.label-size-grid {
  display: inline-flex;
  align-items: flex-start;
  gap: 20px;
  flex-wrap: wrap;
  width: fit-content;
  max-width: 100%;
  align-self: flex-start;
}

.label-card--s2 .label-card__actions {
  display: flex;
  gap: 12px;
  margin-top: auto;
  align-self: flex-end;
}

.label-size {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.label-size--small {
  width: 304px;
}

.label-size--medium {
  width: 390px;
}

.label-size--large {
  width: 600px;
}

.label-radio {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.label-radio__icon {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  color: #637381;
  padding: 8px;
  border: none;
  background: transparent;
  cursor: pointer;
}

.label-radio__icon svg {
  width: 24px;
  height: 24px;
}

.label-radio__icon.is-selected {
  color: #55b77f;
}

.label-radio__icon .radio-dot {
  fill: #55b77f;
}

.label-button--outline:disabled {
  border-color: rgba(145, 158, 171, 0.32);
  color: rgba(145, 158, 171, 0.8);
  cursor: not-allowed;
  background: #ffffff;
}

.label-size__preview {
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(145, 158, 171, 0.08);
  border: 1px dashed rgba(145, 158, 171, 0.48);
  color: #919eab;
  position: relative;
  overflow: hidden;
}

.label-size__preview.has-preview {
  background: #ffffff;
  color: #102d47;
}

.label-preview {
  position: relative;
  width: 100%;
  height: 100%;
  padding: 20px;
  font-family: 'Inter', 'Noto Sans TC', sans-serif;
  color: #102d47;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.label-preview__bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 6px;
  background: #55b77f;
}

.label-preview__body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 75%;
}

.label-preview__producer {
  font-size: 19px;
  font-weight: 700;
  line-height: 23px;
}

.label-preview__name {
  font-size: 14px;
  line-height: 19px;
  font-weight: 400;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.label-preview__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 15px;
  line-height: 20px;
  margin-top: auto;
}

.label-preview__price {
  position: absolute;
  right: 20px;
  bottom: 20px;
  font-weight: 700;
  font-size: 20px;
  line-height: 24px;
  text-align: right;
  letter-spacing: -0.5px;
}

.label-preview--medium .label-preview__producer,
.label-preview--large .label-preview__producer {
  font-size: 23px;
  line-height: 28px;
}

.label-preview--medium .label-preview__name,
.label-preview--large .label-preview__name {
  font-size: 17px;
  line-height: 24px;
}

.label-preview--medium .label-preview__price {
  font-size: 22px;
  line-height: 27px;
  right: 22px;
  bottom: 24px;
}

.label-preview--large {
  gap: 20px;
  padding: 24px;
}

.label-preview--large .label-preview__price {
  top: 24px;
  right: 24px;
  bottom: auto;
  font-size: 24px;
  line-height: 29px;
}

.label-preview--large .label-preview__body {
  max-width: 70%;
}

.label-preview__details {
  display: flex;
  align-items: center;
  gap: 16px;
  border-top: 2px solid #102d47;
  border-bottom: 2px solid #102d47;
  padding: 12px 0;
  font-weight: 700;
  font-size: 15px;
  line-height: 20px;
}

.label-preview__details-group {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-left: auto;
}

.label-preview__detail {
  white-space: nowrap;
}

.label-preview__detail--vintage,
.label-preview__detail--region {
  width: 141px;
  flex: 0 0 141px;
}

.label-preview__divider {
  width: 1px;
  height: 16px;
  background: rgba(22, 62, 97, 0.32);
}

.label-preview__description {
  font-size: 16px;
  line-height: 26px;
  font-weight: 400;
  white-space: pre-line;
}

.label-size--small .label-size__preview {
  height: 206px;
}

.label-size--medium .label-size__preview {
  height: 278px;
}

.label-size--large .label-size__preview {
  height: 402px;
}

.label-size__text {
  text-align: center;
}

.label-size__value {
  font-size: 32px;
  line-height: 48px;
  font-weight: 700;
}

.label-size__desc {
  font-size: 14px;
  line-height: 22px;
}

.label-fab {
  position: fixed;
  right: 48px;
  bottom: 32px;
  width: 56px;
  height: 56px;
  border-radius: 50px;
  background: #55b77f;
  border: none;
  box-shadow: 0 4px 10px rgba(85, 183, 127, 0.2);
  display: grid;
  place-items: center;
  padding: 0;
}

.label-fab svg {
  width: 24px;
  height: 24px;
  fill: #ffffff;
}

.label-fab__badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: #212b36;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  line-height: 20px;
  text-align: center;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.label-snackbar {
  position: fixed;
  right: 120px;
  bottom: 32px;
  width: 296px;
  height: 64px;
  background: #212b36;
  border-radius: 8px;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.13);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  color: #ffffff;
  font-size: 14px;
  line-height: 22px;
  z-index: 1900;
}

.label-snackbar__icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(54, 183, 126, 0.16);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.label-snackbar__icon svg {
  width: 24px;
  height: 24px;
}

.label-snackbar__text {
  font-weight: 600;
}

.label-print-modal {
  position: fixed;
  inset: 0;
  z-index: 1800;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Public Sans', 'Noto Sans TC', sans-serif;
}

.label-print-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(33, 43, 54, 0.8);
}

.label-print-modal__card {
  position: relative;
  width: calc(100vw - 24px);
  height: calc(100vh - 24px);
  max-width: none;
  max-height: calc(100vh - 24px);
  background: #ffffff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 1;
}

.label-print-modal__header {
  height: 76px;
  display: flex;
  align-items: center;
  padding: 18px 8px 18px 24px;
  gap: 12px;
}

.label-print-modal__header h3 {
  margin: 0;
  font-size: 18px;
  line-height: 28px;
  font-weight: 700;
  color: #212b36;
  flex: 1;
}

.label-print-modal__close {
  width: 40px;
  height: 40px;
  border-radius: 50px;
  border: none;
  background: transparent;
  color: #637381;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
}

.label-print-modal__divider {
  height: 0;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  width: 100%;
}

.label-print-modal__body {
  flex: 1;
  min-height: 0;
  padding: 24px 40px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow: auto;
}

.label-print-modal__body.is-empty {
  align-items: center;
  justify-content: center;
}

.label-print-modal__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  line-height: 22px;
  color: #637381;
}

.label-print-modal__summary-value {
  font-weight: 700;
  color: #212b36;
}

.label-print__loading {
  font-size: 14px;
  color: #637381;
}

.label-print__empty {
  min-height: 0;
  background: transparent;
  border-radius: 0;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #919eab;
  text-align: center;
}

.label-print__empty img {
  width: 220px;
  height: auto;
}

.label-print__panels {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.label-print-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.label-print-section__title {
  margin: 0;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
  font-weight: 700;
}

.label-print-section__panels {
  display: flex;
  flex-direction: column;
  gap: 20px;
  align-items: center;
}

.label-print-panel {
  width: 100%;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 6px 14px -4px rgba(145, 158, 171, 0.1), 0 0 2px rgba(145, 158, 171, 0.18);
  padding: 16px;
  display: flex;
  justify-content: center;
}

.label-print-panel__grid {
  display: grid;
  gap: 20px;
  align-items: start;
  justify-content: center;
  justify-items: center;
}

.label-print-panel__grid--small {
  grid-template-columns: repeat(4, 304px);
}

.label-print-panel__grid--medium {
  grid-template-columns: repeat(2, 390px);
}

.label-print-panel__grid--large {
  grid-template-columns: repeat(2, 600px);
}

.label-print-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: transparent;
  border-radius: 0;
  padding: 0;
  box-shadow: none;
}

.label-print-card--small {
  width: 304px;
}

.label-print-card--medium {
  width: 390px;
}

.label-print-card--large {
  width: 600px;
}

.label-print-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 22px;
}

.label-print-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.label-print-card__code {
  color: #637381;
  font-size: 12px;
  line-height: 20px;
  font-weight: 700;
}

.label-print-card__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.label-print-card__actions button {
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
}

.label-print-card__actions svg {
  width: 20px;
  height: 20px;
}

.label-print-card__preview {
  display: flex;
  align-items: flex-start;
}

.label-print-card__preview .label-preview {
  border: 1px dashed rgba(145, 158, 171, 0.48);
  margin: 0;
  background: #ffffff;
  color: #102d47;
  font-family: 'Inter', 'Noto Sans TC', sans-serif;
}

.label-print-card__preview .label-preview__bar {
  height: 6px;
}

.label-print-card__preview .label-preview__body {
  gap: 6px;
}

.label-print-card__preview .label-preview__producer {
  font-weight: 700;
  color: #102d47;
}

.label-print-card__preview .label-preview__name {
  font-weight: 400;
  color: #102d47;
}

.label-print-card__preview .label-preview__meta {
  margin-top: 0;
  position: absolute;
  font-size: 15px;
  line-height: 20px;
  gap: 2px;
}

.label-print-card__preview .label-preview__price {
  letter-spacing: -0.5px;
  color: #102d47;
}

.label-print-card__preview .label-preview--small {
  width: 304px;
  height: 206px;
  padding: 26px 20px 20px;
  gap: 6px;
}

.label-print-card__preview .label-preview--small .label-preview__body {
  width: 264px;
  max-width: 264px;
}

.label-print-card__preview .label-preview--small .label-preview__producer {
  font-size: 24px;
  line-height: 29px;
}

.label-print-card__preview .label-preview--small .label-preview__name {
  font-size: 17px;
  line-height: 24px;
  -webkit-line-clamp: 2;
}

.label-print-card__preview .label-preview--small .label-preview__meta {
  left: 20px;
  bottom: 20px;
  width: 154px;
}

.label-print-card__preview .label-preview--small .label-preview__price {
  right: 20px;
  bottom: 20px;
  font-size: 20px;
  line-height: 24px;
}

.label-print-card__preview .label-preview--medium {
  width: 390px;
  height: 278px;
  padding: 28px 24px 24px;
  gap: 6px;
}

.label-print-card__preview .label-preview--medium .label-preview__body {
  width: 342px;
  max-width: 342px;
}

.label-print-card__preview .label-preview--medium .label-preview__producer {
  font-size: 26px;
  line-height: 31px;
}

.label-print-card__preview .label-preview--medium .label-preview__name {
  font-size: 19px;
  line-height: 26px;
  -webkit-line-clamp: 2;
}

.label-print-card__preview .label-preview--medium .label-preview__meta {
  left: 24px;
  bottom: 24px;
  width: 154px;
}

.label-print-card__preview .label-preview--medium .label-preview__price {
  right: 22px;
  bottom: 24px;
  font-size: 22px;
  line-height: 27px;
}

.label-print-card__preview .label-preview--large {
  width: 600px;
  height: 402px;
  padding: 28px 24px 24px;
  gap: 20px;
}

.label-print-card__preview .label-preview--large .label-preview__body {
  width: 552px;
  max-width: 552px;
}

.label-print-card__preview .label-preview--large .label-preview__producer {
  font-size: 26px;
  line-height: 31px;
}

.label-print-card__preview .label-preview--large .label-preview__name {
  font-size: 19px;
  line-height: 26px;
  -webkit-line-clamp: 2;
}

.label-print-card__preview .label-preview--large .label-preview__price {
  top: 24px;
  right: 24px;
  bottom: auto;
  font-size: 24px;
  line-height: 29px;
}

.label-print-card__preview .label-preview--large .label-preview__details {
  height: 52px;
  padding: 16px 0;
  gap: 16px;
  font-size: 15px;
  line-height: 20px;
}

.label-print-card__preview .label-preview--large .label-preview__detail--rating {
  min-width: 0;
  flex: 1;
}

.label-print-card__preview .label-preview--large .label-preview__detail--vintage {
  width: 60px;
  flex: 0 0 60px;
}

.label-print-card__preview .label-preview--large .label-preview__detail--region {
  width: 72px;
  flex: 0 0 72px;
}

.label-print-card__preview .label-preview--large .label-preview__description {
  font-size: 16px;
  line-height: 26px;
  max-height: 156px;
  overflow: hidden;
}

.label-preview--small {
  width: 304px;
  height: 206px;
}

.label-preview--medium {
  width: 390px;
  height: 278px;
}

.label-preview--large {
  width: 600px;
  height: 402px;
}

.label-print-modal__footer {
  height: 68px;
  padding: 16px 40px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  background: #ffffff;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.label-confirm-modal {
  position: fixed;
  inset: 0;
  z-index: 1900;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Public Sans', 'Noto Sans TC', sans-serif;
}

.label-confirm-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(33, 43, 54, 0.8);
}

.label-confirm-modal__card {
  position: relative;
  width: min(760px, calc(100vw - 32px));
  background: #ffffff;
  border-radius: 24px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  z-index: 1;
  display: flex;
  flex-direction: column;
}

.label-confirm-modal__card--reset {
  width: min(1120px, calc(100vw - 32px));
}

.label-import-result-modal {
  width: min(920px, calc(100vw - 32px));
}

.label-confirm-modal__header {
  min-height: 88px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 26px 16px 18px 48px;
}

.label-confirm-modal__header h3 {
  margin: 0;
  color: #263847;
  font-size: 36px;
  line-height: 1.2;
  font-weight: 700;
  flex: 1;
}

.label-confirm-modal__close {
  width: 40px;
  height: 40px;
  border: none;
  background: transparent;
  color: #637381;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.label-confirm-modal__body {
  padding: 8px 48px 16px;
  color: #637381;
}

.label-confirm-modal__section {
  margin-bottom: 16px;
}

.label-confirm-modal__intro {
  margin: 0 0 6px;
  font-size: 16px;
  line-height: 1.6;
  font-weight: 700;
}

.label-confirm-modal__list {
  margin: 0;
  font-size: 18px;
  line-height: 1.7;
  font-weight: 500;
}

.label-confirm-modal__list--plain {
  list-style: none;
  padding-left: 0;
}

.label-confirm-modal__checklist {
  list-style: none;
  padding-left: 0;
}

.label-confirm-modal__paper {
  margin: 0;
  font-size: 18px;
  line-height: 1.6;
  font-weight: 700;
}

.label-confirm-modal__hint {
  margin: 6px 0 0;
  font-size: 18px;
  line-height: 1.6;
  font-weight: 700;
  color: #637381;
}

.label-confirm-modal__message {
  margin: 0;
  color: #637381;
  font-size: 18px;
  line-height: 1.7;
  font-weight: 500;
}

.label-confirm-modal__footer {
  display: flex;
  justify-content: flex-end;
  gap: 20px;
  padding: 24px 48px 40px;
}

.label-confirm-modal__footer .label-button {
  min-width: 140px;
  height: 44px;
  border-radius: 12px;
  font-size: 16px;
  line-height: 1;
  font-weight: 700;
}

.label-confirm-modal__footer .label-button--ghost {
  border: 1px solid rgba(145, 158, 171, 0.32);
  background: #ffffff;
  color: #263847;
}

.label-import-result-table {
  width: 100%;
  overflow-x: auto;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: var(--ys-control-radius, 6px);
}

.label-import-result-table table {
  width: 100%;
  min-width: 680px;
  border-collapse: collapse;
}

.label-import-result-table th,
.label-import-result-table td {
  padding: 12px 14px;
  font-size: 13px;
  line-height: 20px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid rgba(145, 158, 171, 0.16);
}

.label-import-result-table th {
  background: #f8fafc;
  color: #44546f;
  font-weight: 700;
}

.label-import-result-table tbody tr:last-child td {
  border-bottom: none;
}

.label-edit-modal {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Public Sans', 'Noto Sans TC', sans-serif;
}

.label-edit-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(33, 43, 54, 0.8);
}

.label-edit-modal__card {
  position: relative;
  width: 720px;
  height: 562px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  z-index: 1;
}

.label-edit-modal__card--price-only {
  width: 480px;
  height: 274px;
}

.label-edit-modal__header {
  height: 76px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 8px 18px 24px;
}

.label-edit-modal__header h3 {
  margin: 0;
  font-size: 18px;
  line-height: 28px;
  font-weight: 700;
  color: #212b36;
  flex: 1;
}

.label-edit-modal__close {
  width: 40px;
  height: 40px;
  border-radius: 50px;
  border: none;
  background: transparent;
  color: #637381;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
}

.label-edit-modal__divider {
  height: 0;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  width: 100%;
}

.label-edit-modal__body {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  height: 402px;
  flex: 0 0 402px;
}

.label-edit-modal__body--price-only {
  gap: 0;
  height: auto;
  flex: 1;
}

.label-edit-modal__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.label-edit-modal__field--price {
  width: 324px;
}

.label-edit-modal__field--description {
  width: 672px;
}

.label-edit-modal__description-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.label-edit-modal__label {
  font-size: 14px;
  line-height: 22px;
  font-weight: 400;
  color: #637381;
}

.label-edit-modal__price {
  width: 324px;
  height: 40px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: 8px;
  padding: 8px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
}

.label-edit-modal__currency {
  padding-right: 8px;
  border-right: 1px solid rgba(145, 158, 171, 0.32);
  font-size: 16px;
  line-height: 24px;
  color: #919eab;
}

.label-edit-modal__price input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 16px;
  line-height: 24px;
  color: #212b36;
  flex: 1;
  min-width: 0;
}

.label-edit-modal__price input::placeholder {
  color: #919eab;
}

.label-edit-modal__textarea {
  width: 672px;
  height: 178px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px) var(--ys-control-radius, 6px) 0 0;
  padding: 16px 14px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  background: #ffffff;
}

.label-edit-modal__textarea textarea {
  width: 100%;
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-family: 'Public Sans', 'Noto Sans TC', sans-serif;
  font-size: 16px;
  line-height: 24px;
  color: #212b36;
}

.label-edit-modal__counter {
  font-size: 14px;
  line-height: 22px;
  color: #919eab;
}

.label-edit-modal__chat {
  width: 672px;
  height: 60px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-top: none;
  border-radius: 0 0 var(--ys-control-radius, 6px) var(--ys-control-radius, 6px);
  background: #f4f6f8;
  padding: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.label-edit-modal__chat input {
  flex: 1;
  height: 40px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  padding: 8px 0 8px 20px;
  font-size: 16px;
  line-height: 24px;
  color: #212b36;
  background: #ffffff;
  min-width: 0;
}

.label-edit-modal__chat input::placeholder {
  color: #919eab;
}

.label-edit-modal__send {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 45px;
  background: rgba(145, 158, 171, 0.24);
  color: rgba(145, 158, 171, 0.8);
  display: grid;
  place-items: center;
  padding: 0;
}

.label-edit-modal__send svg {
  width: 22px;
  height: 22px;
}

.label-edit-modal__send-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid rgba(145, 158, 171, 0.4);
  border-top-color: rgba(145, 158, 171, 0.9);
  border-radius: 50%;
  animation: label-edit-spin 0.8s linear infinite;
}

.label-edit-modal__send:disabled {
  cursor: not-allowed;
}

.label-edit-modal__footer {
  height: 84px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 24px;
  gap: 12px;
}

.label-edit-modal__card--price-only .label-edit-modal__footer {
  height: auto;
  padding: 16px 24px 24px;
}

.label-edit-modal__footer .label-button {
  height: 36px;
  min-width: 60px;
  padding: 6px 16px;
  border-radius: 8px;
  font-weight: 700;
}

.label-edit-modal__footer .label-button--ghost {
  border: 1px solid rgba(145, 158, 171, 0.32);
  background: #ffffff;
  color: #212b36;
  width: 80px;
}

.label-edit-modal__footer .label-button--primary {
  width: 80px;
}

@keyframes label-edit-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1700px) {
  .label-print-panel__grid--small {
    grid-template-columns: repeat(3, 304px);
  }
}

@media (max-width: 1500px) {
  .label-print-panel__grid--large {
    grid-template-columns: repeat(1, 600px);
  }
}

@media (max-width: 1360px) {
  .label-print-panel__grid--small {
    grid-template-columns: repeat(2, 304px);
  }

  .label-print-panel__grid--medium {
    grid-template-columns: repeat(1, 390px);
  }
}

@media (max-width: 900px) {
  .label-settings__content {
    width: 100%;
  }

  .label-size--small,
  .label-size--medium,
  .label-size--large {
    width: 100%;
  }

  .label-size--small .label-size__preview,
  .label-size--medium .label-size__preview,
  .label-size--large .label-size__preview {
    height: 220px;
  }

  .label-print-modal__card {
    width: calc(100vw - 24px);
    height: calc(100vh - 24px);
    max-height: calc(100vh - 24px);
  }

  .label-print-modal__body {
    padding: 20px;
  }

  .label-print-panel {
    padding: 12px;
  }

  .label-print-panel__grid--small,
  .label-print-panel__grid--medium,
  .label-print-panel__grid--large {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }

  .label-print-card--small,
  .label-print-card--medium,
  .label-print-card--large {
    width: 100%;
  }

  .label-print-card__preview .label-preview {
    width: 100%;
    height: auto;
    min-height: 206px;
  }

  .label-print-card__preview .label-preview--medium {
    min-height: 278px;
  }

  .label-print-card__preview .label-preview--large {
    min-height: 402px;
  }

  .label-print-modal__footer {
    padding: 12px 20px;
  }

  .label-confirm-modal__card,
  .label-confirm-modal__card--reset {
    width: calc(100vw - 20px);
    border-radius: 16px;
  }

  .label-confirm-modal__header {
    padding: 20px 12px 16px 20px;
    min-height: 64px;
  }

  .label-confirm-modal__header h3 {
    font-size: 24px;
  }

  .label-confirm-modal__body {
    padding: 8px 20px 12px;
  }

  .label-confirm-modal__list,
  .label-confirm-modal__paper,
  .label-confirm-modal__message {
    font-size: 15px;
  }

  .label-confirm-modal__footer {
    padding: 16px 20px 20px;
    gap: 10px;
  }
}

@media (max-width: 720px) {
  .label-settings-stage { padding: 20px 12px 72px; }
  .label-card { border: 1px solid #dbe7df; border-radius: 14px; }
  .label-card__row { align-items: stretch; flex-direction: column; }
  .label-search { max-width: none; width: 100%; flex-basis: auto; }
  .label-card__footer-actions { width: 100%; margin-left: 0; justify-content: stretch; }
  .label-card__footer-actions .label-button { flex: 1; }
  .label-search__dropdown { max-height: min(280px, 45vh); }
}
</style>
