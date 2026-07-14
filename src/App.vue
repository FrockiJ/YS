<script setup>
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { useSystemBrand } from './composables/useSystemBrand'

const { loadSystemBrand } = useSystemBrand()

onMounted(() => {
  loadSystemBrand()
})
</script>

<template>
  <RouterView />
</template>
