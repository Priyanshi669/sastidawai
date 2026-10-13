import { Clock3, Search as SearchIcon, SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/common/EmptyState'
import { SearchBar } from '../../components/common/SearchBar'
import { MedicineCard } from '../../components/medicine/MedicineCard'
import { medicineApi } from '../../services/api'
import type { MedicineRecord } from '../../types'

export function SearchPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') || '')
  const [results, setResults] = useState<MedicineRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('All')

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true)
      setError('')
      medicineApi.search(query)
        .then(setResults)
        .catch(() => setError('Search is unavailable. Try again or use the demo mode.'))
        .finally(() => setLoading(false))
    }, 260)
    return () => window.clearTimeout(timer)
  }, [query])

  const filtered = filter === 'Exact only' ? results.filter((item) => item.matchTier === 'exact') : results

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">{t('search')}</div>
        <h1>{t('searchPageTitle')}</h1>
        <p>{t('searchPageDesc')}</p>
      </div>
    </div>
    <SearchBar value={query} onChange={setQuery} onSubmit={() => undefined} placeholder={t('searchPlaceholder')} autoFocus />
    <div className="filter-row">
      <button className={`filter-chip ${filter === 'All' ? 'active' : ''}`} onClick={() => setFilter('All')}>
        <SlidersHorizontal size={14} style={{ verticalAlign: 'middle' }} /> All results
      </button>
      <button className={`filter-chip ${filter === 'Exact only' ? 'active' : ''}`} onClick={() => setFilter('Exact only')}>
        Exact only
      </button>
      <button className="filter-chip" onClick={() => setQuery('Paracetamol')}>
        Try: Paracetamol
      </button>
    </div>
    {loading && <div className="card card-pad"><p className="muted">{t('searching')}</p></div>}
    {error && <div className="notice notice-warning">
      <span>{error}</span>
      <button className="btn btn-ghost" onClick={() => { setError(''); setQuery((value) => `${value} `) }}>Retry</button>
    </div>}
    {!loading && !error && filtered.length > 0 && (
      <div className="grid-2">{filtered.map((medicine) => <MedicineCard medicine={medicine} key={medicine.id} />)}</div>
    )}
    {!loading && !error && !filtered.length && (
      <div className="card">
        <EmptyState
          icon={SearchIcon}
          title={t('noResults')}
          description={query ? `Nothing matches "${query}". Try a brand or ingredient.` : 'Start with a brand or ingredient.'}
          action={<button className="btn btn-secondary" onClick={() => setQuery('Paracetamol')}><SearchIcon size={16} />{t('tryDemoSearch')}</button>}
        />
      </div>
    )}
    <section className="card card-pad stack-12">
      <div className="row">
        <Clock3 size={17} color="var(--primary-700)" />
        <h3 style={{ fontSize: '1rem' }}>{t('recentSearches')}</h3>
      </div>
      <div className="row-wrap" style={{ marginTop: 4 }}>
        <button className="search-tag" onClick={() => setQuery('Paracetamol')}>Paracetamol</button>
        <button className="search-tag" onClick={() => setQuery('Calpol')}>Calpol</button>
      </div>
    </section>
  </div>
}
