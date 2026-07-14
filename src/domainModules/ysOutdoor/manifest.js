const QuoteView = () => import('../../views/QuoteView.vue')
const ReturnView = () => import('../../views/ReturnView.vue')
const EdmView = () => import('../../views/EdmView.vue')
const EmailView = () => import('../../views/EmailView.vue')
const LabelSettingsView = () => import('../../views/LabelSettingsView.vue')
const LabelPrintView = () => import('../../views/LabelPrintView.vue')

export const domainModuleId = 'ysOutdoor'

export const moduleDefinitions = Object.freeze([
  {
    id: 'domain.cerp',
    name: 'Business connector',
    layer: 'domain',
    category: 'connector',
    routes: [],
    navIds: [],
    metadata: { domainModule: domainModuleId },
  },
  {
    id: 'domain.quote',
    name: 'Quote and return workflow',
    layer: 'domain',
    category: 'business',
    routes: ['quote', 'quote-returns'],
    navIds: ['quote'],
    dependencies: ['domain.cerp'],
    metadata: { domainModule: domainModuleId },
  },
  {
    id: 'domain.label',
    name: 'Label workflow',
    layer: 'domain',
    category: 'business',
    routes: ['label-settings', 'label-print'],
    navIds: ['showcase'],
    metadata: { domainModule: domainModuleId },
  },
  {
    id: 'domain.edm',
    name: 'EDM and email workflow',
    layer: 'domain',
    category: 'business',
    routes: ['edm', 'edm-share', 'email'],
    dependencies: ['domain.quote'],
    metadata: { domainModule: domainModuleId },
  },
])

export const routes = Object.freeze([
  {
    path: '/quote',
    name: 'quote',
    component: QuoteView,
    meta: { requiresAuth: true, moduleId: 'domain.quote' },
  },
  {
    path: '/quote-returns',
    name: 'quote-returns',
    component: ReturnView,
    meta: { requiresAuth: true, moduleId: 'domain.quote' },
  },
  {
    path: '/edm',
    name: 'edm',
    component: EdmView,
    meta: { requiresAuth: true, moduleId: 'domain.edm' },
  },
  {
    path: '/edm/share/:shareToken',
    name: 'edm-share',
    component: EdmView,
    meta: { moduleId: 'domain.edm' },
  },
  {
    path: '/email',
    name: 'email',
    component: EmailView,
    meta: { requiresAuth: true, moduleId: 'domain.edm' },
  },
  {
    path: '/label-settings',
    name: 'label-settings',
    component: LabelSettingsView,
    meta: { requiresAuth: true, moduleId: 'domain.label' },
  },
  {
    path: '/label-print',
    name: 'label-print',
    component: LabelPrintView,
    meta: { requiresAuth: true, moduleId: 'domain.label' },
  },
])

export const buildNavItems = (t, keyPrefix = 'home.nav') => [
  {
    id: 'showcase',
    label: t(`${keyPrefix}.showcase`),
    icon: 'display',
    route: 'label-settings',
    moduleId: 'domain.label',
  },
  {
    id: 'quote',
    label: t(`${keyPrefix}.quote`),
    icon: 'quote',
    route: 'quote-returns',
    moduleId: 'domain.quote',
  },
]

export default {
  id: domainModuleId,
  moduleDefinitions,
  routes,
  buildNavItems,
}
