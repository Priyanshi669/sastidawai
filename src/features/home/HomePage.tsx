import { Bookmark, Camera, ChevronRight, MapPin, Search, ScanLine, Upload, X, AlertTriangle } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useApp } from '../../app/AppProvider'
import { MedicineCard } from '../../components/medicine/MedicineCard'
import { useRef, useState, useEffect, useCallback } from 'react'

export function HomePage() {
  const { t } = useTranslation()
  const { history } = useApp()
  const navigate = useNavigate()
  const [isScanning, setIsScanning] = useState(false)
  const [cameraOpen, setCameraOpen] = useState(false)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  const stopCamera = useCallback(() => {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop())
    }
    setStream(null)
    setCameraOpen(false)
    setCameraError(null)
  }, [stream])

  async function openCamera() {
    setCameraError(null)

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError('Camera API not available. Make sure you are using HTTPS or localhost.')
      setCameraOpen(true)
      return
    }

    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      })
      setStream(mediaStream)
      setCameraOpen(true)
    } catch (err) {
      const error = err as DOMException
      if (error.name === 'NotAllowedError') {
        setCameraError('Camera permission was denied. Please allow camera access in your browser settings.')
      } else if (error.name === 'NotFoundError') {
        setCameraError('No camera found on this device.')
      } else if (error.name === 'NotReadableError') {
        setCameraError('Camera is already in use by another app.')
      } else if (error.name === 'SecurityError') {
        setCameraError('Camera access requires HTTPS. Please use a secure connection.')
      } else {
        setCameraError(`Camera error: ${error.message || 'Unknown error'}`)
      }
      setCameraOpen(true)
    }
  }

  function closeCamera() {
    stopCamera()
  }

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream
    }
  }, [stream])

  useEffect(() => {
    return () => {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop())
      }
    }
  }, [stream])

  function handleUploadClick() {
    fileInputRef.current?.click()
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) {
      navigate('/scan', { state: { uploadFile: file } })
    }
  }

  function handleContinue() {
    stopCamera()
    navigate('/scan')
  }

  return <div className="page-section home-page stack-24">
    <section className="camera-box" onClick={() => { setIsScanning(true); setTimeout(() => setIsScanning(false), 3000) }}>
      <div className="camera-box-inner">
        <div className="camera-scan-area">
          {isScanning && <div className="scan-line" />}
          <ScanLine size={64} />
        </div>
        <h2>{t('scanTitle')}</h2>
        <p>{t('scanDesc')}</p>
        <div className="camera-box-actions">
          <button className="btn btn-primary btn-sharp" onClick={(e) => { e.stopPropagation(); openCamera() }}>
            <Camera size={18} /> {t('scan')}
          </button>
          <button className="btn btn-secondary btn-icon-only" onClick={(e) => { e.stopPropagation(); handleUploadClick() }} aria-label={t('uploadPhoto')}>
            <Upload size={20} />
          </button>
        </div>
      </div>
    </section>

    {cameraOpen && (
      <div className="camera-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeCamera() }}>
        <div className="camera-modal" onClick={(e) => e.stopPropagation()}>
          <div className="camera-modal-header">
            <h3>{t('scanTitle')}</h3>
            <button className="icon-button" onClick={(e) => { e.stopPropagation(); closeCamera() }} aria-label="Close camera">
              <X size={20} />
            </button>
          </div>
          <div className="camera-modal-body">
            {cameraError ? (
              <div className="camera-error">
                <AlertTriangle size={48} />
                <p>{cameraError}</p>
                <button className="btn btn-secondary" onClick={closeCamera}>Close</button>
              </div>
            ) : (
              <>
                <video ref={videoRef} autoPlay muted playsInline className="camera-modal-video" />
                <div className="camera-modal-overlay" />
                <p className="camera-modal-hint">{t('scanPageDesc')}</p>
              </>
            )}
          </div>
          {!cameraError && (
            <div className="camera-modal-footer">
              <button className="btn btn-primary btn-block" onClick={(e) => { e.stopPropagation(); handleContinue() }}>
                <Camera size={17} /> {t('continueBtn')}
              </button>
            </div>
          )}
        </div>
      </div>
    )}

    <input ref={fileInputRef} hidden type="file" accept="image/*" onChange={handleFileChange} />

    <section className="quick-grid">
      <Link className="quick-link" to="/search">
        <span className="quick-link-icon"><Search size={19} /></span>
        <span><strong>{t('search')}</strong><small>{t('searchDesc')}</small></span>
        <ChevronRight size={17} />
      </Link>
      <Link className="quick-link" to="/saved">
        <span className="quick-link-icon"><Bookmark size={19} /></span>
        <span><strong>{t('saved')}</strong><small>{t('savedDesc')}</small></span>
        <ChevronRight size={17} />
      </Link>
      <Link className="quick-link" to="/kendras">
        <span className="quick-link-icon"><MapPin size={19} /></span>
        <span><strong>{t('kendras')}</strong><small>{t('kendrasDesc')}</small></span>
        <ChevronRight size={17} />
      </Link>
    </section>

    {history.length > 0 && <section className="recent-section">
      <div className="section-heading">
        <div><h2>{t('recentScans')}</h2></div>
        <Link to="/history">{t('viewAll')} <ChevronRight size={14} style={{ verticalAlign: 'middle' }} /></Link>
      </div>
      <div className="grid-2">{history.slice(0, 2).map((scan) => <MedicineCard medicine={scan.medicine} key={scan.id} />)}</div>
    </section>}

    <div className="quiet-note">
      <MapPin size={17} />
      <span>{t('disclaimer')}</span>
    </div>
  </div>
}
