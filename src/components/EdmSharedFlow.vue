<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import bannerLogo from '../assets/ysLogo_transparent.png'
import bannerLogoDark from '../assets/ysLogo_transparent.png'
import glassWhite from '../assets/placeholder.png'
import glassRed from '../assets/placeholder.png'
import glassRose from '../assets/placeholder.png'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import { apiRequest } from '../services/apiClient'
import { formatUsdPrice } from '../utils/currency'
import {
  isEdmBundleColumn,
  isEdmColorColumn,
  isEdmPriceColumn,
  isEdmProductColumn,
  normalizeEdmTableColumns,
  resolveEdmTableValue,
} from '../utils/edmTable'
import {
  buildCerpPricingState,
  calculateBundleFreeQuantity,
  calculateBundlePayableQuantity,
  calculateEdmLineSubtotal,
  isBundleDiscountEnabled,
  isElevenPlusOneBundle,
  resolveBundleDiscountType,
  resolveCerpBundleDisplay,
  resolveEdmUnitPrice,
  resolveCerpStock,
} from '../utils/cerpFields'

const { t } = useI18n()
const props = defineProps({
  previewState: {
    type: Object,
    default: null,
  },
})

const currentStep = ref(1)
const stepLabels = ['商品選擇', '報價確認', '完成與分享']
const selectedItems = ref([])
const pdfRef = ref(null)
const isSubmitting = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref('')
const quoteResult = ref(null)

const bannerMetaOrder = ['sales', 'quote_no', 'quote_date']

const orderedBannerMeta = computed(() =>
  bannerMetaOrder.map((key) => {
    if (key === 'sales') {
      return {
        label: t('edm.banner.meta.sales'),
        value: quoteResult.value?.sales_rep || props.previewState?.banner?.sales || props.previewState?.sales_rep || '--',
      }
    }
    if (key === 'quote_no') {
      return {
        label: t('edm.banner.meta.quote_no'),
        value: quoteResult.value?.quote_no || props.previewState?.quote_no || props.previewState?.banner?.quote_no || '--',
      }
    }
    return {
      label: t('edm.banner.meta.quote_date'),
      value: formatDateLabel(
        quoteResult.value?.quote_date ||
          props.previewState?.quote_date ||
          props.previewState?.banner?.quote_date
      ),
    }
  })
)
const heroTitle = computed(() => props.previewState?.hero_text || t('edm.hero.title'))
const tableColumns = computed(() => normalizeEdmTableColumns(props.previewState?.table_columns))

const DEFAULT_MAX_QUANTITY = 24

const colorIcons = {
  white: glassWhite,
  rose: glassRose,
  red: glassRed,
}

const resolveValue = (item, keys, fallback = '') => {
  for (const key of keys) {
    const value = item?.[key]
    if (value !== undefined && value !== null && value !== '') {
      return value
    }
  }
  return fallback
}

const resolveNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  const direct = Number(value)
  if (Number.isFinite(direct)) return direct
  const match = String(value).match(/-?\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : null
}

const normalizeEdmRow = (row = {}) => {
  const pricing = buildCerpPricingState(row, row.selected_quote_tier)
  return {
    ...row,
    ...pricing,
    bundle_discount_enabled: isBundleDiscountEnabled(row),
    bundle_discount_type: resolveBundleDiscountType(row),
  }
}

const getRowQuantityMax = (row) => {
  const stock = resolveNumber(resolveCerpStock(row))
  if (stock === null) return DEFAULT_MAX_QUANTITY
  if (stock < DEFAULT_MAX_QUANTITY) return Math.max(0, Math.floor(stock))
  return DEFAULT_MAX_QUANTITY
}

const getQuantityOptions = (row) =>
  Array.from({ length: getRowQuantityMax(row) + 1 }, (_, index) => index)

const formatCurrency = (value) => {
  return formatUsdPrice(value)
}

const getTableCellText = (row, column) => {
  const value = resolveEdmTableValue(row, column.key)
  if (isEdmPriceColumn(column.key)) return formatCurrency(value)
  if (isEdmBundleColumn(column.key)) return getShareBundleDisplay(row)
  return value
}

