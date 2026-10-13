import { Pill } from 'lucide-react'

export function AppIcon({ size = 22 }: { size?: number }) {
  return <span className="brand-mark" aria-hidden="true"><Pill size={size} strokeWidth={2.2} /></span>
}
