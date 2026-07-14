import { computed, reactive, ref } from 'vue'

import { i18n } from '../i18n'
import { changePassword } from '../services/ysApi'
import { useAuth } from './useAuth'

const CHANGE_PASSWORD_MIN_LENGTH = 8
const LOGOUT_DELAY_MS = 1400

const isChangePasswordOpen = ref(false)
const isSubmitting = ref(false)
const submitError = ref('')
const toast = reactive({
  visible: false,
  title: '',
  message: '',
})
const form = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const fieldErrors = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

let toastTimerId = 0
let logoutTimerId = 0

const t = (key, params = {}) => i18n.global.t(key, params)

const resetFieldErrors = () => {
  fieldErrors.currentPassword = ''
  fieldErrors.newPassword = ''
  fieldErrors.confirmPassword = ''
  submitError.value = ''
}

const resetForm = () => {
  form.currentPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
  resetFieldErrors()
  isSubmitting.value = false
}

const dismissToast = () => {
  toast.visible = false
  toast.title = ''
  toast.message = ''
  if (toastTimerId) {
    window.clearTimeout(toastTimerId)
    toastTimerId = 0
  }
}

const showToast = ({ title, message, duration = 5000 } = {}) => {
  if (typeof window === 'undefined') return
  dismissToast()
  toast.visible = true
  toast.title = title || t('app.topbar.password_modal.toast_title')
  toast.message = message || t('app.topbar.password_modal.toast_message')
  toastTimerId = window.setTimeout(() => {
    dismissToast()
  }, duration)
}

const validateForm = () => {
  resetFieldErrors()
  const currentPassword = String(form.currentPassword || '')
  const newPassword = String(form.newPassword || '')
  const confirmPassword = String(form.confirmPassword || '')

  if (!currentPassword) {
    fieldErrors.currentPassword = t('app.topbar.password_modal.errors.current_required')
  }
  if (!newPassword) {
    fieldErrors.newPassword = t('app.topbar.password_modal.errors.new_required')
  } else if (newPassword.length < CHANGE_PASSWORD_MIN_LENGTH) {
    fieldErrors.newPassword = t('app.topbar.password_modal.errors.new_length', {
      count: CHANGE_PASSWORD_MIN_LENGTH,
    })
  }
  if (!confirmPassword) {
    fieldErrors.confirmPassword = t('app.topbar.password_modal.errors.confirm_required')
  } else if (confirmPassword !== newPassword) {
    fieldErrors.confirmPassword = t('app.topbar.password_modal.errors.confirm_mismatch')
  }

  return !fieldErrors.currentPassword && !fieldErrors.newPassword && !fieldErrors.confirmPassword
}

const scheduleLogoutAfterSuccess = () => {
  if (typeof window === 'undefined') return
  if (logoutTimerId) {
    window.clearTimeout(logoutTimerId)
  }
  const { logout } = useAuth()
  logoutTimerId = window.setTimeout(() => {
    logout({ redirectToPath: '/' })
  }, LOGOUT_DELAY_MS)
}

const openChangePasswordModal = () => {
  resetForm()
  isChangePasswordOpen.value = true
}

const closeChangePasswordModal = () => {
  isChangePasswordOpen.value = false
  resetForm()
}

const submitChangePassword = async () => {
  if (isSubmitting.value) return false
  if (!validateForm()) return false

  isSubmitting.value = true
  submitError.value = ''
  try {
    const result = await changePassword({
      currentPassword: form.currentPassword,
      newPassword: form.newPassword,
      confirmPassword: form.confirmPassword,
    })

    closeChangePasswordModal()
    showToast({
      title: t('app.topbar.password_modal.toast_title'),
      message:
        (result?.message_key && t(result.message_key)) ||
        result?.message ||
        t('app.topbar.password_modal.toast_message'),
      duration: LOGOUT_DELAY_MS + 2400,
    })
    scheduleLogoutAfterSuccess()
    return true
  } catch (error) {
    submitError.value = error?.message || t('api_errors.auth.change_password_failed')
    return false
  } finally {
    isSubmitting.value = false
  }
}

export const usePasswordUi = () => ({
  isChangePasswordOpen: computed(() => isChangePasswordOpen.value),
  isSubmitting: computed(() => isSubmitting.value),
  submitError: computed(() => submitError.value),
  changePasswordToast: computed(() => toast),
  changePasswordForm: form,
  changePasswordFieldErrors: fieldErrors,
  openChangePasswordModal,
  closeChangePasswordModal,
  submitChangePassword,
  dismissChangePasswordToast: dismissToast,
  resetChangePasswordForm: resetForm,
})
