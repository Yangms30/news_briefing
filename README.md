# 서신 · 書信

> **오늘의 AI 뉴스 편지** — 공개 뉴스 API 를 교차 수집하고, 경량 LLM 과 파이프라인 엔지니어링으로 분석하여, 매일 정해진 시각에 웹 · 이메일 · Slack 으로 자동 배달하는 풀스택 시스템.

**서울신문 과제평가 제출작** · 최종 업데이트: 2026-04-21



---

## 핵심 차별화 전략

1. **4 소스 교차 수집** — 연합뉴스 · 서울신문 RSS(본사 직접) + Google News RSS(aggregator) + Naver 검색 API. 단일 포털 의존 차단 + 저작권 안전(메타데이터만).
2. **TF-IDF 클러스터링으로 공영 중요도 자동 판정** — 코사인 유사도 0.45 + bigram + sublinear TF. "여러 매체가 동시 보도 = 공영 가치 높음" 가설을 수학적으로 구현. 60~80건 → 상위 3개 이슈로 압축 → **LLM 호출 비용 약 95% 절감**.
3. **프롬프트 엔지니어링 2단 체인** — Step1 기사별 3줄 요약(문어체) → Step2 카테고리별 라디오 스크립트(2~3분 구어체). `gpt-5-nano` 의 temperature 미지원 제약을 구조화 응답으로 우회.
4. **라디오 편지 (이중 TTS 엔진)** — ElevenLabs `eleven_multilingual_v2` 메인 + OpenAI `gpt-4o-mini-tts` 폴백. 사용자가 설정 페이지에서 엔진 토글. 엔진별 독립 캐시 (`{report_id}.{engine}.mp3`).
5. **인라인 오디오 발송** — 이메일에 카테고리별 mp3 첨부, Slack 에는 `files.upload_v2` 로 스레드 내 재생 가능.
6. **동적 오프셋 스케줄러** — APScheduler cron 이 사용자 카테고리 수 × 1분 만큼 실행 시각을 앞당겨, 파이프라인 완료 시점이 사용자 지정 시각과 정렬.

---

## 아키텍처

```
┌────────────────────────────┐   REST + SSE    ┌──────────────────────────────────┐
│  Next.js 16 UI             │ ──────────────▶ │  FastAPI                         │
│  (App Router)              │                 │                                  │
│  • /          → /dashboard │                 │  Routers                         │
│  • /dashboard              │                 │   ├─ users                       │
│    ├─ CategoryReportGrid   │                 │   ├─ settings (PUT upsert)       │
│    ├─ GenerationProgress   │                 │   ├─ reports  (list/detail/     │
│    ├─ DateGroupedDashboard │                 │   │   generate + /audio + SSE)  │
│    └─ RadioPlayerBar       │                 │   ├─ send     (다채널 배치)      │
│  • /dashboard/settings     │                 │   └─ dispatches (보관함)         │
│  • /dashboard/history      │                 │                                  │
└────────────────────────────┘                 │  Pipeline                        │
                                               │   ├─ collector    (4 소스)       │
                                               │   ├─ preprocessor (TF-IDF 0.45)  │
                                               │   ├─ analyzer     (gpt-5-nano)   │
                                               │   └─ service      (오케스트레이션)│
                                               │                                  │
                                               │  Dispatcher                      │
                                               │   ├─ WebSender    (DB 저장)      │
                                               │   ├─ SlackSender  (Webhook/Bot)  │
                                               │   └─ EmailSender  (SMTP + mp3)   │
                                               │                                  │
                                               │  Services                        │
                                               │   └─ tts.py (ElevenLabs/OpenAI)  │
                                               │                                  │
                                               │  Scheduler (APScheduler, 활성)   │
                                               │   └─ cron + 동적 오프셋          │
                                               │                                  │
                                               │  SQLite (users · settings ·     │
                                               │   reports · articles · send_logs)│
                                               └──────────────────────────────────┘
```

---

## 기술 스택

