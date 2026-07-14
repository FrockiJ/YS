import { getDomainModuleDefinitions } from '../domainModules'

export const CORE_MODULE_IDS = Object.freeze([
  'core.auth',
  'core.admin',
  'core.chat',
  'core.projects',
  'core.files',
  'core.feedback',
  'core.extract',
  'core.search',
  'core.upload',
  'core.console',
])

export const CORE_MODULE_DEFINITIONS = Object.freeze([
  {
    id: 'core.auth',
    name: 'Auth and password flow',
    layer: 'core',
    category: 'platform',
    routes: ['home', 'reset-password', 'setup-password'],
  },
  {
    id: 'core.admin',
    name: 'Admin and RBAC',
    layer: 'core',
    category: 'platform',
    routes: ['account', 'settings'],
    navIds: ['permission', 'settings'],
  },
  {
    id: 'core.chat',
    name: 'Chat workspace',
    layer: 'mixed',
    category: 'ai',
    routes: ['home'],
    navIds: ['chat'],
  },
  {
    id: 'core.projects',
    name: 'Projects',
    layer: 'core',
    category: 'workspace',
    routes: ['projects'],
    navIds: ['project'],
  },
  {
    id: 'core.files',
    name: 'File resources',
    layer: 'mixed',
    category: 'workspace',
    routes: ['file-resources'],
    navIds: ['file-resources'],
  },
])

export const getModuleDefinitions = () => [
  ...CORE_MODULE_DEFINITIONS,
  ...getDomainModuleDefinitions(),
]

export const MODULE_DEFINITIONS = Object.freeze(getModuleDefinitions())

const coreModuleIds = new Set(CORE_MODULE_IDS)

const splitEnvList = (value) =>
  String(value || '')
    .replace(/;/g, ',')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)

const expandModuleList = (values, moduleDefinitions, { includeCoreAliases = true } = {}) => {
  const expanded = new Set()
  const moduleIds = new Set(moduleDefinitions.map((module) => module.id))
  for (const value of values) {
    if (includeCoreAliases && value === 'core') {
      CORE_MODULE_IDS.forEach((id) => expanded.add(id))
    } else if (value === 'domain') {
      moduleDefinitions
        .filter((module) => module.layer === 'domain')
        .forEach((module) => expanded.add(module.id))
    } else if (moduleIds.has(value)) {
      expanded.add(value)
    }
  }
  return expanded
}

const configuredEnabledModules = (moduleDefinitions) => {
  const raw = splitEnvList(
    import.meta.env.VITE_YS_ENABLED_MODULES || import.meta.env.VITE_YS_CORE_ENABLED_MODULES,
  )
  if (!raw.length) return null
  const enabled = expandModuleList(raw, moduleDefinitions)
  CORE_MODULE_IDS.forEach((id) => enabled.add(id))
  return enabled
}

export const getEnabledModuleIds = () => {
  const moduleDefinitions = getModuleDefinitions()
  const enabled =
    configuredEnabledModules(moduleDefinitions) ||
    new Set(moduleDefinitions.map((module) => module.id))
  const disabled = expandModuleList(
    splitEnvList(
      import.meta.env.VITE_YS_DISABLED_MODULES || import.meta.env.VITE_YS_CORE_DISABLED_MODULES,
    ),
    moduleDefinitions,
    { includeCoreAliases: false },
  )
  coreModuleIds.forEach((id) => disabled.delete(id))
  const resolved = new Set([...enabled].filter((id) => !disabled.has(id)))
  let changed = true
  while (changed) {
    changed = false
    for (const module of moduleDefinitions) {
      if (!resolved.has(module.id)) continue
      if ((module.dependencies || []).some((dependency) => !resolved.has(dependency))) {
        resolved.delete(module.id)
        changed = true
      }
    }
  }
  return resolved
}

export const isModuleEnabled = (moduleId) => {
  if (!moduleId) return true
  if (coreModuleIds.has(moduleId)) return true
  return getEnabledModuleIds().has(moduleId)
}

export const isRouteModuleEnabled = (routeRecord) => isModuleEnabled(routeRecord?.meta?.moduleId)

export const isNavModuleEnabled = (item) => isModuleEnabled(item?.moduleId)

export const getModuleManifest = () => {
  const moduleDefinitions = getModuleDefinitions()
  const enabled = getEnabledModuleIds()
  return moduleDefinitions.map((module) => ({
    ...module,
    enabled: enabled.has(module.id),
  }))
}
