import { useEffect, useState } from "react"
import { api, type Pass } from "./api"
import { Mark } from "./mark"

const FALLBACK: Pass[] = [
  { id: "30", days: 30, cents: 2900, label: "30 days" },
  { id: "90", days: 90, cents: 6900, label: "90 days" },
  { id: "365", days: 365, cents: 17900, label: "365 days" },
]

function money(cents: number) {
  return `$${Math.round(cents / 100)}`
}

export function Account({
  email,
  daysLeft,
  open,
  onLeave,
  layout,
}: {
  email: string
  daysLeft: number
  open: boolean
  onLeave: () => void
  layout: "rail" | "gate"
}) {
  const [passes, setPasses] = useState<Pass[]>(FALLBACK)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")

  useEffect(() => {
    api
      .passes()
      .then((body) => {
        if (body.passes.length) setPasses(body.passes)
      })
      .catch((reason: Error) => setError(reason.message))
  }, [])

  function buy(id: string) {
    setError("")
    setBusy(id)
    api
      .checkout(id)
      .then((body) => {
        window.location.href = body.url
      })
      .catch((reason: Error) => {
        setBusy("")
        setError(reason instanceof Error ? reason.message : "Request failed")
      })
  }

  const cards = passes.map((pass) =>
    layout === "rail" ? (
      <button key={pass.id} className="ghost" type="button" disabled={busy === pass.id} onClick={() => buy(pass.id)}>
        {pass.label}
        <small>{busy === pass.id ? "Opening checkout" : `${money(pass.cents)} · one payment`}</small>
      </button>
    ) : (
      <button
        key={pass.id}
        className="price price-buy"
        type="button"
        disabled={busy === pass.id}
        onClick={() => buy(pass.id)}
      >
        <span>{pass.label}</span>
        <strong>{money(pass.cents)}</strong>
        <small>{busy === pass.id ? "Opening checkout" : "One payment"}</small>
      </button>
    ),
  )

  if (layout === "gate") {
    return (
      <main className="gate">
        <section className="panel account-gate">
          <div className="brand">
            <Mark />
            <h1>ATLAS</h1>
          </div>
          <p className="note">{email} · the trial has ended. Files stay. Choose a pass to open the desk.</p>
          {error ? <p className="err">{error}</p> : null}
          <div className="prices">{cards}</div>
          <button className="ghost" type="button" onClick={onLeave}>
            Sign out
          </button>
        </section>
      </main>
    )
  }

  return (
    <section className="account">
      <p className="account-days">{open ? `${daysLeft} days left` : "Trial ended"}</p>
      <p className="note">{email}. One payment. No renewal.</p>
      {error ? <p className="err">{error}</p> : null}
      <div className="stack">{cards}</div>
      <button className="ghost" type="button" onClick={onLeave}>
        Sign out
      </button>
    </section>
  )
}
