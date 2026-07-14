<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle2, KeyRound, LogOut, UserRound, X } from 'lucide-vue-next'

import { useAuth } from '../composables/useAuth'
import { usePasswordUi } from '../composables/usePasswordUi'

const { t } = useI18n()

const props = defineProps({
  placement: { type: String, default: 'sidebar' },
})

const emit = defineEmits(['logout'])

const rootRef = ref(null)
const buttonRef = ref(null)
const menuRef = ref(null)
const isOpen = ref(false)
const showCurrentPassword = ref(false)
const showNewPassword = ref(false)
const showConfirmPassword = ref(false)

const { logout: performLogout, avatarLabel, userProfile } = useAuth()
const {
  isChangePasswordOpen,
  isSubmitting,
  submitError,
  changePasswordToast,
  changePasswordForm,
  changePasswordFieldErrors,
  openChangePasswordModal,
  closeChangePasswordModal,
  submitChangePassword,
  dismissChangePasswordToast,
} = usePasswordUi()

const profileName = computed(() => {
  const profile = userProfile.value || {}
  const name = String(profile.name || profile.username || t('app.topbar.default_name')).trim()
  const account = String(profile.username || '').trim()
  if (!account || name === account) return name
  return `${name} (${account})`
})

const profileEmail = computed(() => String(userProfile.value?.email || '').trim() || t('app.topbar.no_email'))
const resolvedAvatarLabel = computed(() => avatarLabel.value || t('app.topbar.avatar_fallback'))

const modalFields = computed(() => [
  {
    key: 'currentPassword',
    label: t('app.topbar.password_modal.fields.current_password'),
    model: 'currentPassword',
    visible: showCurrentPassword.value,
    error: changePasswordFieldErrors.currentPassword,
    autocomplete: 'current-password',
  },
  {
    key: 'newPassword',
    label: t('app.topbar.password_modal.fields.new_password'),
    model: 'newPassword',
    visible: showNewPassword.value,
    error: changePasswordFieldErrors.newPassword,
    autocomplete: 'new-password',
  },
  {
    key: 'confirmPassword',
    label: t('app.topbar.password_modal.fields.confirm_password'),
    model: 'confirmPassword',
    visible: showConfirmPassword.value,
    error: changePasswordFieldErrors.confirmPassword,
    autocomplete: 'new-password',
  },
])

const toggleMenu = () => {
  isOpen.value = !isOpen.value
}

const closeMenu = () => {
  isOpen.value = false
}

const handleDocumentClick = (event) => {
  if (!isOpen.value) return
  const target = event.target
  if (rootRef.value?.contains(target) || buttonRef.value?.contains(target) || menuRef.value?.contains(target)) {
    return
  }
  closeMenu()
}

const handleKeydown = (event) => {
  if (event.key === 'Escape') closeMenu()
}

const handleOpenChangePassword = () => {
  closeMenu()
  openChangePasswordModal()
}

const handleCloseChangePassword = () => {
  closeChangePasswordModal()
  showCurrentPassword.value = false
  showNewPassword.value = false
  showConfirmPassword.value = false
}

const togglePasswordVisibility = (fieldKey) => {
  if (fieldKey === 'currentPassword') {
    showCurrentPassword.value = !showCurrentPassword.value
    return
  }
  if (fieldKey === 'newPassword') {
    showNewPassword.value = !showNewPassword.value
    return
  }
  showConfirmPassword.value = !showConfirmPassword.value
}

