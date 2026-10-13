import { mockAlternatives, mockKendras, mockMedicine, mockSearchResults } from '../../lib/mockData'
import type { MedicineApi, ScanResponse } from './contracts'

export const mockApi: MedicineApi = {
  async search(query) {
    const value = query.trim().toLowerCase()
    return value ? mockSearchResults.filter((item) => `${item.name} ${item.genericName}`.toLowerCase().includes(value)) : mockSearchResults
  },
  async submitScan() {
    const response: ScanResponse = {
      scanId: 'mock-scan-001',
      status: 'needs_confirmation',
      extraction: mockMedicine,
      fieldStatus: { name: 'high', ingredients: 'high', dosageForm: 'medium', manufacturer: 'low' },
      warnings: ['This is a clearly labelled demo response.'],
      nextAction: 'confirm_or_retake',
      modelVersion: 'mock-provider',
    }
    return response
  },
  async confirmScan() { return mockMedicine },
  async getAlternatives() { return mockAlternatives },
  async getKendras(query = '') {
    return query ? mockKendras.filter((kendra) => kendra.address.toLowerCase().includes(query.toLowerCase())) : mockKendras
  },
}
