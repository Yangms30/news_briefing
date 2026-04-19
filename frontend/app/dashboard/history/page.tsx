"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { toast } from "sonner"
import {
  ArrowLeft,
  Archive,
  Check,
  XCircle,
  MinusCircle,
  Globe,
  Mail,
  MessageSquare,
  Loader2,
} from "lucide-react"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { DashboardHeader } from "@/components/dashboard/dashboard-header"
import { api, BriefBotApiError } from "@/lib/api"
import { getUserId } from "@/lib/storage"
import { categoryBadgeClass, formatRelativeTime } from "@/lib/briefing-display"
import { cn } from "@/lib/utils"
import type { DispatchChannel, DispatchDetail, DispatchSummary } from "@/lib/types"

/**
 * Backend stores sent_at as naive UTC (datetime.utcnow). Pydantic serializes
 * without a timezone suffix, so `new Date(iso)` in modern browsers treats it
 * as local time — which is wrong. Force-UTC interpretation here before any
 * formatting / grouping.
 */
function parseUtcIso(iso: string): Date {
  if (!iso) return new Date(NaN)
  const hasTz = iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasTz ? iso : `${iso}Z`)
}

function formatDateKey(date: Date): string {
  // Stable, locale-formatted date used as the section heading (also groups same days).
  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  })
}

function formatTimeOnly(date: Date): string {
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
}

function channelIcon(channel: string) {
  if (channel === "email") return <Mail className="w-3.5 h-3.5" />
  if (channel === "slack") return <MessageSquare className="w-3.5 h-3.5" />
  return <Globe className="w-3.5 h-3.5" />
}

function channelLabel(channel: string): string {
  if (channel === "email") return "이메일"
  if (channel === "slack") return "Slack"
  if (channel === "web") return "웹"
  return channel
}

function statusTone(status: string): {
  className: string
  Icon: typeof Check
  label: string
} {
  if (status === "success") {
    return {
      className: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
      Icon: Check,
      label: "성공",
    }
  }
  if (status === "failed") {
    return {
      className: "bg-rose-500/10 text-rose-600 border-rose-500/30",
      Icon: XCircle,
      label: "실패",
    }
  }
  return {
    className: "bg-slate-500/10 text-slate-500 border-slate-500/30",
    Icon: MinusCircle,
    label: "스킵",
  }
}

function formatRecipient(channel: DispatchChannel): string {
  const r = channel.recipient ?? ""
  if (channel.channel === "web") return "웹 대시보드"
  if (channel.channel === "slack") {
    if (!r) return "webhook (미기록)"
    // Mask long webhook URL: keep only the last 8 chars for identification.
    const tail = r.length > 8 ? r.slice(-8) : r
    return `hooks.slack.com/…/${tail}`
  }
  return r || "(주소 없음)"
}

type ChannelPillProps = { channel: DispatchChannel }
function ChannelPill({ channel }: ChannelPillProps) {
  const tone = statusTone(channel.status)
  const { Icon } = tone
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        tone.className
      )}
      title={channel.error_msg ?? undefined}
    >
      {channelIcon(channel.channel)}
      <span>{channelLabel(channel.channel)}</span>
      <Icon className="w-3 h-3" />
    </span>
  )
}

function BatchHeader({ dispatch }: { dispatch: DispatchSummary }) {
  const sent = parseUtcIso(dispatch.sent_at)
  const hasFailed = dispatch.channels.some((c) => c.status === "failed")
  return (
    <div className="flex w-full flex-col gap-2 text-left sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-foreground tabular-nums">
          {formatTimeOnly(sent)}
        </span>
        <span className="text-xs text-muted-foreground">
          ({formatRelativeTime(sent.toISOString())})
        </span>
        {hasFailed && (
          <Badge
            variant="outline"
            className="border-rose-500/40 bg-rose-500/10 text-[11px] font-medium text-rose-600"
          >
            일부 실패
          </Badge>
        )}
        <span className="text-xs text-muted-foreground">
          · 리포트 {dispatch.report_count}건
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {dispatch.channels.map((c) => (
          <ChannelPill key={c.channel} channel={c} />
        ))}
      </div>
    </div>
  )
}

function ChannelDetailRow({ channel }: { channel: DispatchChannel }) {
  const tone = statusTone(channel.status)
  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          {channelIcon(channel.channel)}
          <span>{channelLabel(channel.channel)}</span>
          <span className={cn("rounded-full border px-2 py-0.5 text-xs", tone.className)}>
            {tone.label}
          </span>
        </div>
        <span className="text-xs text-muted-foreground break-all">
          {formatRecipient(channel)}
        </span>
      </div>
      {channel.error_msg && (
        <p className="mt-1 text-xs text-rose-600">{channel.error_msg}</p>
      )}
    </div>
  )
}

