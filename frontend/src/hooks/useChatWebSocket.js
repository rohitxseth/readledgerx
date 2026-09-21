import { useState, useRef, useEffect, useCallback } from "react";
import {
  WS_URL,
  RECONNECT_BASE_DELAY,
  RECONNECT_MAX_DELAY,
  PING_INTERVAL,
  DEFAULT_SUGGESTIONS,
} from "../config/constants";

export function useChatWebSocket(token, onLogout) {
  const [messages, setMessages] = useState([]);
  const [connected, setConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [suggestions, setSuggestions] = useState(DEFAULT_SUGGESTIONS);
  const [sessionId, setSessionId] = useState(null);

  const wsRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const timersRef = useRef({ ping: null, reconnect: null });
  const intentionalCloseRef = useRef(false);

  // Accumulates streaming content for the current assistant turn
  const streamingRef = useRef({ text: "", elements: [] });

  const clearTimers = useCallback(() => {
    clearInterval(timersRef.current.ping);
    clearTimeout(timersRef.current.reconnect);
    timersRef.current.ping = null;
    timersRef.current.reconnect = null;
  }, []);

  const sendPayload = useCallback((payload) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const createSocket = useCallback(() => {
    if (!token) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token }));
    };

    ws.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }

      switch (data.type) {
        case "auth_ok":
          reconnectAttemptRef.current = 0;
          setConnected(true);
          clearTimers();
          timersRef.current.ping = setInterval(() => {
            sendPayload({ type: "ping" });
          }, PING_INTERVAL);
          break;

        case "text_chunk":
          streamingRef.current.text += data.content || "";
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant" && last._streaming) {
              updated[updated.length - 1] = {
                ...last,
                streamText: streamingRef.current.text,
              };
            }
            return updated;
          });
          break;

        case "element":
          if (!data.element) break;
          if (data.element.type === "progress") {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant" && last._streaming) {
                updated[updated.length - 1] = {
                  ...last,
                  progressMsg: data.element.message,
                };
              }
              return updated;
            });
            break;
          }
          streamingRef.current.elements.push(data.element);
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant" && last._streaming) {
              updated[updated.length - 1] = {
                ...last,
                elements: [...streamingRef.current.elements],
                progressMsg: null,
              };
            }
            return updated;
          });
          break;

        case "done":
          if (data.session_id) setSessionId(data.session_id);
          if (data.suggestions?.length) setSuggestions(data.suggestions);

          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant" && last._streaming) {
              updated[updated.length - 1] = {
                role: "assistant",
                response: data.response,
                _streaming: false,
              };
            }
            return updated;
          });
          streamingRef.current = { text: "", elements: [] };
          setIsLoading(false);
          break;

        case "error":
          if (data.message?.includes("expired") || data.message?.includes("Auth")) {
            onLogout();
            return;
          }

          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant" && last._streaming) {
              updated[updated.length - 1] = {
                role: "assistant",
                response: data.element,
                _streaming: false,
              };
            } else {
              updated.push({ role: "assistant", response: data.element });
            }
            return updated;
          });
          streamingRef.current = { text: "", elements: [] };
          setIsLoading(false);
          break;
      }
    };

    ws.onclose = () => {
      clearTimers();
      setConnected(false);

      if (!intentionalCloseRef.current) {
        const delay = Math.min(
          RECONNECT_BASE_DELAY * 2 ** reconnectAttemptRef.current,
          RECONNECT_MAX_DELAY
        );
        reconnectAttemptRef.current++;
        timersRef.current.reconnect = setTimeout(() => createSocket(), delay);
      }
    };
  }, [token, onLogout, clearTimers, sendPayload]);

  useEffect(() => {
    if (!token) return;

    intentionalCloseRef.current = false;
    createSocket();

    return () => {
      intentionalCloseRef.current = true;
      clearTimers();
      if (wsRef.current) {
        wsRef.current.close(1000, "Client disconnect");
        wsRef.current = null;
      }
    };
  }, [token, createSocket, clearTimers]);

  const sendMessage = useCallback((msg) => {
    if (!msg.trim() || isLoading || !connected) return false;

    streamingRef.current = { text: "", elements: [] };
    setMessages((prev) => [
      ...prev,
      { role: "user", content: msg.trim() },
      { role: "assistant", _streaming: true, streamText: "", elements: [], progressMsg: null },
    ]);
    setIsLoading(true);

    sendPayload({
      type: "message",
      session_id: sessionId,
      message: msg.trim(),
      message_type: "text",
    });
    return true;
  }, [isLoading, connected, sessionId, sendPayload]);

  const sendAction = useCallback((action, payload) => {
    if (isLoading || !connected) return false;

    streamingRef.current = { text: "", elements: [] };
    setMessages((prev) => [
      ...prev,
      { role: "user", content: payload?.label || action.replace(/_/g, " ") },
      { role: "assistant", _streaming: true, streamText: "", elements: [], progressMsg: null },
    ]);
    setIsLoading(true);

    sendPayload({
      type: "message",
      session_id: sessionId,
      message: "",
      message_type: "action_click",
      action_data: { action, payload },
    });
    return true;
  }, [isLoading, connected, sessionId, sendPayload]);

  return {
    messages,
    connected,
    isLoading,
    suggestions,
    sendMessage,
    sendAction
  };
}
