import axios from "axios";
import { getToken, clearSession, withToken } from "@/lib/auth";

const BASE = process.env.NEXT_PUBLIC_API_URL || "https://systemize-backend.onrender.com";

export const api = axios.create({
  baseURL: BASE,
  headers: { "bypass-tunnel-reminder": "true" },
});

// Every API call carries the session token; a 401 means the session is gone
// (expired, password reset, account disabled) — send the user to sign in.
api.interceptors.request.use((config) => {
  const t = getToken();
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});
api.interceptors.response.use(
  (r) => r,
  (err) => {
    const status = err?.response?.status;
    const url: string = err?.config?.url || "";
    if (status === 401 && typeof window !== "undefined" && !url.includes("/auth/login")) {
      clearSession();
      const here = window.location.pathname + window.location.search;
      if (!here.startsWith("/login")) window.location.href = `/login?next=${encodeURIComponent(here)}`;
    }
    return Promise.reject(err);
  },
);

// ── Auth ───────────────────────────────────────────────────────────────────

export async function listUsers() {
  const { data } = await api.get("/api/v1/auth/users");
  return data;
}

export async function createUser(body: { email: string; password: string; name?: string; role: "admin" | "firm"; firm?: string | null }) {
  const { data } = await api.post("/api/v1/auth/users", body);
  return data;
}

export async function resetUserPassword(userId: number, new_password: string) {
  const { data } = await api.post(`/api/v1/auth/users/${userId}/reset-password`, { new_password });
  return data;
}

export async function setUserActive(userId: number, active: boolean) {
  const { data } = await api.post(`/api/v1/auth/users/${userId}/${active ? "activate" : "deactivate"}`);
  return data;
}

export async function changePassword(current_password: string, new_password: string) {
  const { data } = await api.post("/api/v1/auth/change-password", { current_password, new_password });
  return data;
}

// ── Batches ────────────────────────────────────────────────────────────────

export async function getBatches(skip = 0, limit = 50) {
  const { data } = await api.get("/api/v1/batches/", { params: { skip, limit } });
  return data;
}

export async function getBatch(id: number) {
  const { data } = await api.get(`/api/v1/batches/${id}`);
  return data;
}

export async function getBatchProgress(id: number) {
  const { data } = await api.get(`/api/v1/batches/${id}/progress`);
  return data;
}

// Download links are plain <a href>s, so the token travels as ?token= instead
// of a header (the API accepts either).
export function getTrackerCsvUrl(batchId: number): string {
  return withToken(`${BASE}/api/v1/batches/${batchId}/export/tracker`);
}

export function getLocsZipUrl(jobId: number): string {
  return withToken(`${BASE}/api/v1/jobs/${jobId}/download/locs/zip`);
}

// Paginated — the backend caps this (the un-paged version pulled every job row
// in the batch on a 5s poll and OOM-killed the API).
export async function getBatchJobs(id: number, skip = 0, limit = 500) {
  const { data } = await api.get(`/api/v1/batches/${id}/jobs`, { params: { skip, limit } });
  return data;
}

// ── Cases (IRL cases from the PCP platform) ─────────────────────────────────

// `day` (YYYY-MM-DD, UK calendar day) filters to cases received that day.
export async function getCases(skip = 0, limit = 50, day?: string) {
  const { data } = await api.get("/api/v1/cases/", { params: { skip, limit, ...(day ? { day } : {}) } });
  return data;
}

export async function getCase(id: number) {
  const { data } = await api.get(`/api/v1/cases/${id}`);
  return data;
}

export async function getCasesSummary(day?: string) {
  const { data } = await api.get("/api/v1/cases/stats/summary", { params: day ? { day } : {} });
  return data;
}

// ── Jobs ───────────────────────────────────────────────────────────────────

export async function getJob(id: number) {
  const { data } = await api.get(`/api/v1/jobs/${id}`);
  return data;
}

function absoluteUrl(url: string): string {
  return url.startsWith("/") ? `${BASE}${url}` : url;
}

export async function getJobDownloadAssessment(id: number): Promise<string> {
  // Endpoint returns { url: <presigned S3 url> } — fetch it, then open that URL.
  const { data } = await api.get(`/api/v1/jobs/${id}/download/assessment`);
  return absoluteUrl(data.url);
}

export async function getJobDownloadLocs(id: number) {
  const { data } = await api.get(`/api/v1/jobs/${id}/download/locs`);
  return (data.locs as { lender: string; traffic_light: string; url: string }[]).map((l) => ({
    ...l,
    url: absoluteUrl(l.url),
  }));
}

// ── Clients ────────────────────────────────────────────────────────────────

export async function getClients(skip = 0, limit = 100) {
  const { data } = await api.get("/api/v1/clients/", { params: { skip, limit } });
  return data;
}

export async function getClient(matterRef: string) {
  const { data } = await api.get(`/api/v1/clients/${encodeURIComponent(matterRef)}`);
  return data;
}

export async function getClientJobs(matterRef: string) {
  const { data } = await api.get(`/api/v1/clients/${encodeURIComponent(matterRef)}/jobs`);
  return data;
}

// ── Analytics ──────────────────────────────────────────────────────────────

export async function getAnalyticsSummary() {
  const { data } = await api.get("/api/v1/analytics/summary");
  return data;
}

export async function getLenderAnalytics() {
  const { data } = await api.get("/api/v1/analytics/lenders");
  return data;
}

export async function getRiskIndicators() {
  const { data } = await api.get("/api/v1/analytics/risk-indicators");
  return data;
}

// ── Upload ─────────────────────────────────────────────────────────────────

export async function uploadFile(file: File, batchName: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("batch_name", batchName);
  const { data } = await api.post("/api/v1/upload/file", form);
  return data;
}

export async function uploadZip(file: File, batchName: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("batch_name", batchName);
  const { data } = await api.post("/api/v1/upload/zip", form);
  return data;
}

export async function uploadCsv(file: File, batchName: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("batch_name", batchName);
  const { data } = await api.post("/api/v1/upload/csv", form);
  return data;
}

// ── Spot checks ────────────────────────────────────────────────────────────

export async function getSpotChecks() {
  const { data } = await api.get("/api/v1/jobs/spot-checks");
  return data;
}

export async function markSpotCheckReviewed(jobId: number) {
  const { data } = await api.post(`/api/v1/jobs/${jobId}/spot-check/reviewed`);
  return data;
}

export async function submitFeedback(jobId: number, note: string) {
  const { data } = await api.post(`/api/v1/jobs/${jobId}/feedback`, { note });
  return data;
}

export async function getOpenFeedback() {
  const { data } = await api.get("/api/v1/jobs/feedback/open");
  return data;
}

export async function resolveFeedback(feedbackId: number) {
  const { data } = await api.post(`/api/v1/jobs/feedback/${feedbackId}/resolved`);
  return data;
}
