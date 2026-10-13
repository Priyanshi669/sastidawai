import type { LucideIcon } from 'lucide-react'

export function EmptyState({ icon: Icon, title, description, action }: { icon: LucideIcon, title: string, description: string, action?: React.ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={25} /></div><h2>{title}</h2><p>{description}</p>{action}</div>
}
