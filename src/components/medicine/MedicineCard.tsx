import { ArrowUpRight, Bookmark, Pill, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApp } from '../../app/AppProvider'
import type { MedicineRecord } from '../../types'
import { MatchStatus } from '../common/MatchStatus'
import { useTranslation } from 'react-i18next'

export function MedicineCard({ medicine, removable = false, onRemove }: { medicine: MedicineRecord, removable?: boolean, onRemove?: () => void }) {
  const { t } = useTranslation()
  const { isSaved, toggleSaved, setCurrentScan } = useApp()

  return <article className="card medicine-card card-hover glass">
    <div className="medicine-card-head">
      <div className="medicine-symbol">
        <Pill size={22} />
      </div>
      <div className="stack-8" style={{ minWidth: 0, flex: 1 }}>
        <div className="status-row">
          <h3>{medicine.name}</h3>
          {removable ? (
            <button className="icon-button" onClick={onRemove} aria-label={`Remove ${medicine.name}`}><Trash2 size={16} /></button>
          ) : (
            <button className="icon-button" onClick={() => toggleSaved(medicine)} aria-label={isSaved(medicine.id) ? 'Remove saved medicine' : 'Save medicine'}>
              <Bookmark size={17} fill={isSaved(medicine.id) ? 'currentColor' : 'none'} />
            </button>
          )}
        </div>
        <p className="generic">{medicine.genericName} · {medicine.ingredients.map((item) => `${item.name} ${item.strength}`).join(' + ')}</p>
      </div>
    </div>
    <div className="row-wrap">
      <MatchStatus tier={medicine.matchTier} />
      <span className="pill pill-demo">{t('demoCatalogue')}</span>
    </div>
    <div className="medicine-meta">
      <span>{medicine.dosageForm}</span>
      <span>·</span>
      <span>{medicine.packSize}</span>
      <span>·</span>
      <span>{medicine.manufacturer}</span>
    </div>
    <div className="medicine-actions">
      <Link className="btn btn-secondary" to="/results" onClick={() => setCurrentScan(medicine)}>
        {t('viewDetails')} <ArrowUpRight size={15} />
      </Link>
    </div>
  </article>
}
