import axios from "axios";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({ baseURL: BASE });

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

export function getTrackerCsvUrl(batchId: number): string {
  return `${BASE}/api/v1/batches/${batchId}/export/tracker`;
}

export function getLocsZipUrl(jobId: number): string {
  return `${BASE}/api/v1/jobs/${jobId}/download/locs/zip`;
}

export async function getBatchJobs(id: number) {
  const { data } = await api.get(`/api/v1/batches/${id}/jobs`);
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
