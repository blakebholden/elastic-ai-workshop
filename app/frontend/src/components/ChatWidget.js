import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { MessageCircle, X, Send, Loader, Lock, Bot, Zap, MapPin } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const API_BASE = process.env.REACT_APP_API_URL || '';

function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [chatEnabled, setChatEnabled] = useState(false);
  const [agentEnabled, setAgentEnabled] = useState(false);
  const [useAgent, setUseAgent] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [showTooltip, setShowTooltip] = useState(false);
  const [conversationId, setConversationId] = useState(null);

  const messagesEndRef = useRef(null);
  const navigate = useNavigate();

  // Handle "View on Map" click
  const handleViewOnMap = (incidentIds) => {
    if (incidentIds && incidentIds.length > 0) {
      const ids = incidentIds.join(',');
      navigate(`/map?highlight=${encodeURIComponent(ids)}`);
      setIsOpen(false); // Close chat panel
    }
  };

  // Check if sources contain incident IDs
  const hasIncidentIds = (sources) => {
    return sources && sources.length > 0 && sources.some(s => s.startsWith('INC-'));
  };

  // Fetch feature flags on mount
  useEffect(() => {
    const fetchFeatures = async () => {
      try {
        const resp = await axios.get(`${API_BASE}/features`);
        setChatEnabled(resp.data.chat_enabled);
        setAgentEnabled(resp.data.agent_enabled);
        // Default to agent mode if available
        setUseAgent(resp.data.agent_enabled);
      } catch (err) {
        console.error('Failed to fetch features:', err);
        setChatEnabled(false);
        setAgentEnabled(false);
      } finally {
        setIsLoading(false);
      }
    };
    fetchFeatures();
  }, []);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || chatLoading || !chatEnabled) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setChatLoading(true);

    try {
      let resp;

      if (useAgent && agentEnabled) {
        // Use Agent Builder endpoint
        resp = await axios.post(`${API_BASE}/agent/chat`, {
          message: userMessage,
          conversation_id: conversationId,
        });

        // Store conversation ID for multi-turn
        if (resp.data.conversation_id) {
          setConversationId(resp.data.conversation_id);
        }

        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: resp.data.response,
            sources: resp.data.sources,
            toolCalls: resp.data.tool_calls,
            isAgent: true,
          },
        ]);
      } else {
        // Use direct RAG chat endpoint
        resp = await axios.post(`${API_BASE}/chat`, {
          message: userMessage,
          chat_history: messages.filter(m => !m.toolCalls), // Filter out tool call metadata
        });

        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: resp.data.response,
            sources: resp.data.sources,
            isAgent: false,
          },
        ]);
      }
    } catch (err) {
      console.error('Chat failed:', err);
      setMessages((prev) => [
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

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleButtonClick = () => {
    if (chatEnabled) {
      setIsOpen(!isOpen);
    }
  };

  const handleModeToggle = () => {
    setUseAgent(!useAgent);
    // Clear conversation when switching modes
    setMessages([]);
    setConversationId(null);
  };

  const suggestedQuestions = useAgent ? [
    'Show me incidents in the South district',
    'What are the incident trends this month?',
    'Find high-value theft incidents',
    'Search for armed robberies',
  ] : [
    'What types of incidents are most common?',
    'Show me recent robberies',
    'Any patterns in the South district?',
    'High-value theft incidents',
  ];

  if (isLoading) {
    return null; // Don't render until we know the feature flag status
  }

  return (
    <div className="chat-widget-container">
      {/* Chat Panel */}
      {isOpen && chatEnabled && (
        <div className="chat-widget-panel">
          <div className="chat-widget-header">
            <div className="chat-widget-title">
              {useAgent ? <Bot size={18} /> : <MessageCircle size={18} />}
              <span>{useAgent ? 'Agent Assistant' : 'Investigation Assistant'}</span>
            </div>
            <button className="chat-widget-close" onClick={() => setIsOpen(false)}>
              <X size={18} />
            </button>
          </div>

          {/* Agent Mode Toggle */}
          {agentEnabled && (
            <div className="chat-widget-mode-toggle">
              <span className={!useAgent ? 'active' : ''}>
                <Zap size={14} /> Direct
              </span>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={useAgent}
                  onChange={handleModeToggle}
                />
                <span className="toggle-slider"></span>
              </label>
              <span className={useAgent ? 'active' : ''}>
                <Bot size={14} /> Agent
              </span>
            </div>
          )}

          <div className="chat-widget-messages">
            {messages.length === 0 && (
              <div className="chat-widget-welcome">
                {useAgent ? <Bot size={32} strokeWidth={1} /> : <MessageCircle size={32} strokeWidth={1} />}
                <p>
                  {useAgent
                    ? 'Agent mode: Uses specialized tools for structured queries'
                    : 'Direct mode: Semantic search over narratives'}
                </p>
                <div className="chat-widget-suggestions">
                  {suggestedQuestions.map((question) => (
                    <button
                      key={question}
                      onClick={() => setInputMessage(question)}
                      className="chat-widget-suggestion"
                    >
                      {question}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, idx) => (
              <div key={idx} className={`chat-widget-message ${msg.role}`}>
                {/* Tool calls indicator for agent responses */}
                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="chat-widget-tool-calls">
                    {msg.toolCalls.map((tc, tcIdx) => (
                      <div key={tcIdx} className="tool-call-badge">
                        <Bot size={12} />
                        <span>{tc.tool}</span>
                        {Object.keys(tc.parameters || {}).length > 0 && (
                          <span className="tool-params">
                            ({Object.entries(tc.parameters).map(([k, v]) => `${k}=${v}`).join(', ')})
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <div className="chat-widget-message-content">{msg.content}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="chat-widget-sources">
                    Sources: {msg.sources.join(', ')}
                    {hasIncidentIds(msg.sources) && (
                      <button
                        className="chat-widget-map-btn"
                        onClick={() => handleViewOnMap(msg.sources.filter(s => s.startsWith('INC-')))}
                      >
                        <MapPin size={14} />
                        View on Map
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}

            {chatLoading && (
              <div className="chat-widget-message assistant">
                <Loader size={16} className="spinning" />
                <span style={{ marginLeft: 8 }}>
                  {useAgent ? 'Agent processing...' : 'Thinking...'}
                </span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <div className="chat-widget-input-area">
            <textarea
              className="chat-widget-input"
              placeholder={useAgent ? 'Ask the agent...' : 'Ask about incidents...'}
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              rows={1}
            />
            <button
              className="chat-widget-send"
              onClick={handleSendMessage}
              disabled={chatLoading || !inputMessage.trim()}
            >
              <Send size={18} />
            </button>
          </div>
        </div>
      )}

      {/* Floating Button */}
      <div
        className="chat-widget-button-container"
        onMouseEnter={() => !chatEnabled && setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        {showTooltip && !chatEnabled && (
          <div className="chat-widget-tooltip">
            Enable Chat in Challenge 10
          </div>
        )}
        <button
          className={`chat-widget-button ${!chatEnabled ? 'disabled' : ''} ${isOpen ? 'open' : ''}`}
          onClick={handleButtonClick}
          disabled={!chatEnabled}
        >
          {!chatEnabled ? (
            <Lock size={24} />
          ) : isOpen ? (
            <X size={24} />
          ) : (
            <MessageCircle size={24} />
          )}
        </button>
      </div>
    </div>
  );
}

export default ChatWidget;
