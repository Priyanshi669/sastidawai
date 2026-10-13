import type { Kendra, MedicineRecord, ScanRecord } from '../types'

export const mockMedicine: MedicineRecord = {
  id: 'demo-paracetamol-500',
  name: 'Calpol 500',
  genericName: 'Paracetamol',
  ingredients: [{ name: 'Paracetamol', strength: '500 mg' }],
  dosageForm: 'Tablet',
  manufacturer: 'Demo manufacturer',
  packSize: '15 tablets',
  price: { amount: 22.5, currency: 'INR', source: 'Illustrative demo catalogue', asOf: 'Demo only', isDemo: true },
  matchTier: 'exact',
  matchReason: 'Same active ingredient, strength, form and route in the demo catalogue.',
  confidence: 'high',
  sourceLabel: 'Mock response - not a live medicine result',
}

export const mockAlternatives: MedicineRecord[] = [
  {
    ...mockMedicine,
    id: 'demo-paracetamol-jan',
    name: 'Paracetamol 500 mg',
    manufacturer: 'Demo Jan Aushadhi listing',
    price: { amount: 12.0, currency: 'INR', source: 'Illustrative demo catalogue', asOf: 'Demo only', isDemo: true },
    matchTier: 'exact',
    matchReason: 'Demo exact match: all canonical fields align.',
  },
  {
    ...mockMedicine,
    id: 'demo-paracetamol-close',
    name: 'Paracetamol 650 mg',
    manufacturer: 'Demo catalogue candidate',
    ingredients: [{ name: 'Paracetamol', strength: '650 mg' }],
    price: { amount: 16.0, currency: 'INR', source: 'Illustrative demo catalogue', asOf: 'Demo only', isDemo: true },
    matchTier: 'close',
    matchReason: 'Strength differs, so this is not an exact equivalent.',
  },
]

export const mockSearchResults: MedicineRecord[] = [mockMedicine, ...mockAlternatives]

export const mockKendras: Kendra[] = [
  { id: 'kendra-1', name: 'Jan Aushadhi Kendra - Sardarpura', address: 'Sardarpura, Jodhpur, Rajasthan', distance: '1.8 km', hours: '9:00 AM - 8:00 PM', phone: null, isDemo: true, lat: 26.2830, lng: 73.0217 },
  { id: 'kendra-2', name: 'Jan Aushadhi Kendra - Paota', address: 'Paota, Jodhpur, Rajasthan', distance: '3.4 km', hours: '10:00 AM - 7:00 PM', phone: null, isDemo: true, lat: 26.3100, lng: 73.0650 },
]

export const mockHistory: ScanRecord[] = [
  { id: 'scan-demo-1', medicine: mockMedicine, createdAt: 'Today, 10:42 AM', source: 'demo' },
]
