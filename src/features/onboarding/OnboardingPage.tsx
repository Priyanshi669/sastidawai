import { ArrowRight, Check, Globe2, ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../../app/AppProvider'
import { AppIcon } from '../../components/common/AppIcon'
import { MedicineBottleLoader } from '../../components/common/MedicineBottleLoader'

export function OnboardingPage() {
  const { t } = useTranslation()
  const { language, setLanguage } = useApp()
  const navigate = useNavigate()

  return <main className="loader-page">
    <div className="loader-backdrop">
      <div className="loader-blob loader-blob-1" />
      <div className="loader-blob loader-blob-2" />
      <div className="loader-blob loader-blob-3" />
    </div>
    <section className="loader-card glass-card" style={{ width: 'min(100%, 520px)', padding: '28px 22px' }}>
      <div className="row">
        <AppIcon size={21} />
        <strong>{t('appName')}</strong>
      </div>
      <MedicineBottleLoader size="small" />
      <div className="stack-8">
        <div className="eyebrow">{t('tagline')}</div>
        <h1>{t('homeTitle')}</h1>
        <p>{t('homeSubtitle')}</p>
      </div>
      <div className="card card-pad stack-12" style={{ width: '100%', textAlign: 'left' }}>
        <div className="row">
          <Globe2 size={18} color="var(--green-800)" />
          <strong>{t('language')}</strong>
        </div>
        <div className="segmented" style={{ width: '100%' }}>
          <button style={{ flex: 1 }} className={language === 'en' ? 'active' : ''} onClick={() => setLanguage('en')}>{t('english')}</button>
          <button style={{ flex: 1 }} className={language === 'hi' ? 'active' : ''} onClick={() => setLanguage('hi')}>{t('hindi')}</button>
        </div>
        <div className="stack-8 small muted">
          <span><Check size={14} style={{ verticalAlign: 'middle' }} /> English and Hindi interface</span>
          <span><ShieldCheck size={14} style={{ verticalAlign: 'middle' }} /> No account required for demo mode</span>
        </div>
      </div>
      <button className="btn btn-primary btn-block" onClick={() => navigate('/home')}>{t('continue')} <ArrowRight size={17} /></button>
      <p className="disclaimer">{t('disclaimer')}</p>
    </section>
  </main>
}
