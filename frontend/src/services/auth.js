import { API_BASE } from "../config/constants";

const GENERIC_ERROR = "Something went wrong. Please try again.";

async function authFetch(endpoint, email, password) {
  let response;
  try {
    response = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }

  const data = await response.json();
  localStorage.setItem("token", data.token);
  return data;
}

// FastAPI sends {detail: "..."} for errors it raises and {detail: [{msg}, ...]}
// for validation failures; anything else (a proxy's HTML page, an empty body)
// gets a generic message rather than a JSON parse error.
export async function errorMessage(response) {
  const body = await response.json().catch(() => null);
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) {
    return detail[0].msg.replace(/^Value error, /, "");
  }
  return GENERIC_ERROR;
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
