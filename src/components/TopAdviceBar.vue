<script setup>
import { ref } from 'vue'

const rootRef = ref(null)

defineExpose({ getElement: () => rootRef.value })
</script>

<template>
  <div class="top-advice" ref="rootRef">
    <slot />
  </div>
</template>
