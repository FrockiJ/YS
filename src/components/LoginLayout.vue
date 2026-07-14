<script setup>
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, EyeOff, ShieldCheck, X } from 'lucide-vue-next'

import logoMain from '../assets/ysLogo_transparent.png'
import heroLogo from '../assets/ysLogo_w_transparent.png'
import outdoorLoginHero from '../assets/outdoor-login-hero.png'
import { loginWithCredentials, requestForgotPassword } from '../services/ysApi'
import { useAuth } from '../composables/useAuth'
import LocaleSwitcher from './LocaleSwitcher.vue'

const { t } = useI18n()
const emit = defineEmits(['login-success'])
const { setSession } = useAuth()

const form = reactive({
  account: '',
  password: '',
})

const errors = reactive({
  account: '',
  password: '',
})

const bannerMessage = ref('')
const showPassword = ref(false)
const isLoading = ref(false)
const isForgotModalOpen = ref(false)
const forgotStep = ref('form')
const forgotEmail = ref('')
const forgotError = ref('')
const forgotLoading = ref(false)

const resetFieldErrors = () => {
  errors.account = ''
  errors.password = ''
}

const SPECIAL_USERNAMES = ['Frocki', 'jopasck']
const emailRegex = /\S+@\S+\.\S+/
const usernameRegex = /^[A-Za-z0-9._-]{3,}$/

const validateAccount = (value) => {
  const identifier = value.trim()
  if (!identifier) return false
  return emailRegex.test(identifier) || usernameRegex.test(identifier) || SPECIAL_USERNAMES.includes(identifier)
}

const handleSubmit = async () => {
  resetFieldErrors()
  bannerMessage.value = ''

  if (!form.account) {
    errors.account = t('login.errors.account_required')
  } else if (!validateAccount(form.account)) {
    errors.account = t('login.errors.account_invalid')
  }

  if (!form.password) {
    errors.password = t('login.errors.password_required')
  }

  if (errors.account || errors.password || isLoading.value) {
    return
  }

  try {
    isLoading.value = true
    const result = await loginWithCredentials({
      account: form.account.trim(),
      password: form.password,
    })
    const token = result?.token || result?.access_token
    if (!token) {
      throw new Error(t('login.errors.token_missing'))
    }
    setSession(token, result?.user || null)
    emit('login-success', result?.user || null)
  } catch (error) {
    bannerMessage.value = error?.message || t('login.errors.login_failed')
  } finally {
    isLoading.value = false
  }
}

const togglePassword = () => {
  showPassword.value = !showPassword.value
}

const closeForgotPasswordModal = () => {
  isForgotModalOpen.value = false
  forgotStep.value = 'form'
  forgotEmail.value = ''
  forgotError.value = ''
  forgotLoading.value = false
}

const openForgotPasswordModal = () => {
  forgotStep.value = 'form'
  forgotError.value = ''
  forgotEmail.value = form.account.includes('@') ? form.account.trim() : ''
  isForgotModalOpen.value = true
}

const submitForgotPassword = async () => {
  const email = forgotEmail.value.trim()
  forgotError.value = ''

  if (!email) {
    forgotError.value = t('login.forgot.errors.required')
    return
  }
  if (!emailRegex.test(email)) {
    forgotError.value = t('login.forgot.errors.invalid')
    return
  }
  if (forgotLoading.value) {
    return
  }

  try {
    forgotLoading.value = true
    await requestForgotPassword(email)
    forgotStep.value = 'sent'
  } catch (error) {
    forgotError.value = error?.message || t('login.forgot.errors.submit_failed')
  } finally {
    forgotLoading.value = false
  }
}

watch(
  () => [form.account, form.password],
  () => {
    bannerMessage.value = ''
  }
)
</script>

