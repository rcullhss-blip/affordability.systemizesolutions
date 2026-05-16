"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { StatCard } from "@/components/dashboard/StatCard";
import { BatchTable } from "@/components/dashboard/BatchTable";
import { UploadPanel } from "@/components/dashboard/UploadPanel";
import { getBatches, getAnalyticsSummary, getSpotChecks, markSpotCheckReviewed, getOpenFeedback, resolveFeedback } from "@/lib/api";

function SpotCheckBanner({ checks, onDismiss }: { checks: any[]; onDismiss: (id: number) => void }) {
  if (!checks.length) return null;
  return (
    <div className="mb-6 bg-amber-900/20 border border-amber-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <svg className="w-5 h-5 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        </svg>
        <p className="text-sm font-semibold text-amber-400">
          {checks.length} Job{checks.length > 1 ? "s" : ""} Flagged for Spot Check
        </p>
      </div>
      <div className="space-y-2">
        {checks.map((c) => (
          <div key={c.id} className="flex items-center justify-between gap-4 bg-amber-950/30 rounded-lg px-3 py-2">
            <div className="flex items-center gap-3 min-w-0">
              <Link href={`/jobs/${c.id}`} className="text-sm font-medium text-white hover:text-amber-300 truncate">
                {c.client_name}
              </Link>
              {c.matter_ref && <span className="text-xs text-gray-500 font-mono shrink-0">{c.matter_ref}</span>}
              {c.traffic_light && (
                <span className={`text-xs font-bold shrink-0 ${
                  c.traffic_light === "GREEN" ? "text-green-400" :
                  c.traffic_light === "AMBER" ? "text-amber-400" : "text-red-400"
                }`}>{c.traffic_light}</span>
              )}
            </div>
            <button
              onClick={() => onDismiss(c.id)}
              className="text-xs bg-amber-700/40 hover:bg-amber-700/60 text-amber-200 px-3 py-1 rounded-lg transition-colors shrink-0 font-medium"
            >
              Mark Reviewed
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [batches, setBatches] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [spotChecks, setSpotChecks] = useState<any[]>([]);
  const [openFeedback, setOpenFeedback] = useState<any[]>([]);

  const reload = () => {
    Promise.all([getBatches(), getAnalyticsSummary(), getSpotChecks(), getOpenFeedback()])
      .then(([b, s, sc, fb]) => {
        setBatches(b);
        setSummary(s);
        setSpotChecks(sc);
        setOpenFeedback(fb);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  const dismissSpotCheck = async (jobId: number) => {
    await markSpotCheckReviewed(jobId);
    setSpotChecks((prev) => prev.filter((c) => c.id !== jobId));
  };

  useEffect(() => {
    reload();
    const iv = setInterval(reload, 10000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="p-4 md:p-8">
      <div className="mb-6 md:mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-xl md:text-2xl font-bold text-white">Dashboard</h2>
          <p className="text-gray-500 text-sm mt-1">Live processing overview</p>
        </div>
        <Link href="/batches" className="text-sm text-blue-400 hover:text-blue-300 transition-colors">
          View all →
        </Link>
      </div>

      <SpotCheckBanner checks={spotChecks} onDismiss={dismissSpotCheck} />

      {openFeedback.length > 0 && (
        <div className="mb-6 bg-red-900/20 border border-red-800 rounded-xl p-4">
          <p className="text-sm font-semibold text-red-400 mb-3">
            ⚠ {openFeedback.length} Open Issue{openFeedback.length > 1 ? "s" : ""} Flagged
          </p>
          <div className="space-y-2">
            {openFeedback.map((f: any) => (
              <div key={f.id} className="flex items-start justify-between gap-4 bg-red-950/30 rounded-lg px-3 py-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <Link href={`/jobs/${f.job_id}`} className="text-sm font-medium text-white hover:text-red-300">{f.client_name}</Link>
                    {f.matter_ref && <span className="text-xs text-gray-500 font-mono">{f.matter_ref}</span>}
                  </div>
                  <p className="text-xs text-gray-400 truncate">{f.note}</p>
                </div>
                <button
                  onClick={async () => { await resolveFeedback(f.id); setOpenFeedback(prev => prev.filter(x => x.id !== f.id)); }}
                  className="text-xs bg-red-800/40 hover:bg-red-800/60 text-red-200 px-3 py-1 rounded-lg transition-colors shrink-0 font-medium"
                >
                  Resolved
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 md:gap-4 mb-6 md:mb-8">
        <StatCard label="Total Assessments" value={summary?.total_assessments ?? "—"} />
        <StatCard label="Green"             value={summary?.green ?? "—"}             accent="text-green-400" />
        <StatCard label="Amber"             value={summary?.amber ?? "—"}             accent="text-yellow-400" />
        <StatCard label="Red"               value={summary?.red ?? "—"}               accent="text-red-400" />
        <StatCard label="LOCs Generated"    value={summary?.locs_generated ?? "—"}    accent="text-blue-400" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 md:gap-6">
        <div className="xl:col-span-2 bg-gray-900 border border-gray-800 rounded-xl p-4 md:p-6">
          <h3 className="text-base font-semibold text-white mb-4">Recent Batches</h3>
          {loading ? (
            <p className="text-gray-500 text-sm">Loading...</p>
          ) : batches.length === 0 ? (
            <p className="text-gray-500 text-sm">No batches yet. Upload your first batch to get started.</p>
          ) : (
            <BatchTable batches={batches.slice(0, 10)} />
          )}
        </div>
        <UploadPanel onSuccess={reload} />
      </div>
    </div>
  );
}
