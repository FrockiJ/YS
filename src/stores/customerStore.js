import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiRequest } from '../services/apiClient'

export const useCustomerStore = defineStore('customer', () => {
  const currentCustomer = ref(null)
  const showLinkModal = ref(false)
  const isLinking = ref(false)

  const linkCustomer = async (conversationId, customerId) => {
    if (!conversationId || !customerId) return null
    isLinking.value = true
    try {
      await apiRequest(`/chat/history/${conversationId}/customer`, {
        method: 'PATCH',
        body: { customer_id: customerId },
      })
      return await fetchCustomer(customerId)
    } finally {
      isLinking.value = false
    }
  }

  const fetchCustomer = async (customerId) => {
    if (!customerId) {
      currentCustomer.value = null
      return null
    }
    const data = await apiRequest(`/customers/${customerId}`)
    currentCustomer.value = data
    return data
  }

  const fetchCustomerForConversation = async (conversationId) => {
    if (!conversationId) {
      currentCustomer.value = null
      return null
    }
    const data = await apiRequest(`/chat/history/${conversationId}/messages?limit=1`)
    currentCustomer.value = data?.customer || null
    return currentCustomer.value
  }

  return {
    currentCustomer,
    showLinkModal,
    isLinking,
    linkCustomer,
    fetchCustomer,
    fetchCustomerForConversation,
  }
})
