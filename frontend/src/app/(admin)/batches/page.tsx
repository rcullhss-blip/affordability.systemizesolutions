"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getBatches, getTrackerCsvUrl } from "@/lib/api";
import { UploadPanel } from "@/components/dashboard/UploadPanel";

function StatusDot({ pct }: { pct: number }) {
  const color = pct >= 100 ? "bg-green-400" : pct > 0 ? "bg-yellow-400 animate-pulse" : "bg-gray-600";
  return <span className={`inline-block w-2 h-2 rounded-full ${color} mr-2`} />;
}

function DownloadIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
    </svg>
  );
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);

  const load = () =>
    getBatches()
      .then(setBatches)
      .catch(() => {})
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Batches</h2>
          <p className="text-gray-500 text-sm mt-1">All uploaded batches — auto-refreshes every 8s</p>
        </div>
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
        >
          + New Upload
        </button>
      </div>

      {showUpload && (
        <div className="mb-6 max-w-md">
          <UploadPanel onSuccess={() => { setShowUpload(false); load(); }} />
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500 text-sm">Loading...</div>
        ) : batches.length === 0 ? (
          <div className="p-8 text-center text-gray-500 text-sm">No batches yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-left text-xs uppercase tracking-wider">
                  <th className="px-5 py-3">Batch</th>
                  <th className="px-5 py-3">Total</th>
                  <th className="px-5 py-3 text-green-400">Green</th>
                  <th className="px-5 py-3 text-yellow-400">Amber</th>
                  <th className="px-5 py-3 text-red-400">Red</th>
                  <th className="px-5 py-3">LOCs</th>
                  <th className="px-5 py-3">Progress</th>
                  <th className="px-5 py-3">Date</th>
                  <th className="px-5 py-3">Export</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {batches.map((b) => {
                  const done = (b.processed ?? 0) + (b.failed ?? 0);
                  const pct = b.total_reports > 0
                    ? Math.min(100, Math.round((done / b.total_reports) * 100))
                    : 0;
                  return (
                    <tr key={b.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="px-5 py-3">
                        <Link
                          href={`/batches/${b.id}`}
                          className="font-medium text-blue-400 hover:text-blue-300 hover:underline flex items-center"
                        >
                          <StatusDot pct={pct} />
                          {b.name}
                        </Link>
                        <p className="text-gray-600 text-xs pl-4">#{b.id}</p>
                      </td>
                      <td className="px-5 py-3 text-gray-300">{b.total_reports}</td>
                      <td className="px-5 py-3 text-green-400 font-semibold">{b.green_count}</td>
                      <td className="px-5 py-3 text-yellow-400 font-semibold">{b.amber_count}</td>
                      <td className="px-5 py-3 text-red-400 font-semibold">{b.red_count}</td>
                      <td className="px-5 py-3 text-gray-300">{b.locs_generated}</td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-20 bg-gray-800 rounded-full h-1.5">
                            <div
                              className="bg-blue-500 h-1.5 rounded-full transition-all"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="text-gray-400 text-xs">{pct}%</span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-gray-500 text-xs">
                        {new Date(b.created_at).toLocaleDateString("en-GB")}
                      </td>
                      <td className="px-5 py-3">
                        <a
                          href={getTrackerCsvUrl(b.id)}
                          download
                          title="Download Proclaim tracker CSV"
                          className="inline-flex items-center gap-1.5 bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-700/50 text-emerald-400 hover:text-emerald-300 text-xs font-semibold px-2.5 py-1.5 rounded-md transition-colors whitespace-nowrap"
                        >
                          <DownloadIcon />
                          Tracker CSV
                        </a>
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
