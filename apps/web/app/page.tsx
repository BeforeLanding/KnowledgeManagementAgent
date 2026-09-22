"use client";

import { FormEvent, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Space = { id: string; name: string; description: string; role: string };
type Doc = { id: string; space_id: string; filename: string; status: string; version: number; created_at: string };
type Citation = { document_id: string; chunk_id: string; filename: string; locator: string; snippet: string };
type Trace = { id: string; query: string; status: string; answer: string; latency_ms: number; trace: unknown[]; citations: Citation[] };
type EvaluationSuite = { name: string; version: string; description: string; data_classification: string };
type EvaluationRun = { id: string; suite: string; version: string; status: string; total: number; passed: number; gate_passed: boolean | null; metrics: Record<string, number>; safe_summary: string; started_at: string };
type EvaluationResult = { suite: string; version: string; total: number; passed: number; run_id: string; metrics: Record<string, number>; results: { case_id: string; passed: boolean; latency_ms: number; error_category: string | null; safe_summary: string }[] };

async function request(path: string, token: string, init?: RequestInit) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), Authorization: `Bearer ${token}`, ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.message || body.detail || "Request failed");
  return body;
}

export default function Home() {
  const [token, setToken] = useState("");
  const [tab, setTab] = useState<"chat" | "knowledge" | "evaluation">("chat");
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [evaluationSuites, setEvaluationSuites] = useState<EvaluationSuite[]>([]);
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRun[]>([]);
  const [query, setQuery] = useState("What is the latest documented shipment status?");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [evalResult, setEvalResult] = useState<EvaluationResult | null>(null);

  async function load(accessToken = token) {
    if (!accessToken) return;
    const [spaceData, documentData, traceData, suiteData, runData] = await Promise.all([
      request("/api/v1/spaces", accessToken), request("/api/v1/documents", accessToken), request("/api/v1/traces", accessToken), request("/api/v1/evaluations/suites", accessToken), request("/api/v1/evaluations/runs", accessToken),
    ]);
    setSpaces(spaceData); setDocuments(documentData); setTraces(traceData); setEvaluationSuites(suiteData); setEvaluationRuns(runData);
  }

  useEffect(() => {
    const saved = sessionStorage.getItem("kma-token") || "";
    setToken(saved);
    if (saved) load(saved).catch((e) => setError(e.message));
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError("");
    const data = new FormData(event.currentTarget);
    try {
      const response = await fetch(`${API}/api/v1/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: data.get("email"), password: data.get("password") }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || "Login failed");
      sessionStorage.setItem("kma-token", body.access_token); setToken(body.access_token); await load(body.access_token);
    } catch (e) { setError(e instanceof Error ? e.message : "Login failed"); }
  }

  async function ask() {
    setBusy(true); setError("");
    try {
      const result = await request("/api/v1/chat", token, { method: "POST", body: JSON.stringify({ query }) });
      setAnswer(result.answer); setCitations(result.citations); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Question failed"); } finally { setBusy(false); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try { await request("/api/v1/documents", token, { method: "POST", body: form }); await load(); event.currentTarget.reset(); }
    catch (e) { setError(e instanceof Error ? e.message : "Upload failed"); } finally { setBusy(false); }
  }

  if (!token) return (
    <main className="login-shell">
      <form className="login-card" onSubmit={login}>
        <div className="mark">K</div><h1>Knowledge Management Agent</h1><p>Grounded answers. Visible evidence. Measurable quality.</p>
        <label>Email<input name="email" defaultValue="admin@example.com" /></label>
        <label>Password<input name="password" type="password" defaultValue="Admin123!" /></label>
        <button>Sign in to workspace</button>{error && <div className="error">{error}</div>}
      </form>
    </main>
  );

  return (
    <main className="shell">
      <aside><div className="brand"><span>K</span><div>Knowledge<br/><small>Management Agent</small></div></div>
        <nav>{(["chat", "knowledge", "evaluation"] as const).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "chat" ? "Ask knowledge" : item === "knowledge" ? "Knowledge base" : "Evaluation & traces"}</button>)}</nav>
        <div className="sidebar-foot"><b>{spaces.length}</b> knowledge spaces<br/><button onClick={() => { sessionStorage.clear(); setToken(""); }}>Sign out</button></div>
      </aside>
      <section className="content">
        <header><div><span className="eyebrow">ENTERPRISE KNOWLEDGE</span><h1>{tab === "chat" ? "Ask with confidence" : tab === "knowledge" ? "Knowledge library" : "Quality control"}</h1></div><span className="health">● System ready</span></header>
        {error && <div className="error banner">{error}</div>}
        {tab === "chat" && <div className="chat-layout"><section className="panel question-panel"><label>Question</label><textarea value={query} onChange={(e) => setQuery(e.target.value)} /><button disabled={busy} onClick={ask}>{busy ? "Searching…" : "Search & answer"}</button><div className="hint">The agent searches only spaces you can access and refuses unsupported claims.</div></section><section className="panel answer-panel"><div className="panel-title">Grounded answer</div><p>{answer || "Your answer will appear here with document-level evidence."}</p>{citations.map((citation, i) => <details key={citation.chunk_id}><summary>[{i + 1}] {citation.filename} · {citation.locator}</summary><p>{citation.snippet}</p></details>)}</section></div>}
        {tab === "knowledge" && <><form className="panel upload" onSubmit={upload}><select name="space_id" required>{spaces.filter((s) => s.role !== "viewer").map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><input name="file" type="file" required accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.eml"/><button disabled={busy}>Upload document</button></form><div className="grid">{spaces.map((space) => <section className="panel" key={space.id}><div className="panel-title">{space.name}<span className="pill">{space.role}</span></div><p>{space.description}</p>{documents.filter((d) => d.space_id === space.id).map((doc) => <div className="doc" key={doc.id}><span>{doc.filename}<small>v{doc.version}</small></span><b className={`status ${doc.status}`}>{doc.status}</b></div>)}</section>)}</div></>}
        {tab === "evaluation" && <div className="eval-layout"><section className="panel"><div className="panel-title">Regression gate</div><p>Run the bounded, deterministic smoke suite with the Fake Provider.</p><button disabled={busy} onClick={async () => { setBusy(true); setError(""); try { const result = await request("/api/v1/evaluations/smoke", token, { method: "POST" }); setEvalResult(result); await load(); } catch (e) { setError(e instanceof Error ? e.message : "Evaluation failed"); } finally { setBusy(false); } }}>{busy ? "Running…" : "Run smoke suite"}</button>{evalResult && <><div className="score"><b>{evalResult.passed}/{evalResult.total}</b><span>cases passed · v{evalResult.version}</span></div><div className="metrics">{Object.entries(evalResult.metrics).sort(([a], [b]) => a.localeCompare(b)).map(([name, value]) => <span key={name}>{name}: {(value * 100).toFixed(1)}%</span>)}</div>{evalResult.results.filter((item) => !item.passed).map((item) => <div className="eval-failure" key={item.case_id}><b>{item.case_id}</b><span>{item.safe_summary}</span></div>)}</>}</section><section className="panel traces"><div className="panel-title">Suites</div>{evaluationSuites.map((suite) => <div className="doc" key={`${suite.name}-${suite.version}`}><span>{suite.name}<small>{suite.description}</small></span><b className="pill">v{suite.version}</b></div>)}<div className="panel-title eval-heading">Recent evaluation runs</div>{evaluationRuns.map((run) => <details key={run.id}><summary><span>{run.suite} · v{run.version}</span><b>{run.passed}/{run.total}</b></summary><p>{run.safe_summary}</p></details>)}<div className="panel-title eval-heading">Recent traces</div>{traces.map((trace) => <details key={trace.id}><summary><span>{trace.query}</span><b>{trace.status} · {trace.latency_ms}ms</b></summary><pre>{JSON.stringify(trace.trace, null, 2)}</pre></details>)}</section></div>}
      </section>
    </main>
  );
}
