import { apiRequest } from './apiClient'

const normalizeIdentifierPayload = (account) => {
  const identifier = (account || '').trim()
  if (!identifier) return {}
  const payload = {}
  if (identifier.includes('@')) {
    payload.email = identifier
  } else {
    payload.username = identifier
  }
  return payload
}

export const loginWithCredentials = async ({ account, password }) => {
  const base = normalizeIdentifierPayload(account)
  return apiRequest('/auth/login', {
    method: 'POST',
    auth: false,
    body: {
      ...base,
      password,
    },
  })
}

export const requestForgotPassword = (email) => {
  return apiRequest('/auth/forgot-password', {
    method: 'POST',
    auth: false,
    body: { email },
  })
}

export const validateResetPasswordToken = (token) => {
  return apiRequest('/auth/reset-password/validate', {
    method: 'POST',
    auth: false,
    body: { token },
  })
}

export const completeResetPassword = ({ token, password, confirmPassword }) => {
  return apiRequest('/auth/reset-password/complete', {
    method: 'POST',
    auth: false,
    body: {
      token,
      password,
      confirm_password: confirmPassword,
    },
  })
}

export const validateSetupPasswordToken = (token) => {
  return apiRequest('/auth/setup-password/validate', {
    method: 'POST',
    auth: false,
    body: { token },
  })
}

export const completeSetupPassword = ({ token, password, confirmPassword }) => {
  return apiRequest('/auth/setup-password/complete', {
    method: 'POST',
    auth: false,
    body: {
      token,
      password,
      confirm_password: confirmPassword,
    },
  })
}

export const changePassword = ({ currentPassword, newPassword, confirmPassword }) => {
  return apiRequest('/auth/change-password', {
    method: 'POST',
    body: {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    },
  })
}

export const sendChatMessage = (payload) => {
  return apiRequest('/chat', {
    method: 'POST',
    body: payload,
  })
}

export const fetchCoreModules = () => {
  return apiRequest('/core/modules')
}

export const fetchDomainProfile = () => {
  return apiRequest('/core/domain-profile', { auth: false })
}

export const fetchKnowledgeRagTables = () => {
  return apiRequest('/knowledge/rag-tables')
}

export const importKnowledgeRagTable = (formData) => {
  return apiRequest('/knowledge/rag-tables/import', {
    method: 'POST',
    body: formData,
    headers: {},
  })
}

export const deleteKnowledgeRagTable = (documentId) => {
  return apiRequest(`/knowledge/rag-tables/${documentId}`, {
    method: 'DELETE',
  })
}

export const fetchKnowledgeCompanyProfile = () => {
  return apiRequest('/knowledge/company-profile')
}

export const saveKnowledgeCompanyProfile = (payload) => {
  return apiRequest('/knowledge/company-profile', {
    method: 'POST',
    body: payload,
  })
}

export const fetchKnowledgeExternalSites = () => {
  return apiRequest('/knowledge/external-sites')
}

export const saveKnowledgeExternalSite = (payload) => {
  return apiRequest('/knowledge/external-sites', {
    method: 'POST',
    body: payload,
  })
}

export const ingestKnowledgeExternalSite = (documentId) => {
  return apiRequest(`/knowledge/external-sites/${documentId}/ingest`, {
    method: 'POST',
  })
}

