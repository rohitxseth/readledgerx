import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { login, register } from "./auth";

// Node 25+ defines its own localStorage global (undefined unless started with
// --localstorage-file), which hides jsdom's, so the tests supply one.
function memoryStorage() {
  const items = new Map();
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
    clear: () => items.clear(),
  };
}

beforeEach(() => vi.stubGlobal("localStorage", memoryStorage()));
afterEach(() => vi.unstubAllGlobals());

function respondWith(status, body, contentType = "application/json") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body, { status, headers: { "Content-Type": contentType } })),
  );
}

test("a non-JSON error body shows a friendly message, not a parse error", async () => {
  respondWith(502, "<html>Bad Gateway</html>", "text/html");
  await expect(login("a@b.com", "pw")).rejects.toThrow("Something went wrong. Please try again.");
});

test("an empty error body shows a friendly message", async () => {
  respondWith(500, "");
  await expect(login("a@b.com", "pw")).rejects.toThrow("Something went wrong. Please try again.");
});

test("a string detail from the API is shown as-is", async () => {
  respondWith(400, JSON.stringify({ detail: "Email already registered" }));
  await expect(register("a@b.com", "pw")).rejects.toThrow("Email already registered");
});

test("a validation error shows its first message without pydantic's prefix", async () => {
  respondWith(
    422,
    JSON.stringify({ detail: [{ loc: ["body", "password"], msg: "Value error, Password is too long." }] }),
  );
  await expect(register("a@b.com", "pw")).rejects.toThrow(/^Password is too long\.$/);
});

test("a network failure says the server can't be reached", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  await expect(login("a@b.com", "pw")).rejects.toThrow("Can't reach the server");
});

test("a successful login stores the token", async () => {
  respondWith(200, JSON.stringify({ token: "t0k3n", user_id: "u", user_email: "a@b.com" }));
  await login("a@b.com", "pw");
  expect(localStorage.getItem("token")).toBe("t0k3n");
});
