<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import logoMain from '../assets/ysLogo_transparent.png'
import iconArrowIndicator from '../assets/ic-arrow.svg'
import emptyIllustration from '../assets/label_illustration_empty_content.svg'
import AppSidebar from '../components/AppSidebar.vue'
import AppTopBar from '../components/AppTopBar.vue'
import { usePermissionSideMenu } from '../composables/usePermissionSideMenu'
import { buildPrimaryNavItems, PRIMARY_NAV_ICON_IMAGES } from '../utils/appNavigation'
import {
  deletePrintListItem,
  fetchPrintList,
  regenerateLabelDescription,
  resetPrintList,
  updateLabelDescription,
} from '../services/ysApi'

const router = useRouter()
const { t } = useI18n()
const { isAuthenticated, userProfile } = useAuth()

const navItems = computed(() => buildPrimaryNavItems(t, userProfile.value, 'home.nav'))

const iconImages = PRIMARY_NAV_ICON_IMAGES

const activeNavId = ref('showcase')
const isLoading = ref(false)
const printItems = ref([])
const alwaysExpandedSidebar = computed(() => false)
const { sideMenu, sideMenuOpen, closePermissionMenu, handlePermissionNavClick } =
  usePermissionSideMenu({
    userProfile,
    isTablet: alwaysExpandedSidebar,
    isSidebarCollapsed: alwaysExpandedSidebar,
  })

const isEditModalOpen = ref(false)
const editItem = ref(null)
const editPrice = ref('')
const editDescription = ref('')
const editInstruction = ref('')
const isRegenerating = ref(false)
const isSaving = ref(false)

const LABEL_LANG = 'zh-TW'
const MAX_DESC = 220

