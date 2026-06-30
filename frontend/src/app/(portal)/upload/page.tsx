"use client";
import { useRef, useState, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "https://systemize-backend-production.up.railway.app";
// Instructing firm for this portal — Barings deployment sets NEXT_PUBLIC_FIRM=barings.
const FIRM = process.env.NEXT_PUBLIC_FIRM || "first_legal";
const FIRM_LABEL = FIRM === "barings" ? "Barings Law" : "First Legal";

type Stage = "idle" | "uploading" | "processing" | "success" | "error";
type Mode  = "csv" | "zip" | "json" | "pdf";

const MODE_CONFIG: Record<Mode, { label: string; accept: string; description: string; icon: string }> = {
  csv: {
    label:       "CSV of URLs",
    accept:      ".csv",
    description: "CSV file with one report URL per line — one job per row",
    icon:        "📋",
  },
  zip: {
    label:       "ZIP Batch",
    accept:      ".zip",
    description: "ZIP containing multiple JSON or PDF credit report files",
    icon:        "📦",
  },
  json: {
    label:       "JSON Report",
    accept:      ".json",
    description: "Single Equifax or TransUnion bureau partner-post JSON file",
    icon:        "📄",
  },
  pdf: {
    label:       "Single Report File",
    accept:      ".pdf,.html,.htm,.docx,.xlsx",
    description: "One credit report file — PDF, HTML, DOCX or XLSX",
    icon:        "📑",
  },
};

export default function UploadPortalPage() {
  const [stage, setStage]         = useState<Stage>("idle");
  const [mode, setMode]           = useState<Mode>("csv");
  const [batchName, setBatchName] = useState("");
  const [file, setFile]           = useState<File | null>(null);
  const [dragging, setDragging]   = useState(false);
  const [progress, setProgress]   = useState(0);
  const [errorMsg, setErrorMsg]   = useState("");
  const [result, setResult]       = useState<{ batch_id: number; jobs_created: number } | null>(null);
  const fileInputRef              = useRef<HTMLInputElement>(null);

  const acceptFile = (f: File) => {
    setFile(f);
    if (!batchName) setBatchName(f.name.replace(/\.[^.]+$/, "").replace(/[_-]/g, " "));
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) acceptFile(f);
  }, [batchName]);

  function handleModeChange(m: Mode) {
    setMode(m);
    setFile(null);
    setStage("idle");
    setErrorMsg("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const submit = async () => {
    if (!file || !batchName.trim()) return;
    setStage("uploading");
    setProgress(0);
    setErrorMsg("");

    // Pick the correct endpoint
    const endpointMap: Record<Mode, string> = {
      csv:  "/api/v1/upload/csv",
      zip:  "/api/v1/upload/zip",
      json: "/api/v1/upload/file",
      pdf:  "/api/v1/upload/file",
    };
    const endpoint = endpointMap[mode];

    const form = new FormData();
    form.append("file", file);
    form.append("batch_name", batchName.trim());
    form.append("firm", FIRM);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}${endpoint}`);
    xhr.setRequestHeader("bypass-tunnel-reminder", "true");

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        setProgress(pct);
        if (pct === 100) setStage("processing");
      }
    });

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const data = JSON.parse(xhr.responseText);
        setResult({ batch_id: data.batch_id, jobs_created: data.jobs_created ?? 1 });
        setStage("success");
      } else {
        let msg = "Upload failed. Please check the file and try again, or contact Systemize for support.";
        try {
          const parsed = JSON.parse(xhr.responseText);
          if (parsed.detail) msg = parsed.detail;
        } catch {}
        setErrorMsg(msg);
        setStage("error");
      }
    };

    xhr.onerror = () => {
      setErrorMsg("Connection error — unable to reach the server. Please check your internet connection and try again.");
      setStage("error");
    };

    xhr.send(form);
  };

  const reset = () => {
    setStage("idle");
    setFile(null);
    setBatchName("");
    setProgress(0);
    setErrorMsg("");
    setResult(null);
  };

  const cfg = MODE_CONFIG[mode];

  return (
    <>
      <div className="portal-body">
        {/* Header */}
        <header className="portal-header">
          <div className="portal-header-left">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/first-legal-logo.png" alt="First Legal Solicitors" style={{ height: "52px", width: "52px", objectFit: "cover", borderRadius: "6px" }} />
            <div className="portal-divider" />
            <span className="portal-badge">{FIRM_LABEL} · Secure Upload Portal</span>
          </div>
          <div className="portal-lock">
            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            &nbsp;Encrypted
          </div>
        </header>

        {/* Main */}
        <main className="portal-main">
          {stage === "success" && result ? (
            <SuccessView result={result} onReset={reset} />
          ) : (
            <>
              <div className="portal-eyebrow">First Legal Solicitors</div>
              <h1 className="portal-h1">
                Upload <span>Credit Report</span> Batch
              </h1>
              <p className="portal-sub">
                Upload credit bureau data for automated affordability assessment.
                Supports Equifax and TransUnion JSON feeds, ZIP batches, and CSV URL lists.
              </p>

              <div className="portal-card">
                <div className="section-label">Upload Format</div>

                {/* Mode selector */}
                <div style={{ display: "flex", gap: "8px", marginBottom: "20px" }}>
                  {(Object.keys(MODE_CONFIG) as Mode[]).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => handleModeChange(m)}
                      style={{
                        flex: 1,
                        padding: "8px 4px",
                        borderRadius: "8px",
                        border: mode === m ? "1.5px solid #00d4ff" : "1.5px solid rgba(255,255,255,0.08)",
                        background: mode === m ? "rgba(0, 212, 255, 0.08)" : "rgba(255,255,255,0.03)",
                        color: mode === m ? "#00d4ff" : "rgba(255,255,255,0.45)",
                        fontSize: "11px",
                        fontWeight: 600,
                        cursor: "pointer",
                        letterSpacing: "0.04em",
                        textTransform: "uppercase",
                        transition: "all 0.15s",
                      }}
                    >
                      {MODE_CONFIG[m].label}
                    </button>
                  ))}
                </div>

                <div className="section-label">Batch Details</div>

                <div className="field">
                  <label>Batch Reference</label>
                  <input
                    type="text"
                    value={batchName}
                    onChange={(e) => setBatchName(e.target.value)}
                    placeholder="e.g. May 2026 — Week 1"
                  />
                </div>

                <div
                  className={`drop-zone${dragging ? " drag" : ""}${file ? " has-file" : ""}`}
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={cfg.accept}
                    style={{ display: "none" }}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) acceptFile(f); }}
                  />
                  <span className="drop-icon">{file ? cfg.icon : "📁"}</span>
                  {file ? (
                    <>
                      <h3>{file.name}</h3>
                      <p>{(file.size / 1024).toFixed(1)} KB — click to change</p>
                    </>
                  ) : (
                    <>
                      <h3>Drop your {cfg.label} here</h3>
                      <p>{cfg.description} — or click to browse</p>
                    </>
                  )}
                  {file && <div className="file-pill mono">✓ &nbsp;{file.name}</div>}
                </div>

                {(stage === "uploading" || stage === "processing") && (
                  <div className="progress-wrap">
                    <div className="progress-meta">
                      <span className="mono">
                        {stage === "processing" ? "Registering batch…" : "Uploading…"}
                      </span>
                      <span className="mono">
                        {stage === "processing" ? (
                          <span style={{ display: "inline-flex", gap: "3px" }}>
                            <span style={{ animation: "pulse 1.2s ease-in-out infinite", animationDelay: "0s" }}>·</span>
                            <span style={{ animation: "pulse 1.2s ease-in-out infinite", animationDelay: "0.3s" }}>·</span>
                            <span style={{ animation: "pulse 1.2s ease-in-out infinite", animationDelay: "0.6s" }}>·</span>
                          </span>
                        ) : `${progress}%`}
                      </span>
                    </div>
                    <div className="progress-track">
                      <div className="progress-fill" style={{ width: stage === "processing" ? "100%" : `${progress}%`, opacity: stage === "processing" ? 0.6 : 1 }} />
                    </div>
                  </div>
                )}

                {stage === "error" && (
                  <div className="error-box">
                    <p>⚠ &nbsp;{errorMsg}</p>
                  </div>
                )}

                <button
                  className="submit-btn"
                  onClick={submit}
                  disabled={!file || !batchName.trim() || stage === "uploading" || stage === "processing"}
                >
                  {stage === "uploading" ? "Uploading…" : stage === "processing" ? "Please wait…" : "Submit Batch →"}
                </button>
              </div>

              <div className="info-box">
                <h4>Supported formats</h4>
                <ul>
                  <li><strong>JSON</strong> — Single Equifax or TransUnion bureau partner-post file</li>
                  <li><strong>ZIP</strong> — Batch of JSON or PDF report files (one job per file inside)</li>
                  <li><strong>CSV</strong> — One credit report URL per line for bulk processing</li>
                </ul>
                <h4 style={{ marginTop: "12px" }}>What happens next</h4>
                <ul>
                  <li>Reports are parsed and normalised automatically</li>
                  <li>Each client receives a Green / Amber / Red affordability classification</li>
                  <li>Letters of Claim are generated for all qualifying lenders</li>
                  <li>Results appear in the Systemize dashboard within minutes</li>
                </ul>
              </div>
            </>
          )}
        </main>

        {/* Footer */}
        <footer className="portal-footer">
          <p>
            First Legal Solicitors Ltd &nbsp;·&nbsp; SRA 634939 &nbsp;·&nbsp; Company 10381298
            <br />
            8 Princes Parade, Liverpool, L3 1DL
            <br />
            <span style={{ color: "#2a4060" }}>Powered by Systemize Affordability Platform</span>
          </p>
        </footer>
      </div>
    </>
  );
}

function SuccessView({ result, onReset }: { result: { batch_id: number; jobs_created: number }; onReset: () => void }) {
  return (
    <div className="success-wrap">
      <div className="success-icon">
        <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="#00d4ff" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <div className="success-h">Batch Received</div>
      <p className="success-sub">
        Your upload has been received and queued for processing.
      </p>
      <div className="success-ref">
        REF #{result.batch_id} &nbsp;·&nbsp; {result.jobs_created} REPORT{result.jobs_created !== 1 ? "S" : ""} QUEUED
      </div>
      <div className="next-steps">
        <h4>What happens next</h4>
        <ul>
          <li>Credit reports are parsed and analysed automatically</li>
          <li>Affordability assessments are generated for each client</li>
          <li>Letters of Claim are prepared for qualifying cases</li>
          <li>Results appear in the Systemize dashboard within minutes</li>
        </ul>
      </div>
      <button className="reset-link" onClick={onReset}>
        ← Upload another batch
      </button>
    </div>
  );
}