const handleLogout = () => {
  closeMenu()
  emit('logout')
  performLogout({ redirectToPath: '/' })
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div ref="rootRef" class="account-menu-host" :class="`is-${placement}`">
    <button
      ref="buttonRef"
      type="button"
      class="account-menu-trigger"
      :aria-label="t('app.topbar.avatar_aria')"
      :aria-expanded="isOpen"
      aria-haspopup="menu"
      @click="toggleMenu"
    >
      <UserRound :size="18" :stroke-width="2" aria-hidden="true" />
      <span>{{ resolvedAvatarLabel }}</span>
    </button>

    <div v-if="isOpen" ref="menuRef" class="account-menu-panel" role="menu">
      <div class="account-menu-panel__profile">
        <p class="account-menu-panel__name">{{ profileName }}</p>
        <p class="account-menu-panel__email">{{ profileEmail }}</p>
      </div>
      <div class="account-menu-panel__divider" aria-hidden="true" />
      <button type="button" class="account-menu-panel__item" role="menuitem" @click="handleOpenChangePassword">
        <KeyRound aria-hidden="true" :size="17" :stroke-width="1.9" />
        {{ t('app.topbar.menu.change_password') }}
      </button>
      <button type="button" class="account-menu-panel__item" role="menuitem" @click="handleLogout">
        <LogOut aria-hidden="true" :size="17" :stroke-width="1.9" />
        {{ t('app.topbar.logout') }}
      </button>
    </div>
  </div>

  <div
    v-if="isChangePasswordOpen"
    class="password-modal-mask"
    role="dialog"
    aria-modal="true"
    @click.self="handleCloseChangePassword"
  >
    <div class="password-modal">
      <header class="password-modal__header">
        <div>
          <p class="password-modal__eyebrow">{{ t('app.topbar.password_modal.eyebrow') }}</p>
          <h3>{{ t('app.topbar.password_modal.title') }}</h3>
        </div>
        <button type="button" class="password-modal__close" @click="handleCloseChangePassword">
          <X aria-hidden="true" :size="18" :stroke-width="2" />
        </button>
      </header>
      <div class="password-modal__body">
        <p class="password-modal__copy">{{ t('app.topbar.password_modal.copy') }}</p>
        <label
          v-for="field in modalFields"
          :key="field.key"
          class="password-modal__field"
          :class="{ 'is-error': field.error }"
        >
          <span>{{ field.label }}</span>
          <div class="password-modal__input-wrap">
            <input
              v-model="changePasswordForm[field.model]"
              :type="field.visible ? 'text' : 'password'"
              :autocomplete="field.autocomplete"
            />
            <button type="button" class="password-modal__toggle" @click="togglePasswordVisibility(field.key)">
              {{ field.visible ? t('common.actions.hide') : t('common.actions.show') }}
            </button>
          </div>
          <p v-if="field.error" class="password-modal__hint">{{ field.error }}</p>
        </label>
        <p v-if="submitError" class="password-modal__status is-error">{{ submitError }}</p>
      </div>
      <footer class="password-modal__footer">
        <button type="button" class="password-modal__button is-secondary" @click="handleCloseChangePassword">
          {{ t('common.actions.cancel') }}
        </button>
        <button type="button" class="password-modal__button is-primary" :disabled="isSubmitting" @click="submitChangePassword">
          {{ isSubmitting ? t('common.actions.saving') : t('common.actions.confirm') }}
        </button>
      </footer>
    </div>
  </div>

  <div v-if="changePasswordToast.visible" class="password-toast">
    <div class="password-toast__icon" aria-hidden="true">
      <CheckCircle2 :size="20" :stroke-width="2" />
    </div>
    <div class="password-toast__content">
      <strong>{{ changePasswordToast.title }}</strong>
      <p>{{ changePasswordToast.message }}</p>
    </div>
    <button type="button" class="password-toast__dismiss" @click="dismissChangePasswordToast">
      <X aria-hidden="true" :size="17" :stroke-width="2" />
    </button>
  </div>
</template>

<style scoped>
.account-menu-host {
  position: relative;
}

.account-menu-host.is-sidebar {
  padding-bottom: 0;
}

.account-menu-trigger {
  width: 76px;
  min-height: 54px;
  display: grid;
  place-items: center;
  gap: 3px;
  border-radius: 18px;
  color: rgba(255, 255, 255, 0.82);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.account-menu-trigger span {
  max-width: 66px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 800;
}

.account-menu-trigger:hover,
.account-menu-trigger:focus-visible {
  color: #10241f;
  background: linear-gradient(135deg, #f4d48a, #9fbea8);
}

.account-menu-panel {
  position: fixed;
  left: 128px;
  bottom: 20px;
  width: 286px;
  max-width: calc(100vw - 152px);
  max-height: calc(100vh - 40px);
  overflow: auto;
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 20px;
  border: 1px solid rgba(27, 45, 41, 0.12);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 8px 22px rgba(16, 36, 31, 0.15);
  z-index: 80;
}

.account-menu-panel__profile {
  display: grid;
  gap: 4px;
}

.account-menu-panel__name,
.account-menu-panel__email {
  margin: 0;
}

.account-menu-panel__name {
  color: #10241f;
  font-size: 16px;
  font-weight: 900;
}

.account-menu-panel__email {
  color: #64766f;
  font-size: 12px;
  word-break: break-word;
}

.account-menu-panel__divider {
  height: 1px;
  background: rgba(27, 45, 41, 0.1);
}

.account-menu-panel__item {
  min-height: 42px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border-radius: 12px;
  color: #1b2d29;
  font-weight: 800;
  text-align: left;
}

.account-menu-panel__item:hover,
.account-menu-panel__item:focus-visible {
  color: #6c4300;
  background: #fff3d4;
}

.password-modal-mask {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(16, 36, 31, 0.62);
  z-index: 140;
}

.password-modal {
  width: min(420px, 100%);
  overflow: hidden;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 9px 24px rgba(16, 36, 31, 0.17);
}

.password-modal__header,
.password-modal__footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 22px;
}

.password-modal__header {
  align-items: flex-start;
  padding-bottom: 14px;
}

.password-modal__eyebrow {
  margin: 0 0 6px;
  color: #466779;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.password-modal__header h3 {
  margin: 0;
  color: #10241f;
}

.password-modal__close,
.password-toast__dismiss {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: #64766f;
}

.password-modal__body {
  display: grid;
  gap: 16px;
  padding: 0 22px 22px;
}

.password-modal__copy,
.password-modal__hint,
.password-modal__status {
  margin: 0;
  color: #64766f;
  font-size: 13px;
  line-height: 1.6;
}

.password-modal__field {
  display: grid;
  gap: 8px;
}

.password-modal__field span {
  color: #1b2d29;
  font-size: 12px;
  font-weight: 800;
}

.password-modal__input-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  padding: 0 14px;
  border: 1px solid #d9e2dc;
  border-radius: var(--ys-control-radius, 6px);
}

.password-modal__input-wrap input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: none;
  color: #10241f;
  background: transparent;
}

