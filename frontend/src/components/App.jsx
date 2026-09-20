import { useState, useEffect } from "react";
import { register, login, logout, getToken } from "../services/auth";
import ChatPage from "./ChatPage";

function App() {
  const [token, setToken] = useState(null);
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const savedToken = getToken();
    if (savedToken) {
      setToken(savedToken);
    }
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    try {
      if (isLogin) {
        await login(email, password);
      } else {
        await register(email, password);
      }
      setToken(getToken());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    }
  }

  function handleLogout() {
    logout();
    setToken(null);
  }

  if (token) {
    return <ChatPage onLogout={handleLogout} />;
  }

  return (
    <div className="auth-container">
      <div className="auth-box">
        <h1>{isLogin ? "Login" : "Register"}</h1>
        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit">{isLogin ? "Login" : "Register"}</button>
        </form>
        {error && <div className="error">{error}</div>}
        <div>
          <div className="auth-toggle">
            {isLogin ? "Don't have an account? " : "Already have an account? "}
          </div>
          <div className="auth-toggle-btn">
            <button onClick={() => setIsLogin(!isLogin)}>
            {isLogin ? "Register" : "Login"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