export const fetchConversationHistory = (params = {}) => {
  const query = new URLSearchParams()
  if (params.limit) {
    query.set('limit', params.limit)
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest(`/chat/history${suffix}`)
}

export const fetchConversationMessages = (conversationId, params = {}) => {
  const query = new URLSearchParams()
  if (params.limit) {
    query.set('limit', params.limit)
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest(`/chat/history/${conversationId}/messages${suffix}`)
}

export const renameConversation = (conversationId, payload) => {
  return apiRequest(`/chat/history/${conversationId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export const updateConversationVisibility = (conversationId, payload) => {
  return apiRequest(`/chat/history/${conversationId}/visibility`, {
    method: 'PATCH',
    body: payload,
  })
}

export const updateConversationProject = (conversationId, { projectId = null } = {}) => {
  return apiRequest(`/chat/history/${conversationId}/project`, {
    method: 'PATCH',
    body: {
      project_id: projectId,
    },
  })
}

export const archiveConversation = (conversationId) => {
  return apiRequest(`/chat/history/${conversationId}`, {
    method: 'DELETE',
  })
}

export const restoreConversation = (conversationId) => {
  return apiRequest(`/chat/history/${conversationId}/restore`, {
    method: 'POST',
  })
}

export const listUsers = () => {
  return apiRequest('/admin/users/')
}

export const createUserAccount = (payload) => {
  return apiRequest('/admin/users/', {
    method: 'POST',
    body: payload,
  })
}

export const updateUserAccount = (id, payload) => {
  return apiRequest(`/admin/users/${id}`, {
    method: 'PATCH',
    body: payload,
  })
}

export const sendSetupPasswordEmail = (id) => {
  return apiRequest(`/admin/users/${id}/send-setup-password`, {
    method: 'POST',
  })
}

export const deleteUserAccount = (id) => {
  return apiRequest(`/admin/users/${id}`, {
    method: 'DELETE',
  })
}

export const listRoles = () => {
  return apiRequest('/admin/roles/')
}

export const createRole = (payload) => {
  return apiRequest('/admin/roles/', {
    method: 'POST',
    body: payload,
  })
}

export const updateRole = (id, payload) => {
  return apiRequest(`/admin/roles/${id}`, {
    method: 'PATCH',
    body: payload,
  })
}

export const deleteRole = (id) => {
  return apiRequest(`/admin/roles/${id}`, {
    method: 'DELETE',
  })
}

export const uploadAttachment = (formData) => {
  return apiRequest('/upload', {
    method: 'POST',
    body: formData,
    headers: {},
  })
}

export const searchCerpProducts = ({ query, limit = 20, lang = 'zh-TW', signal } = {}) => {
  return apiRequest('/cerp/products/search', {
    method: 'POST',
    body: { query, limit, lang },
    signal,
  })
}

export const fetchLabelDescription = (code, lang = 'zh-TW') => {
  const params = new URLSearchParams({ code, lang })
  return apiRequest(`/labels/description?${params.toString()}`)
}

export const regenerateLabelDescription = ({
  code,
  lang = 'zh-TW',
  instruction,
  priceOverride,
} = {}) => {
  return apiRequest('/labels/description/regenerate', {
    method: 'POST',
    body: {
      code,
      lang,
      instruction,
      price_override: priceOverride,
    },
  })
}

export const updateLabelDescription = ({
  code,
  lang = 'zh-TW',
  description,
  priceOverride,
} = {}) => {
  return apiRequest('/labels/description/update', {
    method: 'POST',
    body: {
      code,
      lang,
      description,
      price_override: priceOverride,
    },
  })
}

export const addPrintListItem = ({ code, size, productSnapshot, includeItems = false } = {}) => {
  const params = new URLSearchParams()
  if (includeItems) {
    params.set('include_items', '1')
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return apiRequest(`/labels/print-list/items${suffix}`, {
    method: 'POST',
    body: { code, size, product_snapshot: productSnapshot },
  })
}

export const updatePrintListItemPrice = (itemId, { priceOverride } = {}) => {
  return apiRequest(`/labels/print-list/items/${itemId}`, {
    method: 'PATCH',
    body: {
      price_override: priceOverride,
    },
  })
}

export const fetchPrintListCount = () => {
  return apiRequest('/labels/print-list/count')
}

export const fetchPrintList = (lang = 'zh-TW') => {
  const params = new URLSearchParams({ lang })
  return apiRequest(`/labels/print-list?${params.toString()}`)
}

export const deletePrintListItem = (id, { includeItems = false } = {}) => {
  const params = new URLSearchParams()
  if (includeItems) {
    params.set('include_items', '1')
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return apiRequest(`/labels/print-list/items/${id}${suffix}`, {
    method: 'DELETE',
  })
}

export const resetPrintList = () => {
  return apiRequest('/labels/print-list', {
    method: 'DELETE',
  })
}

export const importPrintListItems = (file, lang = 'zh-TW') => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('lang', lang)
  return apiRequest('/labels/print-list/import', {
    method: 'POST',
    body: formData,
    headers: {},
  })
}

export const fetchProjects = ({ q = '', page = 1, pageSize = 10 } = {}) => {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiRequest(`/projects?${params.toString()}`)
}

export const fetchProjectConversationSearch = ({
  q = '',
  page = 1,
  pageSize = 10,
  scope = 'all',
} = {}) => {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  if (scope) params.set('scope', scope)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiRequest(`/projects/conversations/search?${params.toString()}`)
}

export const createProject = ({ name, visibility = 'private', customerProfile = {} } = {}) => {
  return apiRequest('/projects', {
    method: 'POST',
    body: {
      name,
      visibility,
      customer_profile: customerProfile,
    },
  })
}

export const updateProject = (projectId, { name, visibility, customerProfile = {} } = {}) => {
  return apiRequest(`/projects/${projectId}`, {
    method: 'PATCH',
    body: {
      name,
      visibility,
      customer_profile: customerProfile,
    },
  })
}

export const deleteProject = (projectId) => {
  return apiRequest(`/projects/${projectId}`, {
    method: 'DELETE',
  })
}

export const fetchProjectConversations = (
  projectId,
  { q = '', page = 1, pageSize = 10 } = {}
) => {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiRequest(`/projects/${projectId}/conversations?${params.toString()}`)
}

export const fetchProjectInvitations = (projectId) => {
  return apiRequest(`/projects/${projectId}/invitations`)
}

export const createProjectInvitation = (projectId, identifier) => {
  return apiRequest(`/projects/${projectId}/invitations`, {
    method: 'POST',
    body: { identifier },
  })
}

export const deleteProjectInvitation = (projectId, invitationId) => {
  return apiRequest(`/projects/${projectId}/invitations/${invitationId}`, {
    method: 'DELETE',
  })
}

export const createConversationInvitation = (conversationId, identifier) => {
  return apiRequest(`/conversations/${conversationId}/invitations`, {
    method: 'POST',
    body: { identifier },
  })
}

export const fetchConversationInvitations = (conversationId) => {
  return apiRequest(`/conversations/${conversationId}/invitations`)
}

export const deleteConversationInvitation = (conversationId, invitationId) => {
  return apiRequest(`/conversations/${conversationId}/invitations/${invitationId}`, {
    method: 'DELETE',
  })
}

export const fetchPendingProjectInvitations = () => {
  return apiRequest('/projects/invitations/pending')
}

export const acceptProjectInvitation = (invitationId) => {
  return apiRequest(`/projects/invitations/${invitationId}/accept`, {
    method: 'POST',
  })
}

export const rejectProjectInvitation = (invitationId) => {
  return apiRequest(`/projects/invitations/${invitationId}/reject`, {
    method: 'POST',
  })
}

export const fetchProjectNameMap = (ids = []) => {
  const params = new URLSearchParams()
  if (ids.length) {
    params.set('ids', ids.join(','))
  }
  return apiRequest(`/projects/name-map?${params.toString()}`)
}

export const searchInvitationCandidates = ({
  query = '',
  scope = 'conversation',
  targetId = '',
} = {}) => {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  if (scope) params.set('scope', scope)
  if (targetId) params.set('target_id', targetId)
  return apiRequest(`/invitations/candidates?${params.toString()}`)
}

export const createEdmPreview = (payload) => {
  return apiRequest('/edm/previews', {
    method: 'POST',
    body: payload,
  })
}

export const fetchEdmPreview = (shareToken) => {
  return apiRequest(`/edm/previews/${shareToken}`, {
    auth: false,
  })
}

export const updateEdmPreview = (shareToken, payload) => {
  return apiRequest(`/edm/previews/${shareToken}`, {
    method: 'PATCH',
    body: payload,
  })
}

export const shareEdmPreviewEmail = (shareToken, recipients = []) => {
  return apiRequest(`/edm/previews/${shareToken}/share-email`, {
    method: 'POST',
    body: {
      recipients,
    },
  })
}

export const fetchQuotes = ({ q = '', page = 1, pageSize = 10 } = {}) => {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiRequest(`/quotes?${params.toString()}`)
}

export const deleteQuote = (quoteId) => {
  return apiRequest(`/quotes/${quoteId}`, {
    method: 'DELETE',
  })
}

export const fetchFileResources = ({
  type = 'wine_label',
  q = '',
  sort = 'uploaded_desc',
  sorts = [],
  groupBy = '',
  page = 1,
  pageSize = 10,
} = {}) => {
  const params = new URLSearchParams()
  params.set('type', type)
  if (q) params.set('q', q)
  const normalizedSorts = Array.isArray(sorts) && sorts.length ? sorts : [sort]
  normalizedSorts
    .map((item) => String(item || '').trim())
    .filter(Boolean)
    .forEach((item) => params.append('sort', item))
  if (groupBy) params.set('group_by', groupBy)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiRequest(`/file-resources?${params.toString()}`)
}

export const createWineLabelResource = (payload) => {
  return apiRequest('/file-resources/wine-labels', {
    method: 'POST',
    body: payload,
  })
}

export const createImageResource = (payload) => {
  return apiRequest('/file-resources/images', {
    method: 'POST',
    body: payload,
  })
}

export const createDocumentResource = (payload) => {
  return apiRequest('/file-resources/documents', {
    method: 'POST',
    body: payload,
  })
}

export const fetchFileResourceDepartments = () => {
  return apiRequest('/file-resources/departments')
}

export const updateWineLabelResource = (resourceId, payload) => {
  return apiRequest(`/file-resources/${resourceId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export const updateFileResource = (resourceId, payload) => {
  return apiRequest(`/file-resources/${resourceId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export const deleteFileResource = (resourceId) => {
  return apiRequest(`/file-resources/${resourceId}`, {
    method: 'DELETE',
  })
}

export const fetchFileResourceDetail = (resourceId) => {
  return apiRequest(`/file-resources/${resourceId}`)
}

export const fetchFileResourcePreview = (resourceId) => {
  return apiRequest(`/file-resources/${resourceId}/preview`, {
    responseType: 'blob',
  })
}
