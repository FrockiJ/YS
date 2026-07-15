import test from 'node:test'
import assert from 'node:assert/strict'

import {
  resolveKnowledgeSourceKind,
  resolveKnowledgeSourceLocaleKey,
} from '../src/utils/knowledgeSource.js'

test('uses the knowledge contract instead of legacy references', () => {
  const metadata = {
    source_tier: 'external_evidence',
    external_search: { attempted: true },
    knowledge: {
      mode: 'llm_only',
      rag_status: 'empty_corpus',
      external_attempted: false,
      external_status: 'not_attempted',
    },
  }

  assert.equal(
    resolveKnowledgeSourceKind(metadata, [{ kind: 'external', url: 'https://example.test' }]),
    'general'
  )
  assert.equal(
    resolveKnowledgeSourceLocaleKey(metadata, [], 'title'),
    'home.rag.general_knowledge_title'
  )
})

test('labels only grounded external answers as External Search', () => {
  assert.equal(
    resolveKnowledgeSourceKind({
      knowledge: {
        mode: 'external_grounded',
        rag_status: 'no_relevant_hits',
        external_attempted: true,
        external_status: 'used',
      },
    }),
    'external'
  )
  assert.equal(
    resolveKnowledgeSourceKind({
      knowledge: {
        mode: 'llm_only',
        rag_status: 'empty_corpus',
        external_attempted: true,
        external_status: 'unavailable',
      },
    }),
    'external_unavailable'
  )
  assert.equal(
    resolveKnowledgeSourceKind({
      knowledge: {
        mode: 'llm_only',
        rag_status: 'no_relevant_hits',
        external_attempted: true,
        external_status: 'no_results',
      },
    }),
    'external_incomplete'
  )
})

test('distinguishes grounded RAG from an LLM fallback', () => {
  assert.equal(
    resolveKnowledgeSourceKind({
      knowledge: {
        mode: 'rag_grounded',
        rag_status: 'used',
        external_attempted: false,
        external_status: 'not_attempted',
      },
    }),
    'rag'
  )
  assert.equal(
    resolveKnowledgeSourceKind({
      knowledge: {
        mode: 'rag_grounded',
        rag_status: 'used',
        external_attempted: true,
        external_status: 'unavailable',
      },
    }),
    'rag'
  )
  assert.equal(
    resolveKnowledgeSourceKind({
      knowledge: {
        mode: 'llm_only',
        rag_status: 'no_relevant_hits',
        external_attempted: false,
        external_status: 'not_attempted',
      },
    }),
    'general'
  )
})

test('ERP fact lookup metadata overrides the knowledge source card', () => {
  const metadata = {
    intent_task_type: 'erp_lookup',
    intent_lookup_operation: 'inventory_lookup',
    erp_lookup: {
      operation: 'inventory_lookup',
      status: 'used',
      matched_product_count: 1,
    },
    knowledge: {
      mode: 'llm_only',
      rag_status: 'empty_corpus',
      external_attempted: false,
      external_status: 'not_attempted',
    },
  }

  assert.equal(resolveKnowledgeSourceKind(metadata), 'erp')
  assert.equal(
    resolveKnowledgeSourceLocaleKey(metadata, [], 'title'),
    'home.rag.erp_source_title'
  )
  assert.equal(
    resolveKnowledgeSourceLocaleKey(metadata, [], 'status'),
    'home.rag.erp_source_status'
  )
})

test('mixed answers keep the knowledge source while ERP remains on product cards', () => {
  const metadata = {
    execution_plan: { answer_mode: 'mixed', task_type: 'mixed' },
    erp_query: { operation: 'recommendation', status: 'used', row_proof_count: 4 },
    erp_lookup: { operation: 'product_lookup', status: 'used' },
    knowledge: {
      mode: 'llm_only',
      rag_status: 'empty_corpus',
      external_attempted: false,
      external_status: 'not_attempted',
    },
  }

  assert.equal(resolveKnowledgeSourceKind(metadata), 'general')
})

test('keeps legacy source inference for saved messages without knowledge metadata', () => {
  assert.equal(
    resolveKnowledgeSourceKind({}, [{ kind: 'external', url: 'https://example.test' }]),
    'external'
  )
  assert.equal(resolveKnowledgeSourceKind({ source_tier: 'internal_approved' }), 'rag')
})