const formatDateLabel = (value) => {
  if (!value) return '-'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '-'
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd}`
}

const formatDateTime = (value) => {
  if (!value) return ''
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return ''
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const min = String(date.getMinutes()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd} ${hh}:${min}`
}

const resolveColorIcon = (color) => {
  const normalized = String(color || '').trim().toLowerCase()
  return colorIcons[normalized] || glassWhite
}

const conversationId = computed(() => props.previewState?.conversation_id || null)
const customerSnapshot = computed(() => props.previewState?.customer || null)
const hasSelection = computed(() =>
  selectedItems.value.some((row) => Number(row.quantity || 0) > 0)
)

const confirmationItems = computed(() =>
  selectedItems.value.filter((row) => Number(row.quantity || 0) > 0)
)

const totalQuantity = computed(() =>
  confirmationItems.value.reduce((sum, row) => sum + Number(row.quantity || 0), 0)
)

const totalAmount = computed(() =>
  confirmationItems.value.reduce((sum, row) => sum + calculateEdmLineSubtotal(row, row.quantity), 0)
)

const includedTaxTotal = computed(() => totalAmount.value)

const normalizeItems = (items) =>
  Array.isArray(items)
    ? items.map((item) => {
        const normalized = normalizeEdmRow(item)
        const maxQuantity = getRowQuantityMax(normalized)
        const quantity = resolveNumber(item?.quantity) ?? 0
        return {
          ...normalized,
          quantity: Math.min(Math.max(0, Math.floor(quantity)), maxQuantity),
        }
      })
    : []

const setFeedback = (type, message) => {
  feedbackType.value = type
  feedbackMessage.value = message
}

const clearSelection = () => {
  selectedItems.value.forEach((row) => {
    row.quantity = 0
  })
}

const handleConfirm = () => {
  if (!hasSelection.value) return
  currentStep.value = 2
}

const handleBack = () => {
  currentStep.value = 1
}

const getShareBundleDisplay = (row = {}) => {
  if (!isElevenPlusOneBundle(row)) return resolveCerpBundleDisplay(row)
  return isBundleDiscountEnabled(row) ? resolveCerpBundleDisplay(row, '11+1') : '-'
}

const getBundlePayableHint = (row = {}) => {
  const quantity = Number(row.quantity || 0)
  if (!isElevenPlusOneBundle(row) || !quantity) return ''
  const payable = calculateBundlePayableQuantity(quantity, row)
  if (payable >= quantity) return ''
  return t('edm.bundle.payable_hint', {
    quantity,
    payable,
  })
}

const buildSubmittedQuoteItems = () =>
  confirmationItems.value.map((row) => {
    const quantity = Number(row.quantity || 0)
    const payableQuantity = calculateBundlePayableQuantity(quantity, row)
    const freeQuantity = calculateBundleFreeQuantity(quantity, row)
    return {
      ...row,
      quantity,
      payable_quantity: payableQuantity,
      free_quantity: freeQuantity,
      bundle_discount_enabled: isBundleDiscountEnabled(row),
      bundle_discount_type: resolveBundleDiscountType(row),
      line_subtotal: calculateEdmLineSubtotal(row, quantity),
    }
  })

const handleSubmit = async () => {
  if (!hasSelection.value || isSubmitting.value) return
  isSubmitting.value = true
  setFeedback('', '')
  try {
    const payload = {
      conversation_id: conversationId.value,
      customer_id: customerSnapshot.value?.id || null,
      customer_name: customerSnapshot.value?.name || '',
      sales_rep: props.previewState?.banner?.sales || props.previewState?.sales_rep || '',
      quote_items: buildSubmittedQuoteItems(),
      taxable_amount: totalAmount.value,
      tax_amount: 0,
      total_amount: includedTaxTotal.value,
      quote_date: new Date().toISOString(),
      reply_date: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    }
    quoteResult.value = await apiRequest('/quotes', {
      method: 'POST',
      auth: false,
      body: payload,
    })
    currentStep.value = 3
  } catch (error) {
    setFeedback('error', error?.message || t('edm.feedback.failed'))
  } finally {
    isSubmitting.value = false
  }
}

