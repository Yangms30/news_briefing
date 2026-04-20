# 서신 · 書信

> **오늘의 AI 뉴스 편지** — 가벼운 LLM으로도 똑똑하게. 파이프라인 엔지니어링으로 뉴스를 분석하고, 한 통의 편지처럼 매일 독자에게 전달합니다.

서울신문 과제평가 제출용 AI 이슈 브리핑 프로토타입. **Google News + 연합뉴스 + 서울신문 RSS + 네이버 검색 API 4개 소스를 병렬 수집**하고, OpenAI `gpt-5-nano`로 카테고리별 리포트(3건 요약 + 구어체 라디오 스크립트)를 생성하여 웹/Slack/이메일 채널로 자동 전달하는 풀스택 시스템입니다.

**최종 업데이트: 2026-04-19** — Day 1~4 누적 구현 완료(백엔드 파이프라인 + 프론트 연동 + 다채널 발송 + 스케줄러 + TTS + 로그인 제거). 남은 일정: Day 5 SMTP 키 주입 및 실기기 리허설 → 4/21 18:00 제출.

설계 원본 문서: [`plan.md`](./plan.md)

## 핵심 차별화 전략

1. **프롬프트 엔지니어링** — 복잡한 태스크를 "기사별 3줄 요약(Step1) → 카테고리별 구어체 라디오 스크립트(Step2)" 2단계로 분해
2. **컨텍스트 엔지니어링** — LLM 호출 전 TF-IDF + 코사인 유사도(0.6)로 뉴스 클러스터링, 대표 기사 2~3건만 모델에 전달하여 경량 모델의 성능 극대화
3. **하네스 엔지니어링** — 재시도(2회), RSS summary fallback, 카테고리 단위 forward-error-tolerant 루프로 LLM 바깥에서 품질 보장
4. **라디오 모드** — 같은 이슈 데이터를 문어체 요약 + 구어체 스크립트로 동시 생성, OpenAI `gpt-4o-mini-tts`(voice: `nova`)로 서버에서 mp3 합성·캐시 후 재생

## 아키텍처

```
┌───────────────────────┐   REST + SSE   ┌──────────────────────────────────┐
│  Next.js 16 UI        │ ─────────────▶ │  FastAPI                         │
│  (App Router, 3 routes)               │                                  │
│  • /  → /dashboard redirect           │  Routers                         │
│  • /dashboard         │                │   ├─ users                       │
│    - CategoryReportGrid                │   ├─ settings (PUT upsert)       │
│    - RadioPlayerBar   │                │   ├─ reports  (list/detail/     │
│      (OpenAI TTS mp3) │                │     generate + /audio + stream) │
│    - GenerationProgressPanel (SSE)     │   └─ send    (다채널 배치)       │
│  • /dashboard/settings│                │                                  │
└───────────────────────┘                │  Pipeline                        │
                                         │   ├─ collector    (GoogleRSS)   │
                                         │   ├─ preprocessor (TF-IDF)      │
                                         │   ├─ analyzer     (OpenAI 2단)  │
                                         │   └─ service      (오케스트레이션)│
                                         │                                  │
                                         │  Dispatcher                      │
                                         │   ├─ WebSender  (DB 저장)       │
                                         │   ├─ SlackSender (Block Kit)    │
                                         │   └─ EmailSender (SMTP HTML)    │
                                         │                                  │
                                         │  Scheduler (APScheduler)         │
                                         │   ⚠️ 데모 기간 의도적 비활성      │
                                         │                                  │
                                         │  SQLite (users · settings ·     │
                                         │   reports · articles · send_logs)│
                                         └──────────────────────────────────┘
```

## 기술 스택

