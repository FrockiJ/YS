<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import PasswordActionShell from '../components/PasswordActionShell.vue'
import { completeSetupPassword, validateSetupPasswordToken } from '../services/ysApi'

const MIN_PASSWORD_LENGTH = 8

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const token = computed(() => String(route.params.token || '').trim())
const isLoading = ref(true)
const isSubmitting = ref(false)
const isComplete = ref(false)
const showPassword = ref(false)
const showConfirmPassword = ref(false)
const tokenState = ref({ valid: false, expired: false, email: '' })
const form = reactive({
  password: '',
  confirmPassword: '',
})
const fieldErrors = reactive({
  password: '',
  confirmPassword: '',
})
const submitError = ref('')
const successMessage = ref('')

const pageMeta = computed(() => {
  if (isComplete.value) {
    return {
      eyebrow: 'SET UP PASSWORD',
      title: t('password_flow.setup.complete_title'),
      description: t('password_flow.setup.complete_description'),
    }
  }

  if (!isLoading.value && !tokenState.value.valid) {
    return {
      eyebrow: 'SET UP PASSWORD',
      title: tokenState.value.expired
        ? t('password_flow.setup.expired_title')
        : t('password_flow.setup.invalid_title'),
      description: t('password_flow.setup.invalid_description'),
    }
  }

  return {
    eyebrow: 'SET UP PASSWORD',
    title: t('password_flow.setup.title'),
    description: t('password_flow.setup.description'),
  }
})

const resetFieldErrors = () => {
  fieldErrors.password = ''
  fieldErrors.confirmPassword = ''
  submitError.value = ''
}

const validateToken = async () => {
  isLoading.value = true
  submitError.value = ''
  try {
    tokenState.value = await validateSetupPasswordToken(token.value)
  } catch (error) {
    submitError.value = error?.message || t('password_flow.setup.errors.validate')
  } finally {
    isLoading.value = false
  }
}

const canSubmit = computed(() => tokenState.value.valid && !isSubmitting.value)

const validateForm = () => {
  resetFieldErrors()
  if (!form.password) {
    fieldErrors.password = t('password_flow.common.errors.new_required')
  } else if (form.password.length < MIN_PASSWORD_LENGTH) {
    fieldErrors.password = t('password_flow.common.errors.new_length', { count: MIN_PASSWORD_LENGTH })
  }

  if (!form.confirmPassword) {
    fieldErrors.confirmPassword = t('password_flow.common.errors.confirm_required')
  } else if (form.confirmPassword !== form.password) {
    fieldErrors.confirmPassword = t('password_flow.common.errors.confirm_mismatch')
  }

  return !fieldErrors.password && !fieldErrors.confirmPassword
}

const handleSubmit = async () => {
  if (!canSubmit.value || !validateForm()) return

  isSubmitting.value = true
  submitError.value = ''
  try {
    const result = await completeSetupPassword({
      token: token.value,
      password: form.password,
      confirmPassword: form.confirmPassword,
    })
    successMessage.value =
      (result?.message_key && t(result.message_key)) ||
      result?.message ||
      t('password_flow.setup.success_message')
    isComplete.value = true
  } catch (error) {
    submitError.value = error?.message || t('password_flow.setup.errors.submit')
  } finally {
    isSubmitting.value = false
  }
}

const goBackToLogin = () => {
  router.push({ name: 'home' }).catch(() => {})
}

onMounted(() => {
  void validateToken()
})
</script>

