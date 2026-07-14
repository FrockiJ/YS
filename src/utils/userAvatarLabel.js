const normalizeWhitespace = (value = '') =>
  String(value || '')
    .replace(/\s+/g, ' ')
    .trim()

const extractVisibleChars = (value = '') =>
  Array.from(String(value || '').replace(/\s+/g, ''))

const isCjkChar = (char = '') => /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/u.test(char)

export const normalizeAuthorField = (value = '') => normalizeWhitespace(value)

export const buildUserAvatarLabel = ({ authorName = '', authorUsername = '', fallback = 'U' } = {}) => {
  const primary = normalizeAuthorField(authorName) || normalizeAuthorField(authorUsername)
  if (!primary) return fallback

  const compactChars = extractVisibleChars(primary)
  if (!compactChars.length) return fallback

  if (compactChars.some((char) => isCjkChar(char))) {
    return compactChars.filter((char) => !/\s/u.test(char)).slice(0, 2).join('')
  }

  const latinTokens = primary
    .split(/[^A-Za-z0-9]+/u)
    .map((token) => token.trim())
    .filter(Boolean)

  if (latinTokens.length >= 2) {
    return `${latinTokens[0][0] || ''}${latinTokens[1][0] || ''}`.toUpperCase()
  }

  if (latinTokens.length === 1) {
    return latinTokens[0].slice(0, 2).toUpperCase()
  }

  return compactChars.slice(0, 2).join('').toUpperCase()
}
