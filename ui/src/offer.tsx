import { useEffect, useState, type FormEvent } from "react"
import { api, type Pass, type Session } from "./api"
import { Mark } from "./mark"
import { Demo } from "./demo"

const FACTS: [string, string][] = [
  ["Project", "Rows, source, and lineage. Writes stay off until you approve."],
  ["Ask", "Answers stay tied to the file. SQL waits as a draft."],
  ["Pipeline", "A preview first. A local copy only after you keep it."],
  ["Review", "Every decision is logged. The model cannot run a write."],
]

const FALLBACK: Pass[] = [
  { id: "30", days: 30, cents: 2900, label: "30 days" },
  { id: "90", days: 90, cents: 6900, label: "90 days" },
  { id: "365", days: 365, cents: 17900, label: "365 days" },
]

function money(cents: number) {
  return `$${Math.round(cents / 100)}`
}

export function Offer({
  auth,
  onDone,
  onOpen,
}: {
  auth: boolean
  onDone: (session: Session) => void
  onOpen?: () => void
}) {
  const [passes, setPasses] = useState<Pass[]>(FALLBACK)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [mode, setMode] = useState<"register" | "login">("register")
  const [error, setError] = useState("")

  useEffect(() => {
    api
      .passes()
      .then((body) => {
        if (body.passes.length) setPasses(body.passes)
      })
      .catch(() => {})
  }, [])

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
    <div className="offer-page">
      <main className={auth ? "offer" : "offer offer-local"}>
      <section className="offer-copy">
        <div className="brand">
          <Mark />
          <h1>ATLAS</h1>
        </div>
        <p className="lede">A private desk for files you already have. It drafts. You approve.</p>
        <ul className="facts offer-facts">
          {FACTS.map(([title, detail]) => (
            <li className="fact" key={title}>
              <span>{title}</span>
              <strong>{detail}</strong>
            </li>
          ))}
        </ul>
        <div className="prices" aria-label="Passes">
          {passes.map((pass) => (
            <article className="price" key={pass.id}>
              <span>{pass.label}</span>
              <strong>{money(pass.cents)}</strong>
              <small>One payment</small>
            </article>
          ))}
        </div>
        <p className="note">
          14 days free. No card. A pass is a single payment, not a renewal. Files stay if the trial ends.
        </p>
      </section>
      {auth ? (
        <form className="panel offer-form" onSubmit={submit}>
          <h2>{mode === "register" ? "Start the trial" : "Sign in"}</h2>
          <p className="note">
            {mode === "register"
              ? "14 days. No card. Buy a pass from the desk whenever you want."
              : "The desk opens while your trial or pass is still active."}
          </p>
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            type="email"
            required
            placeholder="Email"
            autoComplete="email"
          />
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            required
            minLength={10}
            placeholder="Password, 10 characters"
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
          {error ? <p className="err">{error}</p> : null}
          <button className="action" type="submit">
            {mode === "register" ? "Start trial" : "Sign in"}
          </button>
          <a className="link" href="#demo">
            Or try the free sample first
          </a>
          <button
            className="ghost"
            type="button"
            onClick={() => setMode(mode === "register" ? "login" : "register")}
          >
            {mode === "register" ? "I already have an account" : "Create an account"}
          </button>
        </form>
      ) : (
        <section className="panel offer-form">
          <h2>Open the desk</h2>
          <p className="note">
            Sign-in is off on this install, so the desk is open and the passes are not charged. A hosted
            desk turns sign-in on.
          </p>
          <button className="action" type="button" onClick={onOpen}>
            Open the desk
          </button>
        </section>
      )}
      </main>
      <Demo />
    </div>
  )
}
