import type { Kendra, MedicineRecord } from '../../types'

export interface ScanResponse {
  scanId: string
  status: 'needs_confirmation' | 'ready' | 'error'
  extraction: MedicineRecord
  fieldStatus: Record<string, 'high' | 'medium' | 'low'>
  warnings: string[]
  nextAction: 'confirm_or_retake' | 'view_result' | 'retry'
  modelVersion?: string
  latencyMs?: number
}

export interface MedicineApi {
  search(query: string): Promise<MedicineRecord[]>
  submitScan(image: Blob): Promise<ScanResponse>
  confirmScan(scanId: string, fields: Partial<MedicineRecord>): Promise<MedicineRecord>
  getAlternatives(medicineId: string): Promise<MedicineRecord[]>
  getKendras(query?: string): Promise<Kendra[]>
}
