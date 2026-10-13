import { Check, Globe2, Info, ShieldCheck, Trash2, Moon, Sun, ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useApp } from '../../app/AppProvider'
import { useNavigate } from 'react-router-dom'
import { useState, useRef, useEffect } from 'react'

const languages = [
  { code: 'en', name: 'English' },
  { code: 'hi', name: 'हिन्दी' },
  { code: 'mr', name: 'मराठी' },
  { code: 'gu', name: 'ગુજરાતી' },
  { code: 'ta', name: 'தமிழ்' },
]

export function SettingsPage() {
  const { t, i18n } = useTranslation()
  const { language, setLanguage, clearLocalData } = useApp()
  const navigate = useNavigate()
  const [isDark, setIsDark] = useState(() => document.documentElement.getAttribute('data-theme') === 'dark')
  const [langOpen, setLangOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const currentLang = languages.find(l => l.code === language) || languages[0]

  function toggleDarkMode() {
    const next = !isDark
    setIsDark(next)
    document.documentElement.setAttribute('data-theme', next ? 'dark' : 'light')
    localStorage.setItem('sasti-theme', next ? 'dark' : 'light')
  }

  function selectLanguage(code: string) {
    setLanguage(code as 'en' | 'hi' | 'mr' | 'gu' | 'ta')
    void i18n.changeLanguage(code)
    setLangOpen(false)
  }

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setLangOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return <div className="page-section stack-24 narrow">
    <div className="page-header">
      <div>
        <div className="eyebrow">{t('settings')}</div>
        <h1>{t('settingsPageTitle')}</h1>
        <p>{t('settingsPageDesc')}</p>
      </div>
    </div>

    <section className="card card-pad">
      <div className="settings-item">
        <div className="row">
          <Globe2 size={19} color="var(--primary-700)" />
          <div>
            <h3>{t('language')}</h3>
            <p>{t('settingsPageDesc')}</p>
          </div>
        </div>
        <div className="lang-dropdown" ref={dropdownRef}>
          <button className="lang-dropdown-trigger" onClick={() => setLangOpen(!langOpen)} aria-haspopup="listbox" aria-expanded={langOpen}>
            <span className="lang-name">{currentLang.name}</span>
            <ChevronDown size={16} className={`lang-chevron ${langOpen ? 'open' : ''}`} />
          </button>
          {langOpen && (
            <div className="lang-dropdown-menu" role="listbox">
              {languages.map((lang) => (
                <button
                  key={lang.code}
                  className={`lang-option ${language === lang.code ? 'active' : ''}`}
                  onClick={() => selectLanguage(lang.code)}
                  role="option"
                  aria-selected={language === lang.code}
                >
                  <span className="lang-name">{lang.name}</span>
                  {language === lang.code && <Check size={16} className="lang-check" />}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="settings-item">
        <div className="row">
          {isDark ? <Moon size={19} color="var(--primary-700)" /> : <Sun size={19} color="var(--primary-700)" />}
          <div>
            <h3>{t('darkMode')}</h3>
            <p>{t('darkModeDesc')}</p>
          </div>
        </div>
        <button className={`switch ${isDark ? 'on' : ''}`} onClick={toggleDarkMode} aria-label="Toggle dark mode" />
      </div>

      <div className="settings-item">
        <div className="row">
          <ShieldCheck size={19} color="var(--primary-700)" />
          <div>
            <h3>{t('privacy')}</h3>
            <p>{t('privacyDesc')}</p>
          </div>
        </div>
        <ShieldCheck size={19} color="var(--primary-700)" />
      </div>
    </section>

    <section className="card card-pad stack-16">
      <div className="row">
        <Info size={19} color="var(--primary-700)" />
        <h2 style={{ fontSize: '1.05rem' }}>{t('aboutData')}</h2>
      </div>
      <p className="muted small">{t('aboutDataDesc')}</p>
      <p className="disclaimer">{t('disclaimer')}</p>
    </section>

    <section className="card card-pad stack-12">
      <h2 style={{ fontSize: '1.05rem' }}>{t('localData')}</h2>
      <p className="muted small">{t('clearDataDesc')}</p>
      <button className="btn btn-danger btn-block" onClick={() => { clearLocalData(); navigate('/home') }}>
        <Trash2 size={17} /> {t('clearData')}
      </button>
    </section>
  </div>
}
