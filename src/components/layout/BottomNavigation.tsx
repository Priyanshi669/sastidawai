import { Clock3, Home, MapPin, Search, Settings } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export function BottomNavigation() {
  const { t } = useTranslation()
  const links = [{ to: '/home', label: t('home'), Icon: Home }, { to: '/search', label: t('search'), Icon: Search }, { to: '/kendras', label: t('kendras'), Icon: MapPin }, { to: '/history', label: t('history'), Icon: Clock3 }, { to: '/settings', label: t('settings'), Icon: Settings }]
  return <nav className="bottom-nav" aria-label="Primary navigation">{links.map(({ to, label, Icon }) => <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'active' : ''}><Icon /><span>{label}</span></NavLink>)}</nav>
}
