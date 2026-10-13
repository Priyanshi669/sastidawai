import { Bookmark, Camera, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useApp } from '../../app/AppProvider'
import { EmptyState } from '../../components/common/EmptyState'
import { MedicineCard } from '../../components/medicine/MedicineCard'

export function SavedPage() {
  const { t } = useTranslation()
  const { saved } = useApp()

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">{t('saved')}</div>
        <h1>{t('savedPageTitle')}</h1>
        <p>{t('savedPageDesc')}</p>
      </div>
      <Link className="btn btn-primary" to="/scan"><Camera size={17} />{t('addByScan')}</Link>
    </div>
    {saved.length ? (
      <div className="grid-2">{saved.map((medicine) => <MedicineCard medicine={medicine} key={medicine.id} />)}</div>
    ) : (
      <div className="card">
        <EmptyState
          icon={Bookmark}
          title={t('nothingSaved')}
          description={t('noSaved')}
          action={<Link className="btn btn-secondary" to="/search"><Plus size={16} />{t('browseCatalogue')}</Link>}
        />
      </div>
    )}
    <div className="notice">
      <Bookmark size={17} />
      <span>{t('savedNote')}</span>
    </div>
  </div>
}
