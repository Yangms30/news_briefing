"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { motion } from "framer-motion"
import { toast } from "sonner"
import {
  ArrowLeft,
  Briefcase,
  Globe,
  Users,
  Trophy,
  Cpu,
  Landmark,
  Mail,
  Clock,
  Check,
  AlertTriangle,
  Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { api, BriefBotApiError } from "@/lib/api"
import { getUserId } from "@/lib/storage"
import { KOREAN_TO_CATEGORY_ID, categoryIdsToKorean } from "@/lib/categories"
import type { ChannelConfig } from "@/lib/types"

const categoryOptions = [
  { id: "politics", label: "정치", icon: Landmark },
  { id: "economy", label: "경제", icon: Briefcase },
  { id: "society", label: "사회", icon: Users },
  { id: "international", label: "국제", icon: Globe },
  { id: "sports", label: "스포츠", icon: Trophy },
  { id: "it-science", label: "IT/과학", icon: Cpu },
] as const

function cronToTime(cron: string | null | undefined): string {
  if (!cron) return "08:00"
  const parts = cron.trim().split(/\s+/)
  if (parts.length < 5) return "08:00"
  const mm = Number(parts[0])
  const hh = Number(parts[1])
  if (!Number.isFinite(mm) || !Number.isFinite(hh)) return "08:00"
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`
}

function timeToCron(time: string): string {
  const [hhRaw, mmRaw] = time.split(":")
  const hh = Math.min(23, Math.max(0, Math.trunc(Number(hhRaw) || 0)))
  const mm = Math.min(59, Math.max(0, Math.trunc(Number(mmRaw) || 0)))
  return `${mm} ${hh} * * *`
}

type EmailState = { enabled: boolean; address: string }
type SlackMode = "webhook" | "bot"
type SlackState = {
  enabled: boolean
  mode: SlackMode
  webhook: string
  botToken: string
  channelId: string
}

export default function SettingsPage() {
  const router = useRouter()
  const userId = getUserId()
  const [userName, setUserName] = useState<string>("")
  const [userEmail, setUserEmail] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [time, setTime] = useState<string>("08:00")
  const [email, setEmail] = useState<EmailState>({ enabled: false, address: "" })
  const [slack, setSlack] = useState<SlackState>({
    enabled: false,
    mode: "bot",
    webhook: "",
    botToken: "",
    channelId: "",
  })
  const [ttsEngine, setTtsEngine] = useState<"elevenlabs" | "openai">("elevenlabs")

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const [user, setting] = await Promise.all([
          api.users.get(userId),
          api.settings.get(userId).catch((err) => {
            if (err instanceof BriefBotApiError && err.status === 404) return null
            throw err
          }),
        ])
        if (cancelled) return
        setUserName(user.name)
        setUserEmail(user.email)
        if (setting) {
          const ids: string[] = []
          for (const ko of setting.categories) {
            const id = KOREAN_TO_CATEGORY_ID[ko as keyof typeof KOREAN_TO_CATEGORY_ID]
            if (id) ids.push(id)
          }
          setSelectedCategories(ids)
          setTime(cronToTime(setting.schedule_cron))
          setEmail({
            enabled: !!setting.channels.email,
            address: setting.channels.email ?? user.email,
          })
          {
            const ch = setting.channels
            const hasBot = !!(ch.slack_bot_token && ch.slack_channel_id)
            const hasWebhook = !!ch.slack
            setSlack({
              enabled: hasBot || hasWebhook,
              mode: hasBot ? "bot" : hasWebhook ? "webhook" : "bot",
              webhook: ch.slack ?? "",
              botToken: ch.slack_bot_token ?? "",
              channelId: ch.slack_channel_id ?? "",
            })
            if (ch.tts_engine === "openai" || ch.tts_engine === "elevenlabs") {
              setTtsEngine(ch.tts_engine)
            }
          }
        } else {
          setEmail({ enabled: false, address: user.email })
        }
      } catch (err) {
        const detail = err instanceof BriefBotApiError ? err.detail : (err as Error).message
        toast.error(`설정 로딩 실패: ${detail}`)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [userId])

  const toggleCategory = useCallback((id: string) => {
    setSelectedCategories((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    )
  }, [])

  const handleSave = async () => {
    if (saving) return
    if (selectedCategories.length === 0) {
      toast.error("카테고리를 최소 1개 이상 선택해주세요.")
      return
    }
    const channels: ChannelConfig = { web: true, tts_engine: ttsEngine }
    if (email.enabled && email.address.trim()) channels.email = email.address.trim()
    if (slack.enabled) {
      if (slack.mode === "bot") {
        if (slack.botToken.trim() && slack.channelId.trim()) {
          channels.slack_bot_token = slack.botToken.trim()
          channels.slack_channel_id = slack.channelId.trim()
        }
      } else if (slack.webhook.trim()) {
        channels.slack = slack.webhook.trim()
      }
    }

    setSaving(true)
    try {
      await toast.promise(
        api.settings.save(userId, {
          categories: categoryIdsToKorean(selectedCategories),
          schedule_cron: timeToCron(time),
          channels,
        }),
        {
          loading: "설정 저장 중…",
          success: "설정이 저장됐습니다.",
          error: (err) =>
            err instanceof BriefBotApiError
              ? `저장 실패: ${err.detail}`
              : `저장 실패: ${(err as Error).message}`,
        }
      ).unwrap()
      router.push("/dashboard")
    } catch {
      // toast already reported; stay on page so user can retry
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <div className="mx-auto max-w-3xl px-4 py-12 text-center text-muted-foreground">
          설정을 불러오는 중입니다…
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-4">
            <Link
              href="/dashboard"
              className="flex items-center gap-2 text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <h1 className="text-xl font-semibold">설정</h1>
          </div>
          <div className="text-right">
            <p className="text-sm font-medium">{userName}</p>
            <p className="text-xs text-muted-foreground">{userEmail}</p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-8">
        <div className="space-y-10">
          <section>
            <h2 className="mb-4 text-lg font-semibold">관심 카테고리</h2>
            <p className="mb-4 text-sm text-muted-foreground">
              브리핑 받을 카테고리를 선택하세요.
            </p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {categoryOptions.map((category) => {
                const isSelected = selectedCategories.includes(category.id)
                const Icon = category.icon
                return (
                  <motion.button
                    key={category.id}
                    onClick={() => toggleCategory(category.id)}
                    className={`relative flex items-center gap-3 rounded-xl border-2 p-4 text-left transition-all ${
                      isSelected
                        ? "border-primary bg-primary/10"
                        : "border-border bg-card hover:border-primary/50"
                    }`}
                    whileTap={{ scale: 0.98 }}
                  >
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                        isSelected ? "bg-primary text-white" : "bg-muted"
                      }`}
                    >
                      <Icon className="h-5 w-5" />
                    </div>
                    <span className="font-medium">{category.label}</span>
                    {isSelected && (
                      <div className="absolute right-3 top-3">
                        <Check className="h-4 w-4 text-primary" />
                      </div>
                    )}
                  </motion.button>
                )
              })}
            </div>
          </section>

          <section>
            <h2 className="mb-4 text-lg font-semibold">브리핑 주기</h2>
            <p className="mb-4 text-sm text-muted-foreground">
              브리핑을 받을 시간을 설정하세요. (하루 한 번)
            </p>
            <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-4">
              <Clock className="h-5 w-5 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">매일</span>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </section>

          <section>
            <h2 className="mb-4 text-lg font-semibold">채널 설정</h2>
            <p className="mb-4 text-sm text-muted-foreground">
              브리핑을 받을 채널을 설정하세요.
            </p>
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                      <Globe className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <p className="font-medium">웹 대시보드</p>
                      <p className="text-xs text-muted-foreground">항상 활성화됨</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-green-500">
                    <Check className="h-4 w-4" />
                    연결됨
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-border bg-card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                        email.enabled ? "bg-primary/10" : "bg-muted"
                      }`}
                    >
                      <Mail
                        className={`h-5 w-5 ${
                          email.enabled ? "text-primary" : "text-muted-foreground"
                        }`}
                      />
                    </div>
                    <div>
                      <p className="font-medium">이메일</p>
                      <p className="text-xs text-muted-foreground">이메일로 브리핑 수신</p>
                    </div>
                  </div>
                  <Switch
                    checked={email.enabled}
                    onCheckedChange={(checked) =>
                      setEmail((prev) => ({ ...prev, enabled: checked }))
                    }
                  />
                </div>
                {email.enabled && (
                  <div className="mt-4">
                    <Label className="text-sm text-muted-foreground">이메일 주소</Label>
                    <Input
                      type="email"
                      value={email.address}
                      onChange={(e) =>
                        setEmail((prev) => ({ ...prev, address: e.target.value }))
                      }
                      className="mt-1"
                      placeholder="email@example.com"
                    />
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-border bg-card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                        slack.enabled ? "bg-primary/10" : "bg-muted"
                      }`}
                    >
                      <AlertTriangle
                        className={`h-5 w-5 ${
                          slack.enabled ? "text-primary" : "text-muted-foreground"
                        }`}
                      />
                    </div>
                    <div>
                      <p className="font-medium">Slack</p>
                      <p className="text-xs text-muted-foreground">Slack으로 브리핑 수신</p>
                    </div>
                  </div>
                  <Switch
                    checked={slack.enabled}
                    onCheckedChange={(checked) =>
                      setSlack((prev) => ({ ...prev, enabled: checked }))
                    }
                  />
                </div>
                {slack.enabled && (
                  <div className="mt-4 space-y-4">
                    {/* Mode picker: Bot Token (audio) vs Webhook (text-only) */}
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setSlack((prev) => ({ ...prev, mode: "bot" }))
                        }
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition-all ${
                          slack.mode === "bot"
                            ? "border-primary bg-primary/10"
                            : "border-border bg-background hover:border-primary/50"
                        }`}
                      >
                        <div className="font-medium flex items-center gap-1.5">
                          Bot Token <span className="text-[10px] text-primary">🎧 오디오 포함</span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                          mp3가 Slack에 인라인 플레이어로 렌더
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setSlack((prev) => ({ ...prev, mode: "webhook" }))
                        }
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition-all ${
                          slack.mode === "webhook"
                            ? "border-primary bg-primary/10"
                            : "border-border bg-background hover:border-primary/50"
                        }`}
                      >
                        <div className="font-medium">Webhook</div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                          텍스트만 (설정 간단)
                        </div>
                      </button>
                    </div>

                    {slack.mode === "bot" ? (
                      <div className="space-y-3">
                        <div>
                          <Label className="text-sm text-muted-foreground">
                            Bot User OAuth Token
                          </Label>
                          <Input
                            type="text"
                            value={slack.botToken}
                            onChange={(e) =>
                              setSlack((prev) => ({ ...prev, botToken: e.target.value }))
                            }
                            className="mt-1 font-mono text-xs"
                            placeholder="xoxb-..."
                          />
                        </div>
                        <div>
                          <Label className="text-sm text-muted-foreground">Channel ID</Label>
                          <Input
                            type="text"
                            value={slack.channelId}
                            onChange={(e) =>
                              setSlack((prev) => ({ ...prev, channelId: e.target.value }))
                            }
                            className="mt-1 font-mono text-xs"
                            placeholder="C01234567"
                          />
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            Slack 채널 이름 우클릭 → "View channel details" → 하단에 표시
                          </p>
                        </div>
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                          Slack 앱에 <code>chat:write</code> + <code>files:write</code> 권한 필요.
                          앱을 워크스페이스에 설치하고 해당 채널에 <code>/invite @서신</code>으로 초대하세요.
                        </p>
                      </div>
                    ) : (
                      <div>
                        <Label className="text-sm text-muted-foreground">Webhook URL</Label>
                        <Input
                          type="url"
                          value={slack.webhook}
                          onChange={(e) =>
                            setSlack((prev) => ({ ...prev, webhook: e.target.value }))
                          }
                          className="mt-1"
                          placeholder="https://hooks.slack.com/services/..."
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section>
            <h2 className="mb-4 text-lg font-semibold">AI 모델</h2>
            <div className="space-y-3">
              <div className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
                <div className="font-medium text-foreground mb-1">텍스트 분석</div>
                OpenAI <code className="text-xs">gpt-5-mini</code>
              </div>

              <div className="rounded-xl border border-border bg-card p-4">
                <div className="font-medium mb-1">라디오 음성 엔진</div>
                <p className="mb-3 text-xs text-muted-foreground">
                  리포트를 mp3로 합성할 TTS 엔진을 고르세요. 엔진별 캐시가
                  분리돼 있어 변경해도 기존 파일은 유지됩니다.
                </p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => setTtsEngine("elevenlabs")}
                    className={`rounded-lg border px-3 py-3 text-left text-sm transition-all ${
                      ttsEngine === "elevenlabs"
                        ? "border-primary bg-primary/10"
                        : "border-border bg-background hover:border-primary/50"
                    }`}
                  >
                    <div className="font-medium flex items-center gap-1.5">
                      ElevenLabs
                      {ttsEngine === "elevenlabs" && (
                        <span className="text-[10px] text-primary">✓ 선택됨</span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1 leading-relaxed">
                      자연스러운 음성 · 월 10K자 무료
                      <br />
                      
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTtsEngine("openai")}
                    className={`rounded-lg border px-3 py-3 text-left text-sm transition-all ${
                      ttsEngine === "openai"
                        ? "border-primary bg-primary/10"
                        : "border-border bg-background hover:border-primary/50"
                    }`}
                  >
                    <div className="font-medium flex items-center gap-1.5">
                      OpenAI TTS
                      {ttsEngine === "openai" && (
                        <span className="text-[10px] text-primary">✓ 선택됨</span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1 leading-relaxed">
                      <code className="text-[11px]">gpt-4o-mini-tts</code> ·
                      pay-per-use
                      <br />
                    </div>
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section>
            <h2 className="mb-4 text-lg font-semibold">계정</h2>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label className="text-sm text-muted-foreground">이름</Label>
                  <p className="mt-1 font-medium">{userName}</p>
                </div>
                <div>
                  <Label className="text-sm text-muted-foreground">이메일</Label>
                  <p className="mt-1 font-medium">{userEmail}</p>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div className="sticky bottom-0 mt-10 flex gap-3 border-t border-border bg-background/80 px-4 py-4 backdrop-blur-xl -mx-4">
          <Button variant="outline" className="flex-1" asChild>
            <Link href="/dashboard">취소</Link>
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 bg-primary hover:bg-primary/90"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                저장 중…
              </>
            ) : (
              "저장하기"
            )}
          </Button>
        </div>
      </main>
    </div>
  )
}