| 구분 | 선택 | 상태 |
|------|------|------|
| Frontend | Next.js 16 (App Router) + React 19.2 + TypeScript strict + pnpm | ✅ |
| UI | shadcn/ui + Tailwind 4 + Framer Motion + Sonner | ✅ |
| Backend | FastAPI + SQLAlchemy + SQLite (Python 3.11+) | ✅ |
| LLM (메인) | OpenAI `gpt-5-nano` — 경량 모델, `temperature` 커스텀 불가(항상 1.0) | ✅ |
| LLM (레거시) | Gemini 2.5 Flash Lite — `GeminiAnalyzer` 클래스 유지, 현재 미사용 | ♻️ |
| News | Google News + 연합뉴스 + 서울신문 RSS + **네이버 검색 API** 4-source (`feedparser` + `httpx`, URL/title dedupe, 소스별 24h/20건) | ✅ |
| Clustering | scikit-learn TF-IDF + cosine similarity (threshold 0.6) | ✅ |
| Scheduler | APScheduler (Asia/Seoul) | ⚠️ 데모 기간 lifespan 주석처리 |
| 진행 스트리밍 | Server-Sent Events (`/api/reports/generate/stream`) | ✅ |
| Slack | Incoming Webhook + Block Kit JSON | ✅ |
| Email | SMTP (Gmail App Password) + 반응형 HTML | ⚠️ SMTP 키 주입 대기 |
| TTS | OpenAI `gpt-4o-mini-tts` (voice: `nova`) → mp3 디스크 캐시 | ✅ |

