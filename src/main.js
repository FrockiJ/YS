import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router'
import { i18n } from './i18n'
import { useAuth } from './composables/useAuth'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
useAuth().initializeSessionManager(router)
app.mount('#app')
