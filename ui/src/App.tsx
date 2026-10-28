import { useCallback, useEffect, useState, type FormEvent } from "react"
import { api, type ColumnDetail, type Dataset, type Draft, type ModelStatus, type Pass, type PipelineDraft, type ProfileColumn, type QualityIssue, type ReviewEvent, type ScoreCase, type Session, type Suggestion } from "./api"

type Page = "project" | "ask" | "pipeline" | "review"

const PAGES: { id: Page; label: string }[] = [
  { id: "project", label: "Project" },
  { id: "ask", label: "Ask" },
  { id: "pipeline", label: "Pipeline" },
  { id: "review", label: "Review" },
]

export function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [model, setModel] = useState<ModelStatus | null>(null)
  const [error, setError] = useState("")
  const [page, setPage] = useState<Page>("project")

  const refresh = useCallback(async () => {
    const [listed, status] = await Promise.all([api.datasets(), api.model()])
    setDatasets(listed.datasets)
    setModel(status)
    setSelected((current) => current ?? listed.datasets[0]?.id ?? null)
  }, [])

  useEffect(() => {
    api.session().then(setSession).catch((reason: Error) => setError(reason.message))
  }, [])

  useEffect(() => {
    if (!session || (session.auth && !session.user?.open)) return
    refresh().catch((reason: Error) => setError(reason.message))
  }, [refresh, session])

  if (!session) {
    return <main className="gate"><p className="note">Opening the desk.</p></main>
  }
  if (session.auth && !session.user) {
    return <SignIn onDone={setSession} />
  }
  if (session.auth && session.user && !session.user.open) {
    return <Passes email={session.user.email} onLeave={() => api.logout().then(() => setSession({ auth: true, open: false, user: null }))} />
  }

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
          <div className="brand">
            <Mark />
            <h1>ATLAS</h1>
          </div>
          <span>{session.auth ? `${session.user?.days_left ?? 0}d` : "LOCAL"}</span>
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
          {session.user ? (
            <button
              className="ghost"
              onClick={() => api.logout().then(() => setSession({ auth: true, open: false, user: null }))}
            >
              Sign out
            </button>
          ) : null}
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
              {PAGES.map((item) => (
                <button key={item.id} className={page === item.id ? "tab active" : "tab"} onClick={() => setPage(item.id)}>
                  {item.label}
                </button>
              ))}
            </nav>
            {page === "project" ? (
              <>
                <ProjectFacts dataset={current} datasets={datasets} model={model} />
                <Profile id={current.id} datasets={datasets} />
              </>
            ) : null}
            {page === "ask" ? (
              <>
                <Ask id={current.id} />
                <SqlDesk id={current.id} datasets={datasets} />
              </>
            ) : null}
            {page === "pipeline" ? (
              <PipelineDesk
                id={current.id}
                onDone={async (childId) => {
                  await refresh()
                  if (childId) setSelected(childId)
                }}
              />
            ) : null}
            {page === "review" ? (
              <>
                <Review />
                <ModelDesk id={current.id} status={model} onDone={refresh} />
              </>
            ) : null}
          </>
        )}
      </main>
    </div>
  )
}

function SignIn({ onDone }: { onDone: (session: Session) => void }) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [mode, setMode] = useState<"register" | "login">("register")
  const [error, setError] = useState("")

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError("")
    try {
      const next =
        mode === "register" ? await api.register(email, password) : await api.login(email, password)
      onDone(next)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed")
    }
  }

  return (
    <main className="gate">
      <form className="panel" onSubmit={submit}>
        <div className="brand">
          <Mark />
          <h1>ATLAS</h1>
        </div>
        <p className="note">14 days free. No card. A pass is a one-time payment, not a renewal.</p>
        <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required placeholder="Email" />
        <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required minLength={10} placeholder="Password, 10 characters" />
        {error ? <p className="err">{error}</p> : null}
        <button className="action" type="submit">{mode === "register" ? "Start trial" : "Sign in"}</button>
        <button className="ghost" type="button" onClick={() => setMode(mode === "register" ? "login" : "register")}>
          {mode === "register" ? "I already have an account" : "Create an account"}
        </button>
      </form>
    </main>
  )
}

