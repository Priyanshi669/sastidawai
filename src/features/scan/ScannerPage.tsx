import { Camera, Check, ImagePlus, RotateCcw, ShieldAlert, Upload, AlertTriangle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export function ScannerPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [qualityWarning, setQualityWarning] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => () => stream?.getTracks().forEach((track) => track.stop()), [stream])
  useEffect(() => { if (videoRef.current && stream) videoRef.current.srcObject = stream }, [stream])

  async function openCamera() {
    setError(null)
    setQualityWarning(null)
    if (!navigator.mediaDevices?.getUserMedia) { setError('Camera access is not available in this browser. Upload a photo instead.'); return }
    try {
      setStream(await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false }))
    } catch {
      setError('Camera permission was not granted. You can still upload a gallery photo.')
    }
  }

  function checkImageQuality(img: HTMLImageElement): Promise<boolean> {
    return new Promise((resolve) => {
      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d')
      if (!ctx) { resolve(true); return }
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      ctx.drawImage(img, 0, 0)
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const data = imageData.data
      let totalBrightness = 0
      let totalVariance = 0
      const pixelCount = data.length / 4
      for (let i = 0; i < data.length; i += 4) {
        const brightness = (data[i] + data[i + 1] + data[i + 2]) / 3
        totalBrightness += brightness
      }
      const avgBrightness = totalBrightness / pixelCount
      for (let i = 0; i < data.length; i += 4) {
        const brightness = (data[i] + data[i + 1] + data[i + 2]) / 3
        totalVariance += Math.pow(brightness - avgBrightness, 2)
      }
      const stdDev = Math.sqrt(totalVariance / pixelCount)
      if (avgBrightness < 40) { resolve(false); return }
      if (stdDev < 15) { resolve(false); return }
      resolve(true)
    })
  }

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/') || file.size > 10 * 1024 * 1024) { setError('Choose an image under 10 MB.'); return }
    setQualityWarning(null)
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = async () => {
      const isGoodQuality = await checkImageQuality(img)
      if (!isGoodQuality) {
        setQualityWarning('The image appears blurry or too dark. Hold steady, move closer, and avoid reflection.')
        URL.revokeObjectURL(url)
        return
      }
      setPreview(url)
      setError(null)
      stream?.getTracks().forEach((track) => track.stop())
      setStream(null)
    }
    img.src = url
  }

  function continueToProcessing(source: 'camera' | 'upload' | 'demo') {
    navigate('/scan/processing', { state: { source } })
  }

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">S01 · {t('scan')}</div>
        <h1>{t('scanPageTitle')}</h1>
        <p>{t('scanPageDesc')}</p>
      </div>
    </div>

    <div className="notice notice-warning">
      <ShieldAlert size={17} />
      <span>{t('demoNotice')}</span>
    </div>

    <section className="camera-shell">
      {stream && <video ref={videoRef} autoPlay muted playsInline aria-label={t('cameraPreview')} />}
      {preview && !stream && <img src={preview} alt="Selected medicine package preview" />}
      {!stream && !preview && <div className="camera-placeholder">
        <Camera size={34} />
        <strong>{t('cameraPreview')}</strong>
        <p>{t('cameraHint')}</p>
      </div>}
      <div className="camera-overlay" aria-hidden="true" />
      <div className="camera-hint">{t('scanPageDesc')}</div>
      <div className="camera-controls">
        {!stream && !preview && <button className="btn" onClick={openCamera}><Camera size={17} />{t('useCamera')}</button>}
        {!stream && <button className="btn" onClick={() => fileRef.current?.click()}><Upload size={17} />{t('uploadPhoto')}</button>}
        {preview && <button className="btn" onClick={() => { setPreview(null); if (fileRef.current) fileRef.current.value = '' }}><RotateCcw size={17} />{t('retake')}</button>}
        {(stream || preview) && <button className="btn btn-primary" onClick={() => continueToProcessing(stream ? 'camera' : 'upload')}><Check size={17} />{t('continueBtn')}</button>}
      </div>
    </section>

    <input ref={fileRef} hidden type="file" accept="image/*" capture="environment" onChange={onFile} />

    {qualityWarning && (
      <div className="notice notice-warning" role="alert">
        <AlertTriangle size={17} />
        <span>{qualityWarning}</span>
      </div>
    )}

    {error && <div className="notice notice-warning" role="alert"><ShieldAlert size={17} /><span>{error}</span></div>}

    <section className="card card-pad stack-12">
      <div className="row">
        <ImagePlus size={18} color="var(--green-800)" />
        <strong>{t('tryingWithoutCamera')}</strong>
      </div>
      <button className="btn btn-secondary btn-block" onClick={() => continueToProcessing('demo')}>{t('tryDemo')}</button>
    </section>
  </div>
}
