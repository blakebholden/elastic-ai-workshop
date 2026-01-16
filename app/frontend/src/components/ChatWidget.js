import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { MessageCircle, X, Send, Loader, Lock, Bot, Zap, MapPin, Cog, Database, Brain, Check, AlertCircle, Copy } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';

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
  const [copiedIdx, setCopiedIdx] = useState(null);

  // Streaming state
  const [streamingMessage, setStreamingMessage] = useState('');
  const [streamProgress, setStreamProgress] = useState({
    phase: null, // 'reasoning', 'tool_call', 'tool_progress', 'generating'
    reasoning: '',
    toolCalls: [],
    currentTool: null,
  });

  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Check for openChat URL param to auto-open
  useEffect(() => {
    if (searchParams.get('openChat') === 'true' && chatEnabled) {
      setIsOpen(true);
      // Clean up the URL param
      searchParams.delete('openChat');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams, chatEnabled]);

  // Handle "View on Map" click
  const handleViewOnMap = (incidentIds) => {
    if (incidentIds && incidentIds.length > 0) {
      // Save conversation state before navigating
      sessionStorage.setItem('chatWidget_messages', JSON.stringify(messages));
      sessionStorage.setItem('chatWidget_conversationId', conversationId || '');
      sessionStorage.setItem('chatWidget_useAgent', useAgent.toString());

      const ids = incidentIds.join(',');
      navigate(`/map?highlight=${encodeURIComponent(ids)}&from=widget`);
      setIsOpen(false);
    }
  };

  // Restore conversation when returning from map
  useEffect(() => {
    if (searchParams.get('openChat') === 'true') {
      const savedMessages = sessionStorage.getItem('chatWidget_messages');
      const savedConversationId = sessionStorage.getItem('chatWidget_conversationId');
      const savedUseAgent = sessionStorage.getItem('chatWidget_useAgent');

      if (savedMessages) {
        try {
          setMessages(JSON.parse(savedMessages));
          sessionStorage.removeItem('chatWidget_messages');
        } catch (e) {
          console.error('Failed to restore messages:', e);
        }
      }
      if (savedConversationId) {
        setConversationId(savedConversationId);
        sessionStorage.removeItem('chatWidget_conversationId');
      }
      if (savedUseAgent !== null) {
        setUseAgent(savedUseAgent === 'true');
        sessionStorage.removeItem('chatWidget_useAgent');
      }
    }
  }, [searchParams]);

  // Extract incident IDs from text (e.g., INC-2024-001234)
  const extractIncidentIds = (text) => {
    if (!text) return [];
    const matches = text.match(/INC-\d{4}-\d+/g) || [];
    return [...new Set(matches)];
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
  }, [messages, streamingMessage, streamProgress]);

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

  // Handle streaming agent chat
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
      const response = await fetch(`${API_BASE}/agent/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: userMessage,
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
            // Unwrap nested data structure - API returns {data: {...}}
            const rawData = parsed.value;
            const data = rawData?.data || rawData;

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
                // Mark tool as completed
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
                // Stream is done
                break;

              case 'error':
                const errorMsg = typeof data.error === 'object'
                  ? (data.error.message || JSON.stringify(data.error))
                  : (data.error || 'Stream error');
                throw new Error(errorMsg);

              default:
                break;
            }
            currentEventType = null;
          }
        }
      }

      // Store conversation ID
      if (newConversationId) {
        setConversationId(newConversationId);
      }

      // Add final message
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: finalMessage || 'No response received.',
          toolCalls: collectedToolCalls.filter(tc => tc.status === 'completed'),
          sources: [],
          isAgent: true,
        },
      ]);

    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('Stream aborted');
      } else {
        console.error('Streaming failed:', err);
        setMessages(prev => [
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
    if (!inputMessage.trim() || chatLoading || !chatEnabled) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setChatLoading(true);

    try {
      if (useAgent && agentEnabled) {
        // Use streaming for agent mode
        await handleStreamingChat(userMessage);
      } else {
        // Use direct RAG chat endpoint (non-streaming)
        const resp = await axios.post(`${API_BASE}/chat`, {
          message: userMessage,
          chat_history: messages.filter(m => !m.toolCalls),
        });

        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: resp.data.response,
            sources: resp.data.sources,
            isAgent: false,
          },
        ]);
        setChatLoading(false);
      }
    } catch (err) {
      console.error('Chat failed:', err);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: 'Sorry, I encountered an error. Please try again.',
        },
      ]);
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
    setMessages([]);
    setConversationId(null);
  };

  const handleCopyMessage = async (content, idx) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Render streaming progress
  const renderStreamProgress = () => {
    const { phase, reasoning, toolCalls, currentTool } = streamProgress;

    return (
      <div className="chat-widget-loading stream-progress">
        {/* Reasoning phase */}
        <div className={`loading-step ${phase === 'reasoning' ? 'active' : ''} ${['tool_call', 'tool_progress', 'generating'].includes(phase) ? 'completed' : ''}`}>
          <div className="loading-step-icon">
            {['tool_call', 'tool_progress', 'generating'].includes(phase) ? <Check size={14} /> : <Brain size={14} />}
          </div>
          <span className="loading-step-text">
            {phase === 'reasoning' ? (reasoning || 'Analyzing query...') : 'Query analyzed'}
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

        {/* No tools yet but in tool phase */}
        {toolCalls.length === 0 && phase === 'tool_call' && (
          <div className="loading-step active">
            <div className="loading-step-icon">
              <Cog size={14} />
            </div>
            <span className="loading-step-text">Selecting tools...</span>
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

  // Render non-streaming progress (for direct mode)
  const renderDirectProgress = () => {
    return (
      <div className="chat-widget-loading">
        <div className="loading-step active">
          <div className="loading-step-icon">
            <Loader size={14} className="spinning" />
          </div>
          <span className="loading-step-text">Searching and generating response...</span>
        </div>
      </div>
    );
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
    return null;
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
            {messages.length === 0 && !chatLoading && (
              <div className="chat-widget-welcome">
                {useAgent ? <Bot size={32} strokeWidth={1} /> : <MessageCircle size={32} strokeWidth={1} />}
                <p>
                  {useAgent
                    ? 'Agent mode: Real-time streaming with tool execution'
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

            {messages.map((msg, idx) => {
              // Extract incident IDs from message content for agent responses
              const contentIncidentIds = msg.role === 'assistant' ? extractIncidentIds(msg.content) : [];
              const sourceIncidentIds = (msg.sources || []).filter(s => s.startsWith('INC-'));
              const allIncidentIds = [...new Set([...contentIncidentIds, ...sourceIncidentIds])];
              const hasTools = msg.toolCalls && msg.toolCalls.length > 0;

              return (
                <div key={idx} className={`chat-widget-message ${msg.role} ${hasTools ? 'has-tools' : ''}`}>
                  {/* Tool calls indicator for agent responses */}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="chat-widget-tool-calls">
                      {msg.toolCalls.map((tc, tcIdx) => (
                        <div key={tcIdx} className="tool-call-badge">
                          <Check size={12} />
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
                  <div className="chat-widget-message-content">
                    {msg.role === 'assistant' ? (
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    ) : (
                      msg.content
                    )}
                  </div>
                  {/* Show sources if available */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="chat-widget-sources">
                      Sources: {msg.sources.join(', ')}
                    </div>
                  )}
                  {/* View on Map button - show if any incident IDs found */}
                  {allIncidentIds.length > 0 && (
                    <div className="chat-widget-map-action">
                      <button
                        className="chat-widget-map-btn"
                        onClick={() => handleViewOnMap(allIncidentIds)}
                      >
                        <MapPin size={14} />
                        View {allIncidentIds.length} incident{allIncidentIds.length > 1 ? 's' : ''} on Map
                      </button>
                    </div>
                  )}
                  {/* Copy button for assistant messages */}
                  {msg.role === 'assistant' && (
                    <button
                      className="chat-copy-btn"
                      onClick={() => handleCopyMessage(msg.content, idx)}
                      title="Copy response"
                    >
                      {copiedIdx === idx ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  )}
                </div>
              );
            })}

            {/* Loading/Streaming progress */}
            {chatLoading && (
              useAgent ? renderStreamProgress() : renderDirectProgress()
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
