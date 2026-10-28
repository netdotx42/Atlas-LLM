import { useCallback, useEffect, useState } from "react"
import { api, type ColumnDetail, type Dataset, type Draft, type ModelStatus, type ProfileColumn, type QualityIssue, type Suggestion } from "./api"

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
          <button
            className="action"
            onClick={() =>
              run(async () => {
                const existing = datasets.find(
                  (item) => item.name === "Orders" && item.source_kind === "csv" && !item.parent_id,
                )
                if (existing) {
                  setSelected(existing.id)
                  return
                }
                const created = await api.sample()
                setSelected(created.id)
              })
            }
          >
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
            {tab === "profile" ? <Profile id={current.id} datasets={datasets} /> : null}
            {tab === "ask" ? <Ask id={current.id} /> : null}
            {tab === "sql" ? <SqlDesk id={current.id} datasets={datasets} /> : null}
            {tab === "pipeline" ? (
              <PipelineDesk
                id={current.id}
                onDone={async (childId) => {
                  await refresh()
                  if (childId) setSelected(childId)
                }}
              />
            ) : null}
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
          event.target.value = ""
          if (file) onFile(file)
        }}
      />
    </label>
  )
}

function Profile({ id, datasets }: { id: string; datasets: Dataset[] }) {
  const [columns, setColumns] = useState<ProfileColumn[]>([])
  const [issues, setIssues] = useState<QualityIssue[]>([])
  const [status, setStatus] = useState("")
  const [actions, setActions] = useState<Suggestion[]>([])
  const [focus, setFocus] = useState<string | null>(null)
  const [detail, setDetail] = useState<ColumnDetail | null>(null)
  const [preview, setPreview] = useState("")
  const [saved, setSaved] = useState("")
  const [localError, setLocalError] = useState("")
  const [sample, setSample] = useState<Record<string, unknown>[]>([])
  const current = datasets.find((item) => item.id === id)

  useEffect(() => {
    setFocus(null)
    setDetail(null)
    setPreview("")
    setSaved("")
    setLocalError("")
    Promise.all([api.profile(id), api.quality(id), api.suggestions(id)])
      .then(([profile, quality, suggested]) => {
        setColumns(profile.columns)
        setSample(profile.sample)
        setIssues(quality.issues)
        setStatus(quality.status)
        setActions(suggested.actions)
      })
      .catch((reason: unknown) => setLocalError(message(reason)))
  }, [id])

  useEffect(() => {
    if (!focus) return
    api.column(id, focus).then(setDetail).catch((reason: unknown) => {
      setDetail(null)
      setLocalError(message(reason))
    })
  }, [id, focus])

  const parent = datasets.find((item) => item.id === current?.parent_id)
  const children = datasets.filter((item) => item.parent_id === id)

  return (
    <div className="grid">
      <p className={status === "pass" ? "status" : "status warn"}>Quality {status || "…"}</p>
      {localError ? <p className="err">{localError}</p> : null}
      {issues.map((issue) => (
        <p key={`${issue.code}-${issue.column}`} className={`issue ${issue.severity}`}>
          {issue.detail}
        </p>
      ))}
      {(parent || children.length > 0 || current?.lineage) ? (
        <div className="card">
          <strong>Lineage</strong>
          {parent ? <p className="note">From {parent.name}</p> : null}
          {current?.lineage?.map((step, index) => (
            <p key={`${step.op}-${index}`} className="mono">
              {index + 1}. {step.op}
              {step.columns?.length ? ` ${step.columns.join(", ")}` : ""}
            </p>
          ))}
          {children.map((child) => (
            <p key={child.id} className="note">Child {child.name} · {child.row_count} rows</p>
          ))}
        </div>
      ) : null}
      {actions.length > 0 ? (
        <div className="row">
          {actions.map((action) =>
            action.steps.length > 0 ? (
              <button
                key={action.id}
                className="ghost"
                onClick={() =>
                  api
                    .preview(id, action.steps)
                    .then((result) => {
                      setLocalError("")
                      setPreview(
                        `${result.input_rows} → ${result.output_rows} rows · writes ${String(result.writes)}`,
                      )
                      setSaved(action.reason)
                    })
                    .catch((reason: unknown) => setLocalError(message(reason)))
                }
              >
                {action.label}
              </button>
            ) : (
              <p key={action.id} className="note">{action.label}. {action.reason}</p>
            ),
          )}
        </div>
      ) : null}
      {saved ? <p className="note">{saved}</p> : null}
      {preview ? <p className="note">{preview}</p> : null}
      <div className="sheet">
        <table>
          <thead>
            <tr><th>Column</th><th>Type</th><th>Nulls</th><th>Distinct</th></tr>
          </thead>
          <tbody>
            {columns.map((column) => (
              <tr key={column.column} className={focus === column.column ? "picked" : ""}>
                <td>
                  <button className="link" onClick={() => setFocus(column.column)}>
                    {column.column}
                  </button>
                  {column.sensitive ? " · masked" : ""}
                </td>
                <td>{column.type}</td>
                <td>{column.sensitive ? "—" : percent(column.null_percentage)}</td>
                <td>{column.sensitive ? "—" : column.approx_unique ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail ? (
        <div className="card">
          <strong>{detail.column}</strong>
          <p className="note">
            {detail.sensitive
              ? "Masked. Values stay hidden."
              : `${percent(detail.null_percentage)} null · ${detail.distinct} distinct`}
          </p>
          <div className="row">
            <button
              className="action"
              onClick={() =>
                api
                  .draftSql(id, {
                    select: [detail.column],
                    metrics: [{ fn: "count", alias: "n" }],
                    order_by: "n",
                  })
                  .then(() => setSaved(`Draft saved for ${detail.column}. Approve it on the SQL tab.`))
                  .catch((reason: unknown) => setLocalError(message(reason)))
              }
            >
              Draft group-by
            </button>
            <button
              className="ghost"
              onClick={() =>
                api
                  .preview(id, [{ op: "drop_nulls", columns: [detail.column] }])
                  .then((result) => {
                    setLocalError("")
                    setPreview(
                      `${result.input_rows} → ${result.output_rows} rows · writes ${String(result.writes)}`,
                    )
                  })
                  .catch((reason: unknown) => setLocalError(message(reason)))
              }
            >
              Preview drop nulls
            </button>
          </div>
          {detail.top.length > 0 ? (
            <>
              <ResultTable rows={detail.top.map((item) => ({ value: item.value, n: item.n }))} />
              <button className="ghost" onClick={() => downloadCsv(`${detail.column}.csv`, detail.top)}>
                Download CSV
              </button>
            </>
          ) : null}
        </div>
      ) : null}
      {sample.length > 0 ? (
        <div className="grid">
          <p className="note">Masked sample. Sensitive values are hidden.</p>
          <ResultTable rows={sample} />
        </div>
      ) : null}
    </div>
  )
}

function Ask({ id }: { id: string }) {
  const [question, setQuestion] = useState("Are there duplicates?")
  const [answer, setAnswer] = useState("")
  const [grounded, setGrounded] = useState<boolean | null>(null)
  const [evidence, setEvidence] = useState<{ source: string; detail: string }[]>([])
  const [localError, setLocalError] = useState("")

  useEffect(() => {
    setAnswer("")
    setGrounded(null)
    setEvidence([])
    setLocalError("")
  }, [id])

  return (
    <div className="grid">
      <textarea value={question} onChange={(event) => setQuestion(event.target.value)} />
      <p className="note">Try average of amount, how many distinct region, or is order_id a key.</p>
      <div>
        <button
          className="action"
          onClick={() => {
            setLocalError("")
            api
              .ask(id, question)
              .then((result) => {
                setAnswer(result.answer)
                setGrounded(result.grounded)
                setEvidence(result.evidence)
              })
              .catch((reason: unknown) => setLocalError(message(reason)))
          }}
        >
          Ask the file
        </button>
      </div>
      {localError ? <p className="err">{localError}</p> : null}
      {answer ? (
        <div className="banner">
          <strong>{grounded ? "From the file" : "Not in the file"}</strong>
          <p>{answer}</p>
          {evidence.length > 0 ? (
            <ul className="evidence">
              {evidence.map((item) => (
                <li key={`${item.source}-${item.detail}`}>{item.detail}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function SqlDesk({ id, datasets }: { id: string; datasets: Dataset[] }) {
  const [column, setColumn] = useState("region")
  const [joinId, setJoinId] = useState("")
  const [rightColumn, setRightColumn] = useState("region")
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [localError, setLocalError] = useState("")

  const load = useCallback(() => {
    api.drafts(id).then((result) => setDrafts(result.drafts)).catch((reason: unknown) => {
      setLocalError(message(reason))
    })
  }, [id])
  useEffect(() => {
    setRows([])
    setLocalError("")
    load()
  }, [load])

  const others = datasets.filter((item) => item.id !== id)

  return (
    <div className="grid">
      <div className="row">
        <label>
          Group by
          <input value={column} onChange={(event) => setColumn(event.target.value)} />
        </label>
        <label>
          Join dataset
          <select value={joinId} onChange={(event) => setJoinId(event.target.value)}>
            <option value="">None</option>
            {others.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        {joinId ? (
          <label>
            Right column
            <input value={rightColumn} onChange={(event) => setRightColumn(event.target.value)} />
          </label>
        ) : null}
        <button
          className="action"
          onClick={() => {
            const spec: Record<string, unknown> = {
              select: [column],
              metrics: [{ fn: "count", alias: "n" }],
              order_by: "n",
            }
            if (joinId) {
              spec.join = { dataset_id: joinId, left: column, right: rightColumn, how: "left" }
            }
            api
              .draftSql(id, spec)
              .then(() => {
                setLocalError("")
                load()
              })
              .catch((reason: unknown) => setLocalError(message(reason)))
          }}
        >
          Draft SQL
        </button>
      </div>
      {localError ? <p className="err">{localError}</p> : null}
      {drafts.map((draft) => (
        <article key={draft.id} className="card">
          <p className="mono">{draft.sql}</p>
          <p className="meta">{draft.status}{draft.note ? ` · ${draft.note}` : ""}</p>
          <div className="row">
            {draft.status === "drafted" ? (
              <>
                <button className="action" onClick={() => api.decide(id, draft.id, "approve").then(() => { setLocalError(""); load() }).catch((reason: unknown) => setLocalError(message(reason)))}>Approve</button>
                <button className="ghost bad" onClick={() => api.decide(id, draft.id, "reject").then(() => { setLocalError(""); load() }).catch((reason: unknown) => setLocalError(message(reason)))}>Reject</button>
              </>
            ) : null}
            {draft.status === "approved" ? (
              <button
                className="action"
                onClick={() =>
                  api
                    .execute(id, draft.id)
                    .then((result) => {
                      setLocalError("")
                      setRows(result.rows)
                      load()
                    })
                    .catch((reason: unknown) => setLocalError(message(reason)))
                }
              >
                Run approved SQL
              </button>
            ) : null}
          </div>
        </article>
      ))}
      {rows.length > 0 ? (
        <div className="grid">
          <ResultTable rows={rows} />
          <button className="ghost" onClick={() => downloadCsv("query.csv", rows)}>Download CSV</button>
        </div>
      ) : null}
    </div>
  )
}

function PipelineDesk({ id, onDone }: { id: string; onDone: (childId?: string) => Promise<void> }) {
  const [plan, setPlan] = useState<string[]>([])
  const [counts, setCounts] = useState("")
  const [sample, setSample] = useState<Record<string, unknown>[]>([])
  const [column, setColumn] = useState("amount")
  const [fillColumn, setFillColumn] = useState("status")
  const [dtype, setDtype] = useState("float")
  const [fillValue, setFillValue] = useState("unknown")
  const [localError, setLocalError] = useState("")
  const dedupe = [{ op: "dedupe" }]

  useEffect(() => {
    setPlan([])
    setCounts("")
    setSample([])
    setLocalError("")
  }, [id])

  function show(result: { plan: string[]; input_rows: number; output_rows: number; writes: boolean; sample: Record<string, unknown>[] }) {
    setLocalError("")
    setPlan(result.plan)
    setCounts(`${result.input_rows} → ${result.output_rows} rows · writes ${String(result.writes)}`)
    setSample(result.sample)
  }

  function fail(reason: unknown) {
    setLocalError(message(reason))
  }

  return (
    <div className="grid">
      <p className="note">Preview stays local. Nothing is saved until you approve.</p>
      {localError ? <p className="err">{localError}</p> : null}
      <div className="row">
        <button className="ghost" onClick={() => api.preview(id, dedupe).then(show).catch(fail)}>Preview dedupe</button>
        <button
          className="action"
          onClick={() =>
            api
              .materialize(id, dedupe, "Deduped")
              .then((created) => onDone(created.id))
              .catch(fail)
          }
        >
          Approve and keep a local copy
        </button>
      </div>
      <div className="row">
        <label>
          Cast column
          <input value={column} onChange={(event) => setColumn(event.target.value)} />
        </label>
        <label>
          Cast to
          <select value={dtype} onChange={(event) => setDtype(event.target.value)}>
            <option value="float">float</option>
            <option value="int">int</option>
            <option value="string">string</option>
          </select>
        </label>
        <label>
          Fill column
          <input value={fillColumn} onChange={(event) => setFillColumn(event.target.value)} />
        </label>
        <label>
          Fill nulls with
          <input value={fillValue} onChange={(event) => setFillValue(event.target.value)} />
        </label>
        <button
          className="ghost"
          onClick={() =>
            api
              .preview(id, [
                { op: "cast", columns: [column], dtype },
                { op: "fill", columns: [fillColumn], fill_value: fillValue },
              ])
              .then(show)
              .catch(fail)
          }
        >
          Preview cast and fill
        </button>
      </div>
      {counts ? <p>{counts}</p> : null}
      {plan.map((line) => <p key={line} className="mono">{line}</p>)}
      {sample.length > 0 ? (
        <div className="grid">
          <ResultTable rows={sample} />
          <button className="ghost" onClick={() => downloadCsv("preview.csv", sample)}>Download CSV</button>
        </div>
      ) : null}
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

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Request failed"
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  const headers = Object.keys(rows[0] ?? {})
  return (
    <div className="sheet">
      <table>
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {headers.map((header) => (
                <td key={header}>{row[header] == null ? "—" : String(row[header])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function percent(value: number | null): string {
  if (value == null) return "—"
  return `${Number(value).toFixed(1)}%`
}

function downloadCsv(name: string, rows: Record<string, unknown>[]) {
  if (rows.length === 0) return
  const headers = Object.keys(rows[0])
  const lines = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ]
  const blob = new Blob([lines.join("\n")], { type: "text/csv" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

function csvCell(value: unknown): string {
  if (value == null) return ""
  const text = String(value)
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`
  return text
}
