import { Bookmark, Clock3, Home, MapPin, Menu, Search, Settings, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppIcon } from '../common/AppIcon'
import { SearchBar } from '../common/SearchBar'

const navItems = [
  { to: '/home', key: 'home', Icon: Home },
  { to: '/search', key: 'search', Icon: Search },
  { to: '/saved', key: 'saved', Icon: Bookmark },
  { to: '/kendras', key: 'kendras', Icon: MapPin },
  { to: '/history', key: 'history', Icon: Clock3 },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const isActive = (path: string) => location.pathname.startsWith(path)

  return <div className="app-shell">
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <div className="sidebar-top"><Link className="brand" to="/home" onClick={() => setMenuOpen(false)}><AppIcon /><span>{t('appName')}</span></Link><button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Close navigation"><X size={18} /></button></div>
      <div className="sidebar-label">{t('workspace')}</div>
      <nav className="side-nav" aria-label="Primary navigation">{navItems.map(({ to, key, Icon }) => <NavLink key={to} to={to} onClick={() => setMenuOpen(false)} className={isActive(to) ? 'active' : ''}><Icon size={18} /><span>{t(key)}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><Link className="side-settings" to="/settings" onClick={() => setMenuOpen(false)}><Settings size={18} /><span>{t('settings')}</span></Link><div className="side-note"><span className="side-note-dot" /><span>{t('sideNote')}</span></div></div>
    </aside>
    {menuOpen && <button className="sidebar-scrim" onClick={() => setMenuOpen(false)} aria-label="Close navigation overlay" />}
    <div className="app-frame">
      <header className="topbar">
        <div className="topbar-inner">
          <button className="icon-button menu-button" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <Link className="brand mobile-brand" to="/home"><AppIcon /><span>{t('appName')}</span></Link>
          <div className="topbar-search">
            <SearchBar value={searchQuery} onChange={setSearchQuery} onSubmit={() => {}} placeholder={t('searchPlaceholder')} />
          </div>
        </div>
      </header>
      <main className="app-main">{children}</main>
    </div>
  </div>
}
