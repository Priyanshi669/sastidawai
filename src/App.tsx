import { useEffect, useState, useCallback } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AppShell } from './components/layout/AppShell'
import { AppLoadingScreen } from './components/common/MedicineBottleLoader'
import { OnboardingPage } from './features/onboarding/OnboardingPage'
import { HomePage } from './features/home/HomePage'
import { ScannerPage } from './features/scan/ScannerPage'
import { ProcessingPage } from './features/scan/ProcessingPage'
import { ReviewPage } from './features/scan/ReviewPage'
import { ResultPage } from './features/results/ResultPage'
import { AlternativesPage } from './features/results/AlternativesPage'
import { SearchPage } from './features/search/SearchPage'
import { SavedPage } from './features/saved/SavedPage'
import { KendrasPage } from './features/kendras/KendrasPage'
import { HistoryPage } from './features/history/HistoryPage'
import { SettingsPage } from './features/settings/SettingsPage'
import { ConfirmPage } from './features/scan/ConfirmPage'

function ShellRoute({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>
}

const pageVariants = {
  initial: { opacity: 0, x: 60 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -60 },
}

const pageTransition = {
  type: 'tween',
  ease: 'easeInOut',
  duration: 0.3,
}

function AnimatedPage({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      variants={pageVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={pageTransition}
    >
      {children}
    </motion.div>
  )
}

export default function App() {
  const [isBooting, setIsBooting] = useState(true)
  const location = useLocation()

  const handleLoaded = useCallback(() => {
    setIsBooting(false)
  }, [])

  useEffect(() => {
    if (!isBooting) return
    const fallbackTimer = window.setTimeout(() => setIsBooting(false), 4000)
    return () => window.clearTimeout(fallbackTimer)
  }, [isBooting])

  if (isBooting) return <AppLoadingScreen message="Making your medicine workspace ready" onLoaded={handleLoaded} />

  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/onboarding" element={<AnimatedPage><OnboardingPage /></AnimatedPage>} />
        <Route path="/scan/processing" element={<AnimatedPage><ProcessingPage /></AnimatedPage>} />
        <Route path="/scan/review" element={<AnimatedPage><ShellRoute><ReviewPage /></ShellRoute></AnimatedPage>} />
        <Route path="/scan" element={<AnimatedPage><ShellRoute><ScannerPage /></ShellRoute></AnimatedPage>} />
        <Route path="/scan/confirm" element={<AnimatedPage><ShellRoute><ConfirmPage /></ShellRoute></AnimatedPage>} />
        <Route path="/home" element={<AnimatedPage><ShellRoute><HomePage /></ShellRoute></AnimatedPage>} />
        <Route path="/results" element={<AnimatedPage><ShellRoute><ResultPage /></ShellRoute></AnimatedPage>} />
        <Route path="/alternatives" element={<AnimatedPage><ShellRoute><AlternativesPage /></ShellRoute></AnimatedPage>} />
        <Route path="/search" element={<AnimatedPage><ShellRoute><SearchPage /></ShellRoute></AnimatedPage>} />
        <Route path="/saved" element={<AnimatedPage><ShellRoute><SavedPage /></ShellRoute></AnimatedPage>} />
        <Route path="/kendras" element={<AnimatedPage><ShellRoute><KendrasPage /></ShellRoute></AnimatedPage>} />
        <Route path="/history" element={<AnimatedPage><ShellRoute><HistoryPage /></ShellRoute></AnimatedPage>} />
        <Route path="/settings" element={<AnimatedPage><ShellRoute><SettingsPage /></ShellRoute></AnimatedPage>} />
        <Route path="/" element={<Navigate to={localStorage.getItem('sasti-language') ? '/home' : '/onboarding'} replace />} />
        <Route path="*" element={<Navigate to="/home" replace />} />
      </Routes>
    </AnimatePresence>
  )
}
