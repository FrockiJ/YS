<script setup>
import chatToolbarCopy from '../assets/chat-toolbar-copy.svg'
import chatToolbarShare from '../assets/chat-toolbar-share.svg'

defineProps({
  quoteUi: {
    type: Object,
    required: true,
  },
  copyAriaLabel: {
    type: String,
    default: '',
  },
  shareAriaLabel: {
    type: String,
    default: '',
  },
  followupSummary: {
    type: String,
    default: '',
  },
  followupActions: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['copy', 'share', 'action'])
</script>

<template>
  <div class="quote-response-renderer">
    <div class="chat-message__quote">
      <p v-if="quoteUi?.intro" class="chat-message__quote-paragraph">
        {{ quoteUi.intro }}
      </p>
      <ul v-if="quoteUi?.introBullets?.length" class="chat-message__list chat-message__list--quote">
        <li v-for="(item, index) in quoteUi.introBullets" :key="`quote-intro-${index}`">
          {{ item }}
        </li>
      </ul>

      <article class="chat-result-card chat-result-card--quote">
        <div class="chat-result-card__header">
          <div class="chat-result-card__header-copy">
            <p class="chat-result-card__title">
              {{ quoteUi?.title }}
            </p>
            <div class="chat-result-card__meta">
              <span>{{ quoteUi?.generatedAt }}</span>
              <span
                class="chat-result-card__status"
                :class="`is-${quoteUi?.statusVariant || 'success'}`"
              >
                <span class="dot" />
                {{ quoteUi?.status }}
              </span>
            </div>
          </div>
          <span
            class="chat-result-card__check"
            :class="`is-${quoteUi?.statusVariant || 'success'}`"
            aria-hidden="true"
          >
            ??          </span>
        </div>
      </article>

      <p v-if="quoteUi?.closing" class="chat-message__quote-paragraph">
        {{ quoteUi.closing }}
      </p>
      <ul
        v-if="quoteUi?.closingBullets?.length"
        class="chat-message__list chat-message__list--quote is-secondary"
      >
        <li v-for="(item, index) in quoteUi.closingBullets" :key="`quote-closing-${index}`">
          {{ item }}
        </li>
      </ul>

      <div v-if="followupSummary || followupActions?.length" class="quote-followup">
        <p v-if="followupSummary" class="quote-followup__summary">{{ followupSummary }}</p>
        <div v-if="followupActions?.length" class="quote-followup__actions">
          <button
            v-for="action in followupActions"
            :key="action.id"
            type="button"
            class="quote-followup__chip"
            :class="{ 'is-preferred': action.preferred }"
            @click="emit('action', action)"
          >
            {{ action.label }}
          </button>
        </div>
      </div>

      <div class="chat-toolbar chat-toolbar--quote">
        <button type="button" :aria-label="copyAriaLabel" @click="emit('copy')">
          <img :src="chatToolbarCopy" alt="" aria-hidden="true" />
        </button>
        <button type="button" :aria-label="shareAriaLabel" @click="emit('share')">
          <img :src="chatToolbarShare" alt="" aria-hidden="true" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.quote-followup {
  margin-top: 14px;
  display: grid;
  gap: 10px;
}

.quote-followup__summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #3f566f;
}

.quote-followup__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quote-followup__chip {
  border: 1px solid #c9d7e6;
  background: #fff;
  color: #263847;
  border-radius: 999px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.quote-followup__chip.is-preferred {
  border-color: #263847;
  background: #eef5fb;
  font-weight: 600;
}
</style>
