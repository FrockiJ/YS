<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<template>
  <header class="page-header">
    <div class="page-header__copy">
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
      <div v-if="$slots.meta" class="page-header__meta"><slot name="meta" /></div>
    </div>
    <div v-if="$slots.actions" class="page-header__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.25rem;
  padding: 1.35rem 1.5rem;
  border: 1px solid var(--ys-border, #dbe7df);
  border-radius: 1rem;
  background: #fff;
  box-shadow: 0 10px 28px rgba(22, 73, 50, 0.07);
}

.page-header__copy { min-width: 0; }
.page-header h1 { margin: 0; color: var(--ys-ink, #173c2e); font-size: clamp(1.35rem, 2vw, 1.8rem); line-height: 1.25; }
.page-header__subtitle { margin: .35rem 0 0; color: var(--ys-muted, #62776b); }
.page-header__meta { margin-top: .45rem; color: var(--ys-muted, #62776b); }
.page-header__actions { display: flex; align-items: center; gap: .65rem; flex: 0 0 auto; }

@media (max-width: 720px) {
  .page-header { align-items: stretch; flex-direction: column; padding: 1.05rem; }
  .page-header__actions { width: 100%; }
  .page-header__actions :deep(button), .page-header__actions :deep(a) { flex: 1 1 auto; justify-content: center; }
}
</style>
