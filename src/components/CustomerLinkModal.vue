<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCustomerStore } from '../stores/customerStore'
import { apiRequest } from '../services/apiClient'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  conversationId: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'linked'])

const { t } = useI18n()
const customerStore = useCustomerStore()

const searchQuery = ref('')
const results = ref([])
const isSearching = ref(false)
const errorMessage = ref('')
const isCreating = ref(false)
const createForm = ref({
  name: '',
  email: '',
  phone: '',
})

const isOpen = computed(() => props.modelValue)

const closeModal = () => {
  emit('update:modelValue', false)
}

const resetCreateForm = () => {
  createForm.value = { name: '', email: '', phone: '' }
}

const resolveQuery = (value) => {
  const trimmed = (value || '').trim()
  if (!trimmed) return {}
  if (trimmed.includes('@')) {
    return { email: trimmed }
  }
  return { name: trimmed }
}

const performSearch = async () => {
  errorMessage.value = ''
  isSearching.value = true
  try {
    const query = resolveQuery(searchQuery.value)
    const params = new URLSearchParams(query)
    const suffix = params.toString() ? `?${params.toString()}` : ''
    const data = await apiRequest(`/customers${suffix}`)
    results.value = Array.isArray(data) ? data : data?.items || []
  } catch (error) {
    errorMessage.value = error?.message || t('customer.errors.search_failed')
  } finally {
    isSearching.value = false
  }
}

const handleLink = async (customer) => {
  if (!props.conversationId) {
    errorMessage.value = t('customer.errors.no_conversation')
    return
  }
  errorMessage.value = ''
  try {
    await customerStore.linkCustomer(props.conversationId, customer.id)
    emit('linked', customer)
    closeModal()
  } catch (error) {
    errorMessage.value = error?.message || t('customer.errors.link_failed')
  }
}

const createCustomer = async () => {
  if (!props.conversationId) {
    errorMessage.value = t('customer.errors.no_conversation')
    return
  }
  const name = (createForm.value.name || '').trim()
  if (!name) {
    errorMessage.value = t('customer.create.required')
    return
  }
  errorMessage.value = ''
  isCreating.value = true
  try {
    const payload = {
      name,
      email: (createForm.value.email || '').trim() || null,
      phone: (createForm.value.phone || '').trim() || null,
    }
    const created = await apiRequest('/customers', {
      method: 'POST',
      body: payload,
    })
    await customerStore.linkCustomer(props.conversationId, created.id)
    emit('linked', created)
    resetCreateForm()
    closeModal()
  } catch (error) {
    errorMessage.value = error?.message || t('customer.errors.link_failed')
  } finally {
    isCreating.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      searchQuery.value = ''
      results.value = []
      errorMessage.value = ''
      resetCreateForm()
      performSearch()
    }
  }
)
</script>

<template>
  <div v-if="isOpen" class="customer-modal">
    <div class="customer-modal__backdrop" @click="closeModal" />
    <div class="customer-modal__card" role="dialog" aria-modal="true">
      <header class="customer-modal__header">
        <h3>{{ t('customer.modal.title') }}</h3>
        <button
          type="button"
          class="icon-button"
          :aria-label="t('customer.modal.close')"
          @click="closeModal"
        >
          &times;
        </button>
      </header>

      <form class="customer-modal__search" @submit.prevent="performSearch">
        <input
          type="search"
          v-model="searchQuery"
          :placeholder="t('customer.search.placeholder')"
        />
        <button type="submit" class="primary" :disabled="isSearching">
          {{ isSearching ? t('customer.search.loading') : t('customer.search.action') }}
        </button>
      </form>

      <p v-if="errorMessage" class="customer-modal__error">{{ errorMessage }}</p>

      <div class="customer-modal__results">
        <p v-if="!results.length && !isSearching" class="customer-modal__empty">
          {{ t('customer.search.empty') }}
        </p>
        <article
          v-for="customer in results"
          :key="customer.id"
          class="customer-modal__row"
        >
          <div>
            <p class="customer-modal__name">{{ customer.name }}</p>
            <p class="customer-modal__meta">
              {{ customer.email || t('customer.labels.no_email') }}
            </p>
          </div>
          <button type="button" class="ghost" @click="handleLink(customer)">
            {{ t('customer.actions.link') }}
          </button>
        </article>
      </div>

      <div class="customer-modal__divider" />

      <form class="customer-modal__create" @submit.prevent="createCustomer">
        <h4>{{ t('customer.create.title') }}</h4>
        <label>
          <span>{{ t('customer.create.name_label') }}</span>
          <input v-model="createForm.name" type="text" />
        </label>
        <label>
          <span>{{ t('customer.create.email_label') }}</span>
          <input v-model="createForm.email" type="email" />
        </label>
        <label>
          <span>{{ t('customer.create.phone_label') }}</span>
          <input v-model="createForm.phone" type="text" />
        </label>
        <button type="submit" class="primary" :disabled="isCreating">
          {{ isCreating ? t('customer.create.creating') : t('customer.create.action') }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.customer-modal {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
}

.customer-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(9, 24, 44, 0.45);
}

.customer-modal__card {
  position: relative;
  z-index: 1;
  width: min(520px, 92vw);
  background: #ffffff;
  border-radius: 18px;
  padding: 20px 20px 24px;
  box-shadow: 0 10px 28px rgba(10, 25, 48, 0.16);
}

.customer-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.customer-modal__search {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  margin-bottom: 12px;
}

.customer-modal__search input {
  border: 1px solid #d6deea;
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 12px;
  font-size: 14px;
}

.customer-modal__search .primary {
  border: none;
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 16px;
  background: #263847;
  color: #fff;
  font-weight: 600;
}

.customer-modal__results {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.customer-modal__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 14px;
}

.customer-modal__name {
  margin: 0;
  font-weight: 600;
  color: #0b1d34;
}

.customer-modal__meta {
  margin: 4px 0 0;
  font-size: 13px;
  color: #667085;
}

.customer-modal__error {
  margin: 0 0 12px;
  color: #b42318;
  font-size: 13px;
}

.customer-modal__empty {
  margin: 0;
  font-size: 14px;
  color: #667085;
}

.customer-modal .ghost {
  border: 1px solid #d6deea;
  background: #f8fafc;
  color: #263847;
  border-radius: 999px;
  padding: 8px 14px;
  font-weight: 600;
}

.customer-modal__divider {
  height: 1px;
  background: #e2e8f0;
  margin: 16px 0;
}

.customer-modal__create {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.customer-modal__create h4 {
  margin: 0;
  font-size: 14px;
  color: #0b1d34;
}

.customer-modal__create label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #475569;
}

.customer-modal__create input {
  border: 1px solid #d6deea;
  border-radius: var(--ys-control-radius, 6px);
  padding: 10px 12px;
  font-size: 14px;
}
</style>
