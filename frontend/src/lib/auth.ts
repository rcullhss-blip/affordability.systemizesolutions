"use client";
/**
 * Client-side session for the dashboard and firm portals.
 *
 * The backend issues a 12h JWT on POST /api/v1/auth/login. We keep it in
 * localStorage (the API lives on a different domain from the pages, so a
 * cookie would need cross-site settings on every firm domain) and send it as
 * `Authorization: Bearer` on every API call; download links append `?token=`.
 */

export type Role = "admin" | "firm";
export interface SessionUser {
  id: number;
  email: string;
  name: string | null;
  role: Role;
  firm: string | null;
  is_active: boolean;
}

const TOKEN_KEY = "systemize.token";
const USER_KEY = "systemize.user";

function storage(): Storage | null {
  try { return typeof window !== "undefined" ? window.localStorage : null; } catch { return null; }
}

export function getToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null;
}

export function getUser(): SessionUser | null {
  const raw = storage()?.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw) as SessionUser; } catch { return null; }
}

export function setSession(token: string, user: SessionUser): void {
  storage()?.setItem(TOKEN_KEY, token);
  storage()?.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  storage()?.removeItem(TOKEN_KEY);
  storage()?.removeItem(USER_KEY);
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** Append the session token to a URL used in an <a href> (downloads). */
export function withToken(url: string): string {
  const t = getToken();
  if (!t) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t);
}

export function signOut(next: string = "/login"): void {
  clearSession();
  if (typeof window !== "undefined") window.location.href = next;
}