| 구분 | 선택 | 상태 |
|------|------|------|
| Frontend | Next.js 16 (App Router) + React 19.2 + TypeScript strict + pnpm | ✅ |
| UI | shadcn/ui + Tailwind 4 + Framer Motion + Sonner | ✅ |
| Backend | FastAPI + SQLAlchemy + SQLite (Python 3.11+) | ✅ |
| LLM | OpenAI `gpt-5-nano` — 경량 · 저비용 · temperature 미지원(1.0 고정) | ✅ |
| News | Google News + 연합뉴스 + 서울신문 RSS + Naver 검색 API (4-source, `feedparser` + `httpx`) | ✅ |
| Clustering | scikit-learn TF-IDF(bigram, sublinear) + cosine similarity (threshold 0.45) | ✅ |
| Post-select 안전망 | pairwise 유사도 0.55 초과 시 대표 기사 교체 (최대 4회) | ✅ |
| Scheduler | APScheduler (Asia/Seoul) + 카테고리 수 기반 동적 오프셋 | ✅ |
| SSE | `/api/reports/generate/stream` — 단계별 진행 실시간 | ✅ |
| TTS (메인) | ElevenLabs `eleven_multilingual_v2` | ✅ |
| TTS (폴백) | OpenAI `gpt-4o-mini-tts` | ✅ |
| Slack | Incoming Webhook **또는** Bot Token (`files.upload_v2` 인라인 오디오) | ✅ |
| Email | SMTP (Gmail App Password) + HTML 본문 + 카테고리별 mp3 첨부 | ✅ |

> 모든 LLM/TTS API 호출은 백엔드에서만 수행합니다. 프론트엔드 번들에 외부 AI URL 0건 (`grep` 검증).

---

## 프로젝트 구조

```
briefBot/
├── backend/                         # FastAPI + 파이프라인 + 다채널 발송
│   ├── main.py                      # 앱 엔트리, CORS, lifespan(데모 시딩 + 스케줄러)
│   ├── config.py                    # pydantic-settings (OPENAI_*, ELEVENLABS_*, NAVER_*, SMTP_*)
│   ├── database.py                  # SQLAlchemy engine/session
│   ├── models.py                    # User · Setting · Report · Article · SendLog
│   ├── schemas.py                   # Pydantic DTO
│   ├── scheduler.py                 # APScheduler cron + 동적 오프셋
│   ├── routers/                     # users, settings, reports(SSE), send, dispatches
│   ├── pipeline/                    # collector(4소스), preprocessor(TF-IDF), analyzer, service
│   ├── prompts/                     # article_summary.py, radio_script.py
│   ├── services/                    # tts.py (ElevenLabs/OpenAI pluggable)
│   ├── dispatcher/                  # web, slack(Webhook+Bot), email_sender(+mp3 attach), service
│   └── scripts/                     # seed / ad-hoc
├── frontend/                        # Next.js 16 App Router
│   ├── app/
│   │   ├── page.tsx                 # /dashboard 로 redirect
│   │   └── dashboard/
│   │       ├── page.tsx             # 메인 대시보드 (SSE + 카테고리 카드)
│   │       ├── settings/page.tsx    # 카테고리/주기/채널/TTS 엔진 설정
│   │       └── history/page.tsx     # 발송 이력 아카이브 (날짜별 그룹)
│   ├── components/dashboard/
│   │   ├── category-report-grid.tsx
│   │   ├── date-grouped-dashboard.tsx
│   │   ├── dashboard-header.tsx
│   │   ├── generation-progress-panel.tsx
│   │   ├── radio-player-bar.tsx
│   │   └── quick-actions.tsx
│   └── lib/                         # types, api, briefing-display(parseUtcIso), ...
├── CLAUDE.md                        # 저장소 작업 가이드
└── README.md
```

영역별 작업 가이드:
- [`backend/CLAUDE.md`](./backend/CLAUDE.md) — FastAPI 명령어, 파이프라인 구조, LLM 제약
- [`frontend/CLAUDE.md`](./frontend/CLAUDE.md) — Next.js/shadcn 규약, 라우트, 상태 관리

---

## 실행 방법

