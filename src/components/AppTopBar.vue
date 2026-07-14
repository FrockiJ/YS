<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Command, Menu, Plus, Search, X } from 'lucide-vue-next'

const { t } = useI18n()

const props = defineProps({
  logoSrc: { type: String, required: true },
  logoAlt: { type: String, default: '' },
  isCompactSidebar: { type: Boolean, default: false },
  isSidebarCollapsed: { type: Boolean, default: false },
  hamburgerIcon: { type: String, required: true },
  menuAriaLabel: { type: String, default: '' },
  avatarLabel: { type: String, default: '' },
  avatarAriaLabel: { type: String, default: '' },
})

const emit = defineEmits(['toggle-sidebar', 'logo-click', 'logout'])
const rootRef = ref(null)
const isOpen = ref(false)

const resolvedMenuAriaLabel = computed(() => props.menuAriaLabel || t('app.topbar.menu_aria'))

const openPanel = () => {
  isOpen.value = true
}

const closePanel = () => {
  isOpen.value = false
}

const togglePanel = () => {
  isOpen.value = !isOpen.value
}

const handleDocumentClick = (event) => {
  if (!isOpen.value) return
  if (rootRef.value?.contains(event.target)) return
  closePanel()
}

const handleKeydown = (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    openPanel()
    return
  }
  if (event.key === 'Escape') closePanel()
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleKeydown)
})

defineExpose({ getElement: () => rootRef.value })
</script>

<template>
  <header class="top-bar command-bubble" ref="rootRef" :class="{ 'is-open': isOpen }">
    <button
      v-if="isCompactSidebar"
      class="icon-button command-bubble__menu"
      type="button"
      :aria-expanded="!isSidebarCollapsed"
      :aria-label="resolvedMenuAriaLabel"
      @click="emit('toggle-sidebar')"
    >
      <Menu aria-hidden="true" :size="21" :stroke-width="1.9" />
    </button>

    <button
      type="button"
      class="command-bubble__trigger"
      :aria-label="isOpen ? t('app.command.close') : t('app.command.open')"
      :aria-expanded="isOpen"
      @click="togglePanel"
    >
      <span class="command-bubble__mark">
        <Search v-if="!isOpen" aria-hidden="true" :size="20" :stroke-width="2.1" />
        <X v-else aria-hidden="true" :size="20" :stroke-width="2.1" />
      </span>
      <span class="command-bubble__copy">
        <strong>{{ t('app.command.title') }}</strong>
        <small>{{ t('app.command.search') }}</small>
      </span>
    </button>

    <div v-if="isOpen" class="command-panel">
      <div class="command-panel__header">
        <div>
          <p class="command-panel__eyebrow">
            <Command :size="15" :stroke-width="2" aria-hidden="true" />
            {{ t('app.command.title') }}
          </p>
          <h2>{{ t('app.command.subtitle') }}</h2>
        </div>
        <button type="button" class="command-panel__new" @click="emit('logo-click')">
          <Plus :size="17" :stroke-width="2" aria-hidden="true" />
          {{ t('app.command.new_conversation') }}
        </button>
      </div>

      <div class="command-panel__search">
        <slot name="search" />
      </div>

      <slot name="command">
        <div class="command-panel__empty">
          <p>{{ t('app.command.empty') }}</p>
        </div>
      </slot>
    </div>
  </header>
</template>

<style scoped>
.command-bubble {
  position: sticky;
  top: 18px;
  z-index: 50;
  width: fit-content;
  max-width: calc(100% - 48px);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 18px auto 0;
  padding: 4px;
  border-radius: 999px;
  border: 1px solid rgba(27, 45, 41, 0.1);
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 8px 22px rgba(27, 45, 41, 0.1);
  backdrop-filter: blur(18px);
  transition:
    width 0.22s ease,
    padding 0.22s ease,
    background 0.22s ease,
    box-shadow 0.22s ease;
}

