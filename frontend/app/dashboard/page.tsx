"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard/dashboard-header"
import { RadioPlayerBar } from "@/components/dashboard/radio-player-bar"
import { QuickActions } from "@/components/dashboard/quick-actions"
import { CategoryReportGrid } from "@/components/dashboard/category-report-grid"
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
  const [playingCategory, setPlayingCategory] = useState<string | null>(null)
  const [pauseSignal, setPauseSignal] = useState(0)
  const [progressEvents, setProgressEvents] = useState<GenerateProgressEvent[]>([])
  const [setting, setSetting] = useState<Setting | null>(null)

  const fetchList = useCallback(async (id: number) => {
    try {
      const list = await api.reports.list(id)
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

  return (
    <div className="min-h-screen">
      <DashboardHeader />

      <RadioPlayerBar
        reports={reports}
        isExpanded={isExpanded}
        setIsExpanded={setIsExpanded}
        externalCategory={pendingPlay}
        onExternalConsumed={() => setPendingPlay(null)}
        onPlayingCategoryChange={setPlayingCategory}
        externalPauseSignal={pauseSignal}
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
          <CategoryReportGrid
            reports={filtered}
            playingCategory={playingCategory}
            onPlayCategory={(cat) => setPendingPlay(cat)}
            onPauseCategory={() => {
              setPauseSignal((s) => s + 1)
              setPlayingCategory(null)
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