const glyphs = {
  search:
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5" stroke="#7a879c" stroke-width="2"/><path d="M12.5 12.5 16 16" stroke="#7a879c" stroke-width="2" stroke-linecap="round"/></svg>',
  hamburger:
    '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5h14M3 10h14M3 15h14" stroke="#263847" stroke-width="2" stroke-linecap="round"/></svg>',
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

const resolveProductCode = (item) => (item?.code || '').toString().trim()
const resolveProduct = (item) => item?.product_snapshot || {}
const resolveProductName = (item) => {
  const product = resolveProduct(item)
  return (
    product?.name_en ||
    product?.name_ch ||
    product?.name ||
    product?.invn005 ||
    product?.title ||
    ''
  ).toString().trim()
}

const resolveProducer = (item) => {
  const product = resolveProduct(item)
  return (product?.producer || product?.invn006 || '').toString().trim()
}

const resolveVintage = (item) => {
  const product = resolveProduct(item)
  const raw = (product?.vintage || product?.invn051 || '').toString().trim()
  return raw || 'NV'
}

const resolveRegion = (item) => {
  const product = resolveProduct(item)
  return (product?.region || product?.invn030 || '').toString().trim()
}

const resolveRating = (item) => {
  const product = resolveProduct(item)
  return (product?.rating || product?.invn804 || product?.invn805 || '').toString().trim()
}

const formatPrice = (value) => {
  const number = Number(String(value ?? '').replace(/,/g, ''))
  if (Number.isNaN(number) || number <= 0) return ''
  return `$${number.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

const resolvePriceText = (item) => {
  if (item?.price_override && item.price_override > 0) {
    return formatPrice(item.price_override)
  }
  const product = resolveProduct(item)
  const listPrice = product?.list_price ?? product?.invn013
  const fallbackPrice = product?.price ?? product?.invn015
  return formatPrice(listPrice ?? fallbackPrice)
}

const normalizePriceInput = (value) => {
  const raw = String(value ?? '').replace(/[^\d]/g, '')
  if (!raw) return null
  const number = Number(raw)
  if (Number.isNaN(number) || number <= 0) return null
  return number
}

const loadPrintList = async () => {
  if (!isAuthenticated.value) {
    printItems.value = []
    return
  }
  isLoading.value = true
  try {
    const response = await fetchPrintList(LABEL_LANG)
    printItems.value = response?.items || []
  } catch (error) {
    console.error('Fetch print list failed', error)
  } finally {
    isLoading.value = false
  }
}

const handleReset = async () => {
  if (!isAuthenticated.value) return
  try {
    await resetPrintList()
    printItems.value = []
  } catch (error) {
    console.error('Reset print list failed', error)
  }
}

const handleDelete = async (item) => {
  if (!item?.id) return
  try {
    await deletePrintListItem(item.id)
    await loadPrintList()
  } catch (error) {
    console.error('Delete print item failed', error)
  }
}

const openEditModal = (item) => {
  if (!item) return
  editItem.value = item
  editPrice.value = resolvePriceText(item)
  editDescription.value = (item.description || '').slice(0, MAX_DESC)
  editInstruction.value = ''
  isEditModalOpen.value = true
}

const closeEditModal = () => {
  if (isSaving.value) return
  isEditModalOpen.value = false
}

const handleRegenerate = async () => {
  if (!editItem.value || isRegenerating.value) return
  const instruction = editInstruction.value.trim()
  if (!instruction) return
  const code = resolveProductCode(editItem.value)
  if (!code) return
  const parsedPrice = normalizePriceInput(editPrice.value)
  if (!parsedPrice) return
  isRegenerating.value = true
  try {
    const response = await regenerateLabelDescription({
      code,
      lang: LABEL_LANG,
      instruction,
      priceOverride: parsedPrice,
    })
    editDescription.value = (response?.description || '').slice(0, MAX_DESC)
    editInstruction.value = ''
  } catch (error) {
    console.error('Regenerate label description failed', error)
  } finally {
    isRegenerating.value = false
  }
}

const handleConfirmEdit = async () => {
  if (!editItem.value || isSaving.value) return
  const code = resolveProductCode(editItem.value)
  const parsedPrice = normalizePriceInput(editPrice.value)
  if (!parsedPrice) return
  const nextDescription = (editDescription.value || '').slice(0, MAX_DESC)
  isSaving.value = true
  try {
    const response = await updateLabelDescription({
      code,
      lang: LABEL_LANG,
      description: nextDescription,
      priceOverride: parsedPrice,
    })
    const updated = {
      ...editItem.value,
      description: response?.description || nextDescription,
      price_override: response?.price_override ?? parsedPrice,
    }
    printItems.value = printItems.value.map((item) =>
      item.id === updated.id ? updated : item
    )
    isEditModalOpen.value = false
  } catch (error) {
    console.error('Update label description failed', error)
  } finally {
    isSaving.value = false
  }
}

const resolveSizeLabel = (size) => {
  if (size === 'small') return t('labelSettings.sizeSmall')
  if (size === 'medium') return t('labelSettings.sizeMedium')
  return t('labelSettings.sizeLarge')
}

const handlePrint = () => {
  // Placeholder: future print action
}

onMounted(() => {
  loadPrintList()
})
</script>

<template>
  <div class="app-shell">
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
        :is-compact-sidebar="false"
        :is-sidebar-collapsed="false"
        :hamburger-icon="glyphs.hamburger"
        :menu-aria-label="t('home.aria.toggle_menu')"
        :avatar-aria-label="t('home.aria.open_account_menu')"
        @toggle-sidebar="() => {}"
        @logo-click="handleLogoClick"
      >
        <template #search>
          <label class="search-field">
            <span class="search-field__icon" v-html="glyphs.search" aria-hidden="true" />
            <input type="search" :placeholder="t('home.placeholders.search')" />
          </label>
        </template>
      </AppTopBar>

      <main class="stage-canvas label-print-stage">
        <div class="label-print__content">
          <header class="label-print__header">
            <h1>{{ t('labelPrint.title') }}</h1>
          </header>

          <section v-if="isLoading" class="label-print__loading">
            {{ t('labelPrint.loading') }}
          </section>

          <section v-else-if="!printItems.length" class="label-print__empty">
            <img :src="emptyIllustration" alt="" />
            <p>{{ t('labelPrint.empty') }}</p>
          </section>

          <section v-else class="label-print__list">
            <article v-for="item in printItems" :key="item.id" class="label-print-card">
              <div class="label-print-card__header">
                <div class="label-print-card__title">
                  <span class="label-chip">{{ resolveSizeLabel(item.size) }}</span>
                  <span class="label-print-card__code">{{ resolveProductCode(item) }}</span>
                </div>
                <div class="label-print-card__actions">
                  <button type="button" @click="openEditModal(item)" aria-label="Edit">
                    <svg viewBox="0 0 20 20" aria-hidden="true">
                      <path
                        fill-rule="evenodd"
                        clip-rule="evenodd"
                        d="M13.8836 3.83371L16.1669 6.11704C16.8052 6.72518 16.8313 7.73509 16.2253 8.37537L8.72525 15.8754C8.45361 16.1447 8.09758 16.3125 7.71692 16.3504L4.24192 16.667H4.16692C3.94542 16.6683 3.73252 16.5814 3.57525 16.4254C3.39945 16.2502 3.31086 16.0058 3.33358 15.7587L3.69192 12.2837C3.72984 11.903 3.89756 11.547 4.16692 11.2754L11.6669 3.77537C12.3134 3.22916 13.2667 3.25425 13.8836 3.83371ZM11.1003 6.66715L13.3336 8.90049L15.0003 7.27549L12.7253 5.00049L11.1003 6.66715Z"
                        fill="#637381"
                      />
                    </svg>
                  </button>
                  <button type="button" @click="handleDelete(item)" aria-label="Delete">
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
                  <div class="label-preview__price">{{ resolvePriceText(item) }}</div>
                  <div class="label-preview__body">
                    <div class="label-preview__producer">{{ resolveProducer(item) }}</div>
                    <div class="label-preview__name">{{ resolveProductName(item) }}</div>
                  </div>
                  <div v-if="item.size === 'small'" class="label-preview__meta">
                    <div>??{{ resolveVintage(item) }}</div>
                    <div>??{{ resolveRegion(item) || '-' }}</div>
                  </div>
                  <div v-else-if="item.size === 'medium'" class="label-preview__meta">
                    <div>??{{ resolveRating(item) || '-' }}</div>
                    <div>??{{ resolveVintage(item) }}</div>
                    <div>??{{ resolveRegion(item) || '-' }}</div>
                  </div>
                  <div v-else class="label-preview__details">
                    <span class="label-preview__detail label-preview__detail--rating">
                      {{ resolveRating(item) || '-' }}
                    </span>
                    <div class="label-preview__details-group">
                      <span class="label-preview__divider"></span>
                      <span class="label-preview__detail label-preview__detail--vintage">
                        {{ resolveVintage(item) }}
                      </span>
                      <span class="label-preview__divider"></span>
                      <span class="label-preview__detail label-preview__detail--region">
                        {{ resolveRegion(item) || '-' }}
                      </span>
                    </div>
                  </div>
                  <div v-if="item.size === 'large'" class="label-preview__description">
                    {{ (item.description || '').slice(0, MAX_DESC) }}
                  </div>
                </div>
              </div>
            </article>
          </section>
        </div>

        <div v-if="printItems.length" class="label-print__footer">
          <button class="label-button label-button--outline" type="button" @click="handleReset">
            {{ t('labelPrint.reset') }}
          </button>
          <button class="label-button label-button--primary" type="button" @click="handlePrint">
            {{ t('labelPrint.print') }}
          </button>
        </div>
      </main>
    </div>
  </div>

  <div v-if="isEditModalOpen" class="label-edit-modal">
    <div class="label-edit-modal__backdrop" @click="closeEditModal"></div>
    <div class="label-edit-modal__card" role="dialog" aria-modal="true">
      <header class="label-edit-modal__header">
        <h3>{{ t('labelSettings.editDialogTitle') }}</h3>
        <button class="label-edit-modal__close" type="button" @click="closeEditModal">?</button>
      </header>
      <div class="label-edit-modal__divider"></div>
      <section class="label-edit-modal__body">
        <div class="label-edit-modal__field label-edit-modal__field--price">
          <label class="label-edit-modal__label">{{ t('labelSettings.priceLabel') }}</label>
          <div class="label-edit-modal__price">
            <span class="label-edit-modal__currency">NT$</span>
            <input type="text" v-model="editPrice" />
          </div>
        </div>

        <div class="label-edit-modal__field label-edit-modal__field--description">
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
                  <path d="M4 4L20 12L4 20L8 12L4 4Z" fill="currentColor" />
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
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Public+Sans:wght@400;600;700&display=swap');

.label-print-stage {
  width: 100%;
  padding: 32px 40px 120px;
  font-family: 'Public Sans', 'Noto Sans TC', sans-serif;
}

.label-print__content {
  max-width: 1356px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.label-print__header h1 {
  margin: 0;
  font-size: 24px;
  line-height: 36px;
  font-weight: 700;
  color: #212b36;
}

.label-print__loading {
  font-size: 14px;
  color: #637381;
}

.label-print__empty {
  height: 520px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 6px 14px -4px rgba(145, 158, 171, 0.1), 0 0 2px rgba(145, 158, 171, 0.18);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #919eab;
}

.label-print__empty img {
  width: 220px;
  height: auto;
}

.label-print__list {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.label-print-card {
  background: #ffffff;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 6px 14px -4px rgba(145, 158, 171, 0.1), 0 0 2px rgba(145, 158, 171, 0.18);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.label-print-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.label-print-card__title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.label-print-card__code {
  color: #637381;
  font-size: 14px;
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
  border: 1px dashed rgba(145, 158, 171, 0.48);
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
  max-width: 70%;
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

.label-preview__price {
  position: absolute;
  right: 20px;
  bottom: 20px;
  font-weight: 700;
  font-size: 20px;
  line-height: 24px;
  text-align: right;
}

.label-preview__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 15px;
  line-height: 20px;
  margin-top: auto;
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
  padding: 24px;
  gap: 20px;
}

.label-preview--large .label-preview__price {
  top: 24px;
  right: 24px;
  bottom: auto;
  font-size: 24px;
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

.label-preview--large .label-preview__price {
  top: 24px;
  right: 24px;
  bottom: auto;
  font-size: 24px;
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
}

.label-preview__details-group {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-left: auto;
}

.label-preview__divider {
  width: 1px;
  height: 16px;
  background: rgba(22, 62, 97, 0.32);
}

.label-preview__detail--vintage,
.label-preview__detail--region {
  width: 141px;
  flex: 0 0 141px;
}

.label-preview__description {
  font-size: 16px;
  line-height: 26px;
}

.label-print__footer {
  position: fixed;
  bottom: 0;
  right: 0;
  left: 88px;
  height: 68px;
  padding: 16px 24px;
  border-top: 1px solid rgba(145, 158, 171, 0.24);
  background: #ffffff;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
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
}

.label-button--outline {
  border: 1px solid rgba(145, 158, 171, 0.32);
  background: #ffffff;
  color: #212b36;
}

.label-button--primary {
  background: #55b77f;
  color: #ffffff;
  font-weight: 700;
}

.label-chip {
  height: 24px;
  padding: 3px 6px;
  background: #55b77f;
  border-radius: 50px;
  color: #ffffff;
  font-size: 13px;
  line-height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
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

.label-edit-modal__description-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
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

.label-edit-modal__footer {
  height: 84px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 24px;
  gap: 12px;
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
</style>
