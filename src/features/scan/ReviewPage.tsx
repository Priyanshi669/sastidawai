import { AlertCircle, ArrowRight, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../../app/AppProvider'
import { useTranslation } from 'react-i18next'

export function ReviewPage() {
  const { t } = useTranslation()
  const { currentScan, setCurrentScan, addToHistory } = useApp()
  const navigate = useNavigate()
  const [name, setName] = useState(currentScan.name)
  const [strength, setStrength] = useState(currentScan.ingredients[0]?.strength || '')
  const [form, setForm] = useState(currentScan.dosageForm)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const next = { ...currentScan, name: name.trim(), ingredients: [{ ...currentScan.ingredients[0], strength: strength.trim() }], dosageForm: form }
    setCurrentScan(next)
    addToHistory(next, 'demo')
    navigate('/results')
  }

  return <div className="page-section stack-24 narrow">
    <div className="page-header">
      <div>
        <div className="eyebrow">S02 · {t('reviewTitle')}</div>
        <h1>{t('reviewTitle')}</h1>
        <p>{t('reviewDesc')}</p>
      </div>
    </div>
    <div className="notice">
      <AlertCircle size={17} />
      <span>{t('mockResult')}</span>
    </div>
    <form className="card card-pad stack-24" onSubmit={submit}>
      <div className="row">
        <CheckCircle2 size={19} color="var(--green-800)" />
        <div>
          <strong>{t('visibleFields')}</strong>
          <p className="muted small">{t('editHint')}</p>
        </div>
      </div>
      <div className="form-grid">
        <label className="field">
          <span className="label">{t('medicineName')}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="field">
          <span className="label">{t('strength')}</span>
          <input value={strength} onChange={(event) => setStrength(event.target.value)} required />
        </label>
        <label className="field">
          <span className="label">{t('dosageForm')}</span>
          <select value={form} onChange={(event) => setForm(event.target.value)}>
            <option>Tablet</option>
            <option>Capsule</option>
            <option>Syrup</option>
            <option>Cream</option>
          </select>
        </label>
        <label className="field">
          <span className="label">{t('manufacturer')}</span>
          <input value={currentScan.manufacturer} disabled />
        </label>
      </div>
      <div className="row-wrap">
        <span className="pill pill-demo">{t('medicineName')} · high confidence</span>
        <span className="pill pill-close">{t('dosageForm')} · medium confidence</span>
      </div>
      <button className="btn btn-primary btn-block" type="submit">{t('confirmAndView')} <ArrowRight size={17} /></button>
    </form>
    <p className="disclaimer">{t('disclaimer')}</p>
  </div>
}
