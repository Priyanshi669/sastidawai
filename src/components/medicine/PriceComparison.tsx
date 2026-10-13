import { Info } from 'lucide-react'
import type { MedicineRecord } from '../../types'
import { useTranslation } from 'react-i18next'

export function PriceComparison({ medicine, alternative }: { medicine: MedicineRecord, alternative?: MedicineRecord }) {
  const { t } = useTranslation()
  return <div className="stack-12">
    <div className="row">
      <h3 style={{ fontSize: '1rem' }}>{t('priceContext')}</h3>
      <span className="pill pill-demo">{t('demoOnly')}</span>
    </div>
    <div className="grid-2">
      <div className="price-box">
        <span>Scanned pack<strong>{medicine.price ? `₹${medicine.price.amount?.toFixed(2)}` : 'N/A'}</strong></span>
        <Info size={16} color="var(--ink-500)" />
      </div>
      {alternative && <div className="price-box">
        <span>Candidate pack<strong>{alternative.price ? `₹${alternative.price.amount?.toFixed(2)}` : 'N/A'}</strong></span>
        <Info size={16} color="var(--ink-500)" />
      </div>}
    </div>
    <p className="muted small">{t('priceNote')}</p>
  </div>
}
