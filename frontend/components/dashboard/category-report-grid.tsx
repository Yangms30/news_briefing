"use client"

import { useState } from "react"
import { Clock, ExternalLink, Headphones, Pause, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import type { Article, Report } from "@/lib/types"
import { categoryBadgeClass, formatRelativeTime } from "@/lib/briefing-display"

type Props = {
  reports: Report[]
  playingCategory: string | null
  onPlayCategory: (category: string) => void
  onPauseCategory: () => void
}

export function CategoryReportGrid({ reports, playingCategory, onPlayCategory, onPauseCategory }: Props) {
  return (
    <div className="grid grid-cols-1 gap-6">
      {reports.map((r) => (
        <ReportSection
          key={r.id}
          report={r}
          isPlaying={playingCategory === r.category}
          onPlay={() => onPlayCategory(r.category)}
          onPause={onPauseCategory}
        />
      ))}
    </div>
  )
}

export function ReportSection({
  report,
  isPlaying,
  onPlay,
  onPause,
}: {
  report: Report
  isPlaying: boolean
  onPlay: () => void
  onPause: () => void
}) {
  const [radioOpen, setRadioOpen] = useState(false)
  const badge = categoryBadgeClass(report.category)
  const time = formatRelativeTime(report.created_at)

  return (
    <section className="rounded-2xl border border-border/60 bg-card/60 p-5 shadow-sm">
      <header className="flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <span className={cn("px-3 py-1 rounded-full text-xs font-semibold border", badge)}>
            {report.category}
          </span>
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="w-3 h-3" />
            {time}
          </span>
          <span className="text-xs text-muted-foreground">· 기사 {report.articles.length}건</span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={isPlaying ? "default" : "outline"}
            className={cn("gap-1.5", isPlaying && "bg-primary text-primary-foreground")}
            onClick={() => (isPlaying ? onPause() : onPlay())}
            disabled={!report.radio_script}
          >
            {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            {isPlaying ? "일시정지" : "이 분야 라디오"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => setRadioOpen((s) => !s)}
            disabled={!report.radio_script}
          >
            <Headphones className="w-4 h-4 mr-1" />
            스크립트
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {report.articles.map((a) => (
          <ArticleCard key={a.id} article={a} />
        ))}
      </div>

      {radioOpen && report.radio_script && (
        <div className="mt-4 p-4 rounded-xl bg-[#fff7f0] border border-[#fde4d1] text-sm text-foreground whitespace-pre-line leading-relaxed">
          {report.radio_script}
        </div>
      )}
    </section>
  )
}

function ArticleCard({ article }: { article: Article }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          className="group flex flex-col gap-2 rounded-xl border border-border/50 bg-background p-4 text-left transition-all hover:border-primary/40 hover:shadow-md hover:-translate-y-0.5 cursor-pointer"
        >
          <div className="text-[11px] text-muted-foreground">{article.source ?? "출처 미상"}</div>
          <h3 className="text-sm font-semibold text-foreground line-clamp-2 leading-snug">
            {article.title}
          </h3>
          <p className="text-xs text-muted-foreground whitespace-pre-line line-clamp-5 leading-relaxed">
            {article.summary}
          </p>
          <div className="mt-auto flex items-center gap-1 text-xs text-primary group-hover:underline">
            요약 전체 보기
          </div>
        </button>
      </DialogTrigger>

      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="text-xs text-muted-foreground mb-1">{article.source ?? "출처 미상"}</div>
          <DialogTitle className="text-lg leading-snug pr-6">{article.title}</DialogTitle>
          <DialogDescription className="sr-only">
            AI가 생성한 3줄 요약과 원문 링크
          </DialogDescription>
        </DialogHeader>

        <div className="mt-2 rounded-lg bg-muted/40 p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
            AI 3줄 요약
          </div>
          <p className="text-sm text-foreground whitespace-pre-line leading-relaxed">
            {article.summary}
          </p>
        </div>

        <DialogFooter className="sm:justify-between gap-2 mt-2">
          <span className="text-[11px] text-muted-foreground self-center">
            요약은 AI가 생성했으며 원문과 세부 표현이 다를 수 있습니다.
          </span>
          <Button asChild size="sm" className="gap-1.5">
            <a href={article.link} target="_blank" rel="noreferrer noopener">
              <ExternalLink className="w-4 h-4" />
              원문 기사로 이동
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