<template>
  <div class="login-shell">
    <aside class="login-hero">
      <img :src="outdoorLoginHero" alt="" class="login-hero__image" aria-hidden="true" />
      <div class="login-hero__shade" aria-hidden="true" />
      <div class="login-hero__brand">
        <img :src="heroLogo" :alt="t('login.hero.logo_alt')" class="login-hero__logo" />
      </div>
      <div class="login-hero__content">
        <p class="login-hero__kicker">{{ t('login.outdoor.kicker') }}</p>
        <h1>{{ t('login.outdoor.title') }}</h1>
        <p>
          {{ t('login.outdoor.copy') }}
        </p>
      </div>
      <div class="login-hero__metrics" :aria-label="t('login.outdoor.brand')">
        <span>{{ t('login.outdoor.trail') }}</span>
        <span>{{ t('login.outdoor.tackle') }}</span>
        <span>{{ t('login.outdoor.flow') }}</span>
      </div>
    </aside>

    <section class="login-panel">
      <LocaleSwitcher class="login-locale" />
      <header class="login-panel__header">
        <div class="login-panel__brand">
          <img :src="logoMain" :alt="t('login.hero.logo_alt')" />
          <span>{{ t('login.outdoor.panel_brand') }}</span>
        </div>
        <p class="login-panel__eyebrow">{{ t('login.outdoor.panel_eyebrow') }}</p>
        <h1>{{ t('login.panel.title') }}</h1>
      </header>

      <div v-if="bannerMessage" class="login-banner" role="alert">
        <p>
          <strong>{{ t('login.banner.title') }}</strong>{{ t('login.banner.copy') }}
        </p>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <label class="form-field" :class="{ 'is-error': errors.account }">
          <span>{{ t('login.form.account_label') }}</span>
          <input
            v-model="form.account"
            type="text"
            inputmode="email"
            :placeholder="t('login.form.account_placeholder')"
          />
          <p class="form-field__hint" v-if="errors.account">
            {{ errors.account }}
          </p>
        </label>

        <label class="form-field" :class="{ 'is-error': errors.password }">
          <span>{{ t('login.form.password_label') }}</span>
          <div class="password-field">
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              :placeholder="t('login.form.password_placeholder')"
            />
            <button
              class="icon-button"
              type="button"
              :aria-label="t('login.form.toggle_password')"
              @click="togglePassword"
            >
              <EyeOff v-if="showPassword" :size="19" :stroke-width="1.9" aria-hidden="true" />
              <Eye v-else :size="19" :stroke-width="1.9" aria-hidden="true" />
            </button>
          </div>
          <p class="form-field__hint" v-if="errors.password">
            {{ errors.password }}
          </p>
        </label>

        <button class="forgot-link" type="button" @click="openForgotPasswordModal">
          {{ t('login.form.forgot_password') }}
        </button>

        <button class="login-button" type="submit">
          <ShieldCheck :size="18" :stroke-width="2" aria-hidden="true" />
          {{ t('login.form.submit') }}
        </button>
      </form>
    </section>
  </div>

  <div
    v-if="isForgotModalOpen"
    class="login-modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="closeForgotPasswordModal"
  >
    <div class="login-modal-card">
      <header class="login-modal-card__header">
        <div>
          <h3>
            {{
              forgotStep === 'sent'
                ? t('login.forgot.sent_title')
                : t('login.forgot.title')
            }}
          </h3>
          <p v-if="forgotStep === 'form'">{{ t('login.forgot.description') }}</p>
          <p v-else>{{ t('login.forgot.sent_description') }}</p>
        </div>
        <button type="button" class="login-modal-card__close" @click="closeForgotPasswordModal">
          <X :size="18" :stroke-width="2" aria-hidden="true" />
        </button>
      </header>

      <div class="login-modal-card__body">
        <template v-if="forgotStep === 'form'">
          <label class="login-modal-card__field" :class="{ 'is-error': forgotError }">
            <span>{{ t('login.forgot.field_label') }}</span>
            <input
              v-model="forgotEmail"
              type="email"
              :placeholder="t('login.forgot.field_placeholder')"
              autocomplete="email"
            />
          </label>
          <p v-if="forgotError" class="login-modal-card__error">{{ forgotError }}</p>
        </template>

        <template v-else>
          <div class="login-modal-card__success">
            <p class="login-modal-card__success-title">{{ t('login.forgot.success_title') }}</p>
            <p class="login-modal-card__success-copy">
              {{ t('login.forgot.success_copy', { email: forgotEmail }) }}
            </p>
          </div>
        </template>
      </div>

      <footer class="login-modal-card__footer">
        <template v-if="forgotStep === 'form'">
          <button type="button" class="login-modal-card__button is-secondary" @click="closeForgotPasswordModal">
            {{ t('common.actions.cancel') }}
          </button>
          <button
            type="button"
            class="login-modal-card__button is-primary"
            :disabled="forgotLoading"
            @click="submitForgotPassword"
          >
            {{ forgotLoading ? t('common.actions.sending') : t('common.actions.confirm') }}
          </button>
        </template>

        <button
          v-else
          type="button"
          class="login-modal-card__button is-primary"
          @click="closeForgotPasswordModal"
        >
          {{ t('common.actions.confirm') }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.login-shell {
  min-height: 100vh;
  background:
    radial-gradient(circle at 16% 14%, rgba(139, 216, 168, 0.28), transparent 30%),
    linear-gradient(135deg, #f6faf7 0%, #edf4f1 54%, #fff8e6 100%);
  display: flex;
  gap: 48px;
  padding: 48px;
}

.login-hero {
  width: 420px;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid rgba(95, 117, 138, 0.16);
  border-radius: 24px;
  padding: 48px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  color: #263847;
  box-shadow: 0 8px 22px rgba(38, 56, 71, 0.08);
  backdrop-filter: blur(18px);
}

.login-hero__logo {
  width: 190px;
  height: 190px;
  object-fit: contain;
  border-radius: 22px;
  background: #fff;
  padding: 8px;
  box-shadow: 0 8px 20px rgba(38, 56, 71, 0.08);
}

.login-hero__title {
  font-size: 32px;
  font-weight: 700;
  margin: 40px 0 auto;
}

.login-hero__copy {
  margin: 0;
  font-size: 14px;
  color: #5f758a;
}

.login-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-panel__header h1 {
  margin: 8px 0 0;
  font-size: 18px;
  color: #5f758a;
  font-weight: 500;
}

.login-panel__eyebrow {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  color: #263847;
}

.login-banner {
  background: #ffe9df;
  border: 1px solid #ffc8b1;
  border-radius: 16px;
  padding: 16px 20px;
  color: #9c2a1b;
  font-size: 15px;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-field span {
  font-weight: 600;
  color: #263847;
}

.form-field input {
  border-radius: var(--ys-control-radius, 6px);
  border: 1px solid #d7e4df;
  height: 54px;
  padding: 0 18px;
  font-size: 16px;
  font-family: inherit;
  color: #263847;
  background: #fff;
}

.form-field input:focus {
  outline: none;
  border-color: rgba(85, 183, 127, 0.55);
  box-shadow: 0 0 0 4px rgba(139, 216, 168, 0.18);
}

.form-field.is-error input {
  border-color: #f2594b;
  background: #fff5f3;
}

.form-field__hint {
  margin: 0;
  font-size: 13px;
  color: #d64539;
}

.password-field {
  position: relative;
  display: flex;
}

.password-field input {
  width: 100%;
  padding-right: 48px;
}

.password-field .icon-button {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: transparent;
  display: grid;
  place-items: center;
  cursor: pointer;
}

.forgot-link {
  align-self: flex-start;
  background: none;
  border: none;
  color: #24774d;
  font-weight: 600;
  cursor: pointer;
}

.login-button {
  border: none;
  border-radius: 16px;
  background: linear-gradient(135deg, #55b77f, #8bd8a8);
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  padding: 16px;
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(85, 183, 127, 0.2);
}

.login-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(64, 72, 83, 0.7);
  display: grid;
  place-items: center;
  padding: 24px;
  z-index: 120;
}

.login-modal-card {
  width: min(420px, 100%);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 9px 24px rgba(15, 23, 42, 0.15);
}

.login-modal-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px 14px;
}

.login-modal-card__header h3 {
  margin: 0;
  color: #283243;
  font-size: 18px;
}

.login-modal-card__header p {
  margin: 8px 0 0;
  color: #8a97a9;
  font-size: 12px;
}

.login-modal-card__close {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  color: #8895a7;
  font-size: 20px;
  line-height: 1;
  display: grid;
  place-items: center;
}

.login-modal-card__body {
  padding: 0 22px 20px;
  display: grid;
  gap: 14px;
}

.login-modal-card__field {
  display: grid;
  gap: 8px;
}

.login-modal-card__field span {
  color: #425066;
  font-size: 12px;
  font-weight: 700;
}

.login-modal-card__field input {
  width: 100%;
  height: 44px;
  border: 1px solid #dbe3ee;
  border-radius: var(--ys-control-radius, 6px);
  padding: 0 14px;
  font-size: 14px;
  color: #162031;
  background: #fff;
}

.login-modal-card__field.is-error input {
  border-color: #df6f5e;
  background: #fff9f7;
}

.login-modal-card__error {
  margin: 0;
  color: #c55242;
  font-size: 12px;
  line-height: 1.5;
}

.login-modal-card__success {
  display: grid;
  gap: 10px;
  padding: 10px 0 6px;
}

.login-modal-card__success-title {
  margin: 0;
  color: #243145;
  font-size: 16px;
  font-weight: 700;
}

.login-modal-card__success-copy {
  margin: 0;
  color: #6e7b8d;
  font-size: 13px;
  line-height: 1.7;
}

.login-modal-card__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 0 22px 22px;
}

.login-modal-card__button {
  min-width: 80px;
  height: 34px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
}

.login-modal-card__button.is-secondary {
  border: 1px solid #d7dee8;
  color: #4d5a70;
  background: #fff;
}

.login-modal-card__button.is-primary {
  background: #55b77f;
  color: #fff;
}

.login-modal-card__button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 1280px) {
  .login-shell {
    flex-direction: column;
    padding: 32px 24px;
  }

  .login-hero {
    width: 100%;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 32px;
  }

  .login-hero__title {
    margin: 0;
  }
}

