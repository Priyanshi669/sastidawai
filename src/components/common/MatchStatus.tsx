import { CheckCircle2, CircleAlert, CircleOff, ShieldCheck } from 'lucide-react'
import type { MatchTier } from '../../types'

const labels: Record<MatchTier, string> = { exact: 'Exact match', close: 'Close candidate', none: 'No verified match', needs_confirmation: 'Needs confirmation' }
export function MatchStatus({ tier }: { tier: MatchTier }) {
  const Icon = tier === 'exact' ? ShieldCheck : tier === 'close' ? CircleAlert : tier === 'none' ? CircleOff : CircleAlert
  return <span className={`pill pill-${tier === 'needs_confirmation' ? 'confirm' : tier}`}><Icon size={14} />{labels[tier]}</span>
}
