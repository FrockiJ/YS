import { ref } from 'vue'
import { uploadAttachment } from '../services/ysApi'

export const DEFAULT_ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'pdf', 'xls', 'xlsx', 'csv']
export const DEFAULT_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
const URL_PROTOCOL_RE = /^https?:\/\//i

const createItemId = (prefix) =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

const formatUploadSize = (bytes = 0) => `${(bytes / (1024 * 1024)).toFixed(1)}MB`

const resolveMessage = (messages, key, fallback, payload = {}) => {
  const candidate = messages?.[key]
  if (typeof candidate === 'function') return candidate(payload)
  if (typeof candidate === 'string' && candidate.trim()) return candidate
  return typeof fallback === 'function' ? fallback(payload) : fallback
}

const normalizeUrlValue = (value = '') => String(value || '').trim()

const isValidHttpUrl = (value = '') => {
  const normalized = normalizeUrlValue(value)
  if (!URL_PROTOCOL_RE.test(normalized)) return false
  try {
    const parsed = new URL(normalized)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

const buildUrlLabel = (value = '') => {
  try {
    const parsed = new URL(value)
    const hostname = parsed.hostname.replace(/^www\./i, '')
    const path = `${parsed.pathname || ''}${parsed.search || ''}`.trim()
    if (!path || path === '/') return hostname
    const compactPath = path.length > 28 ? `${path.slice(0, 28)}...` : path
    return `${hostname}${compactPath}`
  } catch {
    return value
  }
}

const createUploadError = (messages, maxBytes, error) => {
  if (error?.status === 413) {
    return new Error(
      resolveMessage(
        messages,
        'payloadTooLarge',
        ({ maxMb }) => `Upload exceeds ${maxMb}MB.`,
        { maxMb: Math.round(maxBytes / (1024 * 1024)) }
      )
    )
  }
  const message = String(error?.message || '').trim()
  if (message) {
    return new Error(message)
  }
  return new Error(
    resolveMessage(messages, 'uploadFailed', 'Upload failed.')
  )
}

const splitUrlInput = (raw = '') =>
  String(raw || '')
    .split(/[\n,]+/)
    .map((item) => normalizeUrlValue(item))
    .filter(Boolean)

export function useFileUploader(options = {}) {
  const allowedExtensions = (options.allowedExtensions || DEFAULT_ALLOWED_EXTENSIONS).map((item) =>
    String(item || '').trim().toLowerCase()
  )
  const maxBytes = options.maxBytes || DEFAULT_MAX_UPLOAD_BYTES
  const messages = options.messages || {}

  const attachments = ref([])
  const warning = ref('')
  const isUploading = ref(false)
  const fileInputRef = ref(null)

  const accept = Array.from(new Set(allowedExtensions.map((ext) => `.${ext}`))).join(',')

  const clearWarning = () => {
    warning.value = ''
  }

  const triggerSelect = () => {
    clearWarning()
    fileInputRef.value?.click()
  }

  const normalizeAttachment = (file) => {
    const ext = (file.name || '').split('.').pop()?.toLowerCase() || ''
    if (!allowedExtensions.includes(ext)) {
      warning.value = resolveMessage(
        messages,
        'fileTypeNotAllowed',
        ({ extension, allowed }) =>
          `Unsupported file type "${extension || 'unknown'}". Allowed: ${allowed.join(', ')}`,
        { extension: ext, allowed: allowedExtensions }
      )
      return null
    }
    if (file.size > maxBytes) {
      warning.value = resolveMessage(
        messages,
        'fileTooLarge',
        ({ filename, maxMb }) => `File "${filename}" exceeds ${maxMb}MB.`,
        {
          filename: file.name,
          maxMb: Math.round(maxBytes / (1024 * 1024)),
        }
      )
      return null
    }
    const previewUrl = (file.type || '').startsWith('image/') ? URL.createObjectURL(file) : ''
    return {
      id: createItemId('att'),
      type: 'file',
      file,
      previewUrl,
      filename: file.name,
      extension: ext,
      label: `${file.name} (${formatUploadSize(file.size)})`,
      tooltip: file.name,
      size: file.size,
    }
  }

  const normalizeUrlItem = (value) => {
    const normalized = normalizeUrlValue(value)
    if (!isValidHttpUrl(normalized)) {
      return null
    }
    return {
      id: createItemId('url'),
      type: 'url',
      url: normalized,
      filename: '',
      extension: 'url',
      previewUrl: '',
      label: buildUrlLabel(normalized),
      tooltip: normalized,
    }
  }

  const appendFiles = (incomingFiles = []) => {
    clearWarning()
    const files = Array.from(incomingFiles || [])
    if (!files.length) return
    const next = []
    files.forEach((file) => {
      const attachment = normalizeAttachment(file)
      if (attachment) {
        next.push(attachment)
      }
    })
    if (next.length) {
      attachments.value = attachments.value.concat(next)
    }
  }

  const handleFilesSelected = (event) => {
    const files = event?.target?.files ? Array.from(event.target.files) : []
    appendFiles(files)
    if (event?.target) {
      event.target.value = ''
    }
  }

  const handleDroppedFiles = (files) => {
    appendFiles(files)
  }

  const addUrlsFromText = (rawInput = '') => {
    clearWarning()
    const parts = splitUrlInput(rawInput)
    if (!parts.length) {
      warning.value = resolveMessage(
        messages,
        'urlInputRequired',
        'Enter at least one URL.',
      )
      return []
    }
    const existing = new Set(
      attachments.value
        .filter((item) => item?.type === 'url')
        .map((item) => normalizeUrlValue(item.url).toLowerCase())
    )
    const invalid = []
    const next = []
    parts.forEach((value) => {
      const normalized = normalizeUrlValue(value)
      if (!isValidHttpUrl(normalized)) {
        invalid.push(normalized)
        return
      }
      const dedupeKey = normalized.toLowerCase()
      if (existing.has(dedupeKey)) {
        return
      }
      const item = normalizeUrlItem(normalized)
      if (!item) {
        invalid.push(normalized)
        return
      }
      existing.add(dedupeKey)
      next.push(item)
    })
    if (next.length) {
      attachments.value = attachments.value.concat(next)
    }
    if (invalid.length) {
      warning.value = resolveMessage(
        messages,
        'invalidUrls',
        ({ invalidUrls }) => `Invalid URLs: ${invalidUrls.join(', ')}`,
        { invalidUrls: invalid }
      )
    }
    return next
  }

  const revokePreview = (attachment) => {
    if (attachment?.previewUrl) {
      URL.revokeObjectURL(attachment.previewUrl)
    }
  }

  const removeAttachment = (id) => {
    const next = []
    attachments.value.forEach((attachment) => {
      if (attachment.id === id) {
        revokePreview(attachment)
        return
      }
      next.push(attachment)
    })
    attachments.value = next
  }

  const clearFiles = () => {
    attachments.value = attachments.value.filter((attachment) => {
      if (attachment?.type === 'file') {
        revokePreview(attachment)
        return false
      }
      return true
    })
  }

  const clearUrls = () => {
    attachments.value = attachments.value.filter((attachment) => attachment?.type !== 'url')
  }

  const clear = () => {
    attachments.value.forEach((attachment) => revokePreview(attachment))
    attachments.value = []
    clearWarning()
  }

  const extractUrlInputs = () =>
    attachments.value
      .filter((attachment) => attachment?.type === 'url' && attachment?.url)
      .map((attachment) => String(attachment.url).trim())
      .filter(Boolean)

  const uploadAll = async () => {
    const fileAttachments = attachments.value.filter((attachment) => attachment?.type === 'file' && attachment?.file)
    if (!fileAttachments.length) return []
    isUploading.value = true
    const metas = []
    try {
      for (const attachment of fileAttachments) {
        const form = new FormData()
        form.append('file', attachment.file)
        warning.value = resolveMessage(
          messages,
          'uploading',
          ({ filename }) => `Uploading ${filename}...`,
          { filename: attachment.file.name }
        )
        const response = await uploadAttachment(form)
        metas.push(response)
      }
    } catch (error) {
      throw createUploadError(messages, maxBytes, error)
    } finally {
      warning.value = ''
      isUploading.value = false
    }
    return metas
  }

  return {
    accept,
    attachments,
    warning,
    isUploading,
    fileInputRef,
    triggerSelect,
    handleFilesSelected,
    handleDroppedFiles,
    addUrlsFromText,
    removeAttachment,
    clear,
    clearFiles,
    clearUrls,
    clearWarning,
    extractUrlInputs,
    uploadAll,
  }
}
