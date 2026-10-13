import { Check, X, ArrowRight, Pill } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../../app/AppProvider'
import { useTranslation } from 'react-i18next'

export function ConfirmPage() {
  const { t } = useTranslation()
  const { currentScan } = useApp()
  const navigate = useNavigate()

  return <div className="page-section stack-24 narrow">
    <div className="page-header">
      <div>
        <div className="eyebrow">S01 · {t('scan')}</div>
        <h1>{t('confirmTitle')}</h1>
        <p>{t('confirmDesc')}</p>
      </div>
    </div>

    <section className="card card-pad glass stack-16" style={{ textAlign: 'center', padding: '32px 24px' }}>
      <div className="feature-icon" style={{ margin: '0 auto', width: 56, height: 56 }}>
        <Pill size={28} />
      </div>
      <h2 style={{ fontSize: '1.4rem', marginTop: 8 }}>{t('isItMedicine', { name: currentScan.name })}</h2>
      <p className="muted" style={{ maxWidth: 400, margin: '0 auto' }}>{t('confirmDesc')}</p>
      <div className="row-wrap" style={{ justifyContent: 'center' }}>
        <span className="pill pill-demo">{currentScan.genericName}</span>
        <span className="pill pill-demo">{currentScan.dosageForm}</span>
      </div>
    </section>

    <button className="btn btn-primary btn-block" onClick={() => navigate('/scan/processing', { state: { source: 'scan' } })}>
      {t('yesItsCorrect')} <ArrowRight size={17} />
    </button>
    <button className="btn btn-ghost btn-block" onClick={() => navigate('/scan')}>
      <X size={17} /> {t('noRescan')}
    </button>

    <p className="disclaimer">{t('disclaimer')}</p>
  </div>
}
