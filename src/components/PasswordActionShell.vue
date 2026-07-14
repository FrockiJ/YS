<script setup>
import { useI18n } from 'vue-i18n'

import logoMain from '../assets/ysLogo_transparent.png'
import LocaleSwitcher from './LocaleSwitcher.vue'

const { t } = useI18n()

defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="password-action-shell">
    <header class="password-action-shell__brand">
      <img :src="logoMain" :alt="t('app.topbar.logo_alt')" />
      <LocaleSwitcher />
    </header>

    <main class="password-action-shell__main">
      <section class="password-action-shell__card">
        <header class="password-action-shell__header">
          <p v-if="eyebrow" class="password-action-shell__eyebrow">{{ eyebrow }}</p>
          <h1>{{ title }}</h1>
          <p v-if="description" class="password-action-shell__description">{{ description }}</p>
        </header>
        <slot />
      </section>
    </main>

    <div class="password-action-shell__glow is-left" aria-hidden="true" />
    <div class="password-action-shell__glow is-right" aria-hidden="true" />
  </div>
</template>

<style scoped>
.password-action-shell {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(139, 216, 168, 0.18), transparent 28%),
    linear-gradient(180deg, #f6faf7 0%, #edf4f1 100%);
}

.password-action-shell__brand {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 28px 36px 0;
}

.password-action-shell__brand img {
  width: 104px;
  height: 104px;
  object-fit: contain;
  border-radius: 18px;
  background: #fff;
  padding: 6px;
  box-shadow: 0 7px 18px rgba(38, 56, 71, 0.1);
}

.password-action-shell__main {
  min-height: calc(100vh - 88px);
  display: grid;
  place-items: center;
  padding: 32px 24px 64px;
}

.password-action-shell__card {
  position: relative;
  z-index: 1;
  width: min(480px, 100%);
  padding: 40px 38px 36px;
  border: 1px solid rgba(95, 117, 138, 0.16);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 9px 24px rgba(15, 23, 42, 0.07);
}

.password-action-shell__header {
  display: grid;
  gap: 12px;
  margin-bottom: 28px;
}

.password-action-shell__eyebrow {
  margin: 0;
  color: #8f9cb0;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.password-action-shell__header h1 {
  margin: 0;
  color: #233143;
  font-size: 32px;
  line-height: 1.15;
}

.password-action-shell__description {
  margin: 0;
  color: #6e7b8d;
  font-size: 15px;
  line-height: 1.75;
}

.password-action-shell__glow {
  position: absolute;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  filter: blur(24px);
  opacity: 0.55;
  pointer-events: none;
}

.password-action-shell__glow.is-left {
  left: -120px;
  bottom: -120px;
  background: rgba(244, 184, 63, 0.2);
}

.password-action-shell__glow.is-right {
  right: -120px;
  top: 120px;
  background: rgba(139, 216, 168, 0.22);
}

@media (max-width: 720px) {
  .password-action-shell__brand {
    padding: 24px 20px 0;
  }

  .password-action-shell__brand img {
    width: 88px;
    height: 88px;
  }

  .password-action-shell__main {
    padding: 24px 16px 40px;
  }

  .password-action-shell__card {
    padding: 32px 22px 28px;
    border-radius: 22px;
  }

  .password-action-shell__header h1 {
    font-size: 28px;
  }
}
</style>