function Passes({ email, onLeave }: { email: string; onLeave: () => void }) {
  const [passes, setPasses] = useState<Pass[]>([])
  const [error, setError] = useState("")

  useEffect(() => {
    api.passes().then((body) => setPasses(body.passes)).catch((reason: Error) => setError(reason.message))
  }, [])

  return (
    <main className="gate">
      <section className="panel">
        <div className="brand">
          <Mark />
          <h1>ATLAS</h1>
        </div>
        <p className="note">{email} · the trial has ended. Files stay. Choose a pass to open the desk.</p>
        {error ? <p className="err">{error}</p> : null}
        <div className="stack">
          {passes.map((pass) => (
            <button
              key={pass.id}
              className="action"
              onClick={() =>
                api.checkout(pass.id).then((body) => {
                  window.location.href = body.url
                }).catch((reason: Error) => setError(reason.message))
              }
            >
              {pass.label} · ${(pass.cents / 100).toFixed(0)}
            </button>
          ))}
        </div>
        <button className="ghost" onClick={onLeave}>Sign out</button>
      </section>
    </main>
  )
}

function ProjectFacts({
  dataset,
  datasets,
  model,
}: {
  dataset: Dataset
  datasets: Dataset[]
  model: ModelStatus | null
}) {
  const parent = datasets.find((item) => item.id === dataset.parent_id)
  const children = datasets.filter((item) => item.parent_id === dataset.id)
  const facts: [string, string][] = [
    ["Rows", String(dataset.row_count)],
    ["Columns", String(dataset.column_count)],
    ["Source", dataset.source_kind],
    ["Added", dataset.created_at.slice(0, 10)],
    ["From", parent?.name ?? "Original file"],
    ["Derived", children.length ? String(children.length) : "None"],
    ["Writes", "Off"],
    ["Model", model?.ready ? "Ready" : "Not installed"],
  ]
  return (
    <div className="facts">
      {facts.map(([label, value]) => (
        <div className="fact" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  )
}

function Mark() {
  return (
    <svg className="arc" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M7.2 19.4C8.7 11.1 12.3 6.8 16 6.8s7.3 4.3 8.8 12.6" />
      <path d="M11.2 23.6h9.6" />
    </svg>
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
                  .then(() => setSaved(`Draft saved for ${detail.column}. Approve it on the Ask page.`))
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
      <p className="note">
        Try min and max of amount, average amount by region, or rows after a date.
      </p>
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
  const [drafts, setDrafts] = useState<PipelineDraft[]>([])
  const dedupe = [{ op: "dedupe" }]

  const load = useCallback(() => {
    api.pipelineDrafts(id).then((result) => setDrafts(result.drafts)).catch((reason: unknown) => {
      setLocalError(message(reason))
    })
  }, [id])

  useEffect(() => {
    setPlan([])
    setCounts("")
    setSample([])
    setLocalError("")
    load()
  }, [load])

  function show(result: { plan: string[]; input_rows: number; output_rows: number; writes: boolean; sample: Record<string, unknown>[] }) {
    setLocalError("")
    setPlan(result.plan)
    setCounts(`${result.input_rows} → ${result.output_rows} rows · writes ${String(result.writes)}`)
    setSample(result.sample)
  }

  function fail(reason: unknown) {
    setLocalError(message(reason))
  }

  function save(steps: unknown[]) {
    api
      .savePipeline(id, steps)
      .then((result) => {
        setLocalError("")
        setCounts(`Draft saved. Preview writes ${String(result.preview.writes)}. Nothing is kept yet.`)
        load()
      })
      .catch(fail)
  }

  return (
    <div className="grid">
      <p className="note">Preview stays local. A draft writes nothing until you approve it, then keep a copy.</p>
      {localError ? <p className="err">{localError}</p> : null}
      <div className="row">
        <button className="ghost" onClick={() => api.preview(id, dedupe).then(show).catch(fail)}>Preview dedupe</button>
        <button className="action" onClick={() => save(dedupe)}>Save dedupe draft</button>
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
        <button
          className="ghost"
          onClick={() =>
            save([
              { op: "cast", columns: [column], dtype },
              { op: "fill", columns: [fillColumn], fill_value: fillValue },
            ])
          }
        >
          Save cast and fill draft
        </button>
      </div>
      {drafts.map((draft) => (
        <article key={draft.id} className="card">
          <p className="mono">{draft.steps.map((step) => step.op).join(" → ")}</p>
          <p className="meta">{draft.status}</p>
          <div className="row">
            {draft.status === "drafted" ? (
              <>
                <button className="action" onClick={() => api.decidePipeline(id, draft.id, "approve").then(() => { setLocalError(""); load() }).catch(fail)}>Approve</button>
                <button className="ghost bad" onClick={() => api.decidePipeline(id, draft.id, "reject").then(() => { setLocalError(""); load() }).catch(fail)}>Reject</button>
              </>
            ) : null}
            {draft.status === "approved" ? (
              <button
                className="action"
                onClick={() =>
                  api
                    .keepPipeline(id, draft.id, "Derived")
                    .then((created) => onDone(created.id))
                    .catch(fail)
                }
              >
                Keep a local copy
              </button>
            ) : null}
          </div>
        </article>
      ))}
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
  const [cases, setCases] = useState<ScoreCase[]>([])
  const [scoreLine, setScoreLine] = useState("")
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
        <button
          className="ghost"
          onClick={() =>
            api
              .modelScore(id)
              .then((result) => {
                setLocalError("")
                setCases(result.cases)
                setScoreLine(`${result.passed} passed, ${result.failed} rejected. One attempt each. Nothing ran.`)
              })
              .catch((reason: Error) => setLocalError(reason.message))
          }
        >
          Score the drafter
        </button>
      </div>
      {localError ? <p className="err">{localError}</p> : null}
      {summary ? <pre className="mono">{summary}</pre> : null}
      {draft ? (
        <article className="card">
          <p className="mono">{draft.sql}</p>
          <p className="meta">Saved as {draft.status}. Approve it on the Ask page before it can run.</p>
        </article>
      ) : null}
      {scoreLine ? <p className="note">{scoreLine}</p> : null}
      {cases.map((item) => (
        <p key={item.id} className={item.outcome === "pass" ? "note" : "err"}>
          {item.id}: {item.outcome}
          {item.reason ? ` — ${item.reason}` : ""} · attempts {item.attempts} · writes {String(item.writes)}
        </p>
      ))}
    </div>
  )
}

function Review() {
  const [events, setEvents] = useState<ReviewEvent[]>([])
  const [localError, setLocalError] = useState("")

  useEffect(() => {
    api.review().then((result) => setEvents(result.events)).catch((reason: unknown) => {
      setLocalError(message(reason))
    })
  }, [])

  return (
    <div className="grid">
      <div className="row">
        <p className="note">Decisions and approved runs. Export is the same log.</p>
        <button className="ghost" onClick={() => downloadCsv("review.csv", events.map((item) => ({
          at: item.at,
          dataset: item.dataset,
          action: item.action,
          decision: item.decision,
          draft: item.draft,
          rows: item.rows ?? "",
          detail: item.detail,
        })))}>
          Download CSV
        </button>
      </div>
      {localError ? <p className="err">{localError}</p> : null}
      {events.length === 0 ? <p className="note">No approvals yet.</p> : <ResultTable rows={events.map((item) => ({
        at: item.at,
        dataset: item.dataset || "—",
        action: item.action,
        decision: item.decision,
        rows: item.rows ?? "—",
        draft: item.draft || "—",
      }))} />}
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
