"use client";
import { useRef, useState, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Stage = "idle" | "uploading" | "success" | "error";

export default function UploadPortalPage() {
  const [stage, setStage] = useState<Stage>("idle");
  const [batchName, setBatchName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const [result, setResult] = useState<{ batch_id: number; jobs_created: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const submit = async () => {
    if (!file || !batchName.trim()) return;
    setStage("uploading");
    setProgress(0);

    const form = new FormData();
    form.append("file", file);
    form.append("batch_name", batchName.trim());

    const name = file.name.toLowerCase();
    const isZip = name.endsWith(".zip");
    const endpoint = isZip ? "/api/v1/upload/zip" : "/api/v1/upload/file";

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}${endpoint}`);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100));
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

  return (
    <>
      <div className="portal-body">
        {/* Header */}
        <header className="portal-header">
          <div className="portal-header-left">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/first-legal-logo.png" alt="First Legal Solicitors" style={{ height: "52px", width: "52px", objectFit: "cover", borderRadius: "6px" }} />
            <div className="portal-divider" />
            <span className="portal-badge">Secure Upload Portal</span>
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
                Submit a ZIP file containing client credit reports. Each report
                will be automatically assessed and a Letter of Claim generated where applicable.
              </p>

              <div className="portal-card">
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
                    accept=".zip,.pdf,.html,.htm,.docx,.xlsx"
                    style={{ display: "none" }}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) acceptFile(f); }}
                  />
                  <span className="drop-icon">{file ? "📄" : "📁"}</span>
                  {file ? (
                    <>
                      <h3>{file.name}</h3>
                      <p>{(file.size / 1024 / 1024).toFixed(2)} MB — click to change</p>
                    </>
                  ) : (
                    <>
                      <h3>Drop your file here</h3>
                      <p>ZIP · PDF · HTML · DOCX · XLSX — or click to browse</p>
                    </>
                  )}
                  {file && <div className="file-pill mono">✓ &nbsp;{file.name}</div>}
                </div>

                {stage === "uploading" && (
                  <div className="progress-wrap">
                    <div className="progress-meta">
                      <span className="mono">Uploading…</span>
                      <span className="mono">{progress}%</span>
                    </div>
                    <div className="progress-track">
                      <div className="progress-fill" style={{ width: `${progress}%` }} />
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
                  disabled={!file || !batchName.trim() || stage === "uploading"}
                >
                  {stage === "uploading" ? "Uploading…" : "Submit Batch →"}
                </button>
              </div>

              <div className="info-box">
                <h4>Accepted Formats</h4>
                <ul>
                  <li>ZIP containing multiple credit report files (recommended for batches)</li>
                  <li>Individual PDF, HTML, DOCX or XLSX credit report exports</li>
                  <li>Boshhh, Experian, Equifax and TransUnion formats supported</li>
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
          <li>You will be contacted when results are ready to review</li>
        </ul>
      </div>
      <button className="reset-link" onClick={onReset}>
        ← Upload another batch
      </button>
    </div>
  );
}
