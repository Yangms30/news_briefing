const CATEGORY_BADGE: Record<string, string> = {
  정치: "bg-rose-500/10 text-rose-600 border-rose-500/30",
  경제: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
  사회: "bg-amber-500/10 text-amber-700 border-amber-500/30",
  국제: "bg-blue-500/10 text-blue-600 border-blue-500/30",
  스포츠: "bg-[#f26930]/10 text-[#f26930] border-[#f26930]/30",
  "IT/과학": "bg-violet-500/10 text-violet-600 border-violet-500/30",
}

const DEFAULT_BADGE = "bg-slate-500/10 text-slate-600 border-slate-500/30"

export function categoryBadgeClass(category: string): string {
  return CATEGORY_BADGE[category] ?? DEFAULT_BADGE
}

/**
 * Backend stores timestamps as naive UTC (datetime.utcnow()). Pydantic
 * serializes them without a tz suffix, so `new Date(iso)` in the browser
 * silently treats the string as *local* time — which is wrong. For KST
 * (UTC+9) this makes everything look ~9 hours old. Force UTC interpretation
 * by appending "Z" when no timezone indicator is present.
 */
export function parseUtcIso(iso: string | null | undefined): Date {
  if (!iso) return new Date(NaN)
  const hasTz = iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasTz ? iso : `${iso}Z`)
}

export function formatRelativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ""
  const d = parseUtcIso(iso)
  if (Number.isNaN(d.getTime())) return ""
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1) return "방금 전"
  if (diffMin < 60) return `${diffMin}분 전`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}시간 전`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}일 전`
  return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" })
}
