<script setup>
import { computed } from 'vue'
import { buildLabelPreviewModel } from '../utils/labelPreviewModel.js'

const props = defineProps({
  source: { type: Object, default: () => ({}) },
  size: { type: String, default: '' },
  priceOverride: { type: [Number, String, null], default: null },
  description: { type: String, default: '' },
})

const label = computed(() =>
  buildLabelPreviewModel(props.source, {
    size: props.size,
    priceOverride: props.priceOverride,
    description: props.description || undefined,
  })
)
</script>

<template>
  <article class="label-preview-v2" :class="`label-preview-v2--${label.size}`">
    <div class="label-preview-v2__bar" />
    <div class="label-preview-v2__top">
      <div class="label-preview-v2__identity">
        <strong class="label-preview-v2__brand">{{ label.brand || '-' }}</strong>
        <span class="label-preview-v2__name">{{ label.name || '-' }}</span>
      </div>
      <div v-if="label.qrSvg" class="label-preview-v2__qr" :style="{ '--qr-size': `${label.qrSizeMm}mm` }">
        <div class="label-preview-v2__qr-art" v-html="label.qrSvg" />
        <span class="label-preview-v2__code">{{ label.code }}</span>
      </div>
    </div>
    <div class="label-preview-v2__bottom">
      <div v-if="label.size === 'small'" class="label-preview-v2__meta">
        <span>{{ label.specification }}</span>
        <span>{{ label.category }}</span>
      </div>
      <div v-else-if="label.size === 'medium'" class="label-preview-v2__meta">
        <span>{{ label.feature }}</span>
        <span>{{ label.specification }}</span>
        <span>{{ label.category }}</span>
      </div>
      <div v-else class="label-preview-v2__details">
        <span>{{ label.feature }}</span>
        <span>{{ label.specification }}</span>
        <span>{{ label.category }}</span>
      </div>
      <strong class="label-preview-v2__price">{{ label.price }}</strong>
    </div>
    <p v-if="label.size === 'large' && label.description" class="label-preview-v2__description">
      {{ label.description }}
    </p>
  </article>
</template>

<style scoped>
.label-preview-v2 { position:relative; width:100%; height:100%; min-height:0; overflow:hidden; padding:24px 20px 18px; color:#102d47; background:#fff; border:1px dashed rgba(145,158,171,.48); display:flex; flex-direction:column; gap:10px; font-family:Inter,'Noto Sans TC',sans-serif; }
.label-preview-v2__bar { position:absolute; inset:0 0 auto; height:6px; background:#55b77f; }
.label-preview-v2__top { display:flex; min-height:0; justify-content:space-between; gap:14px; }
.label-preview-v2__identity { min-width:0; display:flex; flex-direction:column; gap:5px; }
.label-preview-v2__brand { font-size:19px; line-height:1.18; font-weight:750; }
.label-preview-v2__name { display:-webkit-box; overflow:hidden; font-size:14px; line-height:1.35; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.label-preview-v2__qr { flex:0 0 var(--qr-size); width:var(--qr-size); text-align:center; color:#102d47; }
.label-preview-v2__qr-art { width:100%; aspect-ratio:1; background:#fff; line-height:0; }
.label-preview-v2__qr-art :deep(svg) { display:block; width:100%; height:100%; }
.label-preview-v2__code { display:block; margin-top:2px; overflow:hidden; font-size:8px; font-weight:700; letter-spacing:.02em; line-height:1.15; text-overflow:ellipsis; white-space:nowrap; }
.label-preview-v2__bottom { display:flex; align-items:flex-end; justify-content:space-between; gap:10px; margin-top:auto; }
.label-preview-v2__meta { min-width:0; display:flex; flex-direction:column; gap:2px; font-size:12px; line-height:1.25; }
.label-preview-v2__meta span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.label-preview-v2__price { flex:0 0 auto; font-size:20px; line-height:1; text-align:right; }
.label-preview-v2--medium { padding:28px 24px 22px; }
.label-preview-v2--medium .label-preview-v2__brand, .label-preview-v2--large .label-preview-v2__brand { font-size:23px; }
.label-preview-v2--medium .label-preview-v2__name, .label-preview-v2--large .label-preview-v2__name { font-size:17px; }
.label-preview-v2--medium .label-preview-v2__price { font-size:23px; }
.label-preview-v2--large { padding:28px 26px 22px; gap:14px; }
.label-preview-v2__details { min-width:0; display:flex; flex:1; gap:10px; padding:8px 0; border-block:2px solid #102d47; font-size:13px; font-weight:700; }
.label-preview-v2__details span { min-width:0; flex:1; overflow:hidden; text-align:center; text-overflow:ellipsis; white-space:nowrap; }
.label-preview-v2__details span + span { border-left:1px solid rgba(22,62,97,.32); }
.label-preview-v2--large .label-preview-v2__price { font-size:24px; }
.label-preview-v2__description { display:-webkit-box; margin:0; overflow:hidden; font-size:14px; line-height:1.45; -webkit-box-orient:vertical; -webkit-line-clamp:3; white-space:pre-line; }
</style>
