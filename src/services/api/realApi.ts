import type { Kendra, MedicineRecord } from '../../types'
import type { MedicineApi, ScanResponse } from './contracts'

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { headers: { Accept: 'application/json', ...options?.headers }, ...options })
  if (!response.ok) throw new Error(`API request failed (${response.status})`)
  return response.json() as Promise<T>
}

export const realApi: MedicineApi = {
  async search(query) { return request<MedicineRecord[]>(`/v1/search?q=${encodeURIComponent(query)}`) },
  async submitScan(image) {
    const form = new FormData()
    form.append('image', image)
    return request<ScanResponse>('/v1/scan', { method: 'POST', body: form })
  },
  async confirmScan(scanId, fields) { return request<MedicineRecord>(`/v1/scan/${scanId}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields) }) },
  async getAlternatives(medicineId) { return request<MedicineRecord[]>(`/v1/match?medicine_id=${encodeURIComponent(medicineId)}`) },
  async getKendras(query = '') { return request<Kendra[]>(`/v1/kendras/nearby?q=${encodeURIComponent(query)}`) },
}