const downloadPdf = async () => {
  if (!pdfRef.value) return
  if (document.fonts && document.fonts.ready) {
    await document.fonts.ready
  }
  const element = pdfRef.value
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#f4f6f8',
  })
  const imgData = canvas.toDataURL('image/png')
  const pdf = new jsPDF({
    orientation: 'p',
    unit: 'pt',
    format: 'a4',
  })
  const pageWidth = pdf.internal.pageSize.getWidth()
  const pageHeight = pdf.internal.pageSize.getHeight()
  const imgWidth = canvas.width
  const imgHeight = canvas.height
  const ratio = Math.min(pageWidth / imgWidth, pageHeight / imgHeight)
  const scaledWidth = imgWidth * ratio
  const scaledHeight = imgHeight * ratio
  let positionY = 0
  let heightLeft = scaledHeight

  pdf.addImage(
    imgData,
    'PNG',
    (pageWidth - scaledWidth) / 2,
    positionY,
    scaledWidth,
    scaledHeight
  )
  heightLeft -= pageHeight

  while (heightLeft > 0) {
    positionY -= pageHeight
    pdf.addPage()
    pdf.addImage(
      imgData,
      'PNG',
      (pageWidth - scaledWidth) / 2,
      positionY,
      scaledWidth,
      scaledHeight
    )
    heightLeft -= pageHeight
  }

  const filename = quoteResult.value?.quote_no
    ? `${quoteResult.value.quote_no}.pdf`
    : 'quote.pdf'
  pdf.save(filename)
}

const completedSummary = computed(() => ({
  quote_no: quoteResult.value?.quote_no || quoteResult.value?.id || '--',
  created_at:
    quoteResult.value?.quote_date ||
    props.previewState?.quote_date ||
    props.previewState?.banner?.quote_date ||
    new Date().toISOString(),
  total_amount: quoteResult.value?.total_amount ?? includedTaxTotal.value,
  total_qty: totalQuantity.value,
  sales_rep:
    quoteResult.value?.sales_rep ||
    props.previewState?.banner?.sales ||
    props.previewState?.sales_rep ||
    '',
  contact_phone: customerSnapshot.value?.phone || '',
}))

watch(
  () => props.previewState,
  (value) => {
    currentStep.value = 1
    quoteResult.value = null
    setFeedback('', '')
    selectedItems.value = normalizeItems(value?.rows || [])
  },
  { immediate: true }
)
</script>

