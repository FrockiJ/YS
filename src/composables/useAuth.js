import { computed, ref } from 'vue'
import { i18n } from '../i18n'
import { getApiErrorMeta, resolveApiErrorMessage } from '../utils/apiError'

const API_BASE =
  import.meta.env.VITE_YS_API_BASE_URL ||
  import.meta.env.VITE_YS_API ||
  import.meta.env.VITE_YS_AI_BASE_URL ||
  import.meta.env.VITE_YS_AI_API ||
  '/api'

const TOKEN_KEY = 'ys-ai-token'
const PROFILE_KEY = 'ys-ai-profile'
const LAST_ACTIVITY_KEY = 'ys-last-activity-at'
const LOCALE_KEY = 'ys-locale'
const APP_STORAGE_PREFIX = 'ys-'
const SESSION_IDLE_TIMEOUT_MS = 30 * 60 * 1000
const REFRESH_THRESHOLD_MS = 5 * 60 * 1000
const ACTIVITY_WRITE_THROTTLE_MS = 30 * 1000

const readJSON = (value) => {
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

const readNumber = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

const deriveAvatarLabel = (profile) => {
  if (!profile || typeof profile !== 'object') return '??'
  const candidates = [profile.username, profile.email, profile.name].filter(
    (value) => typeof value === 'string' && value.trim()
  )
  const source = candidates.length ? candidates[0].trim() : ''
  if (!source) return '??'
  let label = source[0]
  const rest = source.slice(1)
  const upperMatch = rest.match(/[A-Z]/)
  if (upperMatch) {
    label += upperMatch[0]
  } else {
    const segments = source.replace(/[_-]/g, ' ').split(/\s+/).filter(Boolean)
    if (segments.length > 1) {
      label += segments[1][0]
    }
  }
  return label
}

const decodeJwtPayload = (token) => {
  if (!token || typeof token !== 'string') return null
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const decoded = window.atob(padded)
    return JSON.parse(decoded)
  } catch {
    return null
  }
}

const getTokenExpirationMs = (token) => {
  if (typeof window === 'undefined') return 0
  const payload = decodeJwtPayload(token)
  const exp = Number(payload?.exp || 0)
  return Number.isFinite(exp) && exp > 0 ? exp * 1000 : 0
}

const initialToken =
  typeof window !== 'undefined' ? window.localStorage.getItem(TOKEN_KEY) : ''
const initialProfile =
  typeof window !== 'undefined' ? window.localStorage.getItem(PROFILE_KEY) : null
const initialLastActivity =
  typeof window !== 'undefined' ? readNumber(window.localStorage.getItem(LAST_ACTIVITY_KEY)) : 0

const authToken = ref(initialToken || '')
const userProfile = ref(readJSON(initialProfile))
const lastActivityAt = ref(initialLastActivity)

let idleTimerId = 0
let refreshPromise = null
let isSessionManagerInitialized = false

const clearMatchingKeys = (storage, predicate) => {
  if (typeof window === 'undefined' || !storage) return
  const keys = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (key && predicate(key)) {
      keys.push(key)
    }
  }
  keys.forEach((key) => storage.removeItem(key))
}

const persist = (token, profile) => {
  if (typeof window === 'undefined') return
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token)
  } else {
    window.localStorage.removeItem(TOKEN_KEY)
  }
  if (profile) {
    window.localStorage.setItem(PROFILE_KEY, JSON.stringify(profile))
  } else {
    window.localStorage.removeItem(PROFILE_KEY)
  }
}

const persistLastActivity = (value) => {
  if (typeof window === 'undefined') return
  const normalized = readNumber(value)
  lastActivityAt.value = normalized
  if (normalized) {
    window.localStorage.setItem(LAST_ACTIVITY_KEY, String(normalized))
  } else {
    window.localStorage.removeItem(LAST_ACTIVITY_KEY)
  }
}

const clearIdleTimer = () => {
  if (typeof window === 'undefined' || !idleTimerId) return
  window.clearTimeout(idleTimerId)
  idleTimerId = 0
}

const clearClientState = () => {
  if (typeof window === 'undefined') return

  clearMatchingKeys(
    window.localStorage,
    (key) => key.startsWith(APP_STORAGE_PREFIX) && key !== LOCALE_KEY
  )
  clearMatchingKeys(window.sessionStorage, (key) => key.startsWith(APP_STORAGE_PREFIX))
  lastActivityAt.value = 0
}

const redirectTo = (path = '/') => {
  if (typeof window === 'undefined') return
  const target = path || '/'
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (current === target) {
    window.location.reload()
    return
  }
  window.location.assign(target)
}

const hasSessionTimedOut = (now = Date.now()) => {
  if (!authToken.value || !lastActivityAt.value) return false
  return now - lastActivityAt.value > SESSION_IDLE_TIMEOUT_MS
}

const setSession = (token, profile, options = {}) => {
  authToken.value = token || ''
  userProfile.value = profile || null
  persist(authToken.value, userProfile.value)

  if (!authToken.value) {
    clearIdleTimer()
    return
  }

  if (options.preserveActivity && lastActivityAt.value) {
    persistLastActivity(lastActivityAt.value)
  } else {
    persistLastActivity(Date.now())
  }
  scheduleIdleCheck()
}

const clearSession = () => {
  setSession('', null)
  clearClientState()
}

