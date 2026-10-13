import { mockApi } from './mockApi'
import { realApi } from './realApi'

export const useMocks = import.meta.env.VITE_USE_MOCKS !== 'false'
export const medicineApi = useMocks ? mockApi : realApi
