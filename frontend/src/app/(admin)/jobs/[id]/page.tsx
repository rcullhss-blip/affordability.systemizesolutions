"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getJob, getJobDownloadAssessment, getJobDownloadLocs, getLocsZipUrl } from "@/lib/api";
import { TrafficLightBadge } from "@/components/ui/TrafficLight";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  COMPLETE:   { label: "Complete",   cls: "text-green-400 bg-green-900/20 border-green-800" },
  FAILED:     { label: "Failed",     cls: "text-red-400 bg-red-900/20 border-red-800" },
  PENDING:    { label: "Pending",    cls: "text-gray-400 bg-gray-800/60 border-gray-700" },
  FETCHING:   { label: "Fetching",   cls: "text-blue-400 bg-blue-900/20 border-blue-800" },
  EXTRACTING: { label: "Extracting", cls: "text-blue-400 bg-blue-900/20 border-blue-800" },
  PARSING:    { label: "Parsing",    cls: "text-yellow-400 bg-yellow-900/20 border-yellow-800" },
  ANALYSING:  { label: "Analysing",  cls: "text-yellow-400 bg-yellow-900/20 border-yellow-800" },
  GENERATING: { label: "Generating", cls: "text-purple-400 bg-purple-900/20 border-purple-800" },
  DELIVERING: { label: "Delivering", cls: "text-purple-400 bg-purple-900/20 border-purple-800" },
};

const SEV_COLORS: Record<string, string> = {
  CRITICAL: "text-red-400 bg-red-900/30 border-red-800",
  HIGH:     "text-orange-400 bg-orange-900/20 border-orange-800",
  MEDIUM:   "text-amber-400 bg-amber-900/20 border-amber-800",
  LOW:      "text-gray-400 bg-gray-800 border-gray-700",
};

