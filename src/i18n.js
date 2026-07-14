import { createI18n } from 'vue-i18n'
import zhTw from './locales/zh-tw.json'
import en from './locales/en.json'
import ja from './locales/ja.json'

const DEFAULT_LOCALE = 'zh-TW'
const SYSTEM_NAME_PLACEHOLDER = '__SYSTEM_NAME__'
const DEFAULT_SYSTEM_NAME = '企業系統'

const rawMessages = {
  zh: zhTw,
  'zh-TW': zhTw,
  'zh-Hant': zhTw,
  en,
  ja,
}

const normalizeLocale = (value) => {
  if (!value) return DEFAULT_LOCALE
  const normalized = String(value).trim()
  const lower = normalized.toLowerCase()
  if (lower === 'zh' || lower === 'zh-hant' || lower === 'zh_tw' || lower === 'zh-tw') {
    return DEFAULT_LOCALE
  }
  if (lower === 'en' || lower === 'en-us') {
    return 'en'
  }
  if (lower === 'ja' || lower === 'jp' || lower === 'ja-jp') {
    return 'ja'
  }
  return normalized
}

const resolveLocale = () => {
  if (typeof window === 'undefined') {
    return DEFAULT_LOCALE
  }
  const stored = window.localStorage.getItem('ys-locale')
  const normalized = normalizeLocale(stored)
  if (stored !== normalized) {
    window.localStorage.setItem('ys-locale', normalized)
  }
  return normalized
}

const cloneValue = (value) => {
  if (Array.isArray(value)) {
    return value.map(cloneValue)
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneValue(item)]))
  }
  return value
}

const replaceSystemName = (value, systemName) => {
  if (typeof value === 'string') {
    return value
      .replaceAll(SYSTEM_NAME_PLACEHOLDER, systemName)
      .replace(/\bYS\b/g, systemName)
  }
  if (Array.isArray(value)) {
    return value.map((item) => replaceSystemName(item, systemName))
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, replaceSystemName(item, systemName)]),
    )
  }
  return value
}

const buildMessages = (systemName = DEFAULT_SYSTEM_NAME) => {
  const name = String(systemName || '').trim() || DEFAULT_SYSTEM_NAME
  return Object.fromEntries(
    Object.entries(rawMessages).map(([locale, messages]) => [
      locale,
      replaceSystemName(cloneValue(messages), name),
    ]),
  )
}

export const i18n = createI18n({
  legacy: false,
  locale: resolveLocale(),
  fallbackLocale: 'en',
  messages: buildMessages(DEFAULT_SYSTEM_NAME),
})

export const applySystemBrandName = (systemName = DEFAULT_SYSTEM_NAME) => {
  const messages = buildMessages(systemName)
  for (const [locale, payload] of Object.entries(messages)) {
    i18n.global.setLocaleMessage(locale, payload)
  }
}

export const supportedLocales = ['zh-TW', 'en', 'ja']
export { normalizeLocale }
