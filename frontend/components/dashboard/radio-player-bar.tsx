"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  Headphones,
  ChevronUp,
  ChevronDown,
  Check,
  Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { cn } from "@/lib/utils"
import { getReportAudioUrl } from "@/lib/api"
import type { Report } from "@/lib/types"

type RadioPlayerBarProps = {
  reports: Report[]
  isExpanded: boolean
  setIsExpanded: (expanded: boolean) => void
  externalCategory?: string | null
  onExternalConsumed?: () => void
  onPlayingCategoryChange?: (category: string | null) => void
  /**
   * Monotonically increasing counter — each increment pauses the audio.
   * Used by the dashboard to pause playback when a CategoryReportGrid card
   * toggles to "paused" state.
   */
  externalPauseSignal?: number
  /**
   * Specific report id to play (takes precedence over externalCategory when set).
   * Used by past-date cards to play an older report rather than the current
   * latest-per-category. Report must be included in `reports` prop.
   */
  externalReportId?: number | null
  onExternalReportConsumed?: () => void
}

type LoadState = "idle" | "loading" | "ready" | "error"

function formatTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds))
  const mins = Math.floor(s / 60)
  const secs = s % 60
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

export function RadioPlayerBar({
  reports,
  isExpanded,
  setIsExpanded,
  externalCategory,
  onExternalConsumed,
  onPlayingCategoryChange,
  externalPauseSignal,
  externalReportId,
  onExternalReportConsumed,
}: RadioPlayerBarProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const lastPauseSignalRef = useRef(0)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(0.75)
  const [loadState, setLoadState] = useState<LoadState>("idle")
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const playable = useMemo(
    () => reports.filter((r) => (r.radio_script ?? "").trim().length > 0),
    [reports]
  )
  const current = playable[currentIndex]
  const audioSrc = current ? getReportAudioUrl(current.id) : undefined

  // Reset index if list shrinks.
  useEffect(() => {
    if (currentIndex >= playable.length && playable.length > 0) {
      setCurrentIndex(0)
      setCurrentTime(0)
    }
  }, [playable.length, currentIndex])

  // Keep element volume in sync.
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    el.volume = Math.max(0, Math.min(1, volume))
  }, [volume])

  // When src changes (track switch), reset state; autoplay next if we were playing.
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    setCurrentTime(0)
    setDuration(0)
    setErrorMessage(null)
    setLoadState(audioSrc ? "loading" : "idle")
    if (!audioSrc) return
    // If the user was in an active playing session, continue onto the new track.
    if (isPlaying && !isPaused) {
      const p = el.play()
      if (p && typeof p.catch === "function") {
        p.catch(() => {
          setIsPlaying(false)
          setLoadState("error")
          setErrorMessage("재생 실패 — 잠시 후 다시 시도해주세요")
        })
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioSrc])

  // Bridge: parent requests a specific report id (past-date cards).
  useEffect(() => {
    if (externalReportId === undefined || externalReportId === null) return
    const idx = playable.findIndex((r) => r.id === externalReportId)
    if (idx === -1) {
      onExternalReportConsumed?.()
      return
    }
    setIsPaused(false)
    setCurrentIndex(idx)
    setCurrentTime(0)
    setIsPlaying(true)
    onExternalReportConsumed?.()
  }, [externalReportId, playable, onExternalReportConsumed])

  // Bridge: parent requests a specific category (today's CategoryReportGrid).
  useEffect(() => {
    if (!externalCategory) return
    const idx = playable.findIndex((r) => r.category === externalCategory)
    if (idx === -1) {
      onExternalConsumed?.()
      return
    }
    setIsPaused(false)
    setCurrentIndex(idx)
    setCurrentTime(0)
    setIsPlaying(true)
    onExternalConsumed?.()
  }, [externalCategory, playable, onExternalConsumed])

  // Respond to external pause requests from sibling UI (category cards).
  useEffect(() => {
    if (externalPauseSignal === undefined) return
    if (externalPauseSignal <= lastPauseSignalRef.current) return
    lastPauseSignalRef.current = externalPauseSignal
    audioRef.current?.pause()
  }, [externalPauseSignal])

  // Notify parent of currently-playing category.
  useEffect(() => {
    if (!onPlayingCategoryChange) return
    if (isPlaying && !isPaused && current) {
      onPlayingCategoryChange(current.category)
    } else {
      onPlayingCategoryChange(null)
    }
  }, [isPlaying, isPaused, current, onPlayingCategoryChange])

  const handlePlayPause = useCallback(() => {
    const el = audioRef.current
    if (!el || !current) return
    if (isPlaying && !isPaused) {
      el.pause()
      return
    }
    setIsPaused(false)
    setIsPlaying(true)
    const p = el.play()
    if (p && typeof p.catch === "function") {
      p.catch((err: unknown) => {
        setIsPlaying(false)
        setLoadState("error")
        const msg = (err as Error)?.message ?? ""
        setErrorMessage(
          msg.includes("503") || msg.toLowerCase().includes("unavailable")
            ? "음성 서비스 일시 중단 — 서버 키 확인 필요"
            : "재생 실패 — 잠시 후 다시 시도해주세요"
        )
      })
    }
  }, [current, isPlaying, isPaused])

  const handleSkipForward = () => {
    if (currentIndex + 1 >= playable.length) return
    setIsPaused(false)
    setCurrentIndex((i) => i + 1)
  }

  const handleSkipBackward = () => {
    const el = audioRef.current
    if (el && currentTime > 2) {
      el.currentTime = 0
      setCurrentTime(0)
      return
    }
    if (currentIndex === 0) {
      if (el) {
        el.currentTime = 0
        setCurrentTime(0)
      }
      return
    }
    setIsPaused(false)
    setCurrentIndex((i) => i - 1)
  }

  const handleSeek = (value: number) => {
    const el = audioRef.current
    if (!el) return
    const t = Math.max(0, Math.min(duration || 0, value))
    el.currentTime = t
    setCurrentTime(t)
  }

  const handleVolumeChange = (v: number) => {
    setVolume(Math.max(0, Math.min(1, v / 100)))
  }

  // Audio element event handlers
  const onLoadedMetadata = (e: React.SyntheticEvent<HTMLAudioElement>) => {
    const d = e.currentTarget.duration
    setDuration(Number.isFinite(d) ? d : 0)
    setLoadState("ready")
  }
  const onTimeUpdate = (e: React.SyntheticEvent<HTMLAudioElement>) => {
    setCurrentTime(e.currentTarget.currentTime)
  }
  const onPlay = () => {
    setIsPlaying(true)
    setIsPaused(false)
  }
  const onPause = () => {
    // Pause fires on both user pause and end-of-track; distinguish via `ended`.
    if (audioRef.current?.ended) return
    setIsPaused(true)
  }
  const onEnded = () => {
    if (currentIndex + 1 < playable.length) {
      setIsPaused(false)
      setCurrentIndex((i) => i + 1)
    } else {
      setIsPlaying(false)
      setIsPaused(false)
    }
  }
  const onAudioError = () => {
    setLoadState("error")
    setIsPlaying(false)
    setErrorMessage(
      "음성을 불러오지 못했습니다. 서버 상태 또는 OPENAI_API_KEY를 확인해주세요."
    )
  }

  const label = current ? `${current.category} 분야 라디오` : "오늘의 분야별 라디오"
  const showLoader = loadState === "loading" && isPlaying && !isPaused
  const warning = loadState === "error" ? errorMessage : null
  const playDisabled = !current || loadState === "error"

  const categoryProgress = playable.map((r, i) => ({
    name: r.category,
    done: i < currentIndex,
    playing: i === currentIndex && isPlaying && !isPaused,
  }))

  if (playable.length === 0) return null

  const hiddenAudio = (
    <audio
      ref={audioRef}
      preload="none"
      src={audioSrc}
      onLoadStart={() => {
        setLoadState("loading")
        setErrorMessage(null)
      }}
      onCanPlay={() => setLoadState("ready")}
      onLoadedMetadata={onLoadedMetadata}
      onTimeUpdate={onTimeUpdate}
      onPlay={onPlay}
      onPause={onPause}
      onEnded={onEnded}
      onError={onAudioError}
    />
  )

  if (!isExpanded) {
    return (
      <div className="sticky top-16 z-40 border-b border-border/50 bg-card/90 backdrop-blur-xl">
        {hiddenAudio}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14 gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <Button
                variant="ghost"
                size="icon"
                className="w-10 h-10 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
                onClick={handlePlayPause}
                disabled={playDisabled}
              >
                {showLoader ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : isPlaying && !isPaused ? (
                  <Pause className="w-5 h-5" />
                ) : (
                  <Play className="w-5 h-5 ml-0.5" />
                )}
              </Button>
              <div className="flex items-center gap-2 text-muted-foreground min-w-0">
                <Headphones className="w-4 h-4 shrink-0" />
                <span className="text-sm font-medium truncate max-w-[260px]">{label}</span>
              </div>
            </div>

            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>{formatTime(currentTime)}</span>
              <span>/</span>
              <span>{formatTime(duration)}</span>
            </div>

            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setIsExpanded(true)}
            >
              <ChevronDown className="w-4 h-4 mr-1" />
              확장
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="sticky top-16 z-40 border-b border-border/50 bg-card/90 backdrop-blur-xl">
      {hiddenAudio}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-muted-foreground min-w-0">
              <Headphones className="w-5 h-5 text-primary shrink-0" />
              <span className="font-medium text-foreground truncate">{label}</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setIsExpanded(false)}
            >
              <ChevronUp className="w-4 h-4 mr-1" />
              축소
            </Button>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground"
                onClick={handleSkipBackward}
                disabled={playDisabled}
              >
                <SkipBack className="w-5 h-5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="w-12 h-12 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
                onClick={handlePlayPause}
                disabled={playDisabled}
              >
                {showLoader ? (
                  <Loader2 className="w-6 h-6 animate-spin" />
                ) : isPlaying && !isPaused ? (
                  <Pause className="w-6 h-6" />
                ) : (
                  <Play className="w-6 h-6 ml-0.5" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground"
                onClick={handleSkipForward}
                disabled={playDisabled || currentIndex + 1 >= playable.length}
              >
                <SkipForward className="w-5 h-5" />
              </Button>
            </div>

            <div className="flex-1 w-full sm:w-auto flex items-center gap-3">
              <span className="text-sm text-muted-foreground w-12 text-right">
                {formatTime(currentTime)}
              </span>
              <Slider
                value={[currentTime]}
                max={duration || 1}
                step={1}
                onValueChange={(value) => handleSeek(value[0])}
                className="flex-1"
              />
              <span className="text-sm text-muted-foreground w-12">
                {formatTime(duration)}
              </span>
            </div>

            <div className="hidden md:flex items-center gap-2 w-32">
              <Volume2 className="w-4 h-4 text-muted-foreground" />
              <Slider
                value={[Math.round(volume * 100)]}
                max={100}
                step={1}
                onValueChange={(value) => handleVolumeChange(value[0])}
              />
            </div>
          </div>

          {categoryProgress.length > 0 && (
            <div className="flex items-center justify-center gap-2 text-sm flex-wrap">
              {categoryProgress.map((cat, index) => (
                <div key={`${cat.name}-${index}`} className="flex items-center gap-2">
                  <span
                    className={cn(
                      "flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium",
                      cat.done && "bg-emerald-500/20 text-emerald-600",
                      cat.playing && "bg-primary/20 text-primary animate-pulse",
                      !cat.done && !cat.playing && "bg-muted text-muted-foreground"
                    )}
                  >
                    {cat.done && <Check className="w-3 h-3" />}
                    {cat.name}
                    {cat.playing && " (재생 중)"}
                  </span>
                  {index < categoryProgress.length - 1 && (
                    <span className="text-muted-foreground">→</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {warning && (
            <div className="text-center text-xs text-destructive">{warning}</div>
          )}
        </div>
      </div>
    </div>
  )
}