function FlagBadge({ flag }: { flag: any }) {
  const sev = (typeof flag === "object" ? flag.severity : "")?.toUpperCase() ?? "";
  const desc = typeof flag === "object" ? flag.description : String(flag);
  const cls = SEV_COLORS[sev] ?? SEV_COLORS.LOW;
  return (
    <div className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-xs ${cls}`}>
      {sev && <span className="font-bold shrink-0 opacity-70">[{sev}]</span>}
      <span>{desc}</span>
    </div>
  );
}

export default function JobDetailPage() {
  const { id } = useParams();
  const [job, setJob] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const load = () => getJob(Number(id)).then(setJob).catch(() => {}).finally(() => setLoading(false));
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [id]);

  async function downloadAssessment() {
    if (!id) return;
    setDownloading("assessment");
    try {
      const url = await getJobDownloadAssessment(Number(id));
      window.open(url, "_blank");
    } catch {
      alert("Assessment not available yet.");
    } finally { setDownloading(null); }
  }

  async function downloadAllLocs() {
    if (!id) return;
    setDownloading("locs");
    try {
      const locs = await getJobDownloadLocs(Number(id));
      if (!locs.length) { alert("No LOCs generated for this job."); return; }
      for (const loc of locs) window.open(loc.url, "_blank");
    } catch {
      alert("LOCs not available yet.");
    } finally { setDownloading(null); }
  }

  async function downloadSingleLoc(lender: string) {
    try {
      const locs = await getJobDownloadLocs(Number(id));
      const match = locs.find((l) => l.lender === lender);
      if (match) window.open(match.url, "_blank");
      else alert("LOC not found.");
    } catch { alert("Could not download LOC."); }
  }

  if (loading) return <div className="p-8 text-gray-500 text-sm">Loading…</div>;
  if (!job)    return <div className="p-8 text-red-400 text-sm">Job not found.</div>;

  const meta = STATUS_META[job.status] ?? STATUS_META.PENDING;
  const locsAvailable = job.lender_results?.some((r: any) => r.loc_generated);
  const noLongerTrading = (job.lender_results ?? []).filter((r: any) => r.no_longer_trading);
  const inScope  = (job.lender_results ?? []).filter((r: any) => !r.no_longer_trading && r.traffic_light !== "RED");
  const outScope = (job.lender_results ?? []).filter((r: any) => !r.no_longer_trading && r.traffic_light === "RED");

  return (
    <div className="p-8 max-w-5xl">

      {/* Breadcrumb */}
      <div className="text-xs text-gray-600 mb-4 flex items-center gap-1.5">
        <Link href="/batches" className="hover:text-gray-300 transition-colors">Batches</Link>
        {job.batch_id && (
          <>
            <span>/</span>
            <Link href={`/batches/${job.batch_id}`} className="hover:text-gray-300 transition-colors">
              Batch #{job.batch_id}
            </Link>
          </>
        )}
        <span>/</span>
        <span className="text-gray-400">Job #{job.id}</span>
      </div>

      {/* Header card */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">
              {job.client?.name ?? "Processing…"}
            </h1>
            <div className="flex items-center gap-3 mt-1 flex-wrap">
              {job.client?.matter_ref && (
                <Link href={`/clients/${job.client.matter_ref}`}
                      className="text-xs text-blue-400 hover:underline font-mono">
                  {job.client.matter_ref}
                </Link>
              )}
              {job.client?.dob && (
                <span className="text-xs text-gray-500">DOB: {job.client.dob}</span>
              )}
              {job.client?.address && (
                <span className="text-xs text-gray-500">{job.client.address}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${meta.cls}`}>
              {meta.label}
            </span>
            {job.traffic_light && <TrafficLightBadge light={job.traffic_light} />}
          </div>
        </div>

        {job.error_message && (
          <div className="mt-4 bg-red-900/20 border border-red-800 rounded-xl p-3">
            <p className="text-xs text-red-400 font-semibold mb-0.5">Error</p>
            <p className="text-sm text-red-300">{job.error_message}</p>
          </div>
        )}

        {/* Stat grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 pt-5 border-t border-gray-800/60">
          {[
            { label: "Created",         value: job.created_at ? new Date(job.created_at).toLocaleString("en-GB") : "—" },
            { label: "Completed",        value: job.completed_at ? new Date(job.completed_at).toLocaleString("en-GB") : "—" },
            { label: "Lenders Assessed", value: job.lender_results?.length ?? 0 },
            { label: "LOCs Generated",   value: job.lender_results?.filter((r: any) => r.loc_generated).length ?? 0 },
          ].map(({ label, value }) => (
            <div key={label}>
              <p className="text-xs text-gray-500 mb-0.5">{label}</p>
              <p className="text-sm text-white">{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Download outputs */}
      {job.status === "COMPLETE" && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-6">
          <h2 className="text-sm font-semibold text-white mb-3">Download Outputs</h2>
          <div className="flex gap-3 flex-wrap">
            <button
              onClick={downloadAssessment}
              disabled={!job.s3_assessment_key || downloading === "assessment"}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {downloading === "assessment" ? "Opening…" : "Assessment PDF"}
            </button>
            {locsAvailable && (
              <a
                href={getLocsZipUrl(Number(id))}
                download
                className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                All LOCs ZIP ({inScope.filter((r: any) => r.loc_generated).length})
              </a>
            )}
          </div>
        </div>
      )}

      {/* In-scope lenders */}
      {inScope.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-white">In-Scope Lenders</h2>
            <span className="text-xs text-gray-500">— Letters of Claim generated</span>
          </div>
          <div className="space-y-3">
            {inScope.map((r: any) => (
              <div key={r.id} className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
                {/* Lender header */}
                <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800/60">
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-white">{r.lender_name}</h3>
                    <TrafficLightBadge light={r.traffic_light} />
                  </div>
                  <div className="flex items-center gap-2">
                    {r.loc_generated && (
                      <button
                        onClick={() => downloadSingleLoc(r.lender_name)}
                        className="text-xs bg-violet-900/40 border border-violet-800 text-violet-300 hover:bg-violet-900/60 px-3 py-1.5 rounded-lg transition-colors font-semibold"
                      >
                        Download LOC
                      </button>
                    )}
                  </div>
                </div>
                {/* Evidence */}
                <div className="px-5 py-4">
                  {r.evidence_summary && (
                    <p className="text-sm text-gray-300 mb-3 leading-relaxed">
                      {r.evidence_summary.replace(/\s*\(Claim score:\s*\d+(?:\.\d+)?\/\d+\)/g, "")}
                    </p>
                  )}
                  {r.risk_flags && r.risk_flags.length > 0 && (
                    <div className="space-y-1.5">
                      {r.risk_flags.map((f: any, i: number) => (
                        <FlagBadge key={i} flag={f} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No longer trading */}
      {noLongerTrading.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-orange-400">No Longer Trading</h2>
            <span className="text-xs text-gray-600">— Entity dissolved or in administration</span>
          </div>
          <div className="space-y-2">
            {noLongerTrading.map((r: any) => (
              <div key={r.id} className="bg-orange-950/20 border border-orange-900/40 rounded-xl px-5 py-3.5 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <svg className="w-4 h-4 text-orange-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                  </svg>
                  <h3 className="text-sm font-medium text-gray-300">{r.lender_name}</h3>
                </div>
                <p className="text-xs text-orange-400/80 font-medium">No longer trading — no claim can be pursued</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Out-of-scope lenders */}
      {outScope.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-gray-400">Out-of-Scope Lenders</h2>
            <span className="text-xs text-gray-600">— Insufficient evidence to pursue</span>
          </div>
          <div className="space-y-2">
            {outScope.map((r: any) => (
              <div key={r.id} className="bg-gray-900/50 border border-gray-800/60 rounded-xl px-5 py-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-medium text-gray-400">{r.lender_name}</h3>
                  <TrafficLightBadge light={r.traffic_light} />
                </div>
                {r.evidence_summary && (
                  <p className="text-xs text-gray-600 text-right max-w-xs truncate">
                    {r.evidence_summary.replace(/\s*\(Claim score:\s*\d+(?:\.\d+)?\/\d+\)/g, "")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
