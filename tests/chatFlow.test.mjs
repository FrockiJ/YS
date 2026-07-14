import test from 'node:test'
import assert from 'node:assert/strict'

import {
  assertUsableChatResponse,
  isOpenAiRateLimitPayload,
  normalizeChatAnswerPayload,
  resolveChatFlowErrorMessage,
} from '../src/utils/chatFlow.js'
import { buildQuoteChatRequest } from '../src/utils/quoteChatRequest.js'

test('normalizes a shared chat answer without citations', () => {
  const answer = normalizeChatAnswerPayload({
    answer: {
      text: '梨山一日遊可由福壽山農場開始。',
      citations: [],
      metadata: { retrieval_mode: 'llm_without_rag', rag_used: false },
      conversation_id: 'conversation-1',
    },
  })

  assert.equal(answer.text, '梨山一日遊可由福壽山農場開始。')
  assert.deepEqual(answer.metadata.answer_citations, [])
  assert.equal(answer.metadata.retrieval_mode, 'llm_without_rag')
})

test('identifies a rate-limited chat response for the shared UI error', () => {
  assert.throws(
    () => assertUsableChatResponse({ ok: false, error: { status: 429 } }),
    (error) => error.code === 'openai_429',
  )
  assert.match(resolveChatFlowErrorMessage({ code: 'openai_429' }, (key) => key), /rate limit/i)
})

test('does not misclassify a model-access 403 as an OpenAI rate limit', () => {
  const response = {
    ok: true,
    answer: {
      text: 'AI service configuration is unavailable. Please contact an administrator.',
      citations: [],
      metadata: {
        generation_error: 'OpenAIChatHTTPError',
        generation_error_status: 403,
        model_access_denied: true,
      },
    },
  }

  assert.equal(isOpenAiRateLimitPayload(response), false)
  assert.doesNotThrow(() => assertUsableChatResponse(response))
  assert.equal(normalizeChatAnswerPayload(response).text, response.answer.text)
})

test('preserves QuoteView quote_list and follow-up fields on the shared chat contract', () => {
  const payload = buildQuoteChatRequest({
    message: '請產生報價單',
    conversationId: 'conversation-1',
    project: 'uat-project',
    lang: 'zh-TW',
    followupAction: 'create_quote',
    followupActionSource: 'quote_action',
    urlInputs: ['https://example.test/item'],
  })

  assert.equal(payload.output_type, 'quote_list')
  assert.equal(payload.followup_action, 'create_quote')
  assert.equal(payload.followup_action_source, 'quote_action')
  assert.deepEqual(payload.url_inputs, ['https://example.test/item'])
})
