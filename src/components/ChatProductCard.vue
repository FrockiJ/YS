<template>
  <article class="quote-gallery-card chat-product-card" v-if="product">
    <div class="quote-gallery-card__media">
      <div class="quote-gallery-card__bottle">
        <img v-if="product.photoUrl" :src="product.photoUrl" :alt="product.title" />
        <span v-else>{{ product.photoText }}</span>
      </div>
      <small v-if="product.sku">{{ t('chat_product_card.labels.sku') }} {{ product.sku }}</small>
    </div>

    <div class="quote-gallery-card__body">
      <header class="quote-gallery-card__header">
        <span v-if="product.sku" class="quote-gallery-card__sku">{{ product.sku }}</span>
        <button
          type="button"
          :aria-label="t('chat_product_card.aria.more_options')"
          class="quote-gallery-card__menu"
        >
          ...
        </button>
      </header>

      <p class="quote-gallery-card__title">{{ product.title }}</p>

      <div v-if="product.vipPrice || product.price" class="quote-gallery-card__pricing">
        <span v-if="product.vipPrice" class="is-vip">
          <span class="quote-gallery-card__price-label">{{ t('quote.labels.vip') }}</span>
          {{ formatCurrency(product.vipPrice) }}
        </span>
        <span v-if="product.price" class="is-compare">
          {{ formatCurrency(product.price) }}
        </span>
      </div>

      <ul class="quote-gallery-card__stats">
        <li v-for="stat in visibleStats" :key="stat.label">
          <label>{{ stat.label }}</label>
          <span>{{ stat.value || '-' }}</span>
        </li>
      </ul>

      <p v-if="product.description" class="quote-gallery-card__description">
        {{ product.description }}
      </p>

      <div v-if="tags.length || statusText" class="quote-gallery-card__footer">
        <div v-if="tags.length" class="quote-gallery-card__tags">
          <span v-for="tag in tags" :key="tag">{{ tag }}</span>
        </div>
        <div v-if="statusText" class="quote-gallery-card__status">
          <strong v-if="product.stock != null">{{ product.stock }}</strong>
          <span>{{ statusText }}</span>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  product: {
    type: Object,
    required: true,
  },
})

const visibleStats = computed(() => {
  const base = [
    { label: t('chat_product_card.stats.brand'), value: props.product.brand || props.product.brand },
    { label: t('chat_product_card.stats.category'), value: props.product.category },
    { label: t('chat_product_card.stats.specification'), value: props.product.specification || props.product.spec },
    { label: t('chat_product_card.stats.material'), value: props.product.material },
  ]
  return base.filter(
    (item) =>
      item.value !== undefined && item.value !== null && String(item.value).trim() !== ''
  )
})

const tags = computed(() => props.product.tags || [])

const statusText = computed(() => {
  if (props.product.bundleLabel) return props.product.bundleLabel
  if (props.product.stock != null) return t('chat_product_card.status.stock')
  return ''
})

const formatCurrency = (value) => {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return ''
  return new Intl.NumberFormat('zh-TW', {
    style: 'currency',
    currency: 'TWD',
    maximumFractionDigits: 0,
  }).format(amount)
}
</script>

<style scoped>
.chat-product-card.quote-gallery-card {
  width: 100%;
  margin: 16px 0 12px;
  box-shadow: none;
}

.quote-gallery-card__bottle {
  position: relative;
  overflow: hidden;
}

.quote-gallery-card__bottle img {
  position: absolute;
  inset: 14px;
  width: calc(100% - 28px);
  height: calc(100% - 28px);
  object-fit: contain;
  mix-blend-mode: multiply;
}

.quote-gallery-card__bottle span {
  position: absolute;
  inset: 14px;
  display: grid;
  place-items: center;
  text-align: center;
  font-size: 14px;
  color: #4a5979;
}

.quote-gallery-card__stats {
  justify-content: space-between;
}

.quote-gallery-card__stats li {
  flex: 1;
  padding: 0 8px;
}

</style>
