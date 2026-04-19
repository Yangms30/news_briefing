"use client"

import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { ReportSection } from "@/components/dashboard/category-report-grid"
import type { Report } from "@/lib/types"

/**
 * Dashboard renders reports grouped by the day they were generated. Today's
 * section is auto-expanded; past-date sections start collapsed. Within each
 * day group, the latest report per category is shown by default, and any
 * additional same-day reports for that category are hidden behind a
 * "더 보기 (N)" toggle — user picked option (c) from the UI design Q&A.
 */

type Props = {
  /** Already filtered by selectedCategory tab; groups still work per-date. */
  reports: Report[]
  /** Category currently being played in the radio bar (for primary cards). */
  playingCategory: string | null
  /** Called when a primary (latest-per-category-per-date) card's play is tapped. */
  onPlayCategory: (category: string) => void
  /** Called when the primary category card is paused. */
  onPauseCategory: () => void
  /** Called when a non-primary (older same-day) card is played — by report id. */
  onPlayReportId: (reportId: number) => void
  /** Report id currently playing (used to highlight play state on non-primary cards). */
  playingReportId: number | null
}

/**
 * Backend emits datetime.utcnow() without a tz suffix. `new Date(iso)` in the
 * browser then silently treats it as local time, which shifts the date key.
 * Force UTC interpretation before formatting for consistent day grouping.
 */
function parseUtcIso(iso: string): Date {
  if (!iso) return new Date(NaN)
  const hasTz = iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasTz ? iso : `${iso}Z`)
}

/** Local-timezone YYYY-MM-DD for stable grouping + map lookup. */
function localDateKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

/** Human-readable Korean date heading for a section. */
function formatDateHeading(d: Date, isToday: boolean): string {
  const base = d.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  })
  return isToday ? `오늘 · ${base}` : base
}

type DateGroup = {
  dateKey: string
  heading: string
  isToday: boolean
  byCategory: Array<{
    category: string
    primary: Report
    older: Report[]
  }>
}

function groupByDateThenCategory(reports: Report[]): DateGroup[] {
  const todayKey = localDateKey(new Date())

  // Map<dateKey, Map<category, Report[]>>. The dateKey insertion order tracks
  // the input order of `reports`. Input is expected newest-first from the API,
  // which means both map iteration and in-category arrays are already DESC.
  const byDate = new Map<string, Map<string, Report[]>>()
  for (const r of reports) {
    const d = parseUtcIso(r.created_at)
    if (Number.isNaN(d.getTime())) continue
    const key = localDateKey(d)
    if (!byDate.has(key)) byDate.set(key, new Map())
    const byCat = byDate.get(key)!
    if (!byCat.has(r.category)) byCat.set(r.category, [])
    byCat.get(r.category)!.push(r)
  }

  const out: DateGroup[] = []
  for (const [dateKey, byCat] of byDate) {
    const parsed = parseUtcIso(byCat.values().next().value![0].created_at)
    const isToday = dateKey === todayKey
    const categories: DateGroup["byCategory"] = []
    for (const [category, list] of byCat) {
      // list is DESC because input is DESC (newest-first).
      const [primary, ...older] = list
      categories.push({ category, primary, older })
    }
    out.push({
      dateKey,
      heading: formatDateHeading(parsed, isToday),
      isToday,
      byCategory: categories,
    })
  }
  // Ensure dates are sorted DESC even if input order gets shuffled upstream.
  out.sort((a, b) => b.dateKey.localeCompare(a.dateKey))
  return out
}

function CategoryGroup({
  category,
  primary,
  older,
  isPrimaryPlaying,
  playingReportId,
  onPlayPrimary,
  onPauseCategory,
  onPlayReportId,
}: {
  category: string
  primary: Report
  older: Report[]
  isPrimaryPlaying: boolean
  playingReportId: number | null
  onPlayPrimary: () => void
  onPauseCategory: () => void
  onPlayReportId: (id: number) => void
}) {
  const [showOlder, setShowOlder] = useState(false)

  return (
    <div className="space-y-3">
      <ReportSection
        report={primary}
        isPlaying={isPrimaryPlaying}
        onPlay={onPlayPrimary}
        onPause={onPauseCategory}
      />

      {older.length > 0 && (
        <div className="pl-4 border-l-2 border-muted/60 space-y-3">
          <button
            type="button"
            onClick={() => setShowOlder((s) => !s)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {showOlder ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )}
            <span>
              {showOlder ? `접기 (${category})` : `${category} 이전 리포트 더 보기 (${older.length}개)`}
            </span>
          </button>

          {showOlder && (
            <div className="space-y-3">
              {older.map((r) => (
                <ReportSection
                  key={r.id}
                  report={r}
                  isPlaying={playingReportId === r.id}
                  onPlay={() => onPlayReportId(r.id)}
                  onPause={onPauseCategory}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function DateSection({
  group,
  playingCategory,
  playingReportId,
  onPlayCategory,
  onPauseCategory,
  onPlayReportId,
}: {
  group: DateGroup
  playingCategory: string | null
  playingReportId: number | null
  onPlayCategory: (category: string) => void
  onPauseCategory: () => void
  onPlayReportId: (id: number) => void
}) {
  const [open, setOpen] = useState(group.isToday)

  return (
    <section className="rounded-2xl border border-border/50 bg-background/40">
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        className={cn(
          "w-full flex items-center justify-between px-4 py-3 text-left rounded-2xl",
          "hover:bg-muted/30 transition-colors"
        )}
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="w-4 h-4 text-muted-foreground" />
          )}
          <h2
            className={cn(
              "text-sm font-semibold",
              group.isToday ? "text-foreground" : "text-muted-foreground"
            )}
          >
            {group.heading}
          </h2>
          <span className="text-xs text-muted-foreground">
            · {group.byCategory.reduce(
              (acc, c) => acc + 1 + c.older.length,
              0,
            )}건
          </span>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 space-y-4">
          {group.byCategory.map((c) => (
            <CategoryGroup
              key={c.category}
              category={c.category}
              primary={c.primary}
              older={c.older}
              isPrimaryPlaying={
                playingCategory === c.category && playingReportId === c.primary.id
              }
              playingReportId={playingReportId}
              onPlayPrimary={() => onPlayCategory(c.category)}
              onPauseCategory={onPauseCategory}
              onPlayReportId={onPlayReportId}
            />
          ))}
        </div>
      )}
    </section>
  )
}

export function DateGroupedDashboard({
  reports,
  playingCategory,
  onPlayCategory,
  onPauseCategory,
  onPlayReportId,
  playingReportId,
}: Props) {
  const groups = useMemo(() => groupByDateThenCategory(reports), [reports])

  if (groups.length === 0) return null

  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <DateSection
          key={g.dateKey}
          group={g}
          playingCategory={playingCategory}
          playingReportId={playingReportId}
          onPlayCategory={onPlayCategory}
          onPauseCategory={onPauseCategory}
          onPlayReportId={onPlayReportId}
        />
      ))}
    </div>
  )
}