function DispatchBody({ detail }: { detail: DispatchDetail | undefined }) {
  if (!detail) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin" />
        상세 정보를 불러오는 중…
      </div>
    )
  }
  return (
    <div className="space-y-4 py-2">
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          채널별 결과
        </h4>
        <div className="space-y-2">
          {detail.channels.map((c) => (
            <ChannelDetailRow key={c.channel} channel={c} />
          ))}
        </div>
      </div>
      <Separator />
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          포함된 리포트 ({detail.reports.length})
        </h4>
        {detail.reports.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            포함된 리포트가 없거나 원본 리포트가 삭제됐습니다.
          </p>
        ) : (
          <div className="space-y-3">
            {detail.reports.map((r) => (
              <div
                key={r.id}
                className="rounded-lg border border-border/60 bg-card px-3 py-3"
              >
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-xs font-medium",
                      categoryBadgeClass(r.category)
                    )}
                  >
                    {r.category}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    · 기사 {r.articles.length}건
                  </span>
                </div>
                {r.radio_script && (
                  <p className="mb-2 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                    {r.radio_script}
                  </p>
                )}
                {r.articles.length > 0 && (
                  <ul className="space-y-1">
                    {r.articles.map((a) => (
                      <li key={a.id} className="text-xs">
                        <a
                          href={a.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline"
                        >
                          {a.title}
                        </a>
                        {a.source && (
                          <span className="ml-1 text-muted-foreground">· {a.source}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function HistoryPage() {
  const userId = getUserId()
  const [dispatches, setDispatches] = useState<DispatchSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, DispatchDetail>>({})
  const [expanded, setExpanded] = useState<string[]>([])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.dispatches
      .list(userId)
      .then((list) => {
        if (!cancelled) setDispatches(list)
      })
      .catch((err) => {
        if (cancelled) return
        const detail = err instanceof BriefBotApiError ? err.detail : (err as Error).message
        setError(detail)
        toast.error(`아카이브 로딩 실패: ${detail}`)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  const ensureDetail = useCallback(
    async (id: string) => {
      if (detailCache[id]) return
      try {
        const d = await api.dispatches.get(id)
        setDetailCache((prev) => ({ ...prev, [id]: d }))
      } catch (err) {
        const detail = err instanceof BriefBotApiError ? err.detail : (err as Error).message
        toast.error(`상세 로딩 실패: ${detail}`)
      }
    },
    [detailCache]
  )

  const grouped = useMemo<[string, DispatchSummary[]][]>(() => {
    const map = new Map<string, DispatchSummary[]>()
    for (const d of dispatches) {
      const key = formatDateKey(parseUtcIso(d.sent_at))
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(d)
    }
    return Array.from(map.entries())
  }, [dispatches])

  const handleValueChange = (value: string[]) => {
    setExpanded(value)
    for (const id of value) {
      void ensureDetail(id)
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader />

      <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6 flex items-center gap-3">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            대시보드로
          </Link>
        </div>

        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/20">
            <Archive className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">발송 이력 아카이브</h1>
            <p className="text-sm text-muted-foreground">
              "지금 리포트 받기" 한 번이 1건으로 기록됩니다.
            </p>
          </div>
        </div>

        {loading && (
          <div className="flex items-center gap-2 py-12 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            아카이브를 불러오는 중…
          </div>
        )}

        {!loading && error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-600">
            {error}
          </div>
        )}

        {!loading && !error && dispatches.length === 0 && (
          <div className="rounded-xl border border-dashed border-border bg-card/40 p-8 text-center">
            <p className="text-sm text-muted-foreground">
              아직 발송된 리포트가 없습니다. 대시보드에서 "지금 리포트 받기"를 눌러
              첫 배치를 만들어보세요.
            </p>
          </div>
        )}

        {!loading && !error && dispatches.length > 0 && (
          <div className="space-y-8">
            {grouped.map(([dateLabel, items]) => (
              <section key={dateLabel}>
                <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
                  {dateLabel}
                </h2>
                <Accordion
                  type="multiple"
                  value={expanded}
                  onValueChange={handleValueChange}
                  className="space-y-2"
                >
                  {items.map((d) => (
                    <AccordionItem
                      key={d.dispatch_id}
                      value={d.dispatch_id}
                      className="rounded-xl border border-border bg-card px-4"
                    >
                      <AccordionTrigger className="py-3 hover:no-underline">
                        <BatchHeader dispatch={d} />
                      </AccordionTrigger>
                      <AccordionContent>
                        <DispatchBody detail={detailCache[d.dispatch_id]} />
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </section>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