> 💡 **축소된 범위**: 원 설계에는 `Claude Haiku → Gemini Flash` 멀티모델 폴백과 `네이버 검색 API + NewsAPI + RSS` 다중 소스가 있었으나, 키 미발급으로 `OpenAI gpt-5-nano + Google News RSS` 단일 경로로 축소했습니다. `analyzer.py`는 Analyzer 클래스 치환만으로 폴백 복원 가능, `collector.py`도 Client 클래스 추가만으로 소스 확장 가능한 플러그인 구조입니다. 자세한 경위는 [`plan.md` 변경 이력](./plan.md#변경-이력) 참고.

## 프로젝트 구조

```
briefBot/
├── backend/                          # FastAPI + 파이프라인 + 다채널 발송
│   ├── main.py                       # 앱 엔트리, CORS, lifespan(데모 유저 시딩, 스케줄러 주석처리)
│   ├── config.py                     # pydantic-settings (OPENAI_*, SMTP_*, GEMINI_* 레거시)
│   ├── database.py                   # SQLAlchemy engine/session
│   ├── models.py                     # User · Setting · Report · Article · SendLog
│   ├── schemas.py                    # ReportOut / ArticleOut / ReportGenerateResponse
│   ├── routers/                      # users, settings, reports (SSE 포함), send
│   ├── pipeline/                     # collector, preprocessor, analyzer, service
│   ├── prompts/                      # article_summary.py (Step1), radio_script.py (Step2)
│   ├── dispatcher/                   # web, slack, email_sender, service
│   ├── scheduler.py                  # APScheduler cron 등록 (데모 기간 비활성)
│   └── scripts/                      # seed / ad-hoc 스크립트
├── frontend/                         # Next.js 16 App Router (3 routes)
│   ├── app/
│   │   ├── layout.tsx                # Sonner Toaster
│   │   ├── page.tsx                  # /dashboard 로 redirect (로그인 제거)
│   │   └── dashboard/
│   │       ├── page.tsx              # CategoryReportGrid + ProgressPanel + 생성+발송 체이닝
│   │       └── settings/page.tsx     # 카테고리/주기/채널/AI 모델 설정
│   ├── components/dashboard/
│   │   ├── category-report-grid.tsx        # 카테고리 카드 + 기사 요약 + ▶ 외부 재생 트리거
│   │   ├── generation-progress-panel.tsx   # SSE 단계별 진행 렌더
│   │   ├── radio-player-bar.tsx            # HTMLAudioElement + OpenAI TTS mp3 스트림
│   │   └── quick-actions.tsx               # "지금 리포트 받기" + 카테고리 필터
│   └── lib/                          # types, api, storage(DEMO_USER_ID=1 고정), schedule, categories, briefing-display
├── plan.md                           # 설계 원본 (소스 오브 트루스)
├── CLAUDE.md                         # 저장소 작업 가이드 (루트 인덱스)
└── README.md
```

하위 CLAUDE.md:
- [`backend/CLAUDE.md`](./backend/CLAUDE.md) — FastAPI 명령어, 파이프라인 구조, LLM 제약
- [`frontend/CLAUDE.md`](./frontend/CLAUDE.md) — Next.js/shadcn 규약, 라우트, 상태 관리

## 실행 방법

### 1. 백엔드

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env에 OPENAI_API_KEY를 채워넣으세요 (https://platform.openai.com/api-keys)
# 이메일 발송을 시연하려면 SMTP_USER / SMTP_PASSWORD(Gmail 앱 비밀번호) / SMTP_FROM도 입력
uvicorn main:app --reload --port 8000
```

- http://localhost:8000/docs 에서 Swagger UI 확인
- 첫 실행 시 `backend/briefbot.db` 자동 생성 + 데모 유저(`user_id=1`, 6카테고리, web/email 채널) 멱등 시딩
- 포트 8000 점유 시 `--port 8765` 등으로 변경

### 2. 프론트엔드

```bash
cd frontend
pnpm install
cp .env.example .env.local
# NEXT_PUBLIC_API_URL이 백엔드 주소와 맞는지 확인
pnpm dev
```

- http://localhost:3000 접속 → 곧바로 `/dashboard`로 리다이렉트(로그인 없음)

### 3. E2E 시연 시나리오

1. http://localhost:3000 접속 → 자동으로 대시보드 진입
2. 필요 시 우측 상단 **⚙️ 설정**에서 이메일 주소 / Slack Webhook / 카테고리 / 주기 조정
3. 대시보드 **"지금 리포트 받기"** 버튼 클릭
4. SSE Progress Panel에 `start → category_start → collected → clustered → summarizing_article → synthesizing_radio → category_done → done` 이벤트가 실시간 표시됨
5. 생성 완료 시 자동으로 `POST /api/send`가 체이닝되어 활성 채널(web/email/slack)로 일괄 발송
6. 카테고리별 카드에서 ▶ 버튼 클릭 → 라디오 바가 `GET /api/reports/{id}/audio`로 OpenAI TTS mp3를 스트림 재생 (첫 재생은 합성, 이후는 캐시 hit)

## API 엔드포인트

| Method | Endpoint | 설명 | 상태 |
|--------|----------|------|------|
| GET | `/api/users/{user_id}` | 유저 정보 조회 (로그인 제거로 POST 미노출) | ✅ |
| GET | `/api/settings/{user_id}` | 유저 설정 조회 | ✅ |
| PUT | `/api/settings/{user_id}` | 설정 upsert(카테고리/cron/채널) | ✅ |
| GET | `/api/reports?user_id=&category=&limit=` | 카테고리별 최신 리포트 1건 리스트 | ✅ |
| GET | `/api/reports/{report_id}` | 리포트 상세(articles 포함) | ✅ |
| GET | `/api/reports/articles/{article_id}` | 개별 기사 상세 | ✅ |
| POST | `/api/reports/generate?user_id={id}` | 즉시 리포트 생성(동기, 전 카테고리) | ✅ |
| GET | `/api/reports/generate/stream?user_id={id}` | **SSE 진행 스트림** | ✅ |
| POST | `/api/send?user_id={id}` | 최신 리포트를 활성 채널로 일괄 발송 | ✅ |
| GET | `/api/health` | 헬스 체크 | ✅ |

## 파이프라인 2단 구조

```
[Google News RSS]              카테고리별 쿼리, 24h/20건 컷
        │
        ▼
[Preprocessor]                 HTML/노이즈 제거
        │                      → TF-IDF + cosine (0.6) 클러스터링
        │                      → 대표 기사 2~3건 (최신순 + 출처 다양성)
        ▼
[OpenAIAnalyzer — LLM 구간, gpt-5-nano]
  ├─ Step1: 기사별 3줄 요약 (문어체)
  │         → 길이 검증 + 2회 재시도 → 실패 시 RSS summary fallback
  └─ Step2: 카테고리별 라디오 스크립트 (구어체, 숫자 한글 변환)
            → 실패 시 radio_script=NULL (graceful)
        │
        ▼
[SQLite reports + articles]   → Dispatcher (web/slack/email) → send_logs
```

> 4/17 후속 재설계: 기존 `Step1 구조화 추출(JSON) → Step2-A 3줄 브리핑 → Step2-B 라디오` 3단 구조를 **"기사 단위 요약 + 카테고리 단위 라디오"** 2단으로 축소. 분야별 리포트(카테고리당 기사 3건 + 라디오 1개)라는 데이터 모델과 1:N 정합. 중요도/감성 등 UI에서 소비되지 않는 필드는 제거.

## 개발 현황 (2026-04-19 기준)

| 마일스톤 | 내용 | 상태 |
|---------|------|------|
| Day 1 (4/17 오전) | 백엔드 뼈대 + 파이프라인 E2E (Gemini 초기 적용) | ✅ |
| Day 2 (4/17 오후) | 프론트 4개 페이지 실 API 연동 | ✅ |
| Day 3 (4/17 밤) | Slack/Email dispatcher + APScheduler + Web Speech API | ✅ |
| Day 3 후속 (4/17 새벽) | **OpenAI gpt-5-nano 교체 + briefings→reports/articles 재설계 + SSE 진행 스트리밍 + 상세 페이지 제거 + 생성·발송 체이닝** | ✅ |
| Day 4 (4/19) | 로그인/온보딩 제거(데모 간소화), 데모 유저 부팅 시딩, 스케줄러 의도적 비활성, plan.md 재정합 | ✅ |
| Day 5 (4/20) | SMTP 앱 비밀번호 발급 + `.env` 입력, 실기기 리허설, 제출 패키징 | ⬜ |
| 제출 (4/21 18:00) | 최종 점검 → GitHub 링크 제출 | ⬜ |

**누적 검증 결과**
- `POST /api/reports/generate?user_id=1` → OpenAI `gpt-5-nano` 호출 후 카테고리별 Report + Articles 생성, SQLite 저장, `radio_script` 포함
- `GET /api/reports/generate/stream?user_id=1` → `start` 이벤트부터 `done`까지 SSE 정상 흐름
- `POST /api/send?user_id=1` → 활성 채널(web / email / slack) 결과 반환 + `send_logs` 기록
- 프론트: `pnpm exec tsc --noEmit` pass, `pnpm exec next build` pass (3 routes)
- 남은 실기기 검증: ① Gmail SMTP 앱 비밀번호 기입 후 실제 메일 수신, ② 브라우저 Chrome/Safari에서 OpenAI TTS mp3 재생(첫 재생 합성, 두 번째 재생 캐시 hit), ③ (선택) Slack Webhook으로 Block Kit 메시지 수신

## 설계 의사결정

- **왜 OpenAI gpt-5-nano?** Claude 키 미발급 + Gemini 무료 티어 한계 상황에서 경량·저비용 모델을 확보. gpt-5 family 제약(사용자 지정 temperature 불가)을 반영해 프롬프트 설계만으로 문어체/구어체 톤 차이 확보.
- **왜 2단 구조?** 분야별 리포트 카드(카테고리당 기사 3건 + 라디오 1개)라는 UI 단위와 1:N 정합. 중요도/감성 등 소비되지 않는 필드는 제거해 토큰·지연 절감.
- **왜 reports + articles 2테이블?** 단일 briefings 테이블이 "한 카테고리 = N 기사 + 1 라디오" 구조와 맞지 않아 2테이블로 분리. cascade delete + `report.articles` relationship으로 UI 단위 그대로 영속.
- **왜 SSE 진행 스트림?** 생성에 15~30초가 걸려 UX 불만이 큼 → 단계별 이벤트를 실시간 렌더하여 "무엇이 진행 중인지" 시연 중에도 설명 가능.
- **왜 로그인 제거?** 시연 시간 단축 + 주의를 핵심 기능(브리핑 생성/라디오)에 집중. users/settings 스키마는 유지했으므로 온보딩 컴포넌트만 복구하면 다중 유저 복원 가능.
- **왜 스케줄러 의도적 비활성?** 시연 윈도(4/19~4/21)에 APScheduler cron이 트리거해 예상치 못한 LLM 비용이 발생하지 않도록 차단. 주석 해제 한 줄로 복원.
- **왜 OpenAI `gpt-4o-mini-tts`?** 초기 프로토타입은 Web Speech API(비용 0)였으나 실기기에서 목소리가 인위적이라 교체. 서버에서 mp3를 합성·디스크 캐시(`./media/audio/{report_id}.mp3`)해 두 번째 재생부터는 추가 비용 0. `services/tts.py` 레이어로 감싸 ElevenLabs / CLOVA Voice로 전환도 1파일 수정.
- **왜 클러스터링을 코드로?** 임베딩 API 비용 절감 + LLM 토큰 절약. "코드가 할 수 있는 건 코드가 하고, 모델은 모델만 할 수 있는 일(자연어 이해/생성)에만 집중."

## 라이선스

서울신문 과제평가 제출용 프로토타입. 코드 재사용 시 별도 문의 바랍니다.
