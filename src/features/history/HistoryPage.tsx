import { Clock3, ExternalLink, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useApp } from '../../app/AppProvider'
import { EmptyState } from '../../components/common/EmptyState'
import { MatchStatus } from '../../components/common/MatchStatus'

export function HistoryPage() {
  const { t } = useTranslation()
  const { history, removeFromHistory, setCurrentScan } = useApp()

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">{t('history')}</div>
        <h1>{t('historyPageTitle')}</h1>
        <p>{t('historyPageDesc')}</p>
      </div>
    </div>
    {history.length ? (
      <div className="card card-pad">
        {history.map((scan) => (
          <article className="list-row" key={scan.id}>
            <div className="feature-icon" style={{ margin: 0 }}><Clock3 size={18} /></div>
            <div style={{ flex: 1 }}>
              <div className="row-wrap">
                <h3>{scan.medicine.name}</h3>
                <MatchStatus tier={scan.medicine.matchTier} />
              </div>
              <p>{scan.createdAt} · {scan.source === 'demo' ? 'Demo scan' : 'Uploaded image'}</p>
            </div>
            <Link className="icon-button" to="/results" onClick={() => setCurrentScan(scan.medicine)} aria-label={`Open ${scan.medicine.name}`}>
              <ExternalLink size={17} />
            </Link>
            <button className="icon-button" onClick={() => removeFromHistory(scan.id)} aria-label={`Delete ${scan.medicine.name}`}>
              <Trash2 size={16} />
            </button>
          </article>
        ))}
      </div>
    ) : (
      <div className="card">
        <EmptyState icon={Clock3} title={t('noHistoryTitle')} description={t('noHistory')} />
      </div>
    )}
    <div className="notice">
      <Clock3 size={17} />
      <span>{t('historyNote')}</span>
    </div>
  </div>
}