.password-modal__toggle {
  flex-shrink: 0;
  color: #466779;
  font-size: 12px;
  font-weight: 800;
}

.password-modal__hint,
.password-modal__status.is-error {
  color: #c55242;
}

.password-modal__footer {
  justify-content: flex-end;
  padding-top: 0;
}

.password-modal__button {
  min-width: 84px;
  height: 36px;
  padding: 0 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 900;
}

.password-modal__button.is-secondary {
  border: 1px solid #d9e2dc;
  color: #466779;
  background: #fff;
}

.password-modal__button.is-primary {
  color: #fff;
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
}

.password-toast {
  position: fixed;
  right: 24px;
  bottom: 24px;
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 320px;
  max-width: calc(100vw - 32px);
  padding: 14px 16px;
  border-radius: 14px;
  color: #fff;
  background: #10241f;
  box-shadow: 0 8px 20px rgba(16, 36, 31, 0.16);
  z-index: 145;
}

.password-toast__icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.16);
}

.password-toast__content {
  flex: 1;
}

.password-toast__content strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
}

.password-toast__content p {
  margin: 0;
  color: rgba(255, 255, 255, 0.8);
  font-size: 12px;
}

@media (max-width: 720px) {
  .account-menu-panel {
    left: 16px;
    right: 16px;
    bottom: 16px;
    width: auto;
    max-width: none;
    max-height: min(420px, calc(100vh - 32px));
  }

  .password-toast {
    left: 16px;
    right: 16px;
    min-width: 0;
  }
}
</style>
