import { API_BASE } from "../config/constants";

async function authFetch(endpoint, email, password) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    try {
      const errorData = await response.json();
      throw new Error(errorData.detail || "Authentication failed");
    } catch (e) {
      if (e instanceof Error && e.message !== "Authentication failed") {
        throw e;
      }
      throw new Error("Authentication failed");
    }
  }

  const data = await response.json();
  localStorage.setItem("token", data.token);
  return data;
}

export async function register(email, password) {
  return authFetch("/auth/register", email, password);
}

export async function login(email, password) {
  return authFetch("/auth/login", email, password);
}

export function logout() {
  localStorage.removeItem("token");
}

export function getToken() {
  return localStorage.getItem("token");
}
