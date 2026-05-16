"use client";
import Link from "next/link";

interface Batch {
  id: number;
  name: string;
  created_at: string;
  total_reports: number;
  processed: number;
  green_count: number;
  amber_count: number;
  red_count: number;
  locs_generated: number;
}

export function BatchTable({ batches }: { batches: Batch[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-gray-500 text-left">
            <th className="pb-3 pr-4">Batch</th>
            <th className="pb-3 pr-4">Reports</th>
            <th className="pb-3 pr-4">Processed</th>
            <th className="pb-3 pr-4">Green</th>
            <th className="pb-3 pr-4">Amber</th>
            <th className="pb-3 pr-4">Red</th>
            <th className="pb-3 pr-4">LOCs</th>
            <th className="pb-3">Date</th>
          </tr>
        </thead>
        <tbody>
          {batches.map((b) => (
            <tr key={b.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
              <td className="py-3 pr-4">
                <Link href={`/batches/${b.id}`} className="text-blue-400 hover:underline font-medium">
                  {b.name}
                </Link>
              </td>
              <td className="py-3 pr-4 text-gray-300">{b.total_reports}</td>
              <td className="py-3 pr-4 text-gray-300">{b.processed}</td>
              <td className="py-3 pr-4 text-green-400 font-semibold">{b.green_count}</td>
              <td className="py-3 pr-4 text-yellow-400 font-semibold">{b.amber_count}</td>
              <td className="py-3 pr-4 text-red-400 font-semibold">{b.red_count}</td>
              <td className="py-3 pr-4 text-gray-300">{b.locs_generated}</td>
              <td className="py-3 text-gray-500 text-xs">
                {new Date(b.created_at).toLocaleDateString("en-GB")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
