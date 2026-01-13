import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import axios from 'axios';
import { RefreshCw, Filter, Layers } from 'lucide-react';
import 'leaflet/dist/leaflet.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

// Color coding by incident type
const INCIDENT_COLORS = {
  'Robbery': '#e63946',
  'Burglary': '#f4a261',
  'Assault': '#e76f51',
  'DUI': '#9c89b8',
  'Fraud': '#2a9d8f',
  'Vehicle Theft': '#264653',
  'Vandalism': '#e9c46a',
  'Drug Offense': '#6d597a',
  'Theft': '#bc6c25',
  'Disturbance': '#457b9d',
  'default': '#6c757d'
};

const INCIDENT_TYPES = [
  'All Types',
  'Robbery',
  'Burglary',
  'Assault',
  'DUI',
  'Fraud',
  'Vehicle Theft',
  'Vandalism',
  'Theft',
  'Disturbance',
];

const DISTRICTS = [
  'All Districts',
  'North',
  'South',
  'East',
  'West',
  'Central',
];

// Component to fit map bounds to markers
function FitBounds({ incidents }) {
  const map = useMap();

  useEffect(() => {
    if (incidents.length > 0) {
      const bounds = incidents
        .filter(inc => inc.location?.lat && inc.location?.lon)
        .map(inc => [inc.location.lat, inc.location.lon]);

      if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [20, 20] });
      }
    }
  }, [incidents, map]);

  return null;
}

function MapPage() {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedType, setSelectedType] = useState('All Types');
  const [selectedDistrict, setSelectedDistrict] = useState('All Districts');
  const [showFilters, setShowFilters] = useState(false);

  // Seattle area center (based on data coordinates)
  const defaultCenter = [47.58, -122.30];
  const defaultZoom = 11;

  useEffect(() => {
    loadIncidents();
  }, [selectedType, selectedDistrict]);

  const loadIncidents = async () => {
    setLoading(true);
    setError(null);

    try {
      // Build query params
      const params = new URLSearchParams();
      if (selectedType !== 'All Types') {
        params.append('incident_type', selectedType);
      }
      if (selectedDistrict !== 'All Districts') {
        params.append('district', selectedDistrict);
      }
      params.append('size', '500'); // Get up to 500 incidents for the map

      const resp = await axios.get(`${API_BASE}/documents/map?${params.toString()}`);
      setIncidents(resp.data.incidents || []);
    } catch (err) {
      console.error('Failed to load incidents:', err);
      setError('Failed to load incident data');
      // Try fallback: search for all incidents
      try {
        const fallback = await axios.post(`${API_BASE}/search/keyword`, {
          query: '*',
          size: 200
        });
        const incidentsWithLocation = (fallback.data.hits || [])
          .map(hit => hit.source)
          .filter(inc => inc.location?.lat && inc.location?.lon);
        setIncidents(incidentsWithLocation);
        setError(null);
      } catch (fallbackErr) {
        console.error('Fallback also failed:', fallbackErr);
      }
    } finally {
      setLoading(false);
    }
  };

  const getColor = (type) => {
    return INCIDENT_COLORS[type] || INCIDENT_COLORS.default;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const formatCurrency = (value) => {
    if (!value) return '$0';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
    }).format(value);
  };

  // Count incidents by type for legend
  const typeCounts = incidents.reduce((acc, inc) => {
    const type = inc.incident_type || 'Unknown';
    acc[type] = (acc[type] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="map-page">
      {/* Map Controls */}
      <div className="map-controls">
        <div className="map-header">
          <h2>
            <Layers size={20} />
            Incident Map
          </h2>
          <span className="incident-count">
            {incidents.length.toLocaleString()} incidents
          </span>
        </div>

        <div className="map-actions">
          <button
            className={`filter-toggle ${showFilters ? 'active' : ''}`}
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter size={16} />
            Filters
          </button>
          <button
            className="refresh-btn"
            onClick={loadIncidents}
            disabled={loading}
          >
            <RefreshCw size={16} className={loading ? 'spinning' : ''} />
            Refresh
          </button>
        </div>

        {showFilters && (
          <div className="map-filters">
            <div className="filter-group">
              <label>Incident Type</label>
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value)}
              >
                {INCIDENT_TYPES.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label>District</label>
              <select
                value={selectedDistrict}
                onChange={(e) => setSelectedDistrict(e.target.value)}
              >
                {DISTRICTS.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Legend */}
        <div className="map-legend">
          <h4>Incident Types</h4>
          <div className="legend-items">
            {Object.entries(typeCounts)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8)
              .map(([type, count]) => (
                <div key={type} className="legend-item">
                  <span
                    className="legend-dot"
                    style={{ backgroundColor: getColor(type) }}
                  />
                  <span className="legend-label">{type}</span>
                  <span className="legend-count">{count}</span>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* Map Container */}
      <div className="map-container">
        {error && (
          <div className="map-error">
            <p>{error}</p>
          </div>
        )}

        {loading && (
          <div className="map-loading">
            <div className="loading-spinner"></div>
            <p>Loading incidents...</p>
          </div>
        )}

        <MapContainer
          center={defaultCenter}
          zoom={defaultZoom}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom={true}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          <FitBounds incidents={incidents} />

          {incidents
            .filter(inc => inc.location?.lat && inc.location?.lon)
            .map((incident, idx) => (
              <CircleMarker
                key={incident.incident_id || idx}
                center={[incident.location.lat, incident.location.lon]}
                radius={8}
                fillColor={getColor(incident.incident_type)}
                color="#fff"
                weight={2}
                opacity={1}
                fillOpacity={0.8}
              >
                <Popup>
                  <div className="map-popup">
                    <h3>{incident.incident_id}</h3>
                    <span
                      className="popup-type"
                      style={{ backgroundColor: getColor(incident.incident_type) }}
                    >
                      {incident.incident_type}
                    </span>
                    <p className="popup-date">
                      {formatDate(incident.incident_datetime)}
                    </p>
                    <p className="popup-location">
                      {incident.district} District - {incident.neighborhood}
                    </p>
                    {incident.estimated_loss > 0 && (
                      <p className="popup-loss">
                        Loss: {formatCurrency(incident.estimated_loss)}
                      </p>
                    )}
                    <p className="popup-narrative">
                      {incident.narrative?.substring(0, 200)}...
                    </p>
                    {incident.arrest_made && (
                      <span className="popup-arrest">Arrest Made</span>
                    )}
                  </div>
                </Popup>
              </CircleMarker>
            ))}
        </MapContainer>
      </div>
    </div>
  );
}

export default MapPage;
