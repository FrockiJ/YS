import ysOutdoorManifest from './ysOutdoor/manifest'

const manifests = {
  ysOutdoor: ysOutdoorManifest,
}

const splitEnvList = (value) =>
  String(value || '')
    .replace(/;/g, ',')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)

export const getActiveDomainManifests = () => {
  const configured = splitEnvList(
    import.meta.env.VITE_YS_DOMAIN_MODULES || import.meta.env.VITE_YS_DOMAIN_MODULE,
  )
  const names = configured.length ? configured : ['ysOutdoor']
  return names.map((name) => manifests[name]).filter(Boolean)
}

export const getDomainModuleDefinitions = () =>
  getActiveDomainManifests().flatMap((manifest) => manifest.moduleDefinitions || [])

export const getDomainRoutes = () =>
  getActiveDomainManifests().flatMap((manifest) => manifest.routes || [])

export const getDomainNavItems = (t, keyPrefix = 'home.nav') =>
  getActiveDomainManifests().flatMap((manifest) =>
    typeof manifest.buildNavItems === 'function' ? manifest.buildNavItems(t, keyPrefix) : [],
  )
