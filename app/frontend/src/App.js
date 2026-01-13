import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, useLocation } from 'react-router-dom';
import {
  EuiProvider,
  EuiPageTemplate,
  EuiHeader,
  EuiHeaderSection,
  EuiHeaderSectionItem,
  EuiHeaderLinks,
  EuiHeaderLink,
  EuiIcon,
  EuiBadge,
} from '@elastic/eui';
import { Shield, Search, Activity, Map } from 'lucide-react';
import axios from 'axios';

import SearchPage from './pages/SearchPage';
import MapPage from './pages/MapPage';
import ChatWidget from './components/ChatWidget';
import './App.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

function App() {
  const location = useLocation();
  const [healthStatus, setHealthStatus] = useState('checking');
  const [docCount, setDocCount] = useState(0);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  const checkHealth = async () => {
    try {
      const resp = await axios.get(`${API_BASE}/health`);
      setHealthStatus(resp.data.status);
      setDocCount(resp.data.index?.document_count || 0);
    } catch (err) {
      setHealthStatus('error');
    }
  };

  const getStatusColor = () => {
    switch (healthStatus) {
      case 'healthy': return 'success';
      case 'checking': return 'warning';
      default: return 'danger';
    }
  };

  return (
    <EuiProvider colorMode="light">
      <div className="app-container">
        <EuiHeader position="fixed">
          <EuiHeaderSection grow={false}>
            <EuiHeaderSectionItem>
              <Link to="/" className="logo-link">
                <Shield size={24} className="logo-icon" />
                <span className="logo-text">Police Incident Search</span>
              </Link>
            </EuiHeaderSectionItem>
          </EuiHeaderSection>

          <EuiHeaderSection side="right">
            <EuiHeaderSectionItem>
              <EuiHeaderLinks>
                <EuiHeaderLink
                  iconType="search"
                  isActive={location.pathname === '/'}
                >
                  <Link to="/">Search</Link>
                </EuiHeaderLink>
                <EuiHeaderLink
                  iconType="mapMarker"
                  isActive={location.pathname === '/map'}
                >
                  <Link to="/map">Map</Link>
                </EuiHeaderLink>
              </EuiHeaderLinks>
            </EuiHeaderSectionItem>
            <EuiHeaderSectionItem>
              <div className="status-badge">
                <EuiBadge color={getStatusColor()}>
                  <Activity size={12} style={{ marginRight: 4 }} />
                  {healthStatus === 'healthy' ? `${docCount.toLocaleString()} incidents` : healthStatus}
                </EuiBadge>
              </div>
            </EuiHeaderSectionItem>
          </EuiHeaderSection>
        </EuiHeader>

        <EuiPageTemplate
          panelled={false}
          grow={true}
          restrictWidth={false}
          className="main-content"
        >
          <Routes>
            <Route path="/" element={<SearchPage />} />
            <Route path="/map" element={<MapPage />} />
          </Routes>
        </EuiPageTemplate>

        {/* Floating Chat Widget */}
        <ChatWidget />
      </div>
    </EuiProvider>
  );
}

export default App;
