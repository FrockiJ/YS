<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Languages } from 'lucide-vue-next'

import { normalizeLocale, supportedLocales } from '../i18n'

const { locale, t } = useI18n()

const props = defineProps({
  compact: { type: Boolean, default: false },
  mode: { type: String, default: 'inline' },
})

const rootRef = ref(null)
const isMenuOpen = ref(false)

const localeLabels = computed(() => ({
  'zh-TW': props.compact ? t('app.locale.zh') : t('app.locale.zh_long'),
  en: props.compact ? t('app.locale.en') : t('app.locale.en_long'),
  ja: props.compact ? t('app.locale.ja') : t('app.locale.ja_long'),
}))

const menuLocaleLabels = computed(() => ({
  'zh-TW': t('app.locale.zh_long'),
  en: t('app.locale.en_long'),
  ja: t('app.locale.ja_long'),
}))

const activeLocale = computed(() => normalizeLocale(locale.value))
const activeLocaleLabel = computed(() => localeLabels.value[activeLocale.value] || activeLocale.value)
const isMenuMode = computed(() => props.mode === 'menu')

const setLocale = (value) => {
  const next = normalizeLocale(value)
  locale.value = next
  if (typeof window !== 'undefined') {
    window.localStorage.setItem('ys-locale', next)
    document.documentElement.lang = next
  }
  isMenuOpen.value = false
}

const toggleMenu = () => {
  isMenuOpen.value = !isMenuOpen.value
}

const closeMenu = () => {
  isMenuOpen.value = false
}

const handleDocumentClick = (event) => {
  if (!isMenuOpen.value) return
  if (rootRef.value?.contains(event.target)) return
  closeMenu()
}

const handleKeydown = (event) => {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div
    ref="rootRef"
    class="locale-switcher"
    :class="{ 'is-compact': compact, 'is-menu': isMenuMode, 'is-open': isMenuOpen }"
    :aria-label="t('app.locale.label')"
  >
    <template v-if="isMenuMode">
      <button
        type="button"
        class="locale-switcher__trigger"
        :aria-label="t('app.locale.label')"
        :aria-expanded="isMenuOpen"
        aria-haspopup="menu"
        @click="toggleMenu"
      >
        <Languages aria-hidden="true" :size="19" :stroke-width="2" />
        <span>{{ activeLocaleLabel }}</span>
      </button>
      <div v-if="isMenuOpen" class="locale-switcher__menu" role="menu">
        <button
          v-for="item in supportedLocales"
          :key="item"
          type="button"
          class="locale-switcher__menu-option"
          :class="{ 'is-active': activeLocale === item }"
          role="menuitemradio"
          :aria-checked="activeLocale === item"
          @click="setLocale(item)"
        >
          <span>{{ menuLocaleLabels[item] }}</span>
          <Check
            v-if="activeLocale === item"
            class="locale-switcher__check"
            aria-hidden="true"
            :size="16"
            :stroke-width="2.2"
          />
        </button>
      </div>
    </template>
    <template v-else>
      <button
        v-for="item in supportedLocales"
        :key="item"
        type="button"
        class="locale-switcher__option"
        :class="{ 'is-active': activeLocale === item }"
        :aria-pressed="activeLocale === item"
        @click="setLocale(item)"
      >
        {{ localeLabels[item] }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.locale-switcher {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid rgba(27, 45, 41, 0.1);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
}

.locale-switcher.is-menu {
  padding: 0;
  border: 0;
  background: transparent;
}

.locale-switcher__trigger {
  width: 76px;
  min-height: 42px;
  display: grid;
  place-items: center;
  gap: 2px;
  border-radius: 16px;
  color: rgba(255, 255, 255, 0.82);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.locale-switcher__trigger span {
  max-width: 58px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
}

.locale-switcher__trigger:hover,
.locale-switcher__trigger:focus-visible,
.locale-switcher.is-open .locale-switcher__trigger {
  color: #10241f;
  background: linear-gradient(135deg, #f4d48a, #9fbea8);
}

.locale-switcher__menu {
  position: fixed;
  left: 128px;
  bottom: 188px;
  width: 184px;
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: 16px;
  border: 1px solid rgba(27, 45, 41, 0.12);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 10px 28px rgba(16, 36, 31, 0.18);
  z-index: 90;
}

.locale-switcher__menu-option {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 10px;
  border-radius: 11px;
  color: #1b2d29;
  font-size: 13px;
  font-weight: 850;
  text-align: left;
}

.locale-switcher__menu-option:hover,
.locale-switcher__menu-option:focus-visible {
  color: #6c4300;
  background: #fff3d4;
}

.locale-switcher__menu-option.is-active {
  color: #10241f;
  background: #eaf3ec;
}

.locale-switcher__check {
  flex-shrink: 0;
  color: #2f6f53;
}

.locale-switcher__option {
  min-width: 44px;
  height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  color: #466779;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
}

.locale-switcher.is-compact .locale-switcher__option {
  min-width: 34px;
  height: 28px;
  padding: 0 8px;
}

.locale-switcher__option:hover,
.locale-switcher__option:focus-visible {
  color: #10241f;
  background: #fff3d4;
}

.locale-switcher__option.is-active {
  color: #fff;
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
}

@media (max-width: 720px) {
  .locale-switcher__menu {
    left: 16px;
    right: 16px;
    bottom: 176px;
    width: auto;
  }
}
</style>