### 1. 백엔드

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env에 최소 OPENAI_API_KEY 채워넣기 (https://platform.openai.com/api-keys)
# 선택 설정:
#   - ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID (미입력 시 OpenAI TTS 자동 폴백)
#   - NAVER_CLIENT_ID / NAVER_CLIENT_SECRET (미입력 시 3소스로 폴백)
#   - SMTP_USER / SMTP_PASSWORD(Gmail 앱 비밀번호) / SMTP_FROM (이메일 시연 시)
uvicorn main:app --reload --port 8000
```

- http://localhost:8000/docs 에서 Swagger UI 확인
- 첫 실행 시 `backend/briefbot.db` 자동 생성 + 데모 유저(`user_id=1`, 6카테고리) 멱등 시딩
- 포트 8000 점유 시 `--port 8765` 등 대체 포트 사용 (프론트 `NEXT_PUBLIC_API_URL` 동기화 필요)

### 2. 프론트엔드

```bash
cd frontend
pnpm install
cp .env.example .env.local
# NEXT_PUBLIC_API_URL이 백엔드 주소와 일치하는지 확인
pnpm dev
```

- http://localhost:3000 접속 → 자동으로 `/dashboard` 리다이렉트

### 3. E2E 시연 시나리오

1. http://localhost:3000 접속 → 자동으로 대시보드 진입
2. 우측 상단 **⚙️ 설정**에서 이메일 / Slack (Webhook 또는 Bot Token) / 카테고리 / 주기 / **TTS 엔진** 조정
3. 대시보드 **"지금 리포트 받기"** 클릭
4. SSE Progress Panel 에 `start → category_start → collected → clustered → summarizing_article → synthesizing_radio → category_done → done` 실시간 표시
5. 생성 완료 시 자동으로 `POST /api/send` 체이닝 → 활성 채널로 일괄 발송 (이메일에 mp3 첨부, Slack Bot 모드 시 스레드에 인라인 오디오)
6. 카테고리 카드 ▶ 버튼 → `GET /api/reports/{id}/audio` 로 TTS mp3 스트림 재생
7. 헤더 🗄️ 보관함 → `/dashboard/history` 에서 과거 발송 이력 (날짜별 그룹 + 채널 결과 + 수신자 스냅샷)

---

## API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/health` | 헬스 체크 |
| GET | `/api/users/{user_id}` | 유저 정보 조회 |
| GET | `/api/settings/{user_id}` | 유저 설정 조회 |
| PUT | `/api/settings/{user_id}` | 설정 upsert (카테고리/cron/채널/TTS 엔진) |
| GET | `/api/reports?user_id=&category=&latest_only=` | 리포트 리스트 |
| GET | `/api/reports/{report_id}` | 리포트 상세 (articles 포함) |
| GET | `/api/reports/articles/{article_id}` | 개별 기사 상세 |
| GET | `/api/reports/{report_id}/audio?engine=` | **TTS mp3 스트림** (엔진 선택 가능) |
| POST | `/api/reports/generate?user_id=` | 즉시 리포트 생성(동기) |
| GET | `/api/reports/generate/stream?user_id=` | **SSE 진행 스트림** |
| POST | `/api/send?user_id=` | 최신 리포트 활성 채널 일괄 발송 |
| GET | `/api/dispatches?user_id=&limit=` | **발송 이력 리스트** (보관함) |
| GET | `/api/dispatches/{dispatch_id}` | 발송 이력 상세 (채널 결과 + 리포트 풀바디) |

---

## 파이프라인 2단 구조

```
[수집 단계]                                       [분석 단계]
                                                 ┌─────────────────────────────┐
연합뉴스 RSS    ─┐                                │ OpenAIAnalyzer (gpt-5-nano) │
서울신문 RSS    ─┤   카테고리별 60~80건           │                             │
Google News RSS ─┼─▶  URL + 제목 정규화 dedup ─▶ │ Step1: 기사 3줄 요약        │
Naver 검색 API  ─┘   → 40~60건 unique            │   (문어체 + 재시도 2회)     │
                      ↓                          │                             │
                    TF-IDF 벡터화                │ Step2: 라디오 스크립트      │
                    (ngram 1-2, sublinear)       │   (2~3분 구어체, 숫자 풀이) │
                      ↓                          │                             │
                    Greedy 클러스터링            │ 실패 시 graceful:           │
                    cosine sim ≥ 0.45            │   radio_script = NULL       │
                      ↓                          │   summary = RSS fallback    │
                    클러스터 크기 정렬            │                             │
                    = 공영 중요도 signal          └─────────────────────────────┘
                      ↓
                    Top-3 + 대표 선별                         ↓
                    (서로 다른 매체 우선)
                      ↓                          [SQLite reports + articles]
                    Post-select 안전망                      ↓
                    (pairwise ≥ 0.55 교체)       [Dispatcher: web/slack/email]
                      ↓                                     ↓
                    최종 3건 → LLM              [send_logs: dispatch_id + recipient]
```

---

## 설계 의사결정

- **왜 OpenAI `gpt-5-mini`?** 과제 허용 모델 중 저비용 · 한국어 품질 균형. temperature 미지원 제약은 구조화 응답 프롬프트로 우회. 큰 모델을 쓰는 것보다 경량 모델을 프롬프트 설계로 짜내는 쪽이 실무에 가깝다 판단.
- **왜 TF-IDF 클러스터링?** 임베딩 API 비용 제로 + ms 단위 속도 + 재현성. 클러스터 크기 자체가 "몇 개 매체가 동시 보도했는가" 라는 공영 중요도 signal 이 되어 **LLM 호출 비용 95% 절감 + 품질 signal 강화** 동시 달성. `_article_text_for_clustering()` 한 함수만 교체하면 KoSentenceBERT 임베딩으로 전환 가능.
- **왜 2단 프롬프트 체인?** "기사별 요약(Step1) + 카테고리별 라디오(Step2)" 가 UI 의 카드 단위(카테고리당 기사 3건 + 라디오 1개)와 1:N 정합. 중요도/감성 등 UI 에서 소비되지 않는 필드는 제거해 토큰 · 지연 절감.
- **왜 reports + articles 2 테이블?** 단일 briefings 테이블이 "한 카테고리 = N 기사 + 1 라디오" 구조와 안 맞아 2 테이블로 분리. cascade delete + `report.articles` relationship.
- **왜 SSE 진행 스트림?** 생성에 15~30초 걸림 → UX 불만 큼. 단계별 이벤트를 실시간 렌더하여 "무엇이 진행 중인지" 시연 중에도 설명 가능.
- **왜 이중 TTS 엔진(ElevenLabs + OpenAI)?** ElevenLabs 가 한국어 자연스러움에서 우월하지만 유료 크레딧. OpenAI TTS 는 가격 관리 유리. 사용자가 리허설/프로덕션을 엔진으로 분리 운영하도록 설정 페이지에서 토글. 캐시는 `{report_id}.{engine}.mp3` 로 엔진 독립.
- **왜 Slack 에 Webhook + Bot Token 두 모드?** Webhook 은 설정 간편하지만 파일 업로드 불가. Bot Token 은 `files.upload_v2` 3단계 플로우로 스레드에 mp3 인라인 첨부 가능. 사용자가 상황에 맞게 선택.
- **왜 동적 오프셋 스케줄러?** 고정 오프셋(3분)으로 시작했으나 사용자의 카테고리 수에 따라 파이프라인 길이가 달라짐(카테고리당 ~1분). 카테고리 수 × 1분 앞당기기로 자동 보정. floor 1분 / ceil 15분 클램프.
- **왜 로그인 제거?** 시연 시간 단축 + 핵심 기능 집중. users/settings 스키마는 유지했으므로 온보딩 컴포넌트만 복구하면 다중 유저 확장 가능.

---

## AI 도구 사용 공개 (과제 요건 준수)

**실행 AI (런타임 호출)**
- OpenAI `gpt-5-mini` — LLM 분석 + 라디오 스크립트
- OpenAI `gpt-4o-mini-tts` — TTS 폴백
- ElevenLabs `eleven_multilingual_v2` — TTS 메인

**개발 AI (코드 작성 과정)**
- **Claude Code** (Anthropic) — 주요 개발 파트너. 설계 / 백엔드 / 프론트엔드 / 디버깅 전 단계.
- **v0.app** (Vercel) — 초기 대시보드 UI 스캐폴드. 이후 Claude Code 와 수동 리팩토링.

개발 방법론: **PDCA (Plan → Design → Do → Check → Act)** 

---

## 라이선스

서울신문 과제평가 제출용 프로토타입. 코드 재사용 시 별도 문의 바랍니다.
