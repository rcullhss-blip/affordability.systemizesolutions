"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getClientJobs } from "@/lib/api";
import { TrafficLightBadge } from "@/components/ui/TrafficLight";

const STATUS_COLORS: Record<string, string> = {
  COMPLETE: "text-green-400 bg-green-900/20 border-green-800",
  FAILED: "text-red-400 bg-red-900/20 border-red-800",
  PENDING: "text-gray-400 bg-gray-800 border-gray-700",
  FETCHING: "text-blue-400 bg-blue-900/20 border-blue-800",
  PARSING: "text-yellow-400 bg-yellow-900/20 border-yellow-800",
  ANALYSING: "text-yellow-400 bg-yellow-900/20 border-yellow-800",
  GENERATING: "text-purple-400 bg-purple-900/20 border-purple-800",
};

export default function ClientDetailPage() {
  const { matter_ref } = useParams();
  const ref = decodeURIComponent(matter_ref as string);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ref) return;
    getClientJobs(ref)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [ref]);

  const client = data?.client;
  const jobs: any[] = data?.jobs ?? [];

  const greenLenders = jobs.flatMap((j: any) =>
    (j.lender_results ?? []).filter((r: any) => r.traffic_light === "GREEN")
  );
  const amberLenders = jobs.flatMap((j: any) =>
    (j.lender_results ?? []).filter((r: any) => r.traffic_light === "AMBER")
  );
  const allLocs = jobs.flatMap((j: any) =>
    (j.lender_results ?? []).filter((r: any) => r.loc_generated)
  );

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-2 text-sm text-gray-500">
        <Link href="/clients" className="hover:text-white transition-colors">Clients</Link>
        <span className="mx-2">/</span>
        <span className="text-gray-400">{ref}</span>
      </div>

      {loading ? (
        <p className="text-gray-500 text-sm mt-8">Loading...</p>
      ) : !client ? (
        <p className="text-red-400 text-sm mt-8">Client not found.</p>
      ) : (
        <>
          {/* Client header */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h2 className="text-2xl font-bold text-white">{client.name}</h2>
                <p className="text-gray-500 text-sm mt-0.5 font-mono">{client.matter_ref}</p>
              </div>
              <div className="flex gap-4 text-sm">
                <div className="text-right">
                  <p className="text-gray-500 text-xs">Date of Birth</p>
                  <p className="text-white">{client.dob ? new Date(client.dob).toLocaleDateString("en-GB") : "—"}</p>
                </div>
                <div className="text-right">
                  <p className="text-gray-500 text-xs">Reports</p>
                  <p className="text-white font-bold">{jobs.length}</p>
                </div>
              </div>
            </div>

            {client.address && (
              <p className="text-gray-400 text-sm mt-3">{client.address}</p>
            )}

            {/* Quick stats */}
            <div className="grid grid-cols-4 gap-4 mt-5 pt-5 border-t border-gray-800">
              <div className="text-center">
                <p className="text-2xl font-bold text-green-400">{greenLenders.length}</p>
                <p className="text-xs text-gray-500 mt-0.5">Strong Claims</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-yellow-400">{amberLenders.length}</p>
                <p className="text-xs text-gray-500 mt-0.5">Borderline</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-blue-400">{allLocs.length}</p>
                <p className="text-xs text-gray-500 mt-0.5">LOCs Generated</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-white">{jobs.length}</p>
                <p className="text-xs text-gray-500 mt-0.5">Total Jobs</p>
              </div>
            </div>
          </div>

          {/* Jobs list */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800">
              <h3 className="text-base font-semibold text-white">Assessment History</h3>
            </div>
            {jobs.length === 0 ? (
              <div className="p-6 text-gray-500 text-sm">No jobs found for this client.</div>
            ) : (
              <div className="divide-y divide-gray-800/60">
                {jobs.map((job: any) => {
                  const locsCount = (job.lender_results ?? []).filter((r: any) => r.loc_generated).length;
                  const statusCls = STATUS_COLORS[job.status] ?? "text-gray-400 bg-gray-800 border-gray-700";
                  return (
                    <div key={job.id} className="px-5 py-4 hover:bg-gray-800/20 transition-colors">
                      <div className="flex items-start justify-between gap-4 flex-wrap">
                        <div>
                          <div className="flex items-center gap-3 flex-wrap mb-1.5">
                            <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold border ${statusCls}`}>
                              {job.status}
                            </span>
                            {job.traffic_light && <TrafficLightBadge light={job.traffic_light} />}
                          </div>
                          <div className="text-xs text-gray-500 flex gap-3 flex-wrap">
                            <span>Job #{job.id}</span>
                            {job.batch_id && (
                              <Link href={`/batches/${job.batch_id}`} className="hover:text-blue-400 transition-colors">
                                Batch #{job.batch_id}
                              </Link>
                            )}
                            <span>{job.created_at ? new Date(job.created_at).toLocaleString("en-GB") : "—"}</span>
                          </div>

                          {/* Lender summary */}
                          {job.lender_results && job.lender_results.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-2">
                              {job.lender_results.map((r: any) => (
                                <span
                                  key={r.id}
                                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                    r.traffic_light === "GREEN"
                                      ? "bg-green-900/30 text-green-400 border border-green-800"
                                      : r.traffic_light === "AMBER"
                                      ? "bg-yellow-900/30 text-yellow-400 border border-yellow-800"
                                      : "bg-red-900/30 text-red-400 border border-red-800"
                                  }`}
                                >
                                  {r.lender_name}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-3 text-right">
                          {locsCount > 0 && (
                            <span className="text-xs text-purple-400 font-medium">{locsCount} LOC(s)</span>
                          )}
                          <Link
                            href={`/jobs/${job.id}`}
                            className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
                          >
                            View details →
                          </Link>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