.command-bubble:hover,
.command-bubble:focus-within,
.command-bubble.is-open {
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 10px 28px rgba(27, 45, 41, 0.12);
}

.command-bubble__menu {
  flex-shrink: 0;
}

.command-bubble__trigger {
  width: 44px;
  min-width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  overflow: hidden;
  padding: 0;
  border-radius: 999px;
  color: #fff;
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
  border: 1px solid rgba(27, 45, 41, 0.08);
  transition:
    width 0.24s ease,
    gap 0.24s ease,
    padding 0.24s ease,
    border-color 0.2s ease,
    background 0.2s ease,
    transform 0.2s ease;
}

.command-bubble:hover .command-bubble__trigger,
.command-bubble:focus-within .command-bubble__trigger,
.command-bubble.is-open .command-bubble__trigger {
  width: min(238px, 46vw);
  justify-content: flex-start;
  gap: 12px;
  padding: 0 12px 0 4px;
}

.command-bubble__trigger:hover,
.command-bubble__trigger:focus-visible {
  border-color: rgba(220, 163, 58, 0.5);
  background: linear-gradient(135deg, #2f6f53, #dca33a);
  transform: translateY(-1px);
}

.command-bubble__mark {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  display: grid;
  place-items: center;
  border-radius: 50%;
}

.command-bubble__copy {
  display: grid;
  gap: 1px;
  max-width: 0;
  min-width: 0;
  opacity: 0;
  overflow: hidden;
  color: #fff;
  text-align: left;
  transition:
    max-width 0.24s ease,
    opacity 0.18s ease;
}

.command-bubble:hover .command-bubble__copy,
.command-bubble:focus-within .command-bubble__copy,
.command-bubble.is-open .command-bubble__copy {
  max-width: 152px;
  opacity: 1;
}

.command-bubble__copy strong,
.command-bubble__copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-bubble__copy strong {
  font-size: 13px;
  font-weight: 900;
}

.command-bubble__copy small {
  color: rgba(255, 255, 255, 0.74);
  font-size: 12px;
  font-weight: 760;
}

.command-panel {
  position: absolute;
  top: calc(100% + 12px);
  left: 50%;
  width: min(760px, calc(100vw - 36px));
  transform: translateX(-50%);
  display: grid;
  gap: 16px;
  padding: 18px;
  border-radius: 28px;
  border: 1px solid rgba(27, 45, 41, 0.12);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 9px 24px rgba(16, 36, 31, 0.16);
}

.command-panel__header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
}

.command-panel__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
  color: #d18f24;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.command-panel__header h2 {
  max-width: 480px;
  margin: 0;
  color: #10241f;
  font-size: 20px;
  line-height: 1.35;
}

.command-panel__new {
  height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  border-radius: 999px;
  color: #fff;
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
  font-weight: 900;
}

.command-panel__search :deep(.search-field) {
  width: 100%;
  min-height: 52px;
}

.command-panel__empty {
  display: grid;
  place-items: center;
  min-height: 84px;
  border: 1px dashed rgba(31, 75, 57, 0.24);
  border-radius: 18px;
  color: #64766f;
  background: #f7f9f6;
}

.command-panel__empty p {
  margin: 0;
  font-size: 13px;
}

@media (max-width: 720px) {
  .command-bubble {
    max-width: calc(100% - 24px);
    gap: 6px;
    margin-top: 12px;
  }

  .command-bubble__trigger {
    min-width: 0;
    width: 44px;
    padding: 0;
    justify-content: center;
  }

  .command-bubble:hover .command-bubble__trigger,
  .command-bubble:focus-within .command-bubble__trigger,
  .command-bubble.is-open .command-bubble__trigger {
    width: 44px;
    gap: 0;
    padding: 0;
  }

  .command-bubble__copy {
    display: none;
  }

  .command-panel__header {
    display: grid;
  }
}
</style>
