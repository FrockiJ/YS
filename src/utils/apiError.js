import { i18n } from '../i18n'

const DEFAULT_ERROR_KEY = 'api_errors.request_failed'

const normalizePayload = (payload) => {
  if (!payload || typeof payload !== 'object') return {}
  if (payload.detail && typeof payload.detail === 'object' && !Array.isArray(payload.detail)) {
    return {
      ...payload,
      ...payload.detail,
    }
  }
  return payload
}

const translate = (key, context = {}, fallback = '') => {
  const normalizedKey = String(key || '').trim()
  if (!normalizedKey) return fallback
  const te = i18n.global.te?.bind(i18n.global)
  if (!te || !te(normalizedKey)) return fallback
  return i18n.global.t(normalizedKey, context)
}

export const getApiErrorMeta = (payload) => {
  const normalized = normalizePayload(payload)
  return {
    payload: normalized,
    code: String(normalized.code || '').trim(),
    messageKey: String(
      normalized.message_key || normalized.messageKey || ''
    ).trim(),
    context:
      normalized.context && typeof normalized.context === 'object' && !Array.isArray(normalized.context)
        ? normalized.context
        : {},
    detail:
      normalized.message ||
      normalized.error ||
      normalized.detail_message ||
      normalized.detail ||
      '',
  }
}

export const resolveApiErrorMessage = ({
  payload,
  raw = '',
  fallbackKey = DEFAULT_ERROR_KEY,
  fallbackMessage = '',
} = {}) => {
  const meta = getApiErrorMeta(payload)
  const translatedMessage =
    translate(meta.messageKey, meta.context) ||
    translate(fallbackKey, meta.context)

  return (
    translatedMessage ||
    String(meta.detail || '').trim() ||
    String(raw || '').trim() ||
    fallbackMessage ||
    fallbackKey
  )
}

export const shouldLogoutFromApiError = ({ status, payload, raw = '' } = {}) => {
  const { code, messageKey, detail } = getApiErrorMeta(payload)
  if (status !== 401) return false

  const authCodes = new Set([
    'auth.missing_token',
    'auth.invalid_token',
    'auth.session_expired',
    'auth.credentials_invalid',
    'auth.user_disabled',
    'auth.role_disabled',
  ])
  if (authCodes.has(code)) return true

  const authMessageKeys = new Set([
    'api_errors.auth.missing_token',
    'api_errors.auth.invalid_token',
    'api_errors.auth.session_expired',
    'api_errors.auth.credentials_invalid',
    'api_errors.auth.user_disabled',
    'api_errors.auth.role_disabled',
  ])
  if (authMessageKeys.has(messageKey)) return true

  const normalized = `${detail} ${raw}`.trim().toLowerCase()
  if (!normalized) return false
  return [
    'session expired',
    'could not validate credentials',
    'invalid token',
    'missing token',
    'www-authenticate',
  ].some((fragment) => normalized.includes(fragment))
}
