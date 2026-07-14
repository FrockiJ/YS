import { createRouter, createWebHistory } from 'vue-router'

import { useAuth } from '../composables/useAuth'
import { isRouteModuleEnabled } from '../core/moduleRegistry'
import { getDomainRoutes } from '../domainModules'
import { canAccessRoute, getFirstAllowedRoute } from '../utils/accessControl'

const HomeView = () => import('../views/HomeView.vue')
const AccountView = () => import('../views/AccountView.vue')
const ProjectView = () => import('../views/ProjectView.vue')
const FileResourcesView = () => import('../views/FileResourcesView.vue')
const ResetPasswordView = () => import('../views/ResetPasswordView.vue')
const SetupPasswordView = () => import('../views/SetupPasswordView.vue')

const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { moduleId: 'core.chat' } },
  {
    path: '/reset-password/:token',
    name: 'reset-password',
    component: ResetPasswordView,
    meta: { moduleId: 'core.auth' },
  },
  {
    path: '/setup-password/:token',
    name: 'setup-password',
    component: SetupPasswordView,
    meta: { moduleId: 'core.auth' },
  },
  {
    path: '/account',
    name: 'account',
    component: AccountView,
    meta: { requiresAuth: true, moduleId: 'core.admin' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: AccountView,
    meta: { requiresAuth: true, moduleId: 'core.admin' },
  },
  {
    path: '/projects',
    name: 'projects',
    component: ProjectView,
    meta: { requiresAuth: true, moduleId: 'core.projects' },
  },
  {
    path: '/file-resources',
    name: 'file-resources',
    component: FileResourcesView,
    meta: { requiresAuth: true, moduleId: 'core.files' },
  },
  ...getDomainRoutes(),
]

const router = createRouter({
  history: createWebHistory(),
  routes: routes.filter(isRouteModuleEnabled),
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  const { isAuthenticated, userProfile } = useAuth()
  if (to.meta?.requiresAuth && !isAuthenticated.value) {
    return { name: 'home', query: { redirect: to.fullPath } }
  }
  if (to.meta?.requiresAuth && !canAccessRoute(userProfile.value, to)) {
    return getFirstAllowedRoute(userProfile.value)
  }
  return true
})

export default router
