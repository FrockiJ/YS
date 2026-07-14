import { computed, ref, unref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  canAccessRolesSection,
  canAccessUsersSection,
  resolveAccessibleAccountSection,
} from '../utils/accessControl'

const SECTION_ROLES = 'roles'
const SECTION_USERS = 'users'

export const usePermissionSideMenu = ({
  userProfile,
  isTablet = false,
  isSidebarCollapsed = false,
  sectionLabels = null,
} = {}) => {
  const router = useRouter()
  const route = useRoute()
  const { t } = useI18n()
  const sideMenuOpen = ref(false)

  const resolvedSectionLabels = computed(() => {
    const customLabels = unref(sectionLabels)
    return {
      [SECTION_ROLES]: t('account.sections.roles'),
      [SECTION_USERS]: t('account.sections.users'),
      ...(customLabels && typeof customLabels === 'object' ? customLabels : {}),
    }
  })

  const availableSections = computed(() => {
    const sections = []
    if (canAccessRolesSection(userProfile?.value)) {
      sections.push({ id: SECTION_ROLES, label: resolvedSectionLabels.value[SECTION_ROLES] })
    }
    if (canAccessUsersSection(userProfile?.value)) {
      sections.push({ id: SECTION_USERS, label: resolvedSectionLabels.value[SECTION_USERS] })
    }
    return sections
  })

  const currentSection = computed(() => {
    if (route.name !== 'account') return null
    return resolveAccessibleAccountSection(userProfile?.value, route.query.section)
  })

  const buildSectionRoute = (sectionId) => {
    if (route.name === 'account') {
      return { name: 'account', query: { ...route.query, section: sectionId } }
    }
    return { name: 'account', query: { section: sectionId } }
  }

  const closePermissionMenu = () => {
    sideMenuOpen.value = false
  }

  const handlePermissionMenuSelect = (sectionId) => {
    closePermissionMenu()
    if (!sectionId) return
    const currentQuerySection = String(route.query.section || '').trim().toLowerCase()
    if (route.name === 'account' && currentQuerySection === sectionId) return
    router.push(buildSectionRoute(sectionId))
  }

  const handlePermissionNavClick = () => {
    if (!availableSections.value.length) return true

    if (
      availableSections.value.length === 1 ||
      unref(isTablet) ||
      unref(isSidebarCollapsed)
    ) {
      handlePermissionMenuSelect(availableSections.value[0].id)
      return true
    }

    sideMenuOpen.value = !sideMenuOpen.value
    return true
  }

  const sideMenu = computed(() => {
    if (availableSections.value.length <= 1 || unref(isTablet)) return null
    return {
      anchorId: 'permission',
      items: availableSections.value.map((section) => ({
        id: section.id,
        label: section.label,
        isActive: route.name === 'account' && currentSection.value === section.id,
        onClick: () => handlePermissionMenuSelect(section.id),
      })),
    }
  })

  watch(
    [() => route.fullPath, () => unref(isTablet), () => unref(isSidebarCollapsed), availableSections],
    ([fullPath, tablet, collapsed, sections], [previousFullPath]) => {
      if (fullPath !== previousFullPath || tablet || collapsed || sections.length <= 1) {
        closePermissionMenu()
      }
    }
  )

  return {
    availablePermissionSections: availableSections,
    currentPermissionSection: currentSection,
    sideMenu,
    sideMenuOpen,
    closePermissionMenu,
    handlePermissionNavClick,
    handlePermissionMenuSelect,
  }
}