const logout = ({ redirectToPath = '/' } = {}) => {
  clearSession()
  if (redirectToPath) {
    redirectTo(redirectToPath)
  }
}

const expireSessionForIdle = () => {
  if (!authToken.value) return
  logout({ redirectToPath: '/' })
}

const scheduleIdleCheck = () => {
  if (typeof window === 'undefined') return
  clearIdleTimer()
  if (!authToken.value || !lastActivityAt.value) return

  const remainingMs = SESSION_IDLE_TIMEOUT_MS - (Date.now() - lastActivityAt.value)
  if (remainingMs <= 0) {
    expireSessionForIdle()
    return
  }

  idleTimerId = window.setTimeout(() => {
    if (hasSessionTimedOut()) {
      expireSessionForIdle()
      return
    }
    scheduleIdleCheck()
  }, remainingMs + 250)
}

const markSessionActivity = ({ force = false } = {}) => {
  if (typeof window === 'undefined' || !authToken.value) return false

  const now = Date.now()
  if (hasSessionTimedOut(now)) {
    expireSessionForIdle()
    return false
  }

  if (!force && lastActivityAt.value && now - lastActivityAt.value < ACTIVITY_WRITE_THROTTLE_MS) {
    scheduleIdleCheck()
    return true
  }

  persistLastActivity(now)
  scheduleIdleCheck()
  return true
}

const syncSessionFromStorage = () => {
  if (typeof window === 'undefined') return
  authToken.value = window.localStorage.getItem(TOKEN_KEY) || ''
  userProfile.value = readJSON(window.localStorage.getItem(PROFILE_KEY))
  lastActivityAt.value = readNumber(window.localStorage.getItem(LAST_ACTIVITY_KEY))
  scheduleIdleCheck()
}

const refreshAccessToken = async () => {
  if (typeof window === 'undefined' || !authToken.value) {
    return null
  }
  if (refreshPromise) {
    return refreshPromise
  }

  const activeToken = authToken.value
  refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${activeToken}`,
    },
  })
    .then(async (response) => {
      const raw = await response.text()
      const payload = readJSON(raw) || {}
      if (!response.ok || payload?.ok === false) {
        const { code, messageKey, payload: normalizedPayload } = getApiErrorMeta(payload)
        const error = new Error(resolveApiErrorMessage({ payload, raw, fallbackKey: 'api_errors.auth.refresh_failed' }))
        error.status = response.status
        error.code = code
        error.messageKey = messageKey
        error.payload = normalizedPayload
        throw error
      }
      const nextToken = payload?.access_token || payload?.token
      if (!nextToken) {
        throw new Error(i18n.global.t('api_errors.auth.refresh_failed'))
      }
      setSession(nextToken, payload?.user || userProfile.value, { preserveActivity: true })
      scheduleIdleCheck()
      return nextToken
    })
    .catch((error) => {
      logout({ redirectToPath: '/' })
      throw error
    })
    .finally(() => {
      refreshPromise = null
    })

  return refreshPromise
}

const ensureSessionFresh = async ({ force = false } = {}) => {
  if (typeof window === 'undefined' || !authToken.value) return authToken.value
  if (hasSessionTimedOut()) {
    expireSessionForIdle()
    throw new Error(i18n.global.t('api_errors.auth.session_expired'))
  }

  const expiresAt = getTokenExpirationMs(authToken.value)
  if (!expiresAt) return authToken.value

  const remainingMs = expiresAt - Date.now()
  if (!force && remainingMs > REFRESH_THRESHOLD_MS) {
    return authToken.value
  }

  return refreshAccessToken()
}

const initializeSessionManager = (router) => {
  if (typeof window === 'undefined' || isSessionManagerInitialized) return
  isSessionManagerInitialized = true

  const interactionHandler = () => {
    markSessionActivity()
  }

  window.addEventListener('mousedown', interactionHandler, { passive: true })
  window.addEventListener('scroll', interactionHandler, { passive: true })
  window.addEventListener('touchstart', interactionHandler, { passive: true })
  window.addEventListener('keydown', interactionHandler)
  window.addEventListener('storage', (event) => {
    if (![TOKEN_KEY, PROFILE_KEY, LAST_ACTIVITY_KEY].includes(event.key || '')) return
    syncSessionFromStorage()
    if (!authToken.value) {
      clearIdleTimer()
    }
  })

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || !authToken.value) return
    if (!markSessionActivity({ force: true })) return
    void ensureSessionFresh().catch(() => {})
  })

  if (router?.afterEach) {
    router.afterEach(() => {
      if (!authToken.value) return
      if (!markSessionActivity({ force: true })) return
      void ensureSessionFresh().catch(() => {})
    })
  }

  if (!authToken.value) return

  if (!lastActivityAt.value) {
    persistLastActivity(Date.now())
  }
  if (hasSessionTimedOut()) {
    expireSessionForIdle()
    return
  }
  scheduleIdleCheck()
  void ensureSessionFresh().catch(() => {})
}

export const useAuth = () => {
  const isAuthenticated = computed(() => Boolean(authToken.value))
  const avatarLabel = computed(() => deriveAvatarLabel(userProfile.value))

  return {
    authToken,
    userProfile,
    isAuthenticated,
    avatarLabel,
    lastActivityAt,
    setSession,
    clearSession,
    logout,
    markSessionActivity,
    ensureSessionFresh,
    initializeSessionManager,
  }
}
