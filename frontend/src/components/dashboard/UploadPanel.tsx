"use client";
import { useState, useRef } from "react";
import { uploadFile, uploadZip, uploadCsv } from "@/lib/api";

type Mode = "file" | "zip" | "csv";

const MODE_CONFIG: Record<Mode, { label: string; accept: string; hint: string }> = {
  file: {
    label: "Single Report",
    accept: ".pdf,.html,.htm,.docx,.xlsx",
    hint: "PDF, HTML, DOCX, or XLSX credit report",
  },
  zip: {
    label: "ZIP of Reports",
    accept: ".zip",
    hint: "ZIP containing multiple credit reports — one job per file",
  },
  csv: {
    label: "CSV of URLs",
    accept: ".csv",
    hint: "CSV with one report URL per line (for bulk imports)",
  },
};

interface Props {
  onSuccess?: () => void;
}

export function UploadPanel({ onSuccess }: Props) {
  const [batchName, setBatchName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<Mode>("file");
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [result, setResult] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const cfg = MODE_CONFIG[mode];

  function handleModeChange(m: Mode) {
    setMode(m);
    setFile(null);
    setStatus("idle");
    setResult(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !batchName.trim()) return;
    setStatus("uploading");
    setErrorMsg("");
    try {
      let data: any;
      if (mode === "zip") data = await uploadZip(file, batchName.trim());
      else if (mode === "csv") data = await uploadCsv(file, batchName.trim());
      else data = await uploadFile(file, batchName.trim());
      setResult(data);
      setStatus("done");
      setBatchName("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onSuccess?.();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail ?? "Upload failed. Check the file and try again.");
      setStatus("error");
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <h2 className="text-base font-semibold text-white mb-4">Upload Reports</h2>
      <form onSubmit={handleSubmit} className="space-y-4">

        {/* Mode selector */}
        <div>
          <label className="block text-xs text-gray-400 mb-2">Upload Type</label>
          <div className="flex gap-1.5">
            {(Object.keys(MODE_CONFIG) as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => handleModeChange(m)}
                className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  mode === m
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white"
                }`}
              >
                {MODE_CONFIG[m].label}
              </button>
            ))}
          </div>
        </div>

        {/* Batch name */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Batch Name</label>
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500 transition-colors"
            placeholder="e.g. June 2025 Batch 1"
            value={batchName}
            onChange={(e) => setBatchName(e.target.value)}
            required
          />
        </div>

        {/* File picker */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">{cfg.hint}</label>
          <div
            onClick={() => fileRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-5 text-center cursor-pointer transition-colors ${
              file
                ? "border-blue-600 bg-blue-950/20"
                : "border-gray-700 hover:border-blue-500 hover:bg-gray-800/40"
            }`}
          >
            {file ? (
              <div>
                <p className="text-sm text-blue-400 font-medium">{file.name}</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </div>
            ) : (
              <div>
                <svg className="w-6 h-6 text-gray-600 mx-auto mb-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <p className="text-sm text-gray-500">Click to select file</p>
              </div>
            )}
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept={cfg.accept}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={status === "uploading" || !file || !batchName.trim()}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg text-sm transition-colors"
        >
          {status === "uploading" ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Uploading...
            </span>
          ) : "Upload & Process"}
        </button>

        {status === "done" && result && (
          <div className="bg-green-900/30 border border-green-800 rounded-lg p-3 text-sm text-green-400">
            <p className="font-medium">Queued successfully</p>
            <p className="text-xs text-green-500 mt-0.5">
              {result.jobs_created ?? 1} job(s) created · Batch #{result.batch_id}
            </p>
          </div>
        )}

        {status === "error" && (
          <div className="bg-red-900/30 border border-red-800 rounded-lg p-3 text-sm text-red-400">
            {errorMsg}
          </div>
        )}
      </form>
    </div>
  );
}
