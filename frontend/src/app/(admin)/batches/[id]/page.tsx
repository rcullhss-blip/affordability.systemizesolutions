"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getBatch, getBatchProgress, getBatchJobs, getTrackerCsvUrl } from "@/lib/api";
import { TrafficLightBadge } from "@/components/ui/TrafficLight";
import { StatCard } from "@/components/dashboard/StatCard";

const STATUS_COLORS: Record<string, string> = {
  COMPLETE: "text-green-400 bg-green-900/20",
  FAILED: "text-red-400 bg-red-900/20",
  PENDING: "text-gray-400 bg-gray-800",
  FETCHING: "text-blue-400 bg-blue-900/20",
  EXTRACTING: "text-blue-400 bg-blue-900/20",
  PARSING: "text-yellow-400 bg-yellow-900/20",
  ANALYSING: "text-yellow-400 bg-yellow-900/20",
  GENERATING: "text-purple-400 bg-purple-900/20",
  DELIVERING: "text-purple-400 bg-purple-900/20",
};

export default function BatchDetailPage() {
  const { id } = useParams();
  const [progress, setProgress] = useState<any>(null);
  const [batch, setBatch] = useState<any>(null);
  const [jobs, setJobs] = useState<any[]>([]);

  const load = () => {
    if (!id) return;
    const n = Number(id);
    getBatchProgress(n).then(setProgress).catch(() => {});
    getBatch(n).then(setBatch).catch(() => {});
    getBatchJobs(n).then(setJobs).catch(() => {});
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [id]);

  const pct = progress?.percent_done ?? 0;
  const isComplete = pct >= 100;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6">
        <Link href="/batches" className="text-gray-500 hover:text-white text-sm transition-colors">
          ← Batches
        </Link>
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-white">{batch?.name ?? "Loading..."}</h2>
            {isComplete && (
              <span className="text-xs font-semibold bg-green-900/40 text-green-400 border border-green-800 px-2.5 py-1 rounded-full">
                Complete
              </span>
            )}
            {!isComplete && progress && (
              <span className="text-xs font-semibold bg-blue-900/40 text-blue-400 border border-blue-800 px-2.5 py-1 rounded-full animate-pulse">
                Processing
              </span>
            )}
          </div>
          <a
            href={getTrackerCsvUrl(Number(id))}
            download
            className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Export Tracker CSV
          </a>
        </div>
        <p className="text-gray-500 text-sm mt-0.5">Batch #{id} · auto-refreshes every 5s</p>
      </div>

      {progress && (
        <>
          {/* Stats row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <StatCard label="Total Reports" value={progress.total} />
            <StatCard label="Complete" value={progress.complete} accent="text-blue-400" />
            <StatCard label="Failed" value={progress.failed} accent="text-red-400" />
            <StatCard label="Progress" value={`${progress.percent_done}%`} />
          </div>

          {/* Progress bar */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
            <div className="flex justify-between text-xs text-gray-500 mb-2">
              <span>{isComplete ? "All reports processed" : "Processing..."}</span>
              <span>{progress.complete} / {progress.total} complete</span>
            </div>
            <div className="w-full bg-gray-800 rounded-full h-2.5">
              <div
                className={`h-2.5 rounded-full transition-all duration-500 ${isComplete ? "bg-green-500" : "bg-blue-600"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          {/* Traffic light results */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-green-900/10 border border-green-900/50 rounded-xl p-5 text-center">
              <p className="text-4xl font-bold text-green-400">{progress.green}</p>
              <p className="text-xs text-gray-400 mt-1.5 font-medium">GREEN</p>
              <p className="text-xs text-gray-600">Strong Claims</p>
            </div>
            <div className="bg-yellow-900/10 border border-yellow-900/50 rounded-xl p-5 text-center">
              <p className="text-4xl font-bold text-yellow-400">{progress.amber}</p>
              <p className="text-xs text-gray-400 mt-1.5 font-medium">AMBER</p>
              <p className="text-xs text-gray-600">Borderline</p>
            </div>
            <div className="bg-red-900/10 border border-red-900/50 rounded-xl p-5 text-center">
              <p className="text-4xl font-bold text-red-400">{progress.red}</p>
              <p className="text-xs text-gray-400 mt-1.5 font-medium">RED</p>
              <p className="text-xs text-gray-600">No Viable Claim</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-8">
            <StatCard label="Assessments Generated" value={progress.assessments} accent="text-blue-400" />
            <StatCard label="LOCs Generated" value={progress.locs} accent="text-blue-400" />
          </div>
        </>
      )}

      {/* Jobs table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800">
          <h3 className="text-base font-semibold text-white">Individual Jobs</h3>
          <p className="text-xs text-gray-500 mt-0.5">{jobs.length} report(s) in this batch</p>
        </div>
        {jobs.length === 0 ? (
          <div className="p-6 text-gray-500 text-sm">No jobs yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-left text-xs uppercase tracking-wider">
                  <th className="px-5 py-3">#</th>
                  <th className="px-5 py-3">Client</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Result</th>
                  <th className="px-5 py-3">Lenders</th>
                  <th className="px-5 py-3">LOCs</th>
                  <th className="px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {jobs.map((job) => {
                  const locsCount = job.lender_results?.filter((r: any) => r.loc_generated).length ?? 0;
                  const statusCls = STATUS_COLORS[job.status] ?? "text-gray-400 bg-gray-800";
                  return (
                    <tr key={job.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="px-5 py-3 text-gray-500 text-xs font-mono">{job.id}</td>
                      <td className="px-5 py-3">
                        {job.client ? (
                          <div>
                            <Link
                              href={`/clients/${job.client.matter_ref}`}
                              className="font-medium text-white hover:text-blue-400 transition-colors"
                            >
                              {job.client.name}
                            </Link>
                            <p className="text-xs text-gray-500">{job.client.matter_ref}</p>
                          </div>
                        ) : (
                          <span className="text-gray-600 text-xs italic">Pending parse...</span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${statusCls}`}>
                          {job.status}
                        </span>
                        {job.error_message && (
                          <p className="text-xs text-red-400 mt-1 max-w-xs truncate" title={job.error_message}>
                            {job.error_message}
                          </p>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        {job.traffic_light ? (
                          <TrafficLightBadge light={job.traffic_light} />
                        ) : (
                          <span className="text-gray-600 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-gray-300">
                        {job.lender_results?.length ?? 0}
                      </td>
                      <td className="px-5 py-3 text-gray-300">{locsCount}</td>
                      <td className="px-5 py-3">
                        <Link
                          href={`/jobs/${job.id}`}
                          className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
                        >
                          View →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
