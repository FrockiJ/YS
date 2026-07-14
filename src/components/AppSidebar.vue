<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Files,
  Fish,
  MessagesSquare,
  Mountain,
  Settings2,
  TentTree,
  UsersRound,
} from 'lucide-vue-next'
import AccountMenu from './AccountMenu.vue'
import LocaleSwitcher from './LocaleSwitcher.vue'

const { t } = useI18n()
const props = defineProps({
  logoSrc: { type: String, required: true },
  navItems: { type: Array, required: true },
  iconImages: { type: Object, required: true },
  arrowIconSrc: { type: String, required: true },
  activeNavId: { type: String, required: true },
  sideMenu: { type: Object, default: null },
  sideMenuOpen: { type: Boolean, default: false },
  ariaLabel: { type: String, default: '' },
})

const emit = defineEmits(['logo-click', 'nav-click'])

const handleLogoClick = () => {
  emit('logo-click')
}

const handleNavClick = (item) => {
  if (!item?.route) return
  emit('nav-click', item)
}

const isActive = (id) => id === props.activeNavId
const resolvedAriaLabel = computed(() => props.ariaLabel || t('app.sidebar.aria'))
const isSideMenuVisible = (id) =>
  props.sideMenu && props.sideMenuOpen && props.sideMenu.anchorId === id
const shouldShowAnchor = (id) => isActive(id) || isSideMenuVisible(id)
const utilityNavIds = new Set(['permission', 'settings'])
const primaryNavItems = computed(() => props.navItems.filter((item) => !utilityNavIds.has(item.id)))
const utilityNavItems = computed(() => props.navItems.filter((item) => utilityNavIds.has(item.id)))

const navIconComponents = {
  chat: MessagesSquare,
  folder: Mountain,
  display: TentTree,
  quote: Fish,
  file: Files,
  team: UsersRound,
  settings: Settings2,
}

const resolveNavIcon = (icon) => navIconComponents[icon] || MessagesSquare
</script>

<template>
  <aside class="sidebar" :aria-label="resolvedAriaLabel">
    <div class="sidebar__header">
      <img
        :src="logoSrc"
        class="sidebar__logo"
        :alt="t('app.sidebar.logo_alt')"
        role="button"
        tabindex="0"
        @click="handleLogoClick"
      />
    </div>
    <nav class="sidebar__nav" role="navigation">
      <template v-for="item in primaryNavItems" :key="item.id">
        <button
          class="sidebar__item"
          :class="{ 'is-active': isActive(item.id) }"
          type="button"
          :aria-current="isActive(item.id) ? 'page' : undefined"
          :aria-disabled="item.route ? undefined : 'true'"
          @click="handleNavClick(item)"
        >
          <div class="sidebar__item-icon">
            <component
              :is="resolveNavIcon(item.icon)"
              class="sidebar__icon"
              aria-hidden="true"
              :stroke-width="1.8"
            />
            <span
              v-if="shouldShowAnchor(item.id)"
              class="sidebar__arrow-wrap"
              aria-hidden="true"
            >
              <img :src="arrowIconSrc" class="sidebar__arrow" alt="" aria-hidden="true" />
              <div
                v-if="isSideMenuVisible(item.id)"
                class="account-side-menu"
                role="presentation"
                aria-hidden="true"
              >
                <span
                  v-for="entry in sideMenu.items"
                  :key="entry.id"
                  class="account-side-menu__item"
                  :class="{ 'is-active': entry.isActive }"
                  role="button"
                  tabindex="0"
                  @click.stop="entry.onClick?.()"
                  @keydown.enter.stop.prevent="entry.onClick?.()"
                >
                  {{ entry.label }}
                </span>
              </div>
            </span>
          </div>
          <span class="sidebar__label">{{ item.label }}</span>
        </button>
        <span
          v-if="item.dividerAfter"
          :key="`${item.id}-divider`"
          class="sidebar__divider"
          role="presentation"
          aria-hidden="true"
        />
      </template>
    </nav>
    <div class="sidebar__footer">
      <LocaleSwitcher compact mode="menu" class="sidebar__locale" />
      <div v-if="utilityNavItems.length" class="sidebar__utility-group">
        <button
          v-for="item in utilityNavItems"
          :key="`utility-${item.id}`"
          class="sidebar__item sidebar__utility-item"
          :class="{ 'is-active': isActive(item.id) }"
          type="button"
          :aria-current="isActive(item.id) ? 'page' : undefined"
          :aria-disabled="item.route ? undefined : 'true'"
          @click="handleNavClick(item)"
        >
          <div class="sidebar__item-icon">
            <component
              :is="resolveNavIcon(item.icon)"
              class="sidebar__icon"
              aria-hidden="true"
              :stroke-width="1.8"
            />
            <span
              v-if="shouldShowAnchor(item.id)"
              class="sidebar__arrow-wrap"
              aria-hidden="true"
            >
              <img :src="arrowIconSrc" class="sidebar__arrow" alt="" aria-hidden="true" />
              <div
                v-if="isSideMenuVisible(item.id)"
                class="account-side-menu"
                role="presentation"
                aria-hidden="true"
              >
                <span
                  v-for="entry in sideMenu.items"
                  :key="entry.id"
                  class="account-side-menu__item"
                  :class="{ 'is-active': entry.isActive }"
                  role="button"
                  tabindex="0"
                  @click.stop="entry.onClick?.()"
                  @keydown.enter.stop.prevent="entry.onClick?.()"
                >
                  {{ entry.label }}
                </span>
              </div>
            </span>
          </div>
          <span class="sidebar__label">{{ item.label }}</span>
        </button>
      </div>
      <AccountMenu placement="sidebar" />
    </div>
  </aside>
</template>
