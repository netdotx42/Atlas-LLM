import { useCallback, useEffect, useState } from "react"
import { api, type Dataset, type Draft, type ModelStatus, type ProfileColumn, type QualityIssue } from "./api"

type Tab = "profile" | "ask" | "sql" | "pipeline" | "model"

const TABS: { id: Tab; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "ask", label: "Ask" },
  { id: "sql", label: "SQL" },
  { id: "pipeline", label: "Pipeline" },
  { id: "model", label: "Model" },
]

export function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [model, setModel] = useState<ModelStatus | null>(null)
  const [error, setError] = useState("")
  const [tab, setTab] = useState<Tab>("profile")

  const refresh = useCallback(async () => {
    const [listed, status] = await Promise.all([api.datasets(), api.model()])
    setDatasets(listed.datasets)
    setModel(status)
    setSelected((current) => current ?? listed.datasets[0]?.id ?? null)
  }, [])

  useEffect(() => {
    refresh().catch((reason: Error) => setError(reason.message))
  }, [refresh])

  const current = datasets.find((item) => item.id === selected) ?? null

  async function run(task: () => Promise<unknown>) {
    setError("")
    try {
      await task()
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed")
    }
  }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="mark">
          <h1>ATLAS</h1>
          <span>LOCAL</span>
        </div>
        <p className="note">
          Profiles stay on this machine. The model may draft a request. It cannot run one.
        </p>
        <div className="stack">
          <button className="action" onClick={() => run(() => api.sample())}>
            Load sample orders
          </button>
          <Upload onFile={(file) => run(() => api.upload(file.name.replace(/\.[^.]+$/, ""), file))} />
          {datasets.map((item) => (
            <button
              key={item.id}
              className={item.id === selected ? "dataset active" : "dataset"}
              onClick={() => setSelected(item.id)}
            >
              {item.name}
              <small>
                {item.row_count} rows · {item.source_kind}
                {item.parent_id ? " · derived" : ""}
              </small>
            </button>
          ))}
        </div>
      </aside>
      <main className="main">
        {error ? <p className="err">{error}</p> : null}
        {!current ? (
          <section className="banner">
            <strong>No dataset yet.</strong>
            <p className="note">Load the sample or drop a CSV or Parquet file.</p>
          </section>
        ) : (
          <>
            <header className="head">
              <h2>{current.name}</h2>
              <p className="meta">
                {current.row_count} rows · {current.column_count} columns · {current.source_kind}
              </p>
            </header>
            <nav className="tabs">
              {TABS.map((item) => (
                <button key={item.id} className={tab === item.id ? "tab active" : "tab"} onClick={() => setTab(item.id)}>
                  {item.label}
                </button>
              ))}
            </nav>
            {tab === "profile" ? <Profile id={current.id} /> : null}
            {tab === "ask" ? <Ask id={current.id} /> : null}
            {tab === "sql" ? <SqlDesk id={current.id} /> : null}
            {tab === "pipeline" ? <PipelineDesk id={current.id} onDone={refresh} /> : null}
            {tab === "model" ? <ModelDesk id={current.id} status={model} onDone={refresh} /> : null}
          </>
        )}
      </main>
    </div>
  )
}

function Upload({ onFile }: { onFile: (file: File) => void }) {
  return (
    <label className="file">
      Upload CSV or Parquet
      <input
        type="file"
        accept=".csv,.parquet"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onFile(file)
        }}
      />
    </label>
  )
}

