import { ArrowLeft, CheckCircle2, FileWarning } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApp } from '../../app/AppProvider'
import { MatchStatus } from '../../components/common/MatchStatus'
import { PriceComparison } from '../../components/medicine/PriceComparison'
import { mockAlternatives } from '../../lib/mockData'
import { useTranslation } from 'react-i18next'

export function AlternativesPage() {
  const { t } = useTranslation()
  const { currentScan } = useApp()
  const alternatives = mockAlternatives.filter((item) => item.id !== currentScan.id)

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">S04 · {t('alternativesTitle')}</div>
        <h1>{t('alternativesTitle')}</h1>
        <p>{t('alternativesDesc')}</p>
      </div>
      <Link className="btn btn-ghost" to="/results">
        <ArrowLeft size={17} />{t('back')}
      </Link>
    </div>
    <div className="notice notice-warning">
      <FileWarning size={17} />
      <span>{t('demoComparison')}</span>
    </div>
    {alternatives.map((item) => (
      <article className="card card-pad stack-16" key={item.id}>
        <div className="status-row">
          <div>
            <h2 style={{ fontSize: '1.18rem' }}>{item.name}</h2>
            <p className="muted small" style={{ marginTop: 5 }}>{item.genericName} · {item.manufacturer}</p>
          </div>
          <MatchStatus tier={item.matchTier} />
        </div>
        <div className="grid-3">
          <div>
            <span className="label">{t('ingredient')}</span>
            <strong>{item.ingredients.map((ingredient) => `${ingredient.name} ${ingredient.strength}`).join(' + ')}</strong>
          </div>
          <div>
            <span className="label">{t('formPack')}</span>
            <strong>{item.dosageForm} · {item.packSize}</strong>
          </div>
          <div>
            <span className="label">{t('reason')}</span>
            <strong>{item.matchReason}</strong>
          </div>
        </div>
        <PriceComparison medicine={currentScan} alternative={item} />
        {item.matchTier === 'exact' && (
          <div className="notice">
            <CheckCircle2 size={16} />
            <span>{t('exactOnlyNote')}</span>
          </div>
        )}
      </article>
    ))}
    <p className="disclaimer">{t('disclaimer')}</p>
  </div>
}
