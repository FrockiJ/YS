<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import * as XLSX from 'xlsx'
import logoMain from '../assets/ysLogo_transparent.png'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import iconMoreVertical from '../assets/ic-more-vertical.svg'
import iconExport from '../assets/edm_export.svg'
import emptyIllustration from '../assets/Table No data.svg'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { useAuth } from '../composables/useAuth'
import { deleteQuote, fetchQuotes } from '../services/ysApi'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'
import { formatUsdPrice } from '../utils/currency'

const router = useRouter()
const { t } = useI18n()
const { isAuthenticated, avatarLabel, userProfile } = useAuth()

const SIDEBAR_COLLAPSE_BREAKPOINT = 720
const TABLET_BREAKPOINT = 900
const PAGE_SIZE = 10

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7a879c" stroke-width="2"/><path d="M12.5 12.5 16 16" stroke="#7a879c" stroke-width="2" stroke-linecap="round"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#263847" stroke-width="2" stroke-linecap="round"/></svg>',
}

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'home.nav'))

const iconImages = PRIMARY_NAV_ICON_IMAGES

const stageWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1440)
const isCompactSidebar = computed(() => stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const isTablet = computed(() => stageWidth.value <= TABLET_BREAKPOINT)
const isSidebarCollapsed = ref(stageWidth.value <= SIDEBAR_COLLAPSE_BREAKPOINT)
const activeNavId = ref('quote')
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet,
    isSidebarCollapsed,
  })

const quotes = ref([])
const total = ref(0)
const currentPage = ref(1)
const searchQuery = ref('')
const debouncedQuery = ref('')
const isLoading = ref(false)
const loadError = ref('')
const selectedQuotes = ref(new Map())
const activeRowMenuId = ref('')
const quotePendingDelete = ref(null)
const showDeleteModal = ref(false)
const showSelectionModal = ref(false)
const isDeleting = ref(false)
const isSnackbarVisible = ref(false)
let searchTimer = 0
let snackbarTimer = 0

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const selectionCount = computed(() => selectedQuotes.value.size)
const allPageSelected = computed(
  () => quotes.value.length > 0 && quotes.value.every((quote) => selectedQuotes.value.has(quote.id))
)
const rangeLabel = computed(() => {
  if (!total.value || !quotes.value.length) {
    return `0-0 / ${total.value}`
  }
  const start = (currentPage.value - 1) * PAGE_SIZE + 1
  const end = Math.min(total.value, start + quotes.value.length - 1)
  return `${start}-${end} / ${total.value}`
})
const canGoPrev = computed(() => currentPage.value > 1)
const canGoNext = computed(() => currentPage.value < pageCount.value)

const tableColumns = computed(() => [
  { key: 'quote_no', label: t('returns.table.quote_no') },
  { key: 'customer_name', label: t('returns.table.customer_name') },
  { key: 'sales_rep', label: t('returns.table.sales_rep') },
  { key: 'quote_date', label: t('returns.table.quote_date') },
  { key: 'reply_date', label: t('returns.table.reply_date') },
])

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

