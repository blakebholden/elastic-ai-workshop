import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Search, FileText, Brain, Layers, Filter, MapPin, Calendar, AlertTriangle, DollarSign, Star } from 'lucide-react';
import DocumentModal from '../components/DocumentModal';

const API_BASE = process.env.REACT_APP_API_URL || '';

const SEARCH_TYPES = [
  {
    id: 'keyword',
    name: 'Keyword',
    description: 'Traditional BM25 text matching',
    icon: Search,
    endpoint: '/search/keyword',
  },
  {
    id: 'semantic',
    name: 'Semantic',
    description: 'ELSER-powered meaning search',
    icon: Brain,
    endpoint: '/search/semantic',
  },
  {
    id: 'hybrid',
    name: 'Hybrid',
    description: 'Best of both with RRF fusion',
    icon: Layers,
    endpoint: '/search/hybrid',
  },
  {
    id: 'filtered',
    name: 'Filtered',
    description: 'Hybrid + metadata filters',
    icon: Filter,
    endpoint: '/search/filtered',
  },
];

const INCIDENT_TYPES = [
  'All Types',
  'Robbery',
  'Burglary',
  'Assault',
  'DUI',
  'Fraud',
  'Vehicle Theft',
  'Vandalism',
  'Drug Offense',
];

const DISTRICTS = [
  'All Districts',
  'North',
  'South',
  'East',
  'West',
  'Central',
];

const SEVERITIES = ['All Severities', 'Felony', 'Misdemeanor'];

function SearchPage() {
  const [searchType, setSearchType] = useState('hybrid');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState(null);

  // Filters
  const [incidentType, setIncidentType] = useState('All Types');
  const [district, setDistrict] = useState('All Districts');
  const [severity, setSeverity] = useState('All Severities');

  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setSearched(true);

    const searchConfig = SEARCH_TYPES.find((t) => t.id === searchType);

    try {
      const payload = {
        query: query.trim(),
        size: 20,
      };

      // Add filters for filtered search
      if (searchType === 'filtered') {
        const filters = {};
        if (incidentType !== 'All Types') filters.incident_type = incidentType;
        if (district !== 'All Districts') filters.district = district;
        if (severity !== 'All Severities') filters.severity = severity;
        if (Object.keys(filters).length > 0) {
          payload.filters = filters;
        }
      }

      const resp = await axios.post(`${API_BASE}${searchConfig.endpoint}`, payload);
      setResults(resp.data.hits || []);
      setTotal(resp.data.total || 0);
    } catch (err) {
      console.error('Search failed:', err);
      setResults([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  const getIncidentTypeClass = (type) => {
    const typeMap = {
      'Robbery': 'Robbery',
      'Burglary': 'Burglary',
      'Assault': 'Assault',
      'DUI': 'DUI',
      'Fraud': 'Fraud',
      'Vehicle Theft': 'Vehicle',
    };
    return typeMap[type] || 'default';
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatCurrency = (value) => {
    if (!value) return '$0';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  return (
    <div className="search-page">
      {/* Sidebar */}
      <div className="search-sidebar">
        <div className="search-type-buttons">
          {SEARCH_TYPES.map((type) => {
            const Icon = type.icon;
            return (
              <button
                key={type.id}
                className={`search-type-btn ${searchType === type.id ? 'active' : ''}`}
                onClick={() => setSearchType(type.id)}
              >
                <Icon size={20} className="icon" />
                <div className="search-type-info">
                  <h4>{type.name}</h4>
                  <p>{type.description}</p>
                </div>
              </button>
            );
          })}
        </div>

        {/* Filters (only shown for filtered search) */}
        {searchType === 'filtered' && (
          <div className="filter-section">
            <h3>Filters</h3>

            <div className="filter-group">
              <label>Incident Type</label>
              <select
                value={incidentType}
                onChange={(e) => setIncidentType(e.target.value)}
              >
                {INCIDENT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label>District</label>
              <select
                value={district}
                onChange={(e) => setDistrict(e.target.value)}
              >
                {DISTRICTS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label>Severity</label>
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Main Content */}
      <div className="search-content">
        {/* Search Bar */}
        <form onSubmit={handleSearch} className="search-bar">
          <input
            type="text"
            className="search-input"
            placeholder="Search incidents... (e.g., armed robbery convenience store)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="search-button" disabled={loading}>
            <Search size={20} />
            Search
          </button>
        </form>

        {/* Results Info */}
        {searched && !loading && (
          <div className="results-info">
            <span>
              Found <span className="count">{total.toLocaleString()}</span> incidents
            </span>
            <span className="search-type-badge">
              {SEARCH_TYPES.find((t) => t.id === searchType)?.name} Search
            </span>
          </div>
        )}

        {/* Loading State */}
        {loading && (
          <div className="loading-state">
            <div className="loading-spinner"></div>
            <p>Searching incidents...</p>
          </div>
        )}

        {/* Empty State */}
        {!loading && searched && results.length === 0 && (
          <div className="empty-state">
            <FileText size={48} strokeWidth={1} />
            <h3>No incidents found</h3>
            <p>Try adjusting your search terms or filters</p>
          </div>
        )}

        {/* Initial State */}
        {!loading && !searched && (
          <div className="empty-state">
            <Search size={48} strokeWidth={1} />
            <h3>Search Police Incidents</h3>
            <p>Enter a query to search through incident reports</p>
            <p style={{ marginTop: '12px', fontSize: '14px', color: '#98a2b3' }}>
              Try: "armed robbery", "vehicle theft parking garage", "domestic disturbance"
            </p>
          </div>
        )}

        {/* Results Grid */}
        {!loading && results.length > 0 && (
          <div className="incidents-grid">
            {results.map((hit) => {
              const doc = hit.source;
              return (
                <div
                  key={hit.id}
                  className="incident-card"
                  onClick={() => setSelectedDoc({ id: hit.id, ...doc })}
                >
                  <div className="incident-header">
                    <span className="incident-id">{doc.incident_id}</span>
                    <span className={`incident-type ${getIncidentTypeClass(doc.incident_type)}`}>
                      {doc.incident_type}
                    </span>
                  </div>

                  <div
                    className="incident-narrative"
                    dangerouslySetInnerHTML={{
                      __html: hit.highlight?.narrative?.[0] ||
                        (doc.narrative?.substring(0, 250) + '...') ||
                        'No narrative available',
                    }}
                  />

                  <div className="incident-meta">
                    <span className="meta-item">
                      <MapPin size={14} />
                      {doc.district || 'Unknown'} District
                    </span>
                    <span className="meta-item">
                      <Calendar size={14} />
                      {formatDate(doc.incident_datetime)}
                    </span>
                    {doc.estimated_loss > 0 && (
                      <span className="meta-item">
                        <DollarSign size={14} />
                        {formatCurrency(doc.estimated_loss)}
                      </span>
                    )}
                    {doc.arrest_made && (
                      <span className="meta-item" style={{ color: '#00726b' }}>
                        <AlertTriangle size={14} />
                        Arrest Made
                      </span>
                    )}
                    {hit.score && (
                      <span className="incident-score">
                        <Star size={12} />
                        {hit.score.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Document Modal */}
      {selectedDoc && (
        <DocumentModal
          document={selectedDoc}
          onClose={() => setSelectedDoc(null)}
        />
      )}
    </div>
  );
}

export default SearchPage;
