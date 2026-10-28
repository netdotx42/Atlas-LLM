import { useEffect, useState } from "react"
import { api, type DemoReport } from "./api"

export function Demo() {
  const [report, setReport] = useState<DemoReport | null>(null)
  const [picked, setPicked] = useState<string>("")
  const [error, setError] = useState("")

  useEffect(() => {
    api
      .demo()
      .then(setReport)
      .catch((reason: Error) => setError(reason.message))
  }, [])

  const answer = report?.asks.find((item) => item.id === picked)

  return (
    <section className="demo" id="demo">
      <p className="status">Free demo</p>
      <h2>The sample file, and nothing else.</h2>
      <p className="note demo-lead">
        Three questions. A preview you cannot keep. Your own file, your own question, and an approved copy start
        with the trial.
      </p>
      {error ? <p className="err">{error}</p> : null}
      {report ? (
        <div className="demo-grid">
          <article className="card demo-card">
            <h3>Project</h3>
            <p className="note">
              {report.name}. {report.rows} rows · {report.columns} columns. Writes are off.
            </p>
            <p className="demo-lock">Not your file</p>
          </article>
          <article className="card demo-card">
            <h3>Ask</h3>
            <div className="demo-asks">
              {report.asks.map((item) => (
                <button
                  key={item.id}
                  className={picked === item.id ? "ghost active" : "ghost"}
                  type="button"
                  onClick={() => setPicked(item.id)}
                >
                  {item.question}
                </button>
              ))}
            </div>
            <p className="note">{answer?.answer ?? "Pick one of the three. A blank question is the trial."}</p>
          </article>
          <article className="card demo-card">
            <h3>Pipeline</h3>
            <p className="note">
              {report.pipeline.plan[0]}. {report.pipeline.input_rows} rows in, {report.pipeline.output_rows} rows
              out. Nothing is written.
            </p>
            <button className="action" type="button" disabled>
              Keep the copy
            </button>
            <p className="demo-lock">Keeping a file is a trial</p>
          </article>
          <article className="card demo-card">
            <h3>Review</h3>
            <p className="note">The preview is a draft. It was not approved, and it did not run.</p>
            <p className="demo-lock">The log opens with an account</p>
          </article>
        </div>
      ) : null}
    </section>
  )
}
