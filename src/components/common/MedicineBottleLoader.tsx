import { useEffect, useState } from 'react'

export function MedicineBottleLoader({ size = 'default', progress, onComplete }: { size?: 'small' | 'default'; progress?: number; onComplete?: () => void }) {
  const [fillLevel, setFillLevel] = useState(0)

  useEffect(() => {
    if (progress !== undefined) {
      setFillLevel(Math.min(100, Math.max(0, progress)))
      if (progress >= 100 && onComplete) onComplete()
      return
    }
    let current = 0
    const interval = window.setInterval(() => {
      current += 4
      setFillLevel(current)
      if (current >= 100) {
        window.clearInterval(interval)
        onComplete?.()
      }
    }, 50)
    return () => window.clearInterval(interval)
  }, [progress, onComplete])

  const liquidHeight = 100
  const liquidY = 150 - (fillLevel / 100) * liquidHeight

  return (
    <div className={`bottle-loader ${size === 'small' ? 'small-loader' : ''}`} aria-label="Loading medicine details" role="img">
      <svg viewBox="0 0 120 160" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <clipPath id="bottle-clip">
            <path d="M35 30 h50 v10 c0 4 5 7 5 15 v70 c0 10 -7 15 -14 15 h-32 c-7 0 -14 -5 -14 -15 v-70 c0 -8 5 -11 5 -15 v-10 Z" />
          </clipPath>
          <linearGradient id="liquid-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#a3e635" />
            <stop offset="100%" stopColor="#65a30d" />
          </linearGradient>
          <linearGradient id="bottle-gradient" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="rgba(255,255,255,0.9)" />
            <stop offset="50%" stopColor="rgba(255,255,255,0.6)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0.85)" />
          </linearGradient>
        </defs>

        {/* Cap */}
        <rect x="37" y="8" width="46" height="18" rx="4" fill="#4d7c0f" />
        <rect x="37" y="8" width="46" height="18" rx="4" fill="url(#bottle-gradient)" opacity="0.3" />

        {/* Bottle body */}
        <path d="M35 30 h50 v10 c0 4 5 7 5 15 v70 c0 10 -7 15 -14 15 h-32 c-7 0 -14 -5 -14 -15 v-70 c0 -8 5 -11 5 -15 v-10 Z" fill="rgba(255,255,255,0.25)" stroke="rgba(101, 163, 13, 0.35)" strokeWidth="1.5" />

        {/* Liquid fill */}
        <g clipPath="url(#bottle-clip)">
          <rect className="bottle-liquid" x="20" y={liquidY} width="80" height={150 - liquidY} fill="url(#liquid-gradient)" />
          <path className="bottle-wave" d={`M18 ${liquidY + 1} c12 -8 25 4 42 -1 c15 -4 28 -6 42 1 v8 H18 Z`} fill="#a3e635" opacity="0.8" />

          {/* Bubbles */}
          <circle className="bubble-a" cx="45" cy={liquidY + 20} r="2.5" fill="white" opacity="0.4" />
          <circle className="bubble-b" cx="65" cy={liquidY + 35} r="2" fill="white" opacity="0.35" />
          <circle className="bubble-c" cx="80" cy={liquidY + 15} r="1.8" fill="white" opacity="0.3" />

          {/* Label */}
          <rect x="30" y="65" width="60" height="35" rx="4" fill="white" opacity="0.9" />
          <path d="M40 78 h40 M40 85 h28" stroke="#65a30d" strokeWidth="2" strokeLinecap="round" opacity="0.5" />
          <path d="M60 93 v-8 M55 89 h10" stroke="#65a30d" strokeWidth="2.5" strokeLinecap="round" />
        </g>

        {/* Glass shine */}
        <path d="M35 30 h50 v10 c0 4 5 7 5 15 v70 c0 10 -7 15 -14 15 h-32 c-7 0 -14 -5 -14 -15 v-70 c0 -8 5 -11 5 -15 v-10 Z" fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="0.5" strokeDasharray="2 2" />
      </svg>
    </div>
  )
}

export function AppLoadingScreen({ message = 'Preparing your medicine workspace', onLoaded }: { message?: string; onLoaded?: () => void }) {
  return (
    <main className="loader-page">
      <div className="loader-backdrop">
        <div className="loader-blob loader-blob-1" />
        <div className="loader-blob loader-blob-2" />
      </div>
      <section className="loader-card glass-card">
        <div className="loader-brand">
          <span className="loader-brand-icon">✦</span>
          <span>Sasti Dawai</span>
        </div>
        <MedicineBottleLoader onComplete={onLoaded} />
        <div className="stack-8">
          <h1>Your medicine workspace</h1>
          <p>{message}</p>
        </div>
        <div className="loader-dots">
          <span /><span /><span />
        </div>
      </section>
    </main>
  )
}
