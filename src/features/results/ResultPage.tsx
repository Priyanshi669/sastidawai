import { ArrowRight, Bookmark, CheckCircle2, FileWarning, Share2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useApp } from '../../app/AppProvider'
import { MatchStatus } from '../../components/common/MatchStatus'
import { PriceComparison } from '../../components/medicine/PriceComparison'

export function ResultPage() {
  const { t } = useTranslation()
  const { currentScan, toggleSaved, isSaved } = useApp()

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">S03 · {t('resultTitle')}</div>
        <h1>{t('resultTitle')}</h1>
        <p>{t('resultDesc')}</p>
      </div>
      <button className="btn btn-ghost" onClick={() => toggleSaved(currentScan)}>
        <Bookmark size={17} fill={isSaved(currentScan.id) ? 'currentColor' : 'none'} />
        {isSaved(currentScan.id) ? t('saved') : t('save')}
      </button>
    </div>
    <div className="notice notice-warning">
      <FileWarning size={17} />
      <span><strong>{t('mockResult')}</strong></span>
    </div>
    <section className="result-hero">
      <MatchStatus tier={currentScan.matchTier} />
      <h1>{currentScan.name}</h1>
      <p>{currentScan.genericName} · {currentScan.dosageForm} · {currentScan.packSize}</p>
      <div className="row-wrap" style={{ marginTop: 15 }}>
        <span className="pill pill-demo">{t('demoCatalogue')}</span>
        <span className="pill pill-demo">{currentScan.confidence || 'medium'} confidence</span>
      </div>
    </section>
    <div className="grid-2">
      <section className="card card-pad stack-16">
        <div className="section-heading">
          <h2>{t('activeIngredients')}</h2>
          <CheckCircle2 size={18} color="var(--green-800)" />
        </div>
        <div>{currentScan.ingredients.map((ingredient) => (
          <div className="ingredient-row" key={ingredient.name}>
            <span>{ingredient.name}</span>
            <strong>{ingredient.strength}</strong>
          </div>
        ))}</div>
        <div className="medicine-meta">
          <span>{t('manufacturer')}: {currentScan.manufacturer}</span>
          <span>·</span>
          <span>{t('dosageForm')}: {currentScan.dosageForm}</span>
        </div>
      </section>
      <section className="card card-pad stack-16">
        <div className="section-heading">
          <h2>{t('whyThisStatus')}</h2>
        </div>
        <p className="muted small">{currentScan.matchReason}</p>
        <div className="notice">
          <CheckCircle2 size={16} />
          <span>{t('exactOnlyNote')}</span>
        </div>
      </section>
    </div>
    <section className="card card-pad">
      <PriceComparison medicine={currentScan} />
    </section>
    <p className="disclaimer">{t('disclaimer')}</p>
  </div>
}
