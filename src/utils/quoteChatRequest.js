const appendIfPresent = (payload, key, value) => {
  if (value) payload[key] = value
}

/**
 * Keep QuoteView on the shared /chat HTTP contract while retaining its
 * continuity/action payload.
 */
export const buildQuoteChatRequest = ({
  message,
  conversationId,
  project,
  lang,
  followupAction,
  followupActionSource,
  attachment,
  urlInputs,
}) => {
  const payload = {
    message,
    conversation_id: conversationId,
    project,
    lang,
  }
  appendIfPresent(payload, 'followup_action', followupAction)
  appendIfPresent(payload, 'followup_action_source', followupActionSource)
  appendIfPresent(payload, 'attachment', attachment)
  if (Array.isArray(urlInputs) && urlInputs.length) {
    payload.url_inputs = urlInputs
  }
  return payload
}
