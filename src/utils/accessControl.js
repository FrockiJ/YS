import { isModuleEnabled } from '../core/moduleRegistry'

export const PERMISSIONS = Object.freeze({
  chat: 'admin.chat.access',
  projects: 'admin.projects.access',
  labels: 'admin.labels.access',
  files: 'admin.files.access',
  usersRead: 'admin.users.read',
  usersWrite: 'admin.users.write',
  rolesManage: 'admin.roles.manage',
  permissionsManage: 'admin.permissions.manage',
  settings: 'admin.settings.access',
})

export const normalizePermissionCodes = (permissions = []) => {
  const normalized = new Set()
  for (const entry of permissions || []) {
    const code =
      typeof entry === 'string'
        ? entry
        : typeof entry?.code === 'string'
          ? entry.code
          : ''
    const value = code.trim()
    if (value) {
      normalized.add(value)
    }
  }
  return normalized
}

const isPlatformSuperuser = (profile) => {
  const username = String(profile?.username || '').trim().toLowerCase()
  const roleName = String(profile?.role || '').trim().toLowerCase()
  return Boolean(profile?.is_platform_superuser) || username === 'frocki' || roleName === 'sadmin'
}

const getEffectivePermissionCodes = (profile) => {
  const normalized = normalizePermissionCodes(profile?.permissions)
  if (isPlatformSuperuser(profile)) {
    Object.values(PERMISSIONS).forEach((code) => normalized.add(code))
    return normalized
  }
  if (normalized.size) {
    return normalized
  }
  const roleName = String(profile?.role || '').trim().toLowerCase()
  if (roleName === 'sadmin') {
    Object.values(PERMISSIONS).forEach((code) => normalized.add(code))
  } else if (roleName === 'admin') {
    ;[
      PERMISSIONS.chat,
      PERMISSIONS.projects,
      PERMISSIONS.labels,
      PERMISSIONS.files,
      PERMISSIONS.usersRead,
      PERMISSIONS.usersWrite,
    ].forEach((code) => normalized.add(code))
  }
  return normalized
}

export const hasPermission = (profile, permissionCode) => {
  if (isPlatformSuperuser(profile)) {
    return true
  }
  return getEffectivePermissionCodes(profile).has(permissionCode)
}

export const hasAnyPermission = (profile, permissionCodes = []) => {
  if (isPlatformSuperuser(profile)) {
    return true
  }
  const normalized = getEffectivePermissionCodes(profile)
  return permissionCodes.some((code) => normalized.has(code))
}

export const canAccessRolesSection = (profile) => hasPermission(profile, PERMISSIONS.rolesManage)

export const canAccessUsersSection = (profile) =>
  hasAnyPermission(profile, [PERMISSIONS.usersRead, PERMISSIONS.usersWrite])

export const canWriteUsers = (profile) => hasPermission(profile, PERMISSIONS.usersWrite)

export const canAccessPermissionModule = (profile) =>
  canAccessRolesSection(profile) || canAccessUsersSection(profile)

export const resolveAccessibleAccountSection = (profile, requestedSection) => {
  const normalizedSection = String(requestedSection || '').trim().toLowerCase()
  if (normalizedSection === 'settings' && hasPermission(profile, PERMISSIONS.settings)) {
    return 'settings'
  }
  if (normalizedSection === 'users' && canAccessUsersSection(profile)) {
    return 'users'
  }
  if (normalizedSection === 'roles' && canAccessRolesSection(profile)) {
    return 'roles'
  }
  if (hasPermission(profile, PERMISSIONS.settings)) {
    return 'settings'
  }
  if (canAccessRolesSection(profile)) {
    return 'roles'
  }
  if (canAccessUsersSection(profile)) {
    return 'users'
  }
  return null
}

export const canAccessNavItem = (profile, itemId) => {
  switch (itemId) {
    case 'chat':
      return hasPermission(profile, PERMISSIONS.chat)
    case 'project':
      return isModuleEnabled('core.projects') && hasPermission(profile, PERMISSIONS.projects)
    case 'showcase':
      return isModuleEnabled('domain.label') && hasPermission(profile, PERMISSIONS.labels)
    case 'quote':
      return isModuleEnabled('domain.quote')
    case 'file-resources':
      return isModuleEnabled('core.files') && hasPermission(profile, PERMISSIONS.files)
    case 'permission':
      return canAccessPermissionModule(profile)
    case 'settings':
      return hasPermission(profile, PERMISSIONS.settings)
    default:
      return true
  }
}

export const canAccessRoute = (profile, route) => {
  const routeName = typeof route === 'string' ? route : route?.name
  switch (routeName) {
    case 'home':
      return isModuleEnabled('core.chat') && hasPermission(profile, PERMISSIONS.chat)
    case 'projects':
      return isModuleEnabled('core.projects') && hasPermission(profile, PERMISSIONS.projects)
    case 'label-settings':
    case 'label-print':
      return isModuleEnabled('domain.label') && hasPermission(profile, PERMISSIONS.labels)
    case 'file-resources':
      return isModuleEnabled('core.files') && hasPermission(profile, PERMISSIONS.files)
    case 'quote':
    case 'quote-returns':
      return isModuleEnabled('domain.quote')
    case 'edm':
    case 'edm-share':
    case 'email':
      return isModuleEnabled('domain.edm')
    case 'settings':
      return hasPermission(profile, PERMISSIONS.settings)
    case 'account':
      return resolveAccessibleAccountSection(profile, route?.query?.section) !== null
    default:
      return true
  }
}

export const getFirstAllowedRoute = (profile) => {
  if (isModuleEnabled('core.chat') && hasPermission(profile, PERMISSIONS.chat)) {
    return { name: 'home' }
  }
  if (isModuleEnabled('core.projects') && hasPermission(profile, PERMISSIONS.projects)) {
    return { name: 'projects' }
  }
  if (isModuleEnabled('domain.label') && hasPermission(profile, PERMISSIONS.labels)) {
    return { name: 'label-settings' }
  }
  if (isModuleEnabled('core.files') && hasPermission(profile, PERMISSIONS.files)) {
    return { name: 'file-resources' }
  }
  if (hasPermission(profile, PERMISSIONS.settings)) {
    return { name: 'settings' }
  }
  const accountSection = resolveAccessibleAccountSection(profile)
  if (accountSection && accountSection !== 'settings') {
    return { name: 'account', query: { section: accountSection } }
  }
  if (isModuleEnabled('domain.quote')) {
    return { name: 'quote-returns' }
  }
  return { name: 'home' }
}
