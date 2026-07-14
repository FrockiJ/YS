<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import * as XLSX from 'xlsx'
import { useAuth } from '../composables/useAuth'
import EdmSharedFlow from '../components/EdmSharedFlow.vue'
import {
  createEdmPreview,
  fetchEdmPreview,
  shareEdmPreviewEmail,
  updateEdmPreview,
} from '../services/ysApi'
import { writeClipboard } from '../utils/clipboard'
import { formatUsdPrice } from '../utils/currency'
import {
  buildCerpPricingState,
  DEFAULT_EDM_QUOTE_TIER,
  EDM_QUOTE_TIERS,
  isBundleDiscountEnabled,
  isElevenPlusOneBundle,
  normalizeEdmQuoteTier,
  resolveBundleDiscountType,
  resolveCerpBundle,
  resolveCerpBundleDisplay,
  resolveCerpCode,
  resolveCerpColor,
  resolveCerpProductName,
  resolveCerpProducer,
  resolveCerpRating,
  resolveCerpStock,
  resolveCerpVintage,
  resolveEdmQuotePriceForTier,
  toNullableNumber,
} from '../utils/cerpFields'
import bannerLogo from '../assets/ysLogo_transparent.png'
import glassWhite from '../assets/placeholder.png'
import glassRed from '../assets/placeholder.png'
import glassRose from '../assets/placeholder.png'
import iconCopy from '../assets/ic-copy.svg'
import iconExport from '../assets/edm_export.svg'
import iconLink from '../assets/edm_linkshape.svg'

const EDM_ITEMS_KEY = 'ys-edm-items'
const EDM_CONTEXT_KEY = 'ys-edm-context'
const EDM_PREVIEW_STATE_KEY = 'ys-edm-preview-state'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { userProfile } = useAuth()

const isLoading = ref(true)
const loadError = ref('')
const previewState = ref(null)
const isShareDialogOpen = ref(false)
const shareRecipients = ref([])
const shareInput = ref('')
const shareError = ref('')
const isSubmittingShare = ref(false)
const isSnackbarVisible = ref(false)
const snackbarMessageKey = ref('edm.snackbar.share_sent')
const shareInputRef = ref(null)

let snackbarTimer = 0

const isPublicShareView = computed(() => Boolean(route.params.shareToken))
const previewRows = computed(() => {
  if (!Array.isArray(previewState.value?.rows)) return []
  return previewState.value.rows
})
const shareUrl = computed(() => previewState.value?.share_url || '')
const shareToken = computed(() => previewState.value?.share_token || '')
const quoteNumber = computed(() => previewState.value?.quote_no || previewState.value?.banner?.quote_no || '')
const quoteDate = computed(
  () => previewState.value?.banner?.quote_date || previewState.value?.quote_date || ''
)
const salesRep = computed(
  () => previewState.value?.banner?.sales || previewState.value?.sales_rep || ''
)
const heroText = computed(() => previewState.value?.hero_text || '')
const canExport = computed(() => !isPublicShareView.value && previewRows.value.length > 0)
const canShare = computed(
  () => !isPublicShareView.value && previewRows.value.length > 0 && Boolean(shareToken.value)
)
const canSendShare = computed(
  () => (shareRecipients.value.length > 0 || Boolean(shareInput.value.trim())) && !isSubmittingShare.value
)
const canEditEdmPreview = computed(() => !isPublicShareView.value && !previewState.value?.read_only)
const showQuoteTierColumn = false
const showEmptyState = computed(
  () => !isLoading.value && !loadError.value && previewRows.value.length === 0
)
const tableColumns = computed(() => {
  const columns = [
    { key: 'no', label: t('edm.table.columns.no') },
    { key: 'vintage', label: t('edm.table.columns.vintage') },
    { key: 'producer', label: t('edm.table.columns.producer') },
    { key: 'product', label: t('edm.table.columns.product') },
    { key: 'color', label: t('edm.table.columns.color') },
    { key: 'rating', label: t('edm.table.columns.rating') },
    { key: 'list_price', label: t('edm.table.columns.list_price') },
    { key: 'quote_price', label: t('edm.table.columns.quote_price') },
    { key: 'bundle', label: t('edm.table.columns.bundle') },
  ]
  if (showQuoteTierColumn) {
    columns.push({ key: 'quote_tier_action', label: t('edm.table.columns.quote_action') })
  }
  return columns
})

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const colorIcons = {
  white: glassWhite,
  rose: glassRose,
  red: glassRed,
}

