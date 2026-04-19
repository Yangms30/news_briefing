import type {
  Article,
  GenerateProgressEvent,
  GenerateResult,
  Report,
  SendResponse,
  Setting,
  SettingPayload,
  User,
} from "./types"

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

const DEFAULT_TIMEOUT_MS = 15_000
const GENERATE_TIMEOUT_MS = 120_000

export class BriefBotApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(`[${status}] ${detail}`)
    this.name = "BriefBotApiError"
    this.status = status
    this.detail = detail
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE"
  body?: unknown
  query?: Record<string, string | number | boolean | undefined | null>
  timeoutMs?: number
  signal?: AbortSignal
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = opts

  const url = new URL(path, BASE_URL)
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue
      url.searchParams.set(k, String(v))
    }
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener("abort", () => controller.abort(), { once: true })
  }

  let res: Response
  try {
    res = await fetch(url.toString(), {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timer)
    if ((err as Error).name === "AbortError") {
      throw new BriefBotApiError(0, "요청이 시간 초과됐거나 취소됐습니다")
    }
    throw new BriefBotApiError(0, `네트워크 오류: ${(err as Error).message}`)
  }
  clearTimeout(timer)

  if (!res.ok) {
    const detail = await parseErrorDetail(res)
    throw new BriefBotApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

// Stream Server-Sent Events from the given URL. Resolves on `done`, rejects on `error`
// or transport failure. Parses one event per `data: {...}\n\n` frame (ignores comments).
async function streamSSE<E extends { type: string }>(
  url: string,
  onEvent: (event: E) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(url, {
      method: "GET",
      headers: { Accept: "text/event-stream" },
      signal,
      cache: "no-store",
    })
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      throw new BriefBotApiError(0, "요청이 취소됐습니다")
    }
    throw new BriefBotApiError(0, `네트워크 오류: ${(err as Error).message}`)
  }

  if (!res.ok) {
    const detail = await parseErrorDetail(res)
    throw new BriefBotApiError(res.status, detail)
  }
  if (!res.body) {
    throw new BriefBotApiError(0, "응답 스트림이 비어 있습니다")
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder("utf-8")
  let buffer = ""
  let terminated = false

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE frames are separated by a blank line.
      let sepIndex: number
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)

        const dataLines: string[] = []
        for (const rawLine of frame.split("\n")) {
          const line = rawLine.replace(/\r$/, "")
          if (!line || line.startsWith(":")) continue // comment / heartbeat
          if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).replace(/^ /, ""))
          }
        }
        if (dataLines.length === 0) continue
        const payload = dataLines.join("\n")
        let event: E
        try {
          event = JSON.parse(payload) as E
        } catch {
          continue
        }
        onEvent(event)
        if (event.type === "done") {
          terminated = true
        } else if (event.type === "error") {
          const message =
            (event as unknown as { message?: string }).message ?? "pipeline error"
          throw new BriefBotApiError(500, message)
        }
      }

      if (terminated) break
    }
  } finally {
    try {
      await reader.cancel()
    } catch {
      /* ignore */
    }
  }
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data?.detail === "string") return data.detail
    if (Array.isArray(data?.detail)) {
      return data.detail.map((d: { msg?: string }) => d.msg ?? "invalid").join("; ")
    }
    return JSON.stringify(data)
  } catch {
    return res.statusText || "unknown error"
  }
}

// ---------- Namespace API ----------

/**
 * URL for the mp3 stream of a report's radio_script.
 * Backend synthesizes on first call (OpenAI gpt-4o-mini-tts) and caches on disk.
 */
export function getReportAudioUrl(reportId: number): string {
  return new URL(`/api/reports/${reportId}/audio`, BASE_URL).toString()
}

export const api = {
  users: {
    create(input: { name: string; email: string }): Promise<User> {
      return request<User>("/api/users", { method: "POST", body: input })
    },
    get(id: number): Promise<User> {
      return request<User>(`/api/users/${id}`)
    },
  },

  settings: {
    save(userId: number, payload: SettingPayload): Promise<Setting> {
      return request<Setting>(`/api/settings/${userId}`, { method: "PUT", body: payload })
    },
    get(userId: number): Promise<Setting> {
      return request<Setting>(`/api/settings/${userId}`)
    },
  },

  reports: {
    list(userId: number, opts: { category?: string; limit?: number } = {}): Promise<Report[]> {
      return request<Report[]>("/api/reports", {
        query: { user_id: userId, category: opts.category, limit: opts.limit },
      })
    },
    get(id: number): Promise<Report> {
      return request<Report>(`/api/reports/${id}`)
    },
    getArticle(id: number): Promise<Article> {
      return request<Article>(`/api/reports/articles/${id}`)
    },
    generate(userId: number, signal?: AbortSignal): Promise<GenerateResult> {
      return request<GenerateResult>("/api/reports/generate", {
        method: "POST",
        query: { user_id: userId },
        timeoutMs: GENERATE_TIMEOUT_MS,
        signal,
      })
    },
    generateStream(
      userId: number,
      onEvent: (event: GenerateProgressEvent) => void,
      signal?: AbortSignal,
    ): Promise<void> {
      const url = new URL("/api/reports/generate/stream", BASE_URL)
      url.searchParams.set("user_id", String(userId))
      return streamSSE(url.toString(), onEvent, signal)
    },
  },

  send: {
    dispatch(userId: number): Promise<SendResponse> {
      return request<SendResponse>("/api/send", {
        method: "POST",
        query: { user_id: userId },
      })
    },
  },
}
