import { useAuth } from '../composables/useAuth'
import { getApiErrorMeta, resolveApiErrorMessage, shouldLogoutFromApiError } from '../utils/apiError'

const API_BASE =
  import.meta.env.VITE_YS_API_BASE_URL ||
  import.meta.env.VITE_YS_API ||
  import.meta.env.VITE_YS_AI_BASE_URL ||
  import.meta.env.VITE_YS_AI_API ||
  '/api'

const defaultHeaders = {
  Accept: 'application/json',
}

const parsePayload = (text) => {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

const buildRequestError = ({ data, raw, response, auth, logout }) => {
  const { code, messageKey, payload } = getApiErrorMeta(data)
  const message = resolveApiErrorMessage({ payload: data, raw })
  const error = new Error(message)
  error.payload = payload
  error.status = response.status
  error.code = code
  error.messageKey = messageKey
  error.shouldLogout =
    Boolean(auth) &&
    shouldLogoutFromApiError({ status: response.status, payload: data, raw })
  if (error.shouldLogout) {
    logout({ redirectToPath: '/' })
  }
  return error
}

export const apiRequest = async (path, options = {}) => {
  const { authToken, logout, ensureSessionFresh, markSessionActivity } = useAuth()
  const {
    method = 'GET',
    body,
    headers = {},
    auth = true,
    signal,
    responseType = 'json',
  } = options

  const finalHeaders = { ...defaultHeaders, ...headers }
  const hasBody = body !== undefined && body !== null

  if (
    hasBody &&
    !(body instanceof FormData) &&
    !finalHeaders['Content-Type']
  ) {
    finalHeaders['Content-Type'] = 'application/json'
  }

  const isRefreshRequest = path === '/auth/refresh'

  if (auth && !isRefreshRequest) {
    await ensureSessionFresh()
  }

  if (auth && authToken.value) {
    finalHeaders.Authorization = `Bearer ${authToken.value}`
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: finalHeaders,
    body:
      body instanceof FormData
        ? body
        : hasBody
          ? JSON.stringify(body)
          : undefined,
    signal,
  })

  if (responseType === 'blob') {
    if (!response.ok) {
      const raw = await response.text()
      const data = parsePayload(raw)
      throw buildRequestError({ data, raw, response, auth, logout })
    }
    if (auth && !isRefreshRequest) {
      markSessionActivity()
    }
    return response.blob()
  }

  const raw = await response.text()
  const data = parsePayload(raw)

  if (!response.ok || (data && data.ok === false)) {
    throw buildRequestError({ data, raw, response, auth, logout })
  }

  if (auth && !isRefreshRequest) {
    markSessionActivity()
  }

  return data
}
