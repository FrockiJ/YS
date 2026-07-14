import iconChat from '../assets/ic-chat.svg'
import iconFolder from '../assets/ic-folder.svg'
import iconDisplay from '../assets/ic-display.svg'
import iconQuote from '../assets/ic-quote.svg'
import iconFile from '../assets/ic-file.svg'
import iconTeam from '../assets/ic-team.svg'
import iconSettings from '../assets/ic-settings.svg'
import { isNavModuleEnabled } from '../core/moduleRegistry'
import { getDomainNavItems } from '../domainModules'
import { canAccessNavItem } from './accessControl'

export const PRIMARY_NAV_ICON_IMAGES = {
  chat: iconChat,
  folder: iconFolder,
  display: iconDisplay,
  quote: iconQuote,
  file: iconFile,
  team: iconTeam,
  settings: iconSettings,
}

export const buildPrimaryNavItems = (t, profile, keyPrefix = 'home.nav') =>
  [
    { id: 'chat', label: t(`${keyPrefix}.chat`), icon: 'chat', route: 'home', moduleId: 'core.chat' },
    {
      id: 'project',
      label: t(`${keyPrefix}.project`),
      icon: 'folder',
      route: 'projects',
      moduleId: 'core.projects',
    },
    ...getDomainNavItems(t, keyPrefix),
    {
      id: 'file-resources',
      label: t(`${keyPrefix}.files`),
      icon: 'file',
      route: 'file-resources',
      dividerAfter: true,
      moduleId: 'core.files',
    },
    {
      id: 'permission',
      label: t(`${keyPrefix}.permission`),
      icon: 'team',
      route: 'account',
      moduleId: 'core.admin',
    },
    {
      id: 'settings',
      label: t(`${keyPrefix}.settings`),
      icon: 'settings',
      route: 'settings',
      moduleId: 'core.admin',
    },
  ].filter((item) => isNavModuleEnabled(item) && canAccessNavItem(profile, item.id))
