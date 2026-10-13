export type Language = 'en' | 'hi' | 'mr' | 'gu' | 'ta'
export type MatchTier = 'exact' | 'close' | 'none' | 'needs_confirmation'

export interface PriceInfo {
  amount: number | null
  currency: 'INR'
  source: string
  asOf: string
  isDemo: boolean
}

export interface Ingredient {
  name: string
  strength: string
}

export interface MedicineRecord {
  id: string
  name: string
  genericName: string
  ingredients: Ingredient[]
  dosageForm: string
  manufacturer: string
  packSize: string
  price: PriceInfo | null
  matchTier: MatchTier
  matchReason: string
  confidence?: 'high' | 'medium' | 'low'
  sourceLabel: string
}

export interface ScanRecord {
  id: string
  medicine: MedicineRecord
  createdAt: string
  source: 'demo' | 'upload' | 'camera'
}

export interface Kendra {
  id: string
  name: string
  address: string
  distance: string
  hours: string
  phone: string | null
  isDemo: boolean
  lat?: number
  lng?: number
}
