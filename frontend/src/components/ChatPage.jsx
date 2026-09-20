import { useState, useRef, useEffect, useCallback } from "react";
import { getToken } from "../services/auth";
import { useChatWebSocket } from "../hooks/useChatWebSocket";
import BduiRenderer from "./BduiRenderer";

function ChatPage({ onLogout }) {
  const token = getToken();

  const {
    messages,
    connected,
    isLoading,
    suggestions,
    sendMessage,
    sendAction
  } = useChatWebSocket(token, onLogout);

  const [input, setInput] = useState("");
  const [isDark, setIsDark] = useState(
    localStorage.getItem("theme") === "dark",
  );

  const inputRef = useRef(null);
  const messagesEndRef = useRef(null);

  // ---- theme ----
  useEffect(() => {
    document.body.className = isDark ? "dark" : "";
    localStorage.setItem("theme", isDark ? "dark" : "light");
  }, [isDark]);

  // ---- auto-scroll ----
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ---- focus input ----
  useEffect(() => {
    if (!isLoading) inputRef.current?.focus();
  }, [messages, isLoading]);

  // ---- send message ----
  const handleSend = useCallback(
    (text) => {
      const msg = typeof text === "string" ? text : input;
      if (sendMessage(msg)) {
        if (typeof text !== "string") setInput("");
        else setInput("");
      }
    },
    [input, sendMessage],
  );

  // ---- action button click ----
  const handleAction = useCallback(
    (action, payload) => {
      sendAction(action, payload);
    },
    [sendAction],
  );

  // ---- form submit handler ----
  const onSubmit = (e) => {
    e.preventDefault();
    handleSend();
  };

  return (
    <div className="chat-container">
      {/* Header */}
      <div className="logo-header">
        <svg
          className="book-icon"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
        </svg>
        <h1 className="logo-text">Readledger</h1>
        <div
          className={`connection-dot ${connected ? "connected" : "disconnected"}`}
          title={connected ? "Connected" : "Reconnecting…"}
        />
        <button
          onClick={() => setIsDark(!isDark)}
          className="theme-btn"
          title="Toggle theme"
        >
          {isDark ? "Light" : "Dark"}
        </button>
        <button onClick={onLogout} className="logout-btn">
          Logout
        </button>
      </div>

      {/* Messages */}
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <p className="empty-state__title">What would you like to do?</p>
            <div className="empty-state__suggestions">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  className="suggestion-chip"
                  onClick={() => handleSend(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {/* User message */}
            {msg.role === "user" && (
              <div className="message-content">{msg.content}</div>
            )}

            {/* Assistant message */}
            {msg.role === "assistant" && (
              <div className="assistant-bubble">
                {/* Streaming text */}
                {msg._streaming && msg.streamText && (
                  <div className="bdui-text bdui-text--default">
                    {msg.streamText}
                  </div>
                )}

                {/* Progress indicator while streaming */}
                {msg._streaming && msg.progressMsg && (
                  <div className="bdui-progress">
                    <div className="bdui-progress__spinner" />
                    <span className="bdui-progress__message">
                      {msg.progressMsg}
                    </span>
                  </div>
                )}

                {/* Streaming elements (before done) */}
                {msg._streaming &&
                  msg.elements?.map((el, i) => (
                    <BduiRenderer
                      key={i}
                      element={el}
                      onAction={handleAction}
                    />
                  ))}

                {/* Finalized BDUI response */}
                {!msg._streaming && msg.response && (
                  <BduiRenderer
                    element={msg.response}
                    onAction={handleAction}
                  />
                )}

                {/* Typing indicator */}
                {msg._streaming &&
                  !msg.streamText &&
                  !msg.elements?.length &&
                  !msg.progressMsg && (
                    <div className="typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  )}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Suggestion chips (shown when not loading and messages exist) */}
      {suggestions.length > 0 && messages.length > 0 && !isLoading && (
        <div className="suggestion-bar">
          {suggestions.map((s, i) => (
            <button
              key={i}
              className="suggestion-chip"
              onClick={() => handleSend(s)}
              disabled={!connected}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form onSubmit={onSubmit} className="input-form">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={connected ? "Message Ria..." : "Connecting..."}
          disabled={isLoading || !connected}
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim() || !connected}
        >
          Send
        </button>
      </form>
    </div>
  );
}

export default ChatPage;