@media (max-width: 720px) {
  .login-shell {
    padding: 24px 16px 48px;
  }

  .login-hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .login-modal-card {
    width: min(100%, 360px);
  }
}

/* Premium Outdoor login redesign */
.login-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(520px, 1.12fr) minmax(420px, 0.88fr);
  gap: 0;
  padding: 0;
  background:
    radial-gradient(circle at 80% 16%, rgba(220, 163, 58, 0.16), transparent 30%),
    linear-gradient(135deg, #10241f 0%, #1f4b39 44%, #eef3ee 44%, #f8faf7 100%);
}

.login-hero {
  position: relative;
  width: auto;
  min-height: 100vh;
  padding: 44px;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: #10241f;
  box-shadow: none;
  color: #fff;
  justify-content: space-between;
  backdrop-filter: none;
}

.login-hero__image,
.login-hero__shade {
  position: absolute;
  inset: 0;
}

.login-hero__image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.login-hero__shade {
  background:
    linear-gradient(90deg, rgba(16, 36, 31, 0.94), rgba(16, 36, 31, 0.42) 54%, rgba(16, 36, 31, 0.72)),
    radial-gradient(circle at 28% 72%, rgba(220, 163, 58, 0.24), transparent 32%);
}

.login-hero__brand,
.login-hero__content,
.login-hero__metrics {
  position: relative;
  z-index: 1;
}