const readStorage = (storage, key, fallback) => {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = storage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return parsed ?? fallback
  } catch {
    return fallback
  }
}

const writePreviewCache = (payload) => {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(EDM_PREVIEW_STATE_KEY, JSON.stringify(payload))
}

const clearPreviewCache = () => {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(EDM_PREVIEW_STATE_KEY)
}

const normalizeNumber = (value) => {
  return toNullableNumber(value)
}

const normalizeStock = (value) => {
  if (value === null || value === undefined || value === '') return null
  const direct = Number(value)
  if (Number.isFinite(direct)) return direct
  const match = String(value).match(/-?\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : null
}

const getQuoteTierLabel = (tier) => {
  const normalizedTier = normalizeEdmQuoteTier(tier)
  if (normalizedTier === 'wholesale') return t('edm.quote_tiers.wholesale')
  return t(`edm.quote_tiers.${normalizedTier}`)
}

const getBundleDiscountLabel = (row = {}) => {
  if (!isElevenPlusOneBundle(row)) return resolveCerpBundleDisplay(row)
  return isBundleDiscountEnabled(row)
    ? t('edm.bundle.enabled_11_plus_1')
    : t('edm.bundle.disabled_11_plus_1')
}

const getBundleDiscountStatusText = (row = {}) => {
  if (!isElevenPlusOneBundle(row)) return resolveCerpBundleDisplay(row)
  return `${resolveCerpBundleDisplay(row, '11+1')} ${getBundleDiscountLabel(row)}`
}

const getBundleDiscountAriaLabel = (row = {}) =>
  t('edm.bundle.toggle_aria', {
    product: row.product || row.no || '',
    state: getBundleDiscountLabel(row),
  })

const serializePreviewRow = (row = {}) => ({
  id: String(row.id || resolveCerpCode(row, '')),
  no: resolveCerpCode(row, ''),
  vintage: resolveCerpVintage(row, ''),
  producer: resolveCerpProducer(row, ''),
  product: resolveCerpProductName(row, ''),
  color: resolveCerpColor(row, ''),
  rating: resolveCerpRating(row, ''),
  list_price: normalizeNumber(row.list_price),
  quote_price: normalizeNumber(row.quote_price),
  vip_price: normalizeNumber(row.vip_price),
  fb_price: normalizeNumber(row.fb_price),
  wholesale_price: normalizeNumber(row.wholesale_price),
  selected_quote_tier: normalizeEdmQuoteTier(row.selected_quote_tier),
  display_quote_price: normalizeNumber(row.display_quote_price),
  stock: normalizeStock(resolveCerpStock(row)),
  bundle: resolveCerpBundleDisplay(resolveCerpBundle(row, ''), ''),
  bundle_discount_enabled: isBundleDiscountEnabled(row),
  bundle_discount_type: resolveBundleDiscountType(row),
  product_link: row.product_link || row.link || row.href || '',
})

const getPreviewRowKey = (row = {}) => String(row.id || row.no || '').trim()

const mergePersistedPreviewRows = (serverRows = [], localRows = []) => {
  const localByKey = new Map(
    localRows
      .map((row) => [getPreviewRowKey(row), row])
      .filter(([key]) => Boolean(key))
  )
  return serverRows.map((serverRow, index) => {
    const key = getPreviewRowKey(serverRow)
    const localRow = (key && localByKey.get(key)) || localRows[index] || {}
    if (Object.prototype.hasOwnProperty.call(serverRow, 'bundle_discount_enabled')) {
      return serverRow
    }
    if (!Object.prototype.hasOwnProperty.call(localRow, 'bundle_discount_enabled')) {
      return serverRow
    }
    return {
      ...serverRow,
      bundle_discount_enabled: localRow.bundle_discount_enabled,
      bundle_discount_type: localRow.bundle_discount_type,
    }
  })
}

const persistPreviewState = async () => {
  if (!previewState.value) return
  writePreviewCache(previewState.value)
  if (isPublicShareView.value || !previewState.value.share_token) return

  const rows = Array.isArray(previewState.value.rows)
    ? previewState.value.rows.map((row) => serializePreviewRow(row))
    : []
  if (!rows.length) return

  try {
    const response = await updateEdmPreview(previewState.value.share_token, { rows })
    const normalized = normalizePreviewPayload({
      ...response,
      rows: mergePersistedPreviewRows(response?.rows || [], rows),
    })
    if (normalized) {
      previewState.value = normalized
      writePreviewCache(normalized)
    }
  } catch (error) {
    console.error('Failed to sync EDM preview rows', error)
  }
}

const normalizePreviewRow = (row = {}, index = 0) => {
  const pricing = buildCerpPricingState(row, row.selected_quote_tier)
  return {
    id: String(row.id || resolveCerpCode(row, `row-${index}`)),
    no: resolveCerpCode(row, '-'),
    vintage: resolveCerpVintage(row, '-'),
    producer: resolveCerpProducer(row, '-'),
    product: resolveCerpProductName(row, '-'),
    color: resolveCerpColor(row, '-'),
    rating: resolveCerpRating(row, '-'),
    list_price: pricing.list_price,
    quote_price: pricing.quote_price,
    display_quote_price: pricing.display_quote_price,
    vip_price: pricing.vip_price,
    fb_price: pricing.fb_price,
    wholesale_price: pricing.wholesale_price,
    selected_quote_tier: pricing.selected_quote_tier,
    stock: normalizeStock(resolveCerpStock(row)),
    bundle: resolveCerpBundleDisplay(row),
    bundle_discount_enabled: isBundleDiscountEnabled(row),
    bundle_discount_type: resolveBundleDiscountType(row),
    product_link: row.product_link || row.link || row.href || '',
  }
}

const normalizePreviewPayload = (payload, { readOnly = false } = {}) => {
  if (!payload || typeof payload !== 'object') return null
  return {
    share_token: payload.share_token || '',
    share_url: payload.share_url || '',
    quote_no: payload.quote_no || payload.banner?.quote_no || '',
    quote_date: payload.quote_date || payload.banner?.quote_date || '',
    sales_rep: payload.sales_rep || payload.banner?.sales || '',
    hero_text: payload.hero_text || '',
    banner: {
      sales: payload.banner?.sales || payload.sales_rep || '',
      quote_no: payload.banner?.quote_no || payload.quote_no || '',
      quote_date: payload.banner?.quote_date || payload.quote_date || '',
    },
    rows: Array.isArray(payload.rows)
      ? payload.rows.map((row, index) => normalizePreviewRow(row, index))
      : [],
    project: payload.project || {},
    conversation_id: payload.conversation_id || null,
    customer:
      payload.customer && typeof payload.customer === 'object'
        ? {
            id: payload.customer.id ? String(payload.customer.id) : null,
            name: payload.customer.name || '',
            email: payload.customer.email || '',
            phone: payload.customer.phone || '',
          }
        : null,
    read_only: readOnly || Boolean(payload.read_only),
  }
}

const buildPreviewRows = (items = []) =>
  Array.isArray(items)
    ? items.map((item, index) =>
        normalizePreviewRow(
          {
            id: item.id,
            no: item.no,
            vintage: item.vintage,
            producer: item.producer,
            product: item.product,
            color: item.color,
            rating: item.rating,
            list_price: item.list_price ?? item.price,
            vip_price: item.vip_price ?? item.vip,
            fb_price: item.fb_price,
            wholesale_price:
              item.wholesale_price ??
              item.invn808 ??
              item.invn080 ??
              item.wholesale ??
              item.dealer_price ??
              item.dealer,
            selected_quote_tier: item.selected_quote_tier || DEFAULT_EDM_QUOTE_TIER,
            display_quote_price: item.display_quote_price ?? item.quote_price,
            quote_price: item.quote_price,
            stock: resolveCerpStock(item),
            bundle: resolveCerpBundleDisplay(item),
            bundle_discount_enabled: item.bundle_discount_enabled,
            bundle_discount_type: item.bundle_discount_type,
            product_link: item.link || item.linkHref || item.link_href || item.url || '',
          },
          index
        )
      )
    : []

const cycleRowQuoteTier = async (row) => {
  if (!showQuoteTierColumn || !canEditEdmPreview.value || !row) return
  const currentIndex = EDM_QUOTE_TIERS.indexOf(normalizeEdmQuoteTier(row.selected_quote_tier))
  const nextTier = EDM_QUOTE_TIERS[(currentIndex + 1) % EDM_QUOTE_TIERS.length]
  row.selected_quote_tier = nextTier
  row.display_quote_price = resolveEdmQuotePriceForTier(row, nextTier)
  row.quote_price = row.display_quote_price
  await persistPreviewState()
}

const toggleBundleDiscount = async (row) => {
  if (!canEditEdmPreview.value || !isElevenPlusOneBundle(row)) return
  row.bundle_discount_enabled = !isBundleDiscountEnabled(row)
  row.bundle_discount_type = resolveBundleDiscountType(row)
  await persistPreviewState()
}

const buildHeroText = (rows = []) => {
  const firstProduct = rows[0]?.product || t('edm.hero.product_fallback')
  return t('edm.hero.recommendation', {
    product: firstProduct,
    count: rows.length,
  })
}

const formatDateLabel = (value) => {
  if (!value) return '-'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd}`
}

const formatCurrency = (value) => {
  const numeric = normalizeNumber(value)
  if (numeric === null) return '-'
  return formatUsdPrice(numeric)
}

const resolveColorIcon = (color) => {
  const normalized = String(color || '').trim().toLowerCase()
  return colorIcons[normalized] || glassWhite
}

const clearSnackbarTimer = () => {
  if (typeof window === 'undefined' || !snackbarTimer) return
  window.clearTimeout(snackbarTimer)
  snackbarTimer = 0
}

const closeSnackbar = () => {
  clearSnackbarTimer()
  isSnackbarVisible.value = false
}

const openSnackbar = (messageKey) => {
  snackbarMessageKey.value = messageKey
  isSnackbarVisible.value = true
  if (typeof window === 'undefined') return
  clearSnackbarTimer()
  snackbarTimer = window.setTimeout(() => {
    isSnackbarVisible.value = false
    snackbarTimer = 0
  }, 3200)
}

const resetShareDialogState = () => {
  shareRecipients.value = []
  shareInput.value = ''
  shareError.value = ''
  isSubmittingShare.value = false
}

const focusShareInput = () => {
  shareInputRef.value?.focus()
}

const closeShareDialog = () => {
  isShareDialogOpen.value = false
  resetShareDialogState()
}

const openShareDialog = async () => {
  shareError.value = ''
  isShareDialogOpen.value = true
  await nextTick()
  shareInputRef.value?.focus()
}

const appendRecipientsFromInput = () => {
  const raw = shareInput.value.trim()
  if (!raw) {
    shareError.value = ''
    return true
  }

  const tokens = raw
    .split(/[,\n]/)
    .map((value) => value.trim())
    .filter(Boolean)

  if (!tokens.length) {
    shareError.value = ''
    return true
  }

  const next = [...shareRecipients.value]
  let addedAny = false
  let firstInvalid = ''

  tokens.forEach((token) => {
    const normalized = token.toLowerCase()
    if (!EMAIL_PATTERN.test(normalized)) {
      if (!firstInvalid) {
        firstInvalid = token
      }
      return
    }
    if (next.some((value) => value.toLowerCase() === normalized)) {
      return
    }
    next.push(token)
    addedAny = true
  })

  if (!addedAny && firstInvalid) {
    shareError.value = t('edm.share.errors.invalid_email', { email: firstInvalid })
    return false
  }

  shareRecipients.value = next
  shareInput.value = ''
  shareError.value = firstInvalid
    ? t('edm.share.errors.invalid_email', { email: firstInvalid })
    : ''
  return !firstInvalid
}

const removeRecipient = (recipient) => {
  shareRecipients.value = shareRecipients.value.filter((value) => value !== recipient)
  shareError.value = ''
}

const handleShareInputKeydown = (event) => {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    appendRecipientsFromInput()
    return
  }
  if (event.key === 'Backspace' && !shareInput.value && shareRecipients.value.length) {
    shareRecipients.value = shareRecipients.value.slice(0, -1)
    shareError.value = ''
  }
}

const copyShareLink = async () => {
  if (!shareUrl.value) return
  try {
    await writeClipboard(shareUrl.value)
    shareError.value = ''
  } catch (error) {
    shareError.value = error?.message || t('edm.share.errors.copy_failed')
  }
}

const sendShareLink = async () => {
  const tokensOk = appendRecipientsFromInput()
  if (!tokensOk || !shareRecipients.value.length) {
    if (!shareRecipients.value.length) {
      shareError.value = t('edm.share.errors.recipients_required')
    }
    return
  }

  isSubmittingShare.value = true
  shareError.value = ''
  try {
    await shareEdmPreviewEmail(shareToken.value, shareRecipients.value)
    closeShareDialog()
    openSnackbar('edm.snackbar.share_sent')
  } catch (error) {
    shareError.value = error?.message || t('edm.share.errors.send_failed')
  } finally {
    isSubmittingShare.value = false
  }
}

const exportExcel = () => {
  if (!previewRows.value.length) return

  const exportColumns = tableColumns.value.filter((column) => column.key !== 'quote_tier_action')
  const header = exportColumns.map((column) => column.label)
  const rows = previewRows.value.map((row) => [
    row.no,
    row.vintage,
    row.producer,
    row.product,
    row.color,
    row.rating,
    formatCurrency(row.list_price),
    formatCurrency(row.quote_price),
    getBundleDiscountStatusText(row),
  ])

  const worksheet = XLSX.utils.aoa_to_sheet([header, ...rows])
  worksheet['!cols'] = [
    { wch: 14 },
    { wch: 10 },
    { wch: 22 },
    { wch: 48 },
    { wch: 12 },
    { wch: 14 },
    { wch: 12 },
    { wch: 12 },
    { wch: 10 },
  ]

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, t('edm.export.sheet_name'))
  XLSX.writeFile(workbook, `${quoteNumber.value || 'edm-preview'}.xlsx`)
  openSnackbar('edm.snackbar.exported')
}

const goBackToQuote = () => {
  router.push({ name: 'quote' })
}

const loadInternalPreview = async () => {
  const cached = normalizePreviewPayload(
    readStorage(window.sessionStorage, EDM_PREVIEW_STATE_KEY, null)
  )
  if (cached?.share_token && cached.rows.length) {
    previewState.value = cached
    return
  }

  const items = readStorage(window.sessionStorage, EDM_ITEMS_KEY, [])
  const edmContext = readStorage(window.sessionStorage, EDM_CONTEXT_KEY, {})
  const rows = buildPreviewRows(items)

  if (!rows.length) {
    previewState.value = normalizePreviewPayload({
      rows: [],
      banner: {
        sales: userProfile.value?.username || userProfile.value?.email || '',
        quote_no: '',
        quote_date: new Date().toISOString(),
      },
      hero_text: '',
      share_token: '',
      share_url: '',
      project: edmContext?.project || {},
    })
    return
  }

  const payload = {
    conversation_id: edmContext?.conversation_id || null,
    project: edmContext?.project || null,
    sales_rep: userProfile.value?.username || userProfile.value?.email || '',
    quote_date: new Date().toISOString(),
    hero_text: buildHeroText(rows),
    rows,
  }
  const response = await createEdmPreview(payload)
  const normalized = normalizePreviewPayload(response)
  previewState.value = normalized
  writePreviewCache(normalized)
}

const loadPublicPreview = async () => {
  const currentShareToken = String(route.params.shareToken || '').trim()
  if (!currentShareToken) {
    throw new Error(t('edm.state.invalid_link'))
  }
  const response = await fetchEdmPreview(currentShareToken)
  previewState.value = normalizePreviewPayload(response, { readOnly: true })
}

const initializeView = async () => {
  isLoading.value = true
  loadError.value = ''
  closeSnackbar()
  closeShareDialog()

  try {
    if (isPublicShareView.value) {
      clearPreviewCache()
      await loadPublicPreview()
    } else {
      await loadInternalPreview()
    }
  } catch (error) {
    previewState.value = null
    loadError.value = error?.message || t('edm.state.load_failed')
  } finally {
    isLoading.value = false
  }
}

watch(
  () => route.fullPath,
  () => {
    initializeView()
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  clearSnackbarTimer()
})
</script>

<template>
  <template v-if="isPublicShareView">
    <main v-if="isLoading || loadError || showEmptyState" class="edm-v1">
      <section class="edm-v1__panel">
        <section class="edm-v1__body">
          <div class="edm-state-card" :class="{ 'is-error': Boolean(loadError) }">
            <template v-if="isLoading">
              <p>{{ t('edm.state.loading') }}</p>
            </template>
            <template v-else-if="loadError">
              <h2>{{ t('edm.state.error_title') }}</h2>
              <p>{{ loadError }}</p>
            </template>
            <template v-else>
              <h2>{{ t('edm.state.empty_title') }}</h2>
              <p>{{ t('edm.state.empty_body') }}</p>
            </template>
          </div>
        </section>
      </section>
    </main>
    <EdmSharedFlow v-else :preview-state="previewState" />
  </template>

  <main v-else class="edm-preview-page">
    <header class="edm-preview-page__topbar">
      <div class="edm-preview-page__title">
        {{ t('edm.preview.title') }}
      </div>

      <div class="edm-preview-page__actions">
        <button
          type="button"
          class="edm-preview-page__button edm-preview-page__button--ghost"
          :disabled="!canExport"
          @click="exportExcel"
        >
          <img :src="iconExport" alt="" aria-hidden="true" />
          <span>{{ t('edm.actions.export_excel') }}</span>
        </button>
        <button
          type="button"
          class="edm-preview-page__button edm-preview-page__button--primary"
          :disabled="!canShare"
          @click="openShareDialog"
        >
          <img :src="iconLink" alt="" aria-hidden="true" />
          <span>{{ t('edm.actions.share_link') }}</span>
        </button>
        <button
          type="button"
          class="edm-preview-page__close"
          :aria-label="t('edm.actions.close')"
          @click="goBackToQuote"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M5 5 15 15M15 5 5 15"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>
        </button>
      </div>
    </header>

    <section class="edm-preview-page__canvas">
      <div v-if="isLoading" class="edm-state-card">
        <p>{{ t('edm.state.loading') }}</p>
      </div>

      <div v-else-if="loadError" class="edm-state-card is-error">
        <h2>{{ t('edm.state.error_title') }}</h2>
        <p>{{ loadError }}</p>
        <button type="button" class="edm-state-card__button" @click="goBackToQuote">
          {{ t('edm.actions.back_to_quote') }}
        </button>
      </div>

      <div v-else-if="showEmptyState" class="edm-state-card">
        <h2>{{ t('edm.state.empty_title') }}</h2>
        <p>{{ t('edm.state.empty_body') }}</p>
        <button type="button" class="edm-state-card__button" @click="goBackToQuote">
          {{ t('edm.actions.back_to_quote') }}
        </button>
      </div>

      <section v-else class="edm-preview-shell">
        <header class="edm-banner">
          <div class="edm-banner__brand">
            <img :src="bannerLogo" :alt="t('edm.banner.logo_alt')" />
          </div>
          <div class="edm-banner__meta">
            <div class="edm-banner__meta-item">
              <span>{{ t('edm.banner.meta.sales') }}</span>
              <strong>{{ salesRep }}</strong>
            </div>
            <div class="edm-banner__meta-item">
              <span>{{ t('edm.banner.meta.quote_no') }}</span>
              <strong>{{ quoteNumber }}</strong>
            </div>
            <div class="edm-banner__meta-item">
              <span>{{ t('edm.banner.meta.quote_date') }}</span>
              <strong>{{ formatDateLabel(quoteDate) }}</strong>
            </div>
          </div>
        </header>

        <h1 class="edm-hero">{{ heroText }}</h1>

        <section class="edm-table-card">
          <div class="edm-table-card__viewport">
            <table class="edm-table">
              <thead>
                <tr>
                  <th v-for="column in tableColumns" :key="column.key">
                    {{ column.label }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in previewRows" :key="row.id">
                  <td>{{ row.no }}</td>
                  <td>{{ row.vintage }}</td>
                  <td>{{ row.producer }}</td>
                  <td class="edm-table__product">
                    <a
                      v-if="row.product_link"
                      :href="row.product_link"
                      target="_blank"
                      rel="noopener"
                    >
                      {{ row.product }}
                    </a>
                    <span v-else class="edm-table__product-text">
                      {{ row.product }}
                    </span>
                  </td>
                  <td>
                    <span class="edm-table__color">
                      <img :src="resolveColorIcon(row.color)" alt="" aria-hidden="true" />
                      <span>{{ row.color }}</span>
                    </span>
                  </td>
                  <td>{{ row.rating }}</td>
                  <td class="is-price">{{ formatCurrency(row.list_price) }}</td>
                  <td class="is-price is-quote">{{ formatCurrency(row.quote_price) }}</td>
                  <td>
                    <button
                      v-if="isElevenPlusOneBundle(row) && canEditEdmPreview"
                      type="button"
                      class="edm-table__bundle-toggle"
                      :class="{ 'is-disabled': !isBundleDiscountEnabled(row) }"
                      :aria-label="getBundleDiscountAriaLabel(row)"
                      @click.stop.prevent="toggleBundleDiscount(row)"
                    >
                      <span>{{ resolveCerpBundleDisplay(row, '11+1') }}</span>
                      <strong>{{ getBundleDiscountLabel(row) }}</strong>
                    </button>
                    <span
                      v-else-if="isElevenPlusOneBundle(row)"
                      class="edm-table__bundle-status"
                      :class="{ 'is-disabled': !isBundleDiscountEnabled(row) }"
                    >
                      <span>{{ resolveCerpBundleDisplay(row, '11+1') }}</span>
                      <strong>{{ getBundleDiscountLabel(row) }}</strong>
                    </span>
                    <span v-else>{{ resolveCerpBundleDisplay(row) }}</span>
                  </td>
                  <td v-if="showQuoteTierColumn" class="edm-table__action-cell">
                    <button
                      type="button"
                      class="edm-table__quote-action"
                      :aria-label="`Switch quote tier for ${row.product}`"
                      @click="cycleRowQuoteTier(row)"
                    >
                      {{ getQuoteTierLabel(row.selected_quote_tier) }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </section>

    <div
      v-if="isShareDialogOpen"
      class="modal-mask edm-share-modal"
      role="dialog"
      aria-modal="true"
      @click.self="closeShareDialog"
    >
      <div class="edm-share-modal__card">
        <header class="edm-share-modal__header">
          <h3>{{ t('edm.share.title') }}</h3>
          <button
            type="button"
            class="edm-share-modal__close"
            :aria-label="t('edm.actions.close')"
            @click="closeShareDialog"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                d="M5 5L15 15M15 5L5 15"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
              />
            </svg>
          </button>
        </header>
        <section class="edm-share-modal__body">
          <div class="edm-share-modal__compose">
            <div
              class="edm-share-modal__token-input"
              :class="{ 'has-error': shareError }"
              @click="focusShareInput"
            >
              <span
                v-for="recipient in shareRecipients"
                :key="recipient"
                class="edm-share-modal__token"
              >
                <span>{{ recipient }}</span>
                <button
                  type="button"
                  :aria-label="t('edm.share.remove_recipient', { email: recipient })"
                  @click.stop="removeRecipient(recipient)"
                >
                  <svg
                    width="10"
                    height="10"
                    viewBox="0 0 10 10"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    aria-hidden="true"
                  >
                    <path
                      d="M2 2L8 8M8 2L2 8"
                      stroke="currentColor"
                      stroke-width="1.5"
                      stroke-linecap="round"
                    />
                  </svg>
                </button>
              </span>
              <input
                ref="shareInputRef"
                v-model="shareInput"
                type="email"
                :placeholder="shareRecipients.length ? '' : t('edm.share.email_placeholder')"
                @keydown="handleShareInputKeydown"
                @blur="appendRecipientsFromInput"
              />
            </div>
            <button
              type="button"
              class="edm-share-modal__send"
              :disabled="!canSendShare"
              @click="sendShareLink"
            >
              {{ isSubmittingShare ? t('edm.share.sending') : t('edm.share.send') }}
            </button>
          </div>

          <p v-if="shareError" class="edm-share-modal__error">
            {{ shareError }}
          </p>

          <div class="edm-share-modal__link-block">
            <p class="edm-share-modal__link-title">
              {{ t('edm.share.link_section_title') }}
            </p>
            <div class="edm-share-modal__link-row">
              <div class="edm-share-modal__link-text">{{ shareUrl }}</div>
              <button
                type="button"
                class="edm-share-modal__copy"
                @click="copyShareLink"
              >
                <img :src="iconCopy" alt="" aria-hidden="true" />
                <span>{{ t('edm.share.copy') }}</span>
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>

    <Transition name="snackbar-fade">
      <div
        v-if="isSnackbarVisible"
        class="edm-snackbar"
        role="status"
        aria-live="polite"
      >
        <div class="edm-snackbar__icon" aria-hidden="true">
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="m6.75 12.5 3.5 3.5 7-7"
              stroke="#3CCB90"
              stroke-width="2.2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </div>
        <p class="edm-snackbar__text">{{ t(snackbarMessageKey) }}</p>
        <button
          type="button"
          class="edm-snackbar__close"
          :aria-label="t('edm.actions.close')"
          @click="closeSnackbar"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 20 20"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M5 5L15 15M15 5L5 15"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            />
          </svg>
        </button>
      </div>
    </Transition>
  </main>
</template>

<style src="../edm-style.css" scoped></style>
<style src="../edm-preview-style.css" scoped></style>
