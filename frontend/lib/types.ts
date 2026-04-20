// Mirrors backend/schemas.py — keep in sync when backend types change.

export type User = {
  id: number
  name: string
  email: string
  created_at: string
}

export type ChannelConfig = {
  web?: boolean
  /**
   * Legacy Slack Incoming Webhook URL (text-only, no audio upload).
   * Use `slack_bot_token` + `slack_channel_id` for audio support.
   */
  slack?: string
  /** Slack Bot User OAuth Token ("xoxb-..."), enables audio upload via files.upload_v2. */
  slack_bot_token?: string
  /** Slack channel id (e.g. "C01234567") — required alongside slack_bot_token. */
  slack_channel_id?: string
  email?: string
  /**
   * TTS engine preference. Controls which provider renders the radio script
   * into audio for this user. "elevenlabs" = high-quality (default, uses
   * monthly quota). "openai" = gpt-4o-mini-tts (pay-per-use, useful for
   * rehearsals to preserve ElevenLabs quota).
   */
  tts_engine?: "elevenlabs" | "openai"
}

export type Setting = {
  id: number
  user_id: number
  categories: string[]
  schedule_cron: string | null
  channels: ChannelConfig
  updated_at: string
}

export type SettingPayload = {
  categories: string[]
  schedule_cron: string | null
  channels: ChannelConfig
}

// Known primary categories; keep as string for forward-compat with custom ones.
export type Category = "정치" | "경제" | "사회" | "국제" | "스포츠" | "IT/과학"

export const CATEGORIES: Category[] = ["정치", "경제", "사회", "국제", "스포츠", "IT/과학"]

export type Article = {
  id: number
  report_id: number
  category: string
  title: string
  summary: string
  link: string
  source: string | null
  published_at: string | null
  created_at: string
}

export type Report = {
  id: number
  user_id: number
  category: string
  radio_script: string | null
  created_at: string
  articles: Article[]
}

export type GenerateResult = {
  user_id: number
  generated: number
  reports: Report[]
}

export type SendResult = {
  channel: string
  status: string
  error_msg?: string | null
}

export type SendResponse = {
  user_id: number
  results: SendResult[]
}

// ---------- Dispatch Archive ----------
// Mirrors backend/schemas.py DispatchChannelOut / DispatchSummary / DispatchDetail.

export type DispatchChannel = {
  channel: string
  status: string
  error_msg?: string | null
  recipient?: string | null
  sent_at: string
}

export type DispatchSummary = {
  dispatch_id: string
  sent_at: string
  channels: DispatchChannel[]
  report_count: number
  categories: string[]
}

export type DispatchDetail = {
  dispatch_id: string
  sent_at: string
  channels: DispatchChannel[]
  reports: Report[]
}

// SSE events pushed by GET /api/reports/generate/stream.
export type GenerateProgressEvent =
  | { type: "start"; categories: string[] }
  | { type: "category_start"; category: string; index: number; total: number }
  | { type: "collected"; category: string; count: number }
  | { type: "clustered"; category: string; count: number }
  | {
      type: "summarizing_article"
      category: string
      article_index: number
      article_total: number
      article_title: string
    }
  | { type: "synthesizing_radio"; category: string }
  | {
      type: "category_done"
      category: string
      articles: number
      // Present when at least one article was synthesized for this category.
      // The frontend appends this to the dashboard state immediately so the
      // user can view / play the radio without waiting for the full batch.
      report?: Report
    }
  | { type: "done"; generated: number }
  // Client-side only: pushed after the server SSE finishes, during auto-dispatch chaining.
  | { type: "dispatching"; channels: string[] }
  | { type: "dispatched"; results: SendResult[] }
  | { type: "error"; message: string }