.login-hero__brand {
  display: block;
  width: fit-content;
}

.login-hero__logo {
  width: 148px;
  height: 64px;
  padding: 0;
  border-radius: 0;
  background: transparent;
  object-fit: contain;
  box-shadow: none;
}

.login-hero__content {
  max-width: 620px;
  margin: auto 0 42px;
}

.login-hero__kicker {
  margin: 0 0 16px;
  color: #f4d48a;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.login-hero__content h1 {
  margin: 0;
  max-width: 620px;
  font-size: clamp(42px, 5.4vw, 78px);
  line-height: 0.98;
  letter-spacing: 0;
}

.login-hero__content p:not(.login-hero__kicker) {
  max-width: 520px;
  margin: 22px 0 0;
  color: rgba(255, 255, 255, 0.78);
  font-size: 16px;
  line-height: 1.7;
}

.login-hero__metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
}

.login-hero__metrics span {
  display: inline-flex;
  align-items: center;
  gap: 0;
  min-height: 0;
  padding: 0;
  border-radius: 0;
  background: transparent;
  border: 0;
  color: rgba(255, 255, 255, 0.86);
  font-size: 13px;
  font-weight: 700;
}

.login-hero__metrics span + span::before {
  content: "|";
  margin: 0 12px;
  color: rgba(255, 255, 255, 0.52);
  font-weight: 500;
}

