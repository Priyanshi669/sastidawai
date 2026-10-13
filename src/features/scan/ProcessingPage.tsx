import { ArrowRight, Check, Circle, X } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { MedicineBottleLoader } from '../../components/common/MedicineBottleLoader'
import { useTranslation } from 'react-i18next'

export function ProcessingPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const source = (location.state as { source?: string } | null)?.source || 'demo'

  return <main className="loader-page">
    <div className="loader-backdrop">
      <div className="loader-blob loader-blob-1" />
      <div className="loader-blob loader-blob-2" />
      <div className="loader-blob loader-blob-3" />
    </div>
    <section className="loader-card glass-card">
      <div className="row">
        <strong>{t('appName')}</strong>
        <span className="pill pill-demo">{t('demoMode')}</span>
      </div>
      <MedicineBottleLoader />
      <div className="stack-8">
        <h1>{t('processingTitle')}</h1>
        <p>{t('processingDesc')}</p>
      </div>
      <div className="loader-stages">
        <div className="loader-stage active"><Check size={16} /> {t('photoReceived')} ({source})</div>
        <div className="loader-stage"><Circle size={16} /> {t('readDetails')}</div>
        <div className="loader-stage"><Circle size={16} /> {t('compareFields')}</div>
      </div>
      <button className="btn btn-primary btn-block" onClick={() => navigate('/scan/review')}>{t('openDemoReview')} <ArrowRight size={17} /></button>
      <button className="btn btn-ghost btn-block" onClick={() => navigate('/home')}><X size={17} />{t('cancel')}</button>
    </section>
  </main>
}