<template>
  <main ref="pdfRef" class="edm-v1">
    <section class="edm-v1__panel">
      <header
        class="edm-v1__header"
        :class="{ 'is-complete': currentStep === 3 }"
      >
        <div class="edm-v1__brand">
          <img
            :src="currentStep === 3 ? bannerLogoDark : bannerLogo"
            :alt="t('edm.banner.logo_alt')"
          />
        </div>
        <div v-if="currentStep !== 3" class="edm-v1__meta">
          <div v-for="item in orderedBannerMeta" :key="item.label">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </header>

      <ol class="edm-v1__stepper" aria-label="報價流程">
        <li
          v-for="(label, index) in stepLabels"
          :key="label"
          :class="{ 'is-active': currentStep === index + 1, 'is-complete': currentStep > index + 1 }"
        >
          <span>{{ index + 1 }}</span>
          <strong>{{ label }}</strong>
        </li>
      </ol>

      <section class="edm-v1__body">
        <template v-if="currentStep === 1">
          <h1>{{ heroTitle }}</h1>

          <div class="edm-v1__table">
            <table>
              <thead>
                <tr>
                  <th v-for="column in tableColumns" :key="column.key">{{ column.label }}</th>
                  <th>{{ t('edm.table.columns.quantity') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, index) in selectedItems"
                  :key="resolveValue(row, ['no', 'sku', 'id', 'barcode'], index)"
                >
                  <td
                    v-for="column in tableColumns"
                    :key="column.key"
                    :class="{
                      center: isEdmBundleColumn(column.key),
                      right: isEdmPriceColumn(column.key),
                      'edm-v1__quote': column.key === 'vip' || column.key === 'quote_price',
                    }"
                  >
                    <a
                      v-if="isEdmProductColumn(column.key) && resolveValue(row, ['product_link', 'link', 'href'], '')"
                      class="edm-v1__link"
                      :href="resolveValue(row, ['product_link', 'link', 'href'], '')"
                      target="_blank"
                      rel="noopener"
                    >
                      {{ getTableCellText(row, column) }}
                    </a>
                    <span v-else-if="isEdmProductColumn(column.key)">
                      {{ getTableCellText(row, column) }}
                    </span>
                    <span
                      v-else-if="isEdmColorColumn(column.key)"
                      class="edm-v1__color"
                      :data-tone="getTableCellText(row, column)"
                    >
                      <img
                        class="edm-v1__icon"
                        :src="resolveColorIcon(getTableCellText(row, column))"
                        :alt="t('edm.table.color_icon', { color: getTableCellText(row, column) })"
                      />
                      {{ getTableCellText(row, column) }}
                    </span>
                    <span v-else>{{ getTableCellText(row, column) }}</span>
                  </td>
                  <td>
                    <div class="edm-v1__select">
                      <select v-model.number="row.quantity">
                        <option
                          v-for="qty in getQuantityOptions(row)"
                          :key="qty"
                          :value="qty"
                        >
                          {{ qty }}
                        </option>
                      </select>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>

            <footer class="edm-v1__footer">
              <p>{{ t('edm.table.note') }}</p>
              <div class="edm-v1__actions">
                <button class="ghost" type="button" @click="clearSelection">
                  {{ t('edm.actions.clear') }}
                </button>
                <button
                  class="primary"
                  type="button"
                  :class="{ active: hasSelection }"
                  @click="handleConfirm"
                >
                  {{ t('edm.actions.confirm') }}
                </button>
              </div>
            </footer>
            <p
              v-if="feedbackMessage"
              class="edm-v1__feedback"
              :data-state="feedbackType"
            >
              {{ feedbackMessage }}
            </p>
          </div>
        </template>

        <template v-else-if="currentStep === 2">
          <div class="edm-confirm-top">
            <button
              class="edm-confirm-back"
              type="button"
              @click="handleBack"
              :aria-label="t('edm.confirm.back_aria')"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path
                  d="M15 18l-6-6 6-6"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <h2>{{ t('edm.confirm.title') }}</h2>
          </div>

          <div class="edm-confirm-grid">
            <section class="edm-confirm-list">
              <div class="edm-confirm-list__header">
                <span>{{ t('edm.confirm.list.product') }}</span>
                <span class="is-right">{{ t('edm.confirm.list.unit_price') }}</span>
                <span class="is-right">{{ t('edm.confirm.list.quantity') }}</span>
                <span class="is-right">{{ t('edm.confirm.list.subtotal') }}</span>
              </div>
              <div
                v-for="item in confirmationItems"
                :key="resolveValue(item, ['no', 'sku', 'id', 'barcode'])"
                class="edm-confirm-list__row"
              >
                <div class="edm-confirm-list__name">
                  {{ resolveValue(item, ['product', 'name', 'title'], '-') }}
                </div>
                <div class="edm-confirm-list__price">
                  {{
                    formatCurrency(
                      Number(resolveEdmUnitPrice(item))
                    )
                  }}
                </div>
                <div class="edm-confirm-list__qty">
                  <span>{{ item.quantity || 0 }}</span>
                  <small v-if="getBundlePayableHint(item)">
                    {{ getBundlePayableHint(item) }}
                  </small>
                </div>
                <div class="edm-confirm-list__total">
                  {{
                    formatCurrency(
                      calculateEdmLineSubtotal(item, item.quantity)
                    )
                  }}
                </div>
              </div>
            </section>

            <div class="edm-confirm-aside">
              <aside class="edm-confirm-summary">
                <div class="edm-confirm-summary__header">
                  <span>{{ t('edm.confirm.summary.title') }}</span>
                  <span>{{ t('edm.confirm.summary.count', { count: totalQuantity }) }}</span>
                </div>
                <div class="edm-confirm-summary__row">
                  <span>{{ t('edm.confirm.summary.taxable') }}</span>
                  <strong>{{ formatCurrency(totalAmount) }}</strong>
                </div>
                <div class="edm-confirm-summary__divider"></div>
                <div class="edm-confirm-summary__total">
                  <span>{{ t('edm.confirm.summary.total') }}</span>
                  <strong>{{ formatCurrency(includedTaxTotal) }}</strong>
                </div>
                <button class="edm-confirm-submit" type="button" @click="handleSubmit">
                  {{ t('edm.confirm.submit') }}
                </button>
              </aside>
              <p class="edm-confirm-summary__note">
                {{ t('edm.confirm.note') }}
              </p>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="edm-complete">
            <div class="edm-complete__top">
              <div>
                <h1>{{ t('edm.complete.title') }}</h1>
                <p>{{ t('edm.complete.subtitle') }}</p>
                <p>{{ t('edm.complete.note') }}</p>
              </div>
              <button class="edm-complete__download" type="button" @click="downloadPdf">
                {{ t('edm.complete.download') }}
              </button>
            </div>

            <div class="edm-complete__grid">
              <aside class="edm-complete__info">
                <div class="edm-complete__info-row">
                  <span>{{ t('edm.complete.info.order_no') }}</span>
                  <strong>{{ completedSummary.quote_no }}</strong>
                </div>
                <div class="edm-complete__info-row">
                  <span>{{ t('edm.complete.info.order_date') }}</span>
                  <strong>{{ formatDateTime(completedSummary.created_at) }}</strong>
                </div>
                <div class="edm-complete__info-row">
                  <span>{{ t('edm.complete.info.order_amount') }}</span>
                  <strong>{{ formatCurrency(completedSummary.total_amount) }}</strong>
                </div>
                <div class="edm-complete__info-row">
                  <span>{{ t('edm.complete.info.total_qty') }}</span>
                  <strong>{{ t('edm.units.bottle', { count: completedSummary.total_qty }) }}</strong>
                </div>
                <div class="edm-complete__info-row">
                  <span>{{ t('edm.complete.info.sales_rep') }}</span>
                  <strong>{{ completedSummary.sales_rep }}</strong>
                </div>
                <div class="edm-complete__info-row">
                  <span>{{ t('edm.complete.info.contact_phone') }}</span>
                  <strong>{{ completedSummary.contact_phone }}</strong>
                </div>
              </aside>

              <section class="edm-complete__table">
                <div class="edm-complete__table-header">
                  <span>{{ t('edm.complete.table.sku') }}</span>
                  <span>{{ t('edm.complete.table.product') }}</span>
                  <span>{{ t('edm.complete.table.color') }}</span>
                  <span>{{ t('edm.complete.table.quantity') }}</span>
                  <span>{{ t('edm.complete.table.subtotal') }}</span>
                </div>
                <div
                  v-for="item in confirmationItems"
                  :key="resolveValue(item, ['no', 'sku', 'id', 'barcode'])"
                  class="edm-complete__table-row"
                >
                  <span>{{ resolveValue(item, ['no', 'sku', 'id'], '-') }}</span>
                  <span>{{ resolveValue(item, ['product', 'name', 'title'], '-') }}</span>
                  <span class="edm-complete__color">
                    <img
                      class="edm-complete__color-icon"
                      :src="resolveColorIcon(resolveValue(item, ['color'], '-'))"
                      :alt="resolveValue(item, ['color'], '-')"
                    />
                    {{ resolveValue(item, ['color'], '-') }}
                  </span>
                  <span>{{ t('edm.units.bottle', { count: item.quantity || 0 }) }}</span>
                  <span>
                    {{
                      formatCurrency(
                        calculateEdmLineSubtotal(item, item.quantity)
                      )
                    }}
                  </span>
                </div>
                <div class="edm-complete__table-total">
                  <div>
                    <span>{{ t('edm.confirm.summary.taxable') }}</span>
                    <strong>{{ formatCurrency(totalAmount) }}</strong>
                  </div>
                  <div>
                    <span>{{ t('edm.confirm.summary.total') }}</span>
                    <strong>{{ formatCurrency(includedTaxTotal) }}</strong>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </template>
      </section>
    </section>

    <footer class="edm-v1__disclaimer">
      <div class="edm-v1__disclaimer-row">
        <svg class="edm-v1__disclaimer-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="m3 19 5.2-8.2L12 16l2.7-4.2L21 19H3Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
          <path d="m8.2 10.8 2-3.2 1.8 2.8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <div>
          <strong>登山安全提醒</strong>
          <p>登山前請確認官方天氣、步道及道路公告；依天候、路況與個人能力準備裝備，並告知同行者行程。</p>
        </div>
      </div>
    </footer>
  </main>
</template>

<style src="../edm-style.css" scoped></style>