<template>
  <PasswordActionShell
    :eyebrow="pageMeta.eyebrow"
    :title="pageMeta.title"
    :description="pageMeta.description"
  >
    <div v-if="isLoading" class="password-action-state">
      <p>{{ t('password_flow.setup.loading') }}</p>
    </div>

    <div v-else-if="isComplete" class="password-action-state is-success">
      <div class="password-action-state__badge">✓</div>
      <p class="password-action-state__headline">{{ t('password_flow.setup.success_headline') }}</p>
      <p class="password-action-state__copy">{{ successMessage }}</p>
      <button type="button" class="password-action-button is-primary" @click="goBackToLogin">
        {{ t('password_flow.common.back_to_login') }}
      </button>
    </div>

    <div v-else-if="!tokenState.valid" class="password-action-state is-error">
      <p class="password-action-state__headline">
        {{
          tokenState.expired
            ? t('password_flow.common.expired_headline')
            : t('password_flow.common.invalid_headline')
        }}
      </p>
      <p class="password-action-state__copy">
        {{ t('password_flow.setup.invalid_hint') }}
      </p>
      <button type="button" class="password-action-button is-primary" @click="goBackToLogin">
        {{ t('password_flow.common.back_to_login') }}
      </button>
    </div>

    <form v-else class="password-action-form" @submit.prevent="handleSubmit">
      <p class="password-action-form__note">
        {{ t('password_flow.setup.account_label') }}:
        <strong>{{ tokenState.email || t('password_flow.common.no_email') }}</strong>
      </p>

      <label class="password-action-form__field" :class="{ 'is-error': fieldErrors.password }">
        <span>{{ t('password_flow.common.fields.new_password') }}</span>
        <div class="password-action-form__input-wrap">
          <input
            v-model="form.password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="new-password"
          />
          <button type="button" class="password-action-form__toggle" @click="showPassword = !showPassword">
            {{ showPassword ? t('common.actions.hide') : t('common.actions.show') }}
          </button>
        </div>
        <p v-if="fieldErrors.password" class="password-action-form__hint">{{ fieldErrors.password }}</p>
      </label>

      <label class="password-action-form__field" :class="{ 'is-error': fieldErrors.confirmPassword }">
        <span>{{ t('password_flow.common.fields.confirm_password') }}</span>
        <div class="password-action-form__input-wrap">
          <input
            v-model="form.confirmPassword"
            :type="showConfirmPassword ? 'text' : 'password'"
            autocomplete="new-password"
          />
          <button
            type="button"
            class="password-action-form__toggle"
            @click="showConfirmPassword = !showConfirmPassword"
          >
            {{ showConfirmPassword ? t('common.actions.hide') : t('common.actions.show') }}
          </button>
        </div>
        <p v-if="fieldErrors.confirmPassword" class="password-action-form__hint">
          {{ fieldErrors.confirmPassword }}
        </p>
      </label>

      <p v-if="submitError" class="password-action-form__status is-error">{{ submitError }}</p>

      <div class="password-action-form__actions">
        <button type="button" class="password-action-button is-secondary" @click="goBackToLogin">
          {{ t('password_flow.common.back_to_login') }}
        </button>
        <button type="submit" class="password-action-button is-primary" :disabled="!canSubmit">
          {{ isSubmitting ? t('common.actions.setting') : t('password_flow.setup.submit') }}
        </button>
      </div>
    </form>
  </PasswordActionShell>
</template>

<style scoped>
.password-action-form,
.password-action-state {
  display: grid;
  gap: 18px;
}

.password-action-form__note,
.password-action-state__copy,
.password-action-state p,
.password-action-form__status,
.password-action-form__hint {
  margin: 0;
  color: #6f7c8f;
  line-height: 1.7;
}

.password-action-state {
  justify-items: start;
  padding: 6px 0 0;
}

.password-action-state.is-success,
.password-action-state.is-error {
  justify-items: center;
  text-align: center;
}

.password-action-state__badge {
  width: 66px;
  height: 66px;
  border-radius: 50%;
  background: #173b3a;
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 30px;
  font-weight: 700;
}

.password-action-state__headline {
  margin: 0;
  color: #243145;
  font-size: 22px;
  font-weight: 700;
}

.password-action-form__field {
  display: grid;
  gap: 8px;
}

.password-action-form__field span {
  color: #415066;
  font-size: 13px;
  font-weight: 700;
}

.password-action-form__input-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  padding: 0 16px;
  border: 1px solid #dbe3ee;
  border-radius: var(--ys-control-radius, 6px);
  background: #fff;
}

.password-action-form__field.is-error .password-action-form__input-wrap {
  border-color: #df6f5e;
  background: #fff9f7;
}

.password-action-form__input-wrap input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: none;
  color: #162031;
  font-size: 15px;
  background: transparent;
}

.password-action-form__toggle {
  flex-shrink: 0;
  color: #7e8a9a;
  font-size: 12px;
  font-weight: 700;
}

.password-action-form__hint,
.password-action-form__status.is-error {
  color: #c55242;
  font-size: 12px;
}

.password-action-form__actions {
  display: flex;
  gap: 12px;
  padding-top: 4px;
}

.password-action-button {
  flex: 1;
  min-height: 52px;
  border-radius: 999px;
  font-size: 15px;
  font-weight: 700;
}

.password-action-button.is-secondary {
  border: 1px solid #d7dee8;
  background: #fff;
  color: #435268;
}

.password-action-button.is-primary {
  background: #55b77f;
  color: #fff;
  box-shadow: 0 8px 18px rgba(156, 13, 13, 0.18);
}

.password-action-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .password-action-form__actions {
    flex-direction: column;
  }
}
</style>
