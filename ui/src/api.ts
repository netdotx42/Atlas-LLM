export type Dataset = {
  id: string
  name: string
  source_kind: string
  row_count: number
  column_count: number
  created_at: string
  parent_id: string | null
  lineage: { op: string; columns?: string[] }[] | null
}

export type ProfileColumn = {
  column: string
  type: string
  null_percentage: number | null
  approx_unique: number | null
  min: string | null
  max: string | null
  sensitive: boolean
}

export type QualityIssue = {
  code: string
  severity: string
  column: string | null
  detail: string
}

export type Suggestion = {
  id: string
  label: string
  reason: string
  steps: { op: string; columns?: string[]; dtype?: string; fill_value?: string | number }[]
}

export type ColumnDetail = {
  column: string
  type: string
  nulls: number
  null_percentage: number
  distinct: number
  min: string | null
  max: string | null
  sensitive: boolean
  top: { value: string | null; n: number }[]
}

export type Draft = {
  id: string
  sql: string
  status: string
  note: string
}

export type ReviewEvent = {
  at: string
  dataset: string
  action: string
  decision: string
  draft: string
  sql: string
  rows: number | null
  detail: string
}

export type ScoreCase = {
  id: string
  question: string
  expect: string
  tool: string | null
  outcome: string
  reason: string
  attempts: number
  writes: boolean
}

export type PipelineDraft = {
  id: string
  status: string
  note: string
  steps: { op: string; columns?: string[] }[]
  created_at: string
}

export type ModelStatus = {
  ready?: boolean
  executes?: boolean
  embeddings?: string
  model?: string
  license?: string
  parameters?: string
  path?: string
  detail?: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = (await response.json().catch(() => ({}))) as { detail?: string }
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : response.statusText)
  }
  return body as T
}

export const api = {
  datasets: () => request<{ datasets: Dataset[] }>("/datasets"),
  sample: () => request<Dataset>("/datasets/sample", { method: "POST" }),
  upload: (name: string, file: File) => {
    const body = new FormData()
    body.set("name", name)
    body.set("file", file)
    return request<Dataset>("/datasets", { method: "POST", body })
  },
  profile: (id: string) =>
    request<{ columns: ProfileColumn[]; sample: Record<string, unknown>[] }>(
      `/datasets/${id}/profile`,
    ),
  quality: (id: string) =>
    request<{ status: string; issues: QualityIssue[] }>(`/datasets/${id}/quality`),
  column: (id: string, name: string) =>
    request<ColumnDetail>(`/datasets/${id}/columns/${encodeURIComponent(name)}`),
  suggestions: (id: string) => request<{ actions: Suggestion[] }>(`/datasets/${id}/suggestions`),
  ask: (id: string, question: string) =>
    request<{ grounded: boolean; answer: string; evidence: { source: string; detail: string }[] }>(
      `/datasets/${id}/ask`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question }) },
    ),
  draftSql: (id: string, spec: unknown) =>
    request<Draft>(`/datasets/${id}/sql/drafts`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(spec),
    }),
  drafts: (id: string) => request<{ drafts: Draft[] }>(`/datasets/${id}/sql/drafts`),
  decide: (id: string, draftId: string, decision: "approve" | "reject") =>
    request<Draft>(`/datasets/${id}/sql/drafts/${draftId}/decision`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision }),
    }),
  execute: (id: string, draftId: string) =>
    request<{ columns: string[]; rows: Record<string, unknown>[]; row_count: number }>(
      `/datasets/${id}/sql/drafts/${draftId}/execute`,
      { method: "POST" },
    ),
  preview: (id: string, steps: unknown[]) =>
    request<{ plan: string[]; input_rows: number; output_rows: number; writes: boolean; sample: Record<string, unknown>[] }>(
      `/datasets/${id}/pipeline/preview`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ steps }) },
    ),
  materialize: (id: string, steps: unknown[], name: string) =>
    request<{ id: string; name: string; row_count: number; writes_to_production: boolean }>(
      `/datasets/${id}/pipeline/materialize`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ steps, approve: true, name }),
      },
    ),
  model: () => request<ModelStatus>("/model"),
  modelScore: (id: string) =>
    request<{ passed: number; failed: number; total: number; cases: ScoreCase[] }>(
      `/datasets/${id}/model/score`,
      { method: "POST" },
    ),
  review: () => request<{ events: ReviewEvent[] }>("/review"),
  pipelineDrafts: (id: string) =>
    request<{ drafts: PipelineDraft[] }>(`/datasets/${id}/pipeline/drafts`),
  savePipeline: (id: string, steps: unknown[]) =>
    request<{ id: string; status: string; preview: { writes: boolean; output_rows: number } }>(
      `/datasets/${id}/pipeline/drafts`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ steps }),
      },
    ),
  decidePipeline: (id: string, draftId: string, decision: "approve" | "reject") =>
    request<PipelineDraft>(`/datasets/${id}/pipeline/drafts/${draftId}/decision`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision }),
    }),
  keepPipeline: (id: string, draftId: string, name: string) =>
    request<{ id: string; name: string; row_count: number; writes_to_production: boolean }>(
      `/datasets/${id}/pipeline/drafts/${draftId}/materialize`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      },
    ),
  modelDraft: (id: string, question: string) =>
    request<{
      tool: string
      executed: boolean
      draft: Draft | null
      preview: { plan: string[]; output_rows: number; writes: boolean } | null
      answer: { grounded: boolean; answer: string } | null
      steps?: unknown[]
    }>(`/datasets/${id}/model/draft`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
    }),
}
