import { Search, X } from 'lucide-react'

export function SearchBar({ value, onChange, onSubmit, placeholder, autoFocus = false }: { value: string, onChange: (value: string) => void, onSubmit?: () => void, placeholder: string, autoFocus?: boolean }) {
  return <form className="search-shell" onSubmit={(event) => { event.preventDefault(); onSubmit?.() }} role="search"><Search size={20} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} aria-label={placeholder} autoFocus={autoFocus} />{value && <button type="button" aria-label="Clear search" onClick={() => onChange('')}><X size={18} /></button>}</form>
}