const formatDateLabel = (value) => {
  if (!value) return '-'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd}`
}

const normalizeNumber = (value) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const formatCurrency = (value) => {
  const numeric = normalizeNumber(value)
  if (numeric === null) return '-'
  return formatUsdPrice(numeric)
}

const resolveQuoteItemValue = (item = {}, keys = [], fallback = '-') => {
  for (const key of keys) {
    const value = item?.[key]
    if (value !== undefined && value !== null && value !== '') {
      return value
    }
  }
  return fallback
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

const openSnackbar = () => {
  isSnackbarVisible.value = true
  if (typeof window === 'undefined') return
  clearSnackbarTimer()
  snackbarTimer = window.setTimeout(() => {
    isSnackbarVisible.value = false
    snackbarTimer = 0
  }, 3200)
}

const syncSelectedSnapshots = (items = []) => {
  if (!selectedQuotes.value.size || !items.length) return
  const next = new Map(selectedQuotes.value)
  items.forEach((item) => {
    if (next.has(item.id)) {
      next.set(item.id, item)
    }
  })
  selectedQuotes.value = next
}

const loadQuotes = async () => {
  if (!isAuthenticated.value) {
    quotes.value = []
    total.value = 0
    return
  }
  isLoading.value = true
  loadError.value = ''
  try {
    const response = await fetchQuotes({
      q: debouncedQuery.value,
      page: currentPage.value,
      pageSize: PAGE_SIZE,
    })
    quotes.value = Array.isArray(response?.items) ? response.items : []
    total.value = Number(response?.total || 0)
    syncSelectedSnapshots(quotes.value)
  } catch (error) {
    quotes.value = []
    total.value = 0
    loadError.value = error?.message || t('returns.errors.load')
  } finally {
    isLoading.value = false
  }
}

const isRowSelected = (quote) => selectedQuotes.value.has(quote.id)

const toggleRowSelection = (quote) => {
  const next = new Map(selectedQuotes.value)
  if (next.has(quote.id)) {
    next.delete(quote.id)
  } else {
    next.set(quote.id, quote)
  }
  selectedQuotes.value = next
}

const toggleSelectAll = () => {
  const next = new Map(selectedQuotes.value)
  if (allPageSelected.value) {
    quotes.value.forEach((quote) => {
      next.delete(quote.id)
    })
  } else {
    quotes.value.forEach((quote) => {
      next.set(quote.id, quote)
    })
  }
  selectedQuotes.value = next
}

const closeRowMenu = () => {
  activeRowMenuId.value = ''
}

const toggleRowMenu = (quoteId) => {
  activeRowMenuId.value = activeRowMenuId.value === quoteId ? '' : quoteId
}

const openDeleteModal = (quote) => {
  closeRowMenu()
  quotePendingDelete.value = quote
  showDeleteModal.value = true
}

const closeDeleteModal = () => {
  showDeleteModal.value = false
  quotePendingDelete.value = null
}

const confirmDelete = async () => {
  if (!quotePendingDelete.value?.id || isDeleting.value) return
  isDeleting.value = true
  try {
    await deleteQuote(quotePendingDelete.value.id)
    const nextSelection = new Map(selectedQuotes.value)
    nextSelection.delete(quotePendingDelete.value.id)
    selectedQuotes.value = nextSelection
    closeDeleteModal()
    const remaining = total.value - 1
    const shouldMovePrev = remaining > 0 && currentPage.value > 1 && (currentPage.value - 1) * PAGE_SIZE >= remaining
    if (shouldMovePrev) {
      currentPage.value -= 1
    } else {
      await loadQuotes()
    }
  } catch (error) {
    loadError.value = error?.message || t('returns.errors.delete')
  } finally {
    isDeleting.value = false
  }
}

const exportSelected = () => {
  const items = Array.from(selectedQuotes.value.values())
  if (!items.length) {
    showSelectionModal.value = true
    return
  }

  const sortedItems = items.slice().sort((left, right) => {
    const leftTime = Date.parse(left.reply_date || left.created_at || left.quote_date || 0)
    const rightTime = Date.parse(right.reply_date || right.created_at || right.quote_date || 0)
    return rightTime - leftTime
  })

  const header = [
    t('returns.table.quote_no'),
    t('returns.table.customer_name'),
    t('returns.table.sales_rep'),
    t('returns.table.quote_date'),
    t('returns.table.reply_date'),
    t('returns.export.columns.no'),
    t('returns.export.columns.vintage'),
    t('returns.export.columns.producer'),
    t('returns.export.columns.product'),
    t('returns.export.columns.color'),
    t('returns.export.columns.rating'),
    t('returns.export.columns.list_price'),
    t('returns.export.columns.quote_price'),
    t('returns.export.columns.bundle'),
    t('returns.export.columns.quantity'),
  ]
  const rows = sortedItems.flatMap((quote) => {
    const quoteItems = Array.isArray(quote.quote_items) ? quote.quote_items : []
    return quoteItems.map((item) => [
      quote.quote_no || '',
      quote.customer_name || '',
      quote.sales_rep || '',
      formatDateLabel(quote.quote_date),
      formatDateLabel(quote.reply_date),
      resolveQuoteItemValue(item, ['no', 'id'], ''),
      resolveQuoteItemValue(item, ['vintage'], ''),
      resolveQuoteItemValue(item, ['producer'], ''),
      resolveQuoteItemValue(item, ['product'], ''),
      resolveQuoteItemValue(item, ['color'], ''),
      resolveQuoteItemValue(item, ['rating'], ''),
      formatCurrency(resolveQuoteItemValue(item, ['list_price', 'price'], null)),
      formatCurrency(resolveQuoteItemValue(item, ['quote_price', 'quote', 'list_price', 'price'], null)),
      resolveQuoteItemValue(item, ['bundle'], ''),
      resolveQuoteItemValue(item, ['quantity'], ''),
    ])
  })

  const worksheet = XLSX.utils.aoa_to_sheet([header, ...rows])
  worksheet['!cols'] = [
    { wch: 18 },
    { wch: 24 },
    { wch: 18 },
    { wch: 14 },
    { wch: 14 },
    { wch: 10 },
    { wch: 10 },
    { wch: 24 },
    { wch: 34 },
    { wch: 10 },
    { wch: 10 },
    { wch: 12 },
    { wch: 12 },
    { wch: 12 },
    { wch: 10 },
  ]

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, t('returns.export.sheet_name'))
  const now = new Date()
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('')
  XLSX.writeFile(workbook, `quote-returns-${stamp}.xlsx`)
  openSnackbar()
}

const handleDocumentPointerDown = (event) => {
  if (!activeRowMenuId.value) return
  if (event.target?.closest?.('.return-menu-anchor')) return
  closeRowMenu()
}

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

watch(
  [isAuthenticated, currentPage, debouncedQuery],
  ([authed]) => {
    if (!authed) return
    loadQuotes()
  },
  { immediate: true }
)

onMounted(() => {
  if (typeof window === 'undefined') return
  window.addEventListener('resize', updateViewport)
  document.addEventListener('pointerdown', handleDocumentPointerDown)
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateViewport)
    document.removeEventListener('pointerdown', handleDocumentPointerDown)
    window.clearTimeout(searchTimer)
  }
  clearSnackbarTimer()
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

    <div class="main-stage return-stage-shell">
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
          <div class="return-topbar-spacer" :class="{ 'is-tablet': isTablet }" />
        </template>
      </AppTopBar>

      <main class="stage-canvas return-stage">
        <div class="return-page">
          <header class="return-page__header">
            <h1>{{ t('returns.page_title') }}</h1>
          </header>

          <section class="return-card">
            <div class="return-card__toolbar">
              <label class="return-search-field">
                <span class="return-search-field__icon" v-html="glyphs.search" aria-hidden="true" />
                <input
                  v-model="searchQuery"
                  type="search"
                  :placeholder="t('returns.search.placeholder')"
                  :aria-label="t('returns.search.aria')"
                />
              </label>

              <button
                type="button"
                class="return-export-button"
                @click="exportSelected"
              >
                <img :src="iconExport" alt="" aria-hidden="true" />
                <span>{{ t('returns.actions.export_excel') }}</span>
              </button>
            </div>

            <div class="return-table-wrap">
              <div v-if="loadError" class="return-state return-state--error">
                {{ loadError }}
              </div>
              <div v-else-if="isLoading" class="return-state">
                {{ t('returns.states.loading') }}
              </div>
              <template v-else-if="quotes.length">
                <div class="return-table">
                  <div class="return-table__head">
                    <div class="return-table__cell return-table__cell--checkbox">
                      <label class="return-checkbox">
                        <input
                          type="checkbox"
                          :checked="allPageSelected"
                          :aria-label="t('returns.aria.select_all')"
                          @change="toggleSelectAll"
                        />
                      </label>
                    </div>
                    <div class="return-table__cell">{{ t('returns.table.quote_no') }}</div>
                    <div class="return-table__cell">{{ t('returns.table.customer_name') }}</div>
                    <div class="return-table__cell">{{ t('returns.table.sales_rep') }}</div>
                    <div class="return-table__cell">{{ t('returns.table.quote_date') }}</div>
                    <div class="return-table__cell return-table__cell--sorted">
                      <span>{{ t('returns.table.reply_date') }}</span>
                      <span class="return-table__sort" aria-hidden="true">↕</span>
                    </div>
                    <div class="return-table__cell return-table__cell--action" />
                  </div>

                  <div
                    v-for="quote in quotes"
                    :key="quote.id"
                    class="return-table__row"
                  >
                    <div class="return-table__cell return-table__cell--checkbox">
                      <label class="return-checkbox">
                        <input
                          type="checkbox"
                          :checked="isRowSelected(quote)"
                          :aria-label="t('returns.aria.select_row', { quoteNo: quote.quote_no })"
                          @change="toggleRowSelection(quote)"
                        />
                      </label>
                    </div>
                    <div class="return-table__cell return-table__cell--strong">
                      {{ quote.quote_no }}
                    </div>
                    <div class="return-table__cell">{{ quote.customer_name || '-' }}</div>
                    <div class="return-table__cell">{{ quote.sales_rep || '-' }}</div>
                    <div class="return-table__cell">{{ formatDateLabel(quote.quote_date) }}</div>
                    <div class="return-table__cell">{{ formatDateLabel(quote.reply_date) }}</div>
                    <div class="return-table__cell return-table__cell--action">
                      <div class="return-menu-anchor">
                        <button
                          type="button"
                          class="return-menu-toggle"
                          :aria-label="t('quote.aria.open_actions')"
                          @click.stop="toggleRowMenu(quote.id)"
                        >
                          <img :src="iconMoreVertical" alt="" aria-hidden="true" />
                        </button>
                        <div
                          v-if="activeRowMenuId === quote.id"
                          class="return-menu-popover"
                        >
                          <button
                            type="button"
                            class="return-menu-popover__item is-danger"
                            @click="openDeleteModal(quote)"
                          >
                            {{ t('returns.actions.delete') }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <div v-else class="return-empty">
                <img :src="emptyIllustration" alt="" />
                <p>{{ t('returns.states.empty') }}</p>
              </div>
            </div>

            <footer class="return-card__footer">
              <div class="return-card__rows">
                {{ t('returns.pagination.per_page') }}
                <strong>{{ PAGE_SIZE }}</strong>
              </div>
              <div class="return-card__range">{{ rangeLabel }}</div>
              <div class="return-card__pager">
                <button
                  type="button"
                  :aria-label="t('returns.aria.prev_page')"
                  :disabled="!canGoPrev"
                  @click="currentPage -= 1"
                >
                  ??
                </button>
                <button
                  type="button"
                  :aria-label="t('returns.aria.next_page')"
                  :disabled="!canGoNext"
                  @click="currentPage += 1"
                >
                  ??
                </button>
              </div>
            </footer>
          </section>
        </div>
      </main>
    </div>
  </div>

  <div
    v-if="showSelectionModal"
    class="modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="showSelectionModal = false"
  >
    <article class="return-modal">
      <header class="return-modal__header">
        <h2>{{ t('returns.modals.no_selection.title') }}</h2>
      </header>
      <div class="return-modal__body">
        <p>{{ t('returns.modals.no_selection.body') }}</p>
      </div>
      <footer class="return-modal__footer return-modal__footer--single">
        <button
          type="button"
          class="return-button return-button--primary"
          @click="showSelectionModal = false"
        >
          {{ t('returns.modals.no_selection.confirm') }}
        </button>
      </footer>
    </article>
  </div>

  <div
    v-if="showDeleteModal && quotePendingDelete"
    class="modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="closeDeleteModal"
  >
    <article class="return-modal return-modal--delete">
      <header class="return-modal__header">
        <h2>{{ t('returns.modals.delete.title') }}</h2>
      </header>
      <div class="return-modal__body">
        <p>{{ t('returns.modals.delete.body') }}</p>
      </div>
      <footer class="return-modal__footer">
        <button
          type="button"
          class="return-button return-button--ghost"
          @click="closeDeleteModal"
        >
          {{ t('returns.actions.cancel') }}
        </button>
        <button
          type="button"
          class="return-button return-button--danger"
          :disabled="isDeleting"
          @click="confirmDelete"
        >
          {{ isDeleting ? t('returns.states.deleting') : t('returns.actions.delete') }}
        </button>
      </footer>
    </article>
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
      <p class="edm-snackbar__text">{{ t('returns.snackbar.exported') }}</p>
      <button
        type="button"
        class="edm-snackbar__close"
        :aria-label="t('returns.aria.close_snackbar')"
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
</template>

<style scoped>
.return-stage-shell {
  background: #f4f6f8;
}

.return-topbar-spacer {
  width: 100%;
  min-height: 1px;
}

.return-stage {
  width: 100%;
  max-width: 1280px;
  padding: 32px 24px 48px;
}

.return-page {
  width: min(1080px, 100%);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.return-page__header h1 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 36px;
  font-weight: 700;
}

.return-card {
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 0 2px rgba(145, 158, 171, 0.18), 0 6px 14px -4px rgba(145, 158, 171, 0.1);
  overflow: hidden;
}

.return-card__toolbar {
  min-height: 80px;
  padding: 20px 24px;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.return-search-field {
  position: relative;
  width: min(300px, 100%);
}

.return-search-field__icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.return-search-field input {
  width: 100%;
  height: 40px;
  border: 1px solid rgba(145, 158, 171, 0.32);
  border-radius: var(--ys-control-radius, 6px);
  padding: 8px 14px 8px 46px;
  background: #ffffff;
  color: #212b36;
  font-size: 16px;
  line-height: 24px;
}

.return-search-field input::placeholder {
  color: #919eab;
}

.return-export-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 125px;
  height: 36px;
  border-radius: 8px;
  background: #55b77f;
  color: #ffffff;
  font-size: 14px;
  line-height: 24px;
  font-weight: 700;
  flex-shrink: 0;
}

.return-export-button img {
  width: 20px;
  height: 20px;
  filter: brightness(0) invert(1);
}

.return-table-wrap {
  min-height: 572px;
}

.return-table {
  display: flex;
  flex-direction: column;
}

.return-table__head,
.return-table__row {
  display: grid;
  grid-template-columns: 72px 150px minmax(240px, 1fr) 120px 160px 160px 58px;
  align-items: center;
}

.return-table__head {
  min-height: 56px;
  background: #f4f6f8;
}

.return-table__row {
  min-height: 52px;
  background: #ffffff;
  border-bottom: 1px solid rgba(145, 158, 171, 0.24);
}

.return-table__cell {
  min-width: 0;
  padding: 16px 14px 16px 12px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.return-table__head .return-table__cell {
  color: #637381;
  font-weight: 600;
}

.return-table__cell--checkbox {
  display: flex;
  justify-content: center;
  padding: 6px 16px;
}

.return-table__cell--action {
  display: flex;
  justify-content: center;
  padding: 8px 10px 8px 0;
}

.return-table__cell--strong {
  font-weight: 600;
}

.return-table__cell--sorted {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.return-table__sort {
  color: #212b36;
  font-size: 12px;
}

.return-checkbox {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.return-checkbox input {
  width: 18px;
  height: 18px;
  accent-color: #55b77f;
}

.return-menu-anchor {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.return-menu-toggle {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.return-menu-toggle:hover {
  background: rgba(145, 158, 171, 0.12);
}

.return-menu-toggle img {
  width: 20px;
  height: 20px;
}

.return-menu-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 120px;
  padding: 6px;
  border: 1px solid rgba(145, 158, 171, 0.24);
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 7px 18px rgba(16, 24, 40, 0.13);
  z-index: 10;
}

.return-menu-popover__item {
  width: 100%;
  padding: 8px 10px;
  border-radius: 8px;
  text-align: left;
  font-size: 14px;
  line-height: 22px;
}

.return-menu-popover__item:hover {
  background: #f4f6f8;
}

.return-menu-popover__item.is-danger {
  color: #de3618;
}

.return-state,
.return-empty {
  min-height: 520px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 14px;
  color: #637381;
  padding: 24px;
  text-align: center;
}

.return-state--error {
  color: #b42318;
}

.return-empty img {
  width: 220px;
  max-width: 100%;
}

.return-card__footer {
  min-height: 58px;
  padding: 10px 8px 10px 24px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 24px;
  color: #212b36;
  font-size: 14px;
  line-height: 22px;
}

.return-card__rows strong {
  margin-left: 4px;
}

.return-card__pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.return-card__pager button {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #212b36;
  font-size: 20px;
  line-height: 1;
}

.return-card__pager button:disabled {
  color: rgba(145, 158, 171, 0.8);
  cursor: not-allowed;
}

.return-modal {
  width: min(480px, 100%);
  background: #ffffff;
  border-radius: 16px;
  box-shadow: -14px 14px 34px -6px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.return-modal__header {
  padding: 24px 24px 16px;
}

.return-modal__header h2 {
  margin: 0;
  color: #212b36;
  font-size: 24px;
  line-height: 1.33;
  font-weight: 700;
}

.return-modal__body {
  padding: 0 24px 24px;
}

.return-modal__body p {
  margin: 0;
  color: #637381;
  font-size: 16px;
  line-height: 1.6;
}

.return-modal__footer {
  padding: 0 24px 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.return-modal__footer--single {
  justify-content: center;
}

.return-button {
  min-width: 96px;
  height: 36px;
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 14px;
  line-height: 24px;
  font-weight: 700;
}

.return-button--ghost {
  border: 1px solid rgba(145, 158, 171, 0.32);
  background: #ffffff;
  color: #212b36;
}

.return-button--primary {
  background: #55b77f;
  color: #ffffff;
}

.return-button--danger {
  background: #de3618;
  color: #ffffff;
}

.edm-snackbar {
  position: fixed;
  right: 32px;
  bottom: 32px;
  z-index: 160;
  display: flex;
  flex-direction: row;
  align-items: center;
  width: 309px;
  min-width: 240px;
  max-width: 420px;
  height: 64px;
  padding: 0 0 0 12px;
  gap: 12px;
  background: #212b36;
  color: #ffffff;
  border-radius: 8px;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.13);
}

.edm-snackbar__icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}

.edm-snackbar__text {
  margin: 0;
  flex: 1 1 auto;
  font-size: 14px;
  line-height: 20px;
  font-weight: 600;
  color: #ffffff;
}

.edm-snackbar__close {
  flex: 0 0 auto;
  width: 40px;
  height: 64px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: #c6d0da;
  padding: 0;
}

.snackbar-fade-enter-active,
.snackbar-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.snackbar-fade-enter-from,
.snackbar-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (max-width: 1100px) {
  .return-stage {
    padding: 24px 16px 40px;
  }

  .return-card__toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .return-search-field {
    width: 100%;
  }

  .return-table__head,
  .return-table__row {
    grid-template-columns: 72px 150px minmax(220px, 1fr) 120px 140px 140px 58px;
  }
}

@media (max-width: 900px) {
  .return-stage {
    padding: 20px 12px 32px;
  }

  .return-table__head {
    display: none;
  }

  .return-table__row {
    grid-template-columns: 40px minmax(0, 1fr) 40px;
    gap: 6px 12px;
    padding: 14px 16px;
  }

  .return-table__row .return-table__cell {
    padding: 0;
  }

  .return-table__cell--checkbox {
    grid-column: 1 / 2;
    grid-row: 1 / span 3;
    align-self: start;
    padding-top: 2px;
  }

  .return-table__cell--action {
    grid-column: 3 / 4;
    grid-row: 1 / span 3;
    align-self: start;
  }

  .return-table__row .return-table__cell:nth-child(2) {
    grid-column: 2 / 3;
    font-weight: 700;
  }

  .return-table__row .return-table__cell:nth-child(3),
  .return-table__row .return-table__cell:nth-child(4),
  .return-table__row .return-table__cell:nth-child(5),
  .return-table__row .return-table__cell:nth-child(6) {
    grid-column: 2 / 3;
    color: #637381;
    font-size: 13px;
    line-height: 20px;
  }

  .return-card__footer {
    flex-wrap: wrap;
    justify-content: space-between;
    padding-inline: 16px;
  }
}

@media (max-width: 720px) {
  .edm-snackbar {
    right: 12px;
    bottom: 12px;
    width: auto;
    min-width: 0;
    max-width: calc(100vw - 24px);
  }
}
</style>
