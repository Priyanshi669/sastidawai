import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import i18n from '../i18n'
import { mockHistory, mockMedicine } from '../lib/mockData'
import type { Language, MedicineRecord, ScanRecord } from '../types'

interface AppContextValue {
  language: Language
  setLanguage: (language: Language) => void
  currentScan: MedicineRecord
  setCurrentScan: (medicine: MedicineRecord) => void
  saved: MedicineRecord[]
  toggleSaved: (medicine: MedicineRecord) => void
  isSaved: (medicineId: string) => boolean
  history: ScanRecord[]
  addToHistory: (medicine: MedicineRecord, source?: ScanRecord['source']) => void
  removeFromHistory: (scanId: string) => void
  clearLocalData: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

function readJson<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || '') as T } catch { return fallback }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>((localStorage.getItem('sasti-language') as Language) || 'en')
  const [currentScan, setCurrentScan] = useState<MedicineRecord>(mockMedicine)
  const [saved, setSaved] = useState<MedicineRecord[]>(() => readJson('sasti-saved', []))
  const [history, setHistory] = useState<ScanRecord[]>(() => readJson('sasti-history', mockHistory))

  useEffect(() => { void i18n.changeLanguage(language); localStorage.setItem('sasti-language', language) }, [language])
  useEffect(() => { localStorage.setItem('sasti-saved', JSON.stringify(saved)) }, [saved])
  useEffect(() => { localStorage.setItem('sasti-history', JSON.stringify(history)) }, [history])

  // Apply saved theme on mount
  useEffect(() => {
    const savedTheme = localStorage.getItem('sasti-theme')
    if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme)
  }, [])

  const value = useMemo<AppContextValue>(() => ({
    language,
    setLanguage: (next) => setLanguageState(next),
    currentScan,
    setCurrentScan,
    saved,
    toggleSaved: (medicine) => setSaved((items) => items.some((item) => item.id === medicine.id) ? items.filter((item) => item.id !== medicine.id) : [...items, medicine]),
    isSaved: (medicineId) => saved.some((item) => item.id === medicineId),
    history,
    addToHistory: (medicine, source = 'demo') => setHistory((items) => [{ id: `scan-${Date.now()}`, medicine, createdAt: 'Just now', source }, ...items.filter((item) => item.medicine.id !== medicine.id)].slice(0, 12)),
    removeFromHistory: (scanId) => setHistory((items) => items.filter((item) => item.id !== scanId)),
    clearLocalData: () => { setSaved([]); setHistory([]); localStorage.removeItem('sasti-saved'); localStorage.removeItem('sasti-history') },
  }), [currentScan, history, language, saved])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used inside AppProvider')
  return context
}
