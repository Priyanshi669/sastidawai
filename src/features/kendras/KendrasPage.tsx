import { Clock3, Compass, MapPin, Navigation, Phone, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { SearchBar } from '../../components/common/SearchBar'
import { EmptyState } from '../../components/common/EmptyState'
import { medicineApi } from '../../services/api'
import type { Kendra } from '../../types'
import { useTranslation } from 'react-i18next'

// Fix Leaflet default marker icons
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

// Custom lime marker
const limeIcon = L.divIcon({
  className: 'custom-marker',
  html: `<div style="width:32px;height:32px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:#65a30d;border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);"></div>`,
  iconSize: [32, 32],
  iconAnchor: [16, 32],
  popupAnchor: [0, -32],
})

export function KendrasPage() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<Kendra[]>([])
  const [locationNotice, setLocationNotice] = useState('')
  const [selectedKendra, setSelectedKendra] = useState<Kendra | null>(null)

  useEffect(() => { medicineApi.getKendras(query).then(setItems) }, [query])

  function useLocation() {
    if (!navigator.geolocation) { setLocationNotice('Location is not available. Search by city instead.'); return }
    navigator.geolocation.getCurrentPosition(
      () => setLocationNotice('Location received. Showing nearby kendras.'),
      () => setLocationNotice('Location permission was not granted. Search by city instead.')
    )
  }

  function openInGoogleMaps(kendra: Kendra) {
    if (kendra.lat && kendra.lng) {
      window.open(`https://www.google.com/maps/dir/?api=1&destination=${kendra.lat},${kendra.lng}`, '_blank')
    } else {
      window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(kendra.address)}`, '_blank')
    }
  }

  const mapCenter: [number, number] = selectedKendra?.lat && selectedKendra?.lng
    ? [selectedKendra.lat, selectedKendra.lng]
    : [26.2960, 73.0430]

  return <div className="page-section stack-24">
    <div className="page-header">
      <div>
        <div className="eyebrow">{t('kendras')}</div>
        <h1>{t('kendrasPageTitle')}</h1>
        <p>{t('kendrasPageDesc')}</p>
      </div>
      <button className="btn btn-secondary" onClick={useLocation}><Compass size={17} />{t('useLocation')}</button>
    </div>
    <SearchBar value={query} onChange={setQuery} placeholder={t('searchCity')} />

    <div className="kendra-map-container">
      <MapContainer center={mapCenter} zoom={13} style={{ height: '100%', width: '100%' }} scrollWheelZoom={true}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {items.filter(k => k.lat && k.lng).map((kendra) => (
          <Marker
            key={kendra.id}
            position={[kendra.lat!, kendra.lng!]}
            icon={limeIcon}
            eventHandlers={{ click: () => setSelectedKendra(kendra) }}
          >
            <Popup>
              <div style={{ minWidth: 180 }}>
                <strong style={{ fontSize: '0.9rem' }}>{kendra.name}</strong>
                <p style={{ margin: '4px 0', fontSize: '0.8rem', color: '#666' }}>{kendra.address}</p>
                <p style={{ margin: '4px 0', fontSize: '0.8rem' }}>{kendra.hours}</p>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>

    {locationNotice && <div className="notice"><Navigation size={17} /><span>{locationNotice}</span></div>}

    {items.length ? (
      <div className="card card-pad">
        <div className="section-heading">
          <h2>Nearby Kendras</h2>
          <span className="muted small">{items.length} found</span>
        </div>
        {items.map((item) => (
          <article className="list-row" key={item.id}>
            <div className="feature-icon" style={{ margin: 0 }}><MapPin size={18} /></div>
            <div style={{ flex: 1 }}>
              <div className="row">
                <h3>{item.name}</h3>
                <span className="spacer" />
                <strong>{item.distance}</strong>
              </div>
              <p>{item.address}</p>
              <div className="row-wrap" style={{ marginTop: 7 }}>
                <span className="muted small"><Clock3 size={13} style={{ verticalAlign: 'middle' }} /> {item.hours}</span>
                {item.phone && <span className="muted small"><Phone size={13} /> {item.phone}</span>}
              </div>
            </div>
            <button className="icon-button" title="Get directions" onClick={() => openInGoogleMaps(item)}>
              <Navigation size={17} />
            </button>
          </article>
        ))}
      </div>
    ) : (
      <div className="card">
        <EmptyState icon={Search} title={t('noLocations')} description="Try searching Jodhpur or clear the search." />
      </div>
    )}
  </div>
}
