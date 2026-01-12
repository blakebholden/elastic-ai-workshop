import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { X, Send, MessageCircle, FileText, Loader } from 'lucide-react';

const API_BASE = process.env.REACT_APP_API_URL || '';

function DocumentModal({ document, onClose }) {
  const [activeTab, setActiveTab] = useState('content');
  const [chatMessages, setChatMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    // Reset chat when document changes
    setChatMessages([]);
    setSummary(null);
  }, [document.id]);

  useEffect(() => {
    // Auto-scroll chat
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || chatLoading) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setChatMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setChatLoading(true);

    try {
      const resp = await axios.post(`${API_BASE}/chat/document`, {
        document_id: document.id || document.incident_id,
        message: userMessage,
        chat_history: chatMessages,
      });

      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: resp.data.response },
      ]);
    } catch (err) {
      console.error('Chat failed:', err);
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Sorry, I encountered an error. Please try again.',
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleGenerateSummary = async () => {
    if (summaryLoading || summary) return;

    setSummaryLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/chat/summarize`, {
        document_id: document.id || document.incident_id,
      });
      setSummary(resp.data.summary);
    } catch (err) {
      console.error('Summary failed:', err);
      setSummary('Unable to generate summary.');
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
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
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <h2>{document.incident_id}</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={24} />
          </button>
        </div>

        {/* Tabs */}
        <div className="modal-tabs">
          <button
            className={`modal-tab ${activeTab === 'content' ? 'active' : ''}`}
            onClick={() => setActiveTab('content')}
          >
            <FileText size={16} style={{ marginRight: 6 }} />
            Incident Details
          </button>
          <button
            className={`modal-tab ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            <MessageCircle size={16} style={{ marginRight: 6 }} />
            Chat with AI
          </button>
        </div>

        {/* Content Tab */}
        {activeTab === 'content' && (
          <div className="modal-body">
            <div className="document-detail">
              {/* Summary Button */}
              <div className="detail-section">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3>AI Summary</h3>
                  {!summary && (
                    <button
                      onClick={handleGenerateSummary}
                      disabled={summaryLoading}
                      style={{
                        padding: '8px 16px',
                        background: '#0077cc',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: summaryLoading ? 'not-allowed' : 'pointer',
                        fontSize: '13px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                      }}
                    >
                      {summaryLoading ? (
                        <>
                          <Loader size={14} className="spinning" />
                          Generating...
                        </>
                      ) : (
                        'Generate Summary'
                      )}
                    </button>
                  )}
                </div>
                {summary && (
                  <div
                    style={{
                      marginTop: '12px',
                      padding: '16px',
                      background: '#f0f7ff',
                      borderRadius: '6px',
                      whiteSpace: 'pre-wrap',
                      lineHeight: '1.6',
                    }}
                  >
                    {summary}
                  </div>
                )}
              </div>

              {/* Key Details */}
              <div className="detail-section">
                <h3>Key Details</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Incident Type</label>
                    <div className="value">{document.incident_type} - {document.incident_subtype || 'General'}</div>
                  </div>
                  <div className="detail-item">
                    <label>Severity</label>
                    <div className="value">{document.severity || 'Unknown'}</div>
                  </div>
                  <div className="detail-item">
                    <label>Date & Time</label>
                    <div className="value">{formatDate(document.incident_datetime)}</div>
                  </div>
                  <div className="detail-item">
                    <label>Resolution</label>
                    <div className="value">{document.resolution || 'Open'}</div>
                  </div>
                </div>
              </div>

              {/* Location */}
              <div className="detail-section">
                <h3>Location</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Address</label>
                    <div className="value">{document.address_block || 'Unknown'}</div>
                  </div>
                  <div className="detail-item">
                    <label>Neighborhood</label>
                    <div className="value">{document.neighborhood || 'Unknown'}</div>
                  </div>
                  <div className="detail-item">
                    <label>District</label>
                    <div className="value">{document.district || 'Unknown'}</div>
                  </div>
                </div>
              </div>

              {/* Additional Info */}
              <div className="detail-section">
                <h3>Additional Information</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Arrest Made</label>
                    <div className="value">{document.arrest_made ? 'Yes' : 'No'}</div>
                  </div>
                  <div className="detail-item">
                    <label>Injuries Reported</label>
                    <div className="value">{document.injuries_reported ? 'Yes' : 'No'}</div>
                  </div>
                  <div className="detail-item">
                    <label>Weapon Involved</label>
                    <div className="value">{document.weapon_involved || 'None'}</div>
                  </div>
                  <div className="detail-item">
                    <label>Estimated Loss</label>
                    <div className="value">{formatCurrency(document.estimated_loss)}</div>
                  </div>
                  <div className="detail-item">
                    <label>Victim Count</label>
                    <div className="value">{document.victim_count || 0}</div>
                  </div>
                  <div className="detail-item">
                    <label>Responding Units</label>
                    <div className="value">{document.responding_units || 0}</div>
                  </div>
                </div>
              </div>

              {/* Full Narrative */}
              <div className="detail-section">
                <h3>Full Narrative</h3>
                <div className="narrative-full">{document.narrative || 'No narrative available.'}</div>
              </div>

              {/* Tags */}
              {document.tags && document.tags.length > 0 && (
                <div className="detail-section">
                  <h3>Tags</h3>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {document.tags.map((tag, idx) => (
                      <span
                        key={idx}
                        style={{
                          padding: '4px 10px',
                          background: '#f5f7fa',
                          borderRadius: '4px',
                          fontSize: '13px',
                          color: '#69707d',
                        }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Chat Tab */}
        {activeTab === 'chat' && (
          <div className="chat-container">
            <div className="chat-messages">
              {chatMessages.length === 0 && (
                <div
                  style={{
                    textAlign: 'center',
                    color: '#69707d',
                    padding: '40px 20px',
                  }}
                >
                  <MessageCircle size={40} strokeWidth={1} />
                  <p style={{ marginTop: '12px' }}>
                    Ask questions about this incident
                  </p>
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '8px',
                      justifyContent: 'center',
                      marginTop: '16px',
                    }}
                  >
                    {[
                      'What happened?',
                      'Was anyone arrested?',
                      'What evidence was collected?',
                      'Were there any witnesses?',
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => {
                          setInputMessage(suggestion);
                        }}
                        style={{
                          padding: '8px 12px',
                          background: '#f5f7fa',
                          border: '1px solid #d3dae6',
                          borderRadius: '16px',
                          cursor: 'pointer',
                          fontSize: '13px',
                        }}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {chatMessages.map((msg, idx) => (
                <div key={idx} className={`chat-message ${msg.role}`}>
                  {msg.content}
                </div>
              ))}

              {chatLoading && (
                <div className="chat-message assistant">
                  <Loader size={16} className="spinning" style={{ marginRight: 8 }} />
                  Thinking...
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-area">
              <textarea
                className="chat-input"
                placeholder="Ask a question about this incident..."
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyPress={handleKeyPress}
                rows={1}
              />
              <button
                className="chat-send"
                onClick={handleSendMessage}
                disabled={chatLoading || !inputMessage.trim()}
              >
                <Send size={18} />
              </button>
            </div>
          </div>
        )}
      </div>

      <style>{`
        .spinning {
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export default DocumentModal;
