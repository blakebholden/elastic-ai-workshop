import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { X, Send, MessageCircle, FileText, Loader, Lock, MapPin, Brain, Database, Bot, Check, Cog } from 'lucide-react';

const API_BASE = process.env.REACT_APP_API_URL || '';

function DocumentModal({ document, onClose }) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('content');
  const [chatMessages, setChatMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [ragEnabled, setRagEnabled] = useState(false);
  const [chatEnabled, setChatEnabled] = useState(false);
  const [agentEnabled, setAgentEnabled] = useState(false);
  const [showLlmTooltip, setShowLlmTooltip] = useState(false);
  const [conversationId, setConversationId] = useState(null);

  // Streaming state
  const [streamingMessage, setStreamingMessage] = useState('');
  const [streamProgress, setStreamProgress] = useState({
    phase: null,
    reasoning: '',
    toolCalls: [],
    currentTool: null,
  });

  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);

  // Handle "View on Map" click
  const handleViewOnMap = (incidentIds) => {
    if (incidentIds && incidentIds.length > 0) {
      const ids = incidentIds.join(',');
      navigate(`/map?highlight=${encodeURIComponent(ids)}`);
      onClose();
    }
  };

  // Extract incident IDs from text
  const extractIncidentIds = (text) => {
    const matches = text.match(/INC-\d{4}-\d+/g) || [];
    return [...new Set(matches)];
  };

  // Fetch feature flags on mount
  useEffect(() => {
    const fetchFeatures = async () => {
      try {
        const resp = await axios.get(`${API_BASE}/features`);
        setLlmEnabled(resp.data.llm_enabled);
        setRagEnabled(resp.data.rag_enabled);
        setChatEnabled(resp.data.chat_enabled);
        setAgentEnabled(resp.data.agent_enabled);
      } catch (err) {
        console.error('Failed to fetch features:', err);
        setLlmEnabled(false);
        setRagEnabled(false);
        setChatEnabled(false);
        setAgentEnabled(false);
      }
    };
    fetchFeatures();
  }, []);

  useEffect(() => {
    setChatMessages([]);
    setSummary(null);
    setConversationId(null);
  }, [document.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, streamingMessage, streamProgress]);

  // Parse SSE line into event type and data
  const parseSSELine = (line) => {
    if (line.startsWith('event:')) {
      return { type: 'event', value: line.slice(6).trim() };
    }
    if (line.startsWith('data:')) {
      try {
        return { type: 'data', value: JSON.parse(line.slice(5).trim()) };
      } catch {
        return { type: 'data', value: line.slice(5).trim() };
      }
    }
    return null;
  };

  // Handle streaming chat
  const handleStreamingChat = async (userMessage) => {
    abortControllerRef.current = new AbortController();

    setStreamProgress({
      phase: 'reasoning',
      reasoning: '',
      toolCalls: [],
      currentTool: null,
    });
    setStreamingMessage('');

    try {
      const response = await fetch(`${API_BASE}/chat/document/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          document_id: document.id || document.incident_id,
          message: userMessage,
          chat_history: chatMessages,
          conversation_id: conversationId,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEventType = null;
      let finalMessage = '';
      let collectedToolCalls = [];
      let newConversationId = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const parsed = parseSSELine(line);
          if (!parsed) continue;

          if (parsed.type === 'event') {
            currentEventType = parsed.value;
          } else if (parsed.type === 'data' && currentEventType) {
            const data = parsed.value;

            switch (currentEventType) {
              case 'conversation_id_set':
              case 'conversation_created':
                if (data.conversation_id) {
                  newConversationId = data.conversation_id;
                }
                break;

              case 'reasoning':
                setStreamProgress(prev => ({
                  ...prev,
                  phase: 'reasoning',
                  reasoning: data.reasoning || prev.reasoning,
                }));
                break;

              case 'tool_call':
                const toolCall = {
                  tool: data.tool_id,
                  parameters: data.params || {},
                  status: 'running',
                  toolCallId: data.tool_call_id,
                };
                collectedToolCalls.push(toolCall);
                setStreamProgress(prev => ({
                  ...prev,
                  phase: 'tool_call',
                  currentTool: data.tool_id,
                  toolCalls: [...collectedToolCalls],
                }));
                break;

              case 'tool_progress':
                setStreamProgress(prev => ({
                  ...prev,
                  phase: 'tool_progress',
                }));
                break;

              case 'tool_result':
                collectedToolCalls = collectedToolCalls.map(tc =>
                  tc.toolCallId === data.tool_call_id
                    ? { ...tc, status: 'completed', result: data.results }
                    : tc
                );
                setStreamProgress(prev => ({
                  ...prev,
                  toolCalls: [...collectedToolCalls],
                  currentTool: null,
                }));
                break;

              case 'thinking_complete':
                setStreamProgress(prev => ({
                  ...prev,
                  phase: 'generating',
                }));
                break;

              case 'message_chunk':
                if (data.text_chunk) {
                  finalMessage += data.text_chunk;
                  setStreamingMessage(finalMessage);
                }
                break;

              case 'message_complete':
                if (data.message_content) {
                  finalMessage = data.message_content;
                  setStreamingMessage(finalMessage);
                }
                break;

              case 'round_complete':
                break;

              case 'error':
                throw new Error(data.error || 'Stream error');

              default:
                break;
            }
            currentEventType = null;
          }
        }
      }

      if (newConversationId) {
        setConversationId(newConversationId);
      }

      setChatMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: finalMessage || 'No response received.',
          toolCalls: collectedToolCalls.filter(tc => tc.status === 'completed'),
        },
      ]);

    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('Stream aborted');
      } else {
        console.error('Streaming failed:', err);
        setChatMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: 'Sorry, I encountered an error. Please try again.',
          },
        ]);
      }
    } finally {
      setStreamingMessage('');
      setStreamProgress({
        phase: null,
        reasoning: '',
        toolCalls: [],
        currentTool: null,
      });
      setChatLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || chatLoading) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setChatMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setChatLoading(true);

    // Use streaming if agent is enabled
    if (agentEnabled) {
      await handleStreamingChat(userMessage);
    } else {
      // Fallback to non-streaming
      try {
        const resp = await axios.post(`${API_BASE}/chat/document`, {
          document_id: document.id || document.incident_id,
          message: userMessage,
          chat_history: chatMessages,
          conversation_id: conversationId,
        });

        if (resp.data.conversation_id) {
          setConversationId(resp.data.conversation_id);
        }

        setChatMessages(prev => [
          ...prev,
          { role: 'assistant', content: resp.data.response },
        ]);
      } catch (err) {
        console.error('Chat failed:', err);
        setChatMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: 'Sorry, I encountered an error. Please try again.',
          },
        ]);
      } finally {
        setChatLoading(false);
      }
    }
  };

  const handleGenerateSummary = async () => {
    if (summaryLoading || summary) return;

    setSummaryLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/rag/summarize`, {
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

  // Render streaming progress
  const renderStreamProgress = () => {
    const { phase, reasoning, toolCalls } = streamProgress;

    return (
      <div className="chat-widget-loading stream-progress" style={{ margin: '12px 0' }}>
        {/* Reasoning phase */}
        <div className={`loading-step ${phase === 'reasoning' ? 'active' : ''} ${['tool_call', 'tool_progress', 'generating'].includes(phase) ? 'completed' : ''}`}>
          <div className="loading-step-icon">
            {['tool_call', 'tool_progress', 'generating'].includes(phase) ? <Check size={14} /> : <Brain size={14} />}
          </div>
          <span className="loading-step-text">
            {phase === 'reasoning' ? (reasoning || 'Analyzing question...') : 'Question analyzed'}
          </span>
        </div>

        {/* Tool calls */}
        {toolCalls.length > 0 && (
          <div className="stream-tool-calls">
            {toolCalls.map((tc, idx) => (
              <div
                key={idx}
                className={`loading-step ${tc.status === 'running' ? 'active' : ''} ${tc.status === 'completed' ? 'completed' : ''}`}
              >
                <div className="loading-step-icon">
                  {tc.status === 'completed' ? <Check size={14} /> : <Cog size={14} />}
                </div>
                <span className="loading-step-text">
                  <code>{tc.tool}</code>
                  {tc.status === 'running' && ' (executing...)'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Generating phase */}
        {phase === 'generating' && (
          <div className="loading-step active">
            <div className="loading-step-icon">
              <Bot size={14} />
            </div>
            <span className="loading-step-text">Generating response...</span>
          </div>
        )}

        {/* Streaming message preview */}
        {streamingMessage && (
          <div className="stream-message-preview">
            <ReactMarkdown>{streamingMessage}</ReactMarkdown>
          </div>
        )}
      </div>
    );
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
            onClick={() => chatEnabled && setActiveTab('chat')}
            disabled={!chatEnabled}
            style={{
              opacity: chatEnabled ? 1 : 0.5,
              cursor: chatEnabled ? 'pointer' : 'not-allowed',
            }}
            title={!chatEnabled ? 'Enable Chat in Challenge 10' : ''}
          >
            {!chatEnabled && <Lock size={14} style={{ marginRight: 4 }} />}
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
                    <div
                      style={{ position: 'relative' }}
                      onMouseEnter={() => !ragEnabled && setShowLlmTooltip(true)}
                      onMouseLeave={() => setShowLlmTooltip(false)}
                    >
                      {showLlmTooltip && !ragEnabled && (
                        <div
                          style={{
                            position: 'absolute',
                            bottom: '100%',
                            right: 0,
                            marginBottom: '8px',
                            padding: '8px 12px',
                            background: '#343741',
                            color: 'white',
                            fontSize: '12px',
                            borderRadius: '6px',
                            whiteSpace: 'nowrap',
                            zIndex: 10,
                          }}
                        >
                          Complete Challenge 8 RAG Pipeline
                        </div>
                      )}
                      <button
                        onClick={ragEnabled ? handleGenerateSummary : undefined}
                        disabled={summaryLoading || !ragEnabled}
                        style={{
                          padding: '8px 16px',
                          background: ragEnabled ? '#0077cc' : '#98a2b3',
                          color: 'white',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: (!ragEnabled || summaryLoading) ? 'not-allowed' : 'pointer',
                          fontSize: '13px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}
                      >
                        {!ragEnabled ? (
                          <>
                            <Lock size={14} />
                            Generate Summary
                          </>
                        ) : summaryLoading ? (
                          <>
                            <Loader size={14} className="spinning" />
                            Generating...
                          </>
                        ) : (
                          'Generate Summary'
                        )}
                      </button>
                    </div>
                  )}
                </div>
                {summary && (
                  <div
                    style={{
                      marginTop: '12px',
                      padding: '16px',
                      background: '#f0f7ff',
                      borderRadius: '6px',
                      lineHeight: '1.6',
                    }}
                    className="chat-widget-message-content"
                  >
                    <ReactMarkdown>{summary}</ReactMarkdown>
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
              {chatMessages.length === 0 && !chatLoading && (
                <div
                  style={{
                    textAlign: 'center',
                    color: '#69707d',
                    padding: '40px 20px',
                  }}
                >
                  <MessageCircle size={40} strokeWidth={1} />
                  <p style={{ marginTop: '12px' }}>
                    {agentEnabled
                      ? 'Ask questions about this incident (streaming enabled)'
                      : 'Ask questions about this incident'}
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
                      'Are there any related incidents?',
                      'What evidence was collected?',
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setInputMessage(suggestion)}
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

              {chatMessages.map((msg, idx) => {
                const incidentIds = msg.role === 'assistant' ? extractIncidentIds(msg.content) : [];
                return (
                  <div key={idx} className={`chat-message ${msg.role}`}>
                    {/* Tool calls */}
                    {msg.toolCalls && msg.toolCalls.length > 0 && (
                      <div className="chat-widget-tool-calls" style={{ marginBottom: '8px' }}>
                        {msg.toolCalls.map((tc, tcIdx) => (
                          <div key={tcIdx} className="tool-call-badge">
                            <Check size={12} />
                            <span>{tc.tool}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="chat-widget-message-content">
                      {msg.role === 'assistant' ? (
                        <ReactMarkdown>{msg.content}</ReactMarkdown>
                      ) : (
                        msg.content
                      )}
                    </div>
                    {incidentIds.length > 0 && (
                      <div style={{
                        marginTop: '10px',
                        paddingTop: '10px',
                        borderTop: '1px solid rgba(0,0,0,0.1)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        flexWrap: 'wrap'
                      }}>
                        <span style={{ fontSize: '12px', color: '#69707d' }}>
                          Related: {incidentIds.join(', ')}
                        </span>
                        <button
                          onClick={() => handleViewOnMap(incidentIds)}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '4px 8px',
                            background: '#e6f0f8',
                            color: '#0077cc',
                            border: '1px solid #0077cc',
                            borderRadius: '4px',
                            fontSize: '11px',
                            fontWeight: '500',
                            cursor: 'pointer',
                          }}
                        >
                          <MapPin size={12} />
                          View on Map
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Loading/Streaming progress */}
              {chatLoading && (
                agentEnabled ? renderStreamProgress() : (
                  <div className="chat-message assistant">
                    <Loader size={16} className="spinning" style={{ marginRight: 8 }} />
                    Thinking...
                  </div>
                )
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
