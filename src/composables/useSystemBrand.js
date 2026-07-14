import { computed, ref } from 'vue'
import { applySystemBrandName } from '../i18n'
import { fetchDomainProfile } from '../services/ysApi'

const DEFAULT_SYSTEM_NAME = '企業系統'

const domainProfile = ref(null)
const isLoading = ref(false)
const loadError = ref('')
let inflight = null

const normalizeSystemName = (profile) => {
  const value = String(profile?.system_display_name || profile?.display_name || '').trim()
  return value || DEFAULT_SYSTEM_NAME
}

export const useSystemBrand = () => {
  const systemName = computed(() => normalizeSystemName(domainProfile.value))
  const companyName = computed(() => String(domainProfile.value?.company_name || '').trim())

  const loadSystemBrand = async ({ force = false } = {}) => {
    if (inflight && !force) return inflight
    if (domainProfile.value && !force) return domainProfile.value
    isLoading.value = true
    loadError.value = ''
    inflight = fetchDomainProfile()
      .then((profile) => {
        domainProfile.value = profile || {}
        applySystemBrandName(systemName.value)
        return domainProfile.value
      })
      .catch((error) => {
        loadError.value = error?.message || 'Unable to load system profile.'
        applySystemBrandName(DEFAULT_SYSTEM_NAME)
        return domainProfile.value
      })
      .finally(() => {
        isLoading.value = false
        inflight = null
      })
    return inflight
  }

  const setSystemBrandProfile = (profile) => {
    domainProfile.value = profile || {}
    applySystemBrandName(systemName.value)
  }

  return {
    companyName,
    domainProfile,
    isLoading,
    loadError,
    loadSystemBrand,
    setSystemBrandProfile,
    systemName,
  }
}