function Profile({ id }: { id: string }) {
  const [columns, setColumns] = useState<ProfileColumn[]>([])
  const [issues, setIssues] = useState<QualityIssue[]>([])
  const [status, setStatus] = useState("")
  const [sample, setSample] = useState<Record<string, unknown>[]>([])

  useEffect(() => {
    Promise.all([api.profile(id), api.quality(id)]).then(([profile, quality]) => {
      setColumns(profile.columns)
      setSample(profile.sample)
      setIssues(quality.issues)
      setStatus(quality.status)
    })
  }, [id])

  return (
    <div className="grid">
      <p className={status === "pass" ? "status" : "status warn"}>Quality {status || "…"}</p>
      {issues.map((issue) => (
        <p key={`${issue.code}-${issue.column}`} className="note">
          {issue.severity}: {issue.detail}
        </p>
      ))}
      <div className="sheet">
      <table>
        <thead>
          <tr><th>Column</th><th>Type</th><th>Nulls</th><th>Distinct</th></tr>
        </thead>
        <tbody>
          {columns.map((column) => (
            <tr key={column.column}>
              <td>{column.column}{column.sensitive ? " · masked" : ""}</td>
              <td>{column.type}</td>
              <td>{column.sensitive ? "—" : column.null_percentage ?? "—"}</td>
              <td>{column.sensitive ? "—" : column.approx_unique ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {sample.length > 0 ? <pre className="mono">{JSON.stringify(sample, null, 2)}</pre> : null}
    </div>
  )
}

function Ask({ id }: { id: string }) {
  const [question, setQuestion] = useState("Are there duplicates?")
  const [answer, setAnswer] = useState("")
  const [grounded, setGrounded] = useState<boolean | null>(null)

  return (
    <div className="grid">
      <textarea value={question} onChange={(event) => setQuestion(event.target.value)} />
      <div>
        <button
          className="action"
          onClick={() => {
            api.ask(id, question).then((result) => {
              setAnswer(result.answer)
              setGrounded(result.grounded)
            })
          }}
        >
          Ask the file
        </button>
      </div>
      {answer ? (
        <div className="banner">
          <strong>{grounded ? "From the file" : "Not in the file"}</strong>
          <p>{answer}</p>
        </div>
      ) : null}
    </div>
  )
}

function SqlDesk({ id }: { id: string }) {
  const [column, setColumn] = useState("region")
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [rows, setRows] = useState<Record<string, unknown>[]>([])

  const load = useCallback(() => {
    api.drafts(id).then((result) => setDrafts(result.drafts))
  }, [id])
  useEffect(() => { load() }, [load])

  return (
    <div className="grid">
      <div className="row">
        <label>
          Group by
          <input value={column} onChange={(event) => setColumn(event.target.value)} />
        </label>
        <button
          className="action"
          onClick={() =>
            api.draftSql(id, {
              select: [column],
              metrics: [{ fn: "count", alias: "n" }],
              order_by: "n",
            }).then(load)
          }
        >
          Draft SQL
        </button>
      </div>
      {drafts.map((draft) => (
        <article key={draft.id} className="card">
          <p className="mono">{draft.sql}</p>
          <p className="meta">{draft.status}{draft.note ? ` · ${draft.note}` : ""}</p>
          <div className="row">
            {draft.status === "drafted" ? (
              <>
                <button className="action" onClick={() => api.decide(id, draft.id, "approve").then(load)}>Approve</button>
                <button className="ghost bad" onClick={() => api.decide(id, draft.id, "reject").then(load)}>Reject</button>
              </>
            ) : null}
            {draft.status === "approved" ? (
              <button className="action" onClick={() => api.execute(id, draft.id).then((result) => { setRows(result.rows); load() })}>
                Run approved SQL
              </button>
            ) : null}
          </div>
        </article>
      ))}
      {rows.length > 0 ? <pre className="mono">{JSON.stringify(rows, null, 2)}</pre> : null}
    </div>
  )
}

function PipelineDesk({ id, onDone }: { id: string; onDone: () => Promise<void> }) {
  const [plan, setPlan] = useState<string[]>([])
  const [counts, setCounts] = useState("")
  const steps = [{ op: "dedupe" }]

  return (
    <div className="grid">
      <p className="note">Preview drops exact duplicate rows. Nothing is saved until you approve.</p>
      <div className="row">
        <button
          className="ghost"
          onClick={() =>
            api.preview(id, steps).then((result) => {
              setPlan(result.plan)
              setCounts(`${result.input_rows} → ${result.output_rows} rows · writes ${String(result.writes)}`)
            })
          }
        >
          Preview dedupe
        </button>
        <button
          className="action"
          onClick={() => api.materialize(id, steps, "Deduped").then(() => onDone())}
        >
          Approve and keep a local copy
        </button>
      </div>
      {counts ? <p>{counts}</p> : null}
      {plan.map((line) => <p key={line} className="mono">{line}</p>)}
    </div>
  )
}

function ModelDesk({
  id,
  status,
  onDone,
}: {
  id: string
  status: ModelStatus | null
  onDone: () => Promise<void>
}) {
  const [question, setQuestion] = useState("count paid orders by region")
  const [summary, setSummary] = useState("")
  const [draft, setDraft] = useState<Draft | null>(null)
  const [localError, setLocalError] = useState("")

  return (
    <div className="grid">
      <div className="banner">
        <strong>{status?.model ?? "Local model"}</strong>
        <p className="note">
          {status?.parameters ?? "3.8B"} · {status?.license ?? "MIT"} · embeddings {status?.embeddings ?? "feature-hash"}.
          Executes: {String(status?.executes ?? false)}. Weights: {status?.ready ? "ready" : "not downloaded"}.
        </p>
        {!status?.ready ? (
          <p className="note">Install the runner with <span className="mono">uv sync --extra model</span>, then <span className="mono">atlas pull-model</span>.</p>
        ) : null}
      </div>
      <textarea value={question} onChange={(event) => setQuestion(event.target.value)} />
      <div>
        <button
          className="action"
          onClick={() =>
            api
              .modelDraft(id, question)
              .then(async (result) => {
                const bits = [`Tool ${result.tool}`, `executed ${String(result.executed)}`]
                if (result.answer) bits.push(result.answer.answer)
                if (result.preview) bits.push(result.preview.plan.join(" · "))
                setSummary(bits.join("\n"))
                setDraft(result.draft)
                setLocalError("")
                await onDone()
              })
              .catch((reason: Error) => setLocalError(reason.message))
          }
        >
          Draft with the local model
        </button>
      </div>
      {localError ? <p className="err">{localError}</p> : null}
      {summary ? <pre className="mono">{summary}</pre> : null}
      {draft ? (
        <article className="card">
          <p className="mono">{draft.sql}</p>
          <p className="meta">Saved as {draft.status}. Approve it on the SQL tab before it can run.</p>
        </article>
      ) : null}
    </div>
  )
}
