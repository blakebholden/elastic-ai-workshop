import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { MessageCircle, X, Send, Loader, Lock } from 'lucide-react';

const API_BASE = process.env.REACT_APP_API_URL || '';

function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [chatEnabled, setChatEnabled] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [showTooltip, setShowTooltip] = useState(false);

  const messagesEndRef = useRef(null);

  // Fetch feature flags on mount
  useEffect(() => {
    const fetchFeatures = async () => {
      try {
        const resp = await axios.get(`${API_BASE}/features`);
        setChatEnabled(resp.data.chat_enabled);
      } catch (err) {
        console.error('Failed to fetch features:', err);
        setChatEnabled(false);
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
      const resp = await axios.post(`${API_BASE}/chat`, {
        message: userMessage,
        chat_history: messages,
      });

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.data.response,
          sources: resp.data.sources,
        },
      ]);
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

  const suggestedQuestions = [
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
              <MessageCircle size={18} />
              <span>Investigation Assistant</span>
            </div>
            <button className="chat-widget-close" onClick={() => setIsOpen(false)}>
              <X size={18} />
            </button>
          </div>

          <div className="chat-widget-messages">
            {messages.length === 0 && (
              <div className="chat-widget-welcome">
                <MessageCircle size={32} strokeWidth={1} />
                <p>Ask questions about police incidents</p>
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
                <div className="chat-widget-message-content">{msg.content}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="chat-widget-sources">
                    Sources: {msg.sources.join(', ')}
                  </div>
                )}
              </div>
            ))}

            {chatLoading && (
              <div className="chat-widget-message assistant">
                <Loader size={16} className="spinning" />
                <span style={{ marginLeft: 8 }}>Thinking...</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <div className="chat-widget-input-area">
            <textarea
              className="chat-widget-input"
              placeholder="Ask about incidents..."
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