.login-panel {
  position: relative;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 470px);
  align-content: center;
  justify-content: center;
  gap: 26px;
  padding: 96px min(7vw, 86px) 64px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 247, 0.96)),
    url('../assets/outdoor-dashboard-texture.png') center/cover;
}

.login-locale {
  position: absolute;
  top: 28px;
  right: 32px;
  z-index: 2;
}

.login-panel__brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
  color: #1f4b39;
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.login-panel__brand img {
  width: 38px;
  height: 38px;
  padding: 3px;
  border-radius: 12px;
  background: #fff;
  object-fit: contain;
  box-shadow: 0 6px 16px rgba(27, 45, 41, 0.07);
}

.login-panel__eyebrow {
  color: #d18f24;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.login-panel__header h1 {
  margin-top: 10px;
  color: #10241f;
  font-size: 34px;
  line-height: 1.1;
  font-weight: 800;
}

.form-field span {
  color: #1b2d29;
}

.form-field input {
  border-radius: var(--ys-control-radius, 6px);
  border-color: rgba(27, 45, 41, 0.14);
  background: rgba(247, 249, 246, 0.9);
  color: #10241f;
}

.form-field input:focus {
  border-color: rgba(220, 163, 58, 0.58);
  box-shadow: 0 0 0 4px rgba(220, 163, 58, 0.16);
}

.password-field .icon-button {
  color: #466779;
}

.forgot-link {
  color: #1f4b39;
}

.login-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 18px;
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
  box-shadow: 0 10px 24px rgba(31, 75, 57, 0.18);
}

.login-button:hover,
.login-button:focus-visible {
  transform: translateY(-1px);
}

.login-modal-card {
  border: 1px solid rgba(27, 45, 41, 0.1);
  box-shadow: 0 9px 24px rgba(16, 36, 31, 0.17);
}

.login-modal-card__button.is-primary {
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
}

@media (max-width: 1100px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-hero {
    min-height: 430px;
  }

  .login-panel {
    min-height: auto;
    padding: 72px 20px 56px;
  }
}

@media (max-width: 720px) {
  .login-hero {
    min-height: 430px;
    padding: 26px 18px;
  }

  .login-hero__content h1 {
    font-size: 38px;
  }

  .login-panel {
    grid-template-columns: minmax(0, 1fr);
    align-content: start;
    gap: 22px;
    padding: 78px 18px 48px;
  }

  .login-panel__header h1 {
    font-size: 28px;
  }
}
</style>
