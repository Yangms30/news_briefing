"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard/dashboard-header"
import { RadioPlayerBar } from "@/components/dashboard/radio-player-bar"
import { QuickActions } from "@/components/dashboard/quick-actions"
import {
  DateGroupedDashboard,
  localDateKey,
  parseUtcIso,
} from "@/components/dashboard/date-grouped-dashboard"
import { GenerationProgressPanel } from "@/components/dashboard/generation-progress-panel"
import { Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api, BriefBotApiError } from "@/lib/api"
import { getUserId } from "@/lib/storage"
import type { GenerateProgressEvent, Report, Setting } from "@/lib/types"

const categories = ["전체", "정치", "경제", "사회", "국제", "스포츠", "IT/과학"]

export default function DashboardPage() {
  const userId = getUserId()
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState("전체")
  const [isExpanded, setIsExpanded] = useState(true)
  const [pendingPlay, setPendingPlay] = useState<string | null>(null)
  const [pendingPlayReportId, setPendingPlayReportId] = useState<number | null>(null)
  const [playingCategory, setPlayingCategory] = useState<string | null>(null)
  const [playingReportId, setPlayingReportId] = useState<number | null>(null)
  const [pauseSignal, setPauseSignal] = useState(0)
  const [progressEvents, setProgressEvents] = useState<GenerateProgressEvent[]>([])
  const [setting, setSetting] = useState<Setting | null>(null)
  // Which date sections are expanded in the grouped dashboard. Today is
  // auto-expanded on mount; past dates start collapsed. This state controls
  // BOTH the accordion UI and the radio player's playback queue (see
  // `radioQueueReports` below) — a section has to be visible to be playable.
  const [openDateKeys, setOpenDateKeys] = useState<Set<string>>(() =>
    new Set([localDateKey(new Date())])
  )

  const handleToggleDate = useCallback((dateKey: string) => {
    setOpenDateKeys((prev) => {
      const next = new Set(prev)
      if (next.has(dateKey)) next.delete(dateKey)
      else next.add(dateKey)
      return next
    })
  }, [])

  const fetchList = useCallback(async (id: number) => {
    try {
      // Pull every report (not just latest-per-category) so the date-grouped
      // dashboard can show past days. Newest-first ordering preserved by the API.
      const list = await api.reports.list(id, { latestOnly: false })
      setReports(list)
    } catch (err) {
      const detail = err instanceof BriefBotApiError ? err.detail : (err as Error).message
      toast.error(`리포트 목록 로딩 실패: ${detail}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void fetchList(userId)
    // Fetch current setting once so handleGenerate can announce which channels will receive.
    api.settings
      .get(userId)
      .then(setSetting)
      .catch(() => {
        // Non-fatal: chaining will just fall back to generic labels.
      })
  }, [userId, fetchList])

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    setProgressEvents([])
    try {
      await api.reports.generateStream(userId, (event) => {
        setProgressEvents((prev) => [...prev, event])
        // Incremental rendering: as soon as a category finishes and the server
        // ships its fully-realized Report, insert it into the grid so the user
        // can read / listen to that category without waiting for the whole
        // batch. Any older report for the same category is replaced — the
        // dashboard is a "latest per category" view.
        if (event.type === "category_done" && event.report) {
          const fresh = event.report
          setReports((prev) => {
            const others = prev.filter((r) => r.category !== fresh.category)
            return [fresh, ...others]
          })
        }
      })
      await fetchList(userId)

      // Auto-dispatch: once reports exist, push them to configured channels.
      const channelLabels = activeChannelLabels(setting)
      setProgressEvents((prev) => [
        ...prev,
        { type: "dispatching", channels: channelLabels },
      ])
      try {
        const res = await api.send.dispatch(userId)
        setProgressEvents((prev) => [
          ...prev,
          { type: "dispatched", results: res.results },
        ])
        const total = res.results.length
        if (total === 0) {
          toast.success("리포트 생성 완료 · 활성화된 외부 채널 없음")
        } else {
          const ok = res.results.filter((r) => r.status === "success").length
          toast.success(`리포트 생성 완료 · ${ok}/${total} 채널 발송`)
        }
      } catch (err) {
        const detail =
          err instanceof BriefBotApiError ? err.detail : (err as Error).message
        setProgressEvents((prev) => [
          ...prev,
          { type: "error", message: `메일 발송 실패: ${detail}` },
        ])
        toast.error(
          `메일 발송 실패: ${detail} (대시보드에는 리포트가 저장됐습니다)`,
        )
      }

      setTimeout(() => setProgressEvents([]), 4000)
    } catch (err) {
      const detail =
        err instanceof BriefBotApiError ? err.detail : (err as Error).message
      toast.error(`생성 실패: ${detail}`)
      setProgressEvents((prev) => [
        ...prev,
        { type: "error", message: detail },
      ])
    } finally {
      setGenerating(false)
    }
  }

  const handleSend = async () => {
    if (sending) return
    setSending(true)
    try {
      await toast.promise(api.send.dispatch(userId), {
        loading: "메일/슬랙 발송 중…",
        success: (res) => {
          const ok = res.results.filter((r) => r.status === "success").length
          const total = res.results.length
          if (total === 0) return "활성화된 채널이 없습니다."
          return `${ok}/${total} 채널 발송 완료`
        },
        error: (err) =>
          err instanceof BriefBotApiError
            ? `발송 실패: ${err.detail}`
            : `발송 실패: ${(err as Error).message}`,
      }).unwrap()
    } catch {
      // toast already reported
    } finally {
      setSending(false)
    }
  }

  const filtered = useMemo(
    () => (selectedCategory === "전체" ? reports : reports.filter((r) => r.category === selectedCategory)),
    [reports, selectedCategory]
  )

  // Radio player queue = primary report per (date × category) for every
  // currently-expanded date section. Collapsed dates contribute nothing,
  // which keeps the queue scoped to what the user can actually see.
  // `reports` is DESC by `created_at`, so the first entry encountered per
  // (date, category) pair is the newest — the "primary" card.
  const radioQueueReports = useMemo(() => {
    const byDateCat = new Map<string, Report>()
    for (const r of reports) {
      const d = parseUtcIso(r.created_at)
      if (Number.isNaN(d.getTime())) continue
      const dk = localDateKey(d)
      if (!openDateKeys.has(dk)) continue
      const key = `${dk}::${r.category}`
      if (!byDateCat.has(key)) byDateCat.set(key, r)
    }
    return Array.from(byDateCat.values())
  }, [reports, openDateKeys])

  return (
    <div className="min-h-screen">
      <DashboardHeader />

      <RadioPlayerBar
        reports={radioQueueReports}
        isExpanded={isExpanded}
        setIsExpanded={setIsExpanded}
        externalCategory={pendingPlay}
        onExternalConsumed={() => setPendingPlay(null)}
        onPlayingCategoryChange={(cat) => {
          setPlayingCategory(cat)
          // When the player clears (cat === null), also clear the playing id.
          if (cat === null) setPlayingReportId(null)
        }}
        externalPauseSignal={pauseSignal}
        externalReportId={pendingPlayReportId}
        onExternalReportConsumed={() => setPendingPlayReportId(null)}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 pb-12">
        <QuickActions
          categories={categories}
          selectedCategory={selectedCategory}
          setSelectedCategory={setSelectedCategory}
          onGenerate={handleGenerate}
          generating={generating}
          onSend={handleSend}
          sending={sending}
          hasReports={reports.length > 0}
        />

        <GenerationProgressPanel events={progressEvents} isRunning={generating} />

        {loading ? (
          <div className="py-20 text-center text-muted-foreground">
            리포트를 불러오는 중입니다…
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState onGenerate={handleGenerate} generating={generating} hasAny={reports.length > 0} />
        ) : (
          <DateGroupedDashboard
            reports={filtered}
            playingCategory={playingCategory}
            playingReportId={playingReportId}
            openDateKeys={openDateKeys}
            onToggleDate={handleToggleDate}
            onPlayCategory={(cat) => {
              setPendingPlay(cat)
              setPlayingReportId(null)
            }}
            onPlayReportId={(id) => {
              setPendingPlayReportId(id)
              setPlayingReportId(id)
            }}
            onPauseCategory={() => {
              setPauseSignal((s) => s + 1)
              setPlayingCategory(null)
              setPlayingReportId(null)
            }}
          />
        )}
      </main>
    </div>
  )
}

function activeChannelLabels(setting: Setting | null): string[] {
  if (!setting) return []
  const out: string[] = []
  if (setting.channels.email) out.push("이메일")
  if (setting.channels.slack) out.push("Slack")
  return out
}

function EmptyState({
  onGenerate,
  generating,
  hasAny,
}: {
  onGenerate: () => void
  generating: boolean
  hasAny: boolean
}) {
  return (
    <div className="py-20 text-center space-y-4">
      <p className="text-muted-foreground">
        {hasAny
          ? "선택한 필터 조건에 해당하는 리포트가 없습니다."
          : "아직 리포트가 없어요. 첫 리포트를 생성해 보세요."}
      </p>
      {!hasAny && (
        <Button onClick={onGenerate} disabled={generating} size="lg" className="gap-2">
          <Sparkles className="w-5 h-5" />
          지금 리포트 받기
        </Button>
      )}
    </div>
  )
}
