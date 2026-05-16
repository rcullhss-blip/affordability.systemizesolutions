"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { StatCard } from "@/components/dashboard/StatCard";
import { BatchTable } from "@/components/dashboard/BatchTable";
import { UploadPanel } from "@/components/dashboard/UploadPanel";
import { getBatches, getAnalyticsSummary } from "@/lib/api";

export default function DashboardPage() {
  const [batches, setBatches] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const reload = () => {
    Promise.all([getBatches(), getAnalyticsSummary()])
      .then(([b, s]) => {
        setBatches(b);
        setSummary(s);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    reload();
    const iv = setInterval(reload, 10000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Dashboard</h2>
          <p className="text-gray-500 text-sm mt-1">Live processing overview</p>
        </div>
        <Link
          href="/batches"
          className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
        >
          View all batches →
        </Link>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        <StatCard label="Total Assessments" value={summary?.total_assessments ?? "—"} />
        <StatCard label="Green" value={summary?.green ?? "—"} accent="text-green-400" />
        <StatCard label="Amber" value={summary?.amber ?? "—"} accent="text-yellow-400" />
        <StatCard label="Red" value={summary?.red ?? "—"} accent="text-red-400" />
        <StatCard label="LOCs Generated" value={summary?.locs_generated ?? "—"} accent="text-blue-400" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 bg-gray-900 border border-gray-800 rounded-xl p-6">
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
