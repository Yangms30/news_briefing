# 서신 · 書信 — AI 이슈 브리핑 시스템
## 서울신문 과제평가 아키텍처 문서

> **오늘의 AI 뉴스 편지** · *이름 유래: "서울신문" 줄임이자 한자 書信(편지).  매일 AI가 큐레이션한 뉴스를 한 통의 편지처럼 독자에게 전달한다는 컨셉.*

> 최종 업데이트: 2026-04-19
> 상태: **Day 1 백엔드 파이프라인 + Day 2 프론트 연동 완료 (E2E 동작 확인) + Day 3 발송/스케줄러/TTS + Day 4 로그인 제거 (데모 간소화)**

---

## 1. 프로젝트 개요

### 과제 요약
공개 API, 검색도구 등을 활용하여 국내외 주요 이슈를 실시간으로 수집/분석하고, 특정 채널(Slack, 웹페이지, 이메일)을 통해 자동으로 보고하는 AI 기반 프로토타입

### 서비스 한 줄 정의
**"가벼운 LLM으로도 똑똑하게 — 파이프라인 엔지니어링으로 뉴스를 분석하고 자동 브리핑하는 시스템"**

### 핵심 차별화 전략
1. **프롬프트 엔지니어링** — 복잡한 태스크를 단순 태스크로 분해, 각 단계에 전문화된 프롬프트
2. **컨텍스트 엔지니어링** — 모델에 넘기기 전 컨텍스트를 정제하여 경량 모델의 성능 극대화
3. **하네스 엔지니어링** — 검증 레이어, 폴백 체인, 규칙 기반 보정으로 모델 바깥에서 품질 보장
4. **라디오 모드** — 텍스트 브리핑을 구어체 스크립트로 변환 + TTS 재생, "읽는 뉴스"에서 "듣는 뉴스"로 확장

---

## 2. 기술 스택

| 구분 | 선택 | 버전/비고 | 현재 상태 |
|------|------|-----------|-----------|
| **Frontend** | Next.js 16 (App Router) | React 19.2 / TS strict / pnpm | ✅ 구현 완료 |
| **UI** | shadcn/ui + Tailwind 4 + Framer Motion + Sonner | v0.app 프로토타입 기반 | ✅ 연동 완료 |
| **Backend** | FastAPI | Python 3.11+ / uvicorn | ✅ 구현 완료 |
| **Database** | SQLite + SQLAlchemy | 로컬 환경, 별도 DB 서버 불필요 | ✅ 구현 완료 |
| **LLM (메인)** | OpenAI `gpt-5-nano` | 경량 모델, 저비용 고성능 | ✅ 구현 완료 (`OpenAIAnalyzer`) |
| **LLM (레거시)** | Gemini 2.5 Flash Lite | `gemini-2.5-flash-lite` | ♻️ 클래스 유지(`GeminiAnalyzer`), 현재 미사용 |
| **스케줄러** | APScheduler | FastAPI 프로세스 내장 | ⚠️ **데모 기간 의도적 비활성화** (LLM 비용 통제, `main.py` lifespan 주석처리) — 코드 자체는 완성 |
| **뉴스 소스** | Google News + 연합뉴스 + 서울신문 RSS + **네이버 검색 API** (4중) | 병렬 수집 + URL/title 두 단계 dedupe + 소스별 20건/24h. 한 소스 실패해도 나머지로 진행 | ✅ 구현 완료 (Day 5 확장) |
| **~~네이버/NewsAPI~~** | (키 미발급으로 보류) | 추후 확장 포인트 | ⬜ 미적용 |
| **이메일 발송** | SMTP (Gmail App Password) | 반응형 HTML 템플릿 | ✅ 구현 완료 (.env 키만 채우면 동작) |
| **Slack 발송** | Incoming Webhook | Block Kit JSON | ✅ 구현 완료 (Webhook URL 설정 시 동작) |
| **TTS (라디오)** | OpenAI `gpt-4o-mini-tts` (voice: `nova`) | `/api/reports/{id}/audio` 엔드포인트, mp3 디스크 캐시 | ✅ 구현 완료 |
| **진행 상황 스트리밍** | Server-Sent Events (SSE) | `/api/reports/generate/stream` | ✅ 구현 완료 (프론트 Progress Panel 연동) |

---

## 3. API 키 발급 현황

| API | 발급 URL | 무료 한도 | 발급 상태 |
|-----|----------|-----------|-----------|
| **OpenAI API** (`gpt-5-nano`) | platform.openai.com | Pay-as-you-go (경량 모델, 토큰 단가 낮음) | ✅ 발급 + **기본 LLM으로 적용** |
| Gemini API (`gemini-2.5-flash-lite`) | ai.google.dev | 무료 티어 | ✅ 발급 완료 — 레거시 클래스로 코드에 유지 |
| Claude API (Haiku 4.5) | platform.claude.com | Pay-as-you-go | ⬜ 미발급 |
| 네이버 검색 API | ncloud.com | 25,000건/일 | ⬜ 미발급 (RSS로 대체) |
| NewsAPI.org | newsapi.org/register | 100건/일 | ⬜ 미발급 (RSS로 대체) |
| Google News RSS | (키 불필요) | 무제한 | ✅ 1차 소스 (aggregator, 여러 언론사 커버) |
| 연합뉴스 RSS | (키 불필요) | 무제한 | ✅ 2차 소스 (국내 최대 공영 통신사, 카테고리별 피드) |
| 서울신문 RSS | (키 불필요) | 무제한 | ✅ 3차 소스 (과제 주최사, 카테고리별 피드) |
| Gmail SMTP (앱 비밀번호) | myaccount.google.com/apppasswords | 무료 | ⚠️ 데모 직전 발급 필요 (`SMTP_PASSWORD` 환경변수) |
| Slack Incoming Webhook | api.slack.com/apps | 무료 | ⬜ 선택 사항 (발급 시 `/dashboard/settings`에서 URL 입력) |

> 💡 **변경 이력**: ① 본래 `Claude Haiku (메인) → Gemini Flash (폴백)` 체인 → Claude 키 미발급으로 `Gemini 2.5 Flash Lite 단일`로 축소(4/17) → OpenAI 키 확보 후 `gpt-5-nano`로 교체하고 Gemini는 클래스 형태로만 유지(4/17 후속). ② `OpenAIAnalyzer`는 gpt-5 family 제약(사용자 지정 temperature 불가, 항상 default 1.0)을 반영해 temperature 파라미터를 전달하지 않음.

---

## 4. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (Next.js 16)                │
│                                                         │
│  /  ──(auto-redirect)─▶  /dashboard                     │
│                                                         │
│  ┌─────────────────────────┐   ┌──────────────────┐    │
│  │ /dashboard              │   │ /dashboard/      │    │
│  │  • Category Report Grid │   │   settings       │    │
│  │  • Radio Player Bar     │   │  • 카테고리/주기/  │    │
│  │    (OpenAI TTS mp3)     │   │    채널 설정      │    │
│  │  • Quick Actions         │   │  • AI 모델 표기   │    │
│  │  • Generation Progress   │   └──────────────────┘    │
│  │    Panel (SSE stream)    │                           │
│  └─────────────────────────┘                            │
└──────────────────────┬──────────────────────────────────┘
                       │ REST + SSE
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                      │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              API Layer (Routers)                 │   │
│  │   /api/users     — 유저 조회 (로그인 없음)       │   │
│  │   /api/settings  — 설정 GET/PUT (upsert)         │   │
│  │   /api/reports   — 리포트 리스트/상세            │   │
│  │   /api/reports/generate        — 즉시 생성       │   │
│  │   /api/reports/generate/stream — SSE 진행 이벤트 │   │
│  │   /api/send      — 다채널 발송                   │   │
│  └─────────────────────┬───────────────────────────┘   │
│                        │                                │
│  ┌─────────────────────▼───────────────────────────┐   │
│  │           News Pipeline (2단 LLM 호출)            │   │
│  │                                                   │   │
│  │  [Collector]  GoogleRSSClient (feedparser)        │   │
│  │       │  카테고리당 20건, 24h 필터                │   │
│  │       ▼                                           │   │
│  │  [Preprocessor]  (LLM 없음)                        │   │
│  │       • 제목 TF-IDF + 코사인 유사도 ≥0.6 클러스터링 │   │
│  │       • 노이즈 패턴 정제                          │   │
│  │       • 클러스터당 대표 기사 2-3건 선정            │   │
│  │       │                                           │   │
│  │       ▼                                           │   │
│  │  [Analyzer] — OpenAI gpt-5-nano                   │   │
│  │       ① summarize_article  (기사별 3줄 요약)      │   │
│  │          └ 재시도 2회, 실패 시 RSS summary fallback │   │
│  │       ② synthesize_radio   (카테고리별 구어체 스크립트) │   │
│  │          └ 실패 시 radio_script=NULL (graceful)     │   │
│  │       │                                           │   │
│  │       ▼                                           │   │
│  │  [Persist]  Report + Article rows                 │   │
│  └─────────────────────┬───────────────────────────┘   │
│                        │                                │
│  ┌─────────────────────▼───────────────────────────┐   │
│  │           Dispatcher (backend/dispatcher/)        │   │
│  │   • WebSender     (DB 저장 → 프론트 조회)        │   │
│  │   • SlackSender   (Incoming Webhook + Block Kit) │   │
│  │   • EmailSender   (SMTP Gmail + 반응형 HTML)     │   │
│  │   → 각 결과를 send_logs 에 기록                  │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │     Scheduler (APScheduler, Asia/Seoul)          │   │
│  │     ⚠️ 데모 기간 의도적 비활성화 (비용 통제)        │   │
│  │     — 코드/cron 등록 로직은 완성, lifespan 주석처리 │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │     Database (SQLite)                             │   │
│  │     users · settings · reports · articles · send_logs │   │
│  │     (부팅 시 데모 유저 id=1 멱등 시딩)            │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 5. 뉴스 파이프라인 상세 (핵심)

### 5.1 수집 (Collector)

| 소스 | 용도 | 호출 방식 | 구현 상태 |
|------|------|-----------|-----------|
| Google News RSS | 국내외 통합 aggregator | `https://news.google.com/rss/search?q=...&hl=ko&gl=KR&ceid=KR:ko` → feedparser | ✅ `GoogleRSSClient` |
| 연합뉴스 RSS | 국내 공영 통신사 직접 피드 | `https://www.yna.co.kr/rss/{politics|economy|society|international|sports|industry}.xml` → feedparser | ✅ `YonhapRSSClient` |
| 서울신문 RSS | 과제 주최사 직접 피드 | `https://www.seoul.co.kr/xml/rss/rss_{politics|economy|society|international|sports}.xml` → feedparser (IT/과학 전용 피드 없음, skip) | ✅ `SeoulNewsRSSClient` |
| Multi-source fanout | 3개 소스 병합 + URL dedupe | `MultiSourceCollector` — 한 소스가 타임아웃/404여도 graceful 유지 | ✅ `MultiSourceCollector` |
| ~~네이버 검색 API~~ | 국내 뉴스 | Client ID/Secret 미발급으로 보류 | ⬜ 확장 포인트 |
| ~~NewsAPI.org~~ | 해외 뉴스 | API Key 미발급으로 보류 | ⬜ 확장 포인트 |

- 카테고리별 키워드 매핑: `{"정치": "정치", "경제": "한국 경제 OR 금리", "사회": "사회", "국제": "국제", "스포츠": "스포츠", "IT/과학": "IT 과학"}`
- 수집량: 카테고리당 최대 20건, 발행일 기준 최근 24시간 필터
- 수집 주기: 스케줄러 트리거 시 (Day 3 예정) 또는 즉시 생성 API 호출 시

### 5.2 전처리 (Preprocessor) — LLM 호출 없음, 코드로 처리

```
[수집된 기사 목록]
     │
     ▼
(1) 제목 기반 중복 제거 — 자카드 유사도 or TF-IDF 코사인 유사도
     │
     ▼
(2) 본문 정제 — 광고, 관련기사 링크, 기자 정보 등 노이즈 제거
     │
     ▼
(3) 클러스터링 — TF-IDF 벡터화 → 코사인 유사도 → 임계값 기반 그룹핑
     │
     ▼
(4) 클러스터별 대표 기사 2~3건 선정 (최신순 + 소스 다양성)
     │
     ▼
[정제된 컨텍스트] → Analyzer로 전달
```

**설계 원칙:** "코드가 할 수 있는 건 코드가 하고, 모델은 모델만 할 수 있는 일(자연어 이해/생성)에만 집중"

### 5.3 분석 (Analyzer) — LLM 호출 구간 (2단 구조)

> 4/17 후속 재설계: 기존 `Step1 구조화 추출 → Step2-A 3줄 브리핑 → Step2-B 라디오` 3단 구조를 **"기사 단위 요약 + 카테고리 단위 라디오"** 2단으로 축소. 분야별 리포트(카테고리당 기사 3건 + 라디오 스크립트 1개)라는 데이터 모델에 맞추기 위함. 구조화 JSON(`extract`) 단계는 제거되고, 중요도 점수/감성 등은 UI에서 요구되지 않아 함께 삭제.

#### Step 1: 기사별 3줄 요약 (`analyzer.summarize_article`)
```
입력: 카테고리 + RawArticle(title, summary, source, link)
프롬프트: prompts/article_summary.py (ARTICLE_SUMMARY_SYSTEM / USER_TEMPLATE)
          "이 기사를 3줄로 요약하세요. 각 줄은 개행으로 구분하며
           1줄: 핵심 팩트 / 2줄: 맥락 · 배경 / 3줄: 의미 · 전망"
호출: OpenAI chat.completions (gpt-5-nano, temperature 미지정)
출력: 3줄 자연어 요약 텍스트
검증: 길이 >= 30자 체크, 실패 시 최대 2회 재시도
Fallback: 모두 실패 시 RSS summary를 문장 단위로 쪼개 3줄 구성 (`_fallback_summary`)
```

#### Step 2: 카테고리별 라디오 스크립트 (`analyzer.synthesize_radio`)
```
입력: 카테고리 + 해당 카테고리의 기사 3건 + Step1에서 생성된 각 요약
프롬프트: prompts/radio_script.py (RADIO_SYSTEM / USER_TEMPLATE)
          "당신은 뉴스 라디오 앵커입니다. 아래 3건의 뉴스를 하나의
           자연스러운 구어체 라디오 스크립트로 엮으세요.
           - 카테고리 오프닝 → 기사별 설명 → 마무리 멘트
           - 숫자/약어는 읽기 좋은 형태로 변환 (0.25%p → 영점이오 퍼센트포인트)
           - 30초~1분 분량"
호출: OpenAI chat.completions (gpt-5-nano)
출력: 한 카테고리 전체를 하나의 라디오 스크립트 문자열로
Graceful 실패: 예외 발생 시 `radio_script=None`으로 저장(리포트 자체는 유지)
```

#### 하네스 엔지니어링 적용 (구현됨)
- **재시도 + Fallback:** `summarize_article`은 최대 2회 재시도 후 `_fallback_summary()`로 degraded 요약 반환 → 한 기사 실패가 리포트 전체를 막지 않음.
- **카테고리 단위 부분 성공:** 한 카테고리에서 RSS 수집 0건이거나 요약 전원 실패해도 해당 카테고리만 건너뛰고 다음 카테고리 진행(`service.py` forward-error-tolerant 루프).
- **모델 호출 격리:** LLM 호출은 전부 `analyzer.py`에만 존재하며, `service.py`는 오케스트레이션과 DB 영속화만 담당 → 모델 교체(OpenAI↔Gemini) 시 클래스만 교체.
- **진행 상황 스트리밍:** 각 단계 (`start / category_start / collected / clustered / summarizing_article / synthesizing_radio / category_done / done`)가 SSE 이벤트로 프론트 Progress Panel에 즉시 반영.
- **gpt-5 제약 준수:** `temperature` 커스텀 불가(항상 기본값 1.0). 문어체/구어체 차이는 프롬프트 설계만으로 확보.

### 5.4 포맷팅 (Formatter)

| 채널 | 포맷 | 비고 |
|------|------|------|
| 웹 | HTML 카드 UI | Next.js 컴포넌트로 렌더링 |
| Slack | Markdown + Block Kit JSON | Webhook 전송 |
| 이메일 | HTML 템플릿 | 반응형 이메일 레이아웃 |
| 라디오 | 구어체 스크립트 → OpenAI `gpt-4o-mini-tts` (voice: `nova`) → mp3 | 서버에서 합성 + 디스크 캐시, 프론트 `<audio>` 재생 |

### 5.5 라디오 모드 상세 (NEW)

#### 구현 방식
- **현재:** OpenAI `gpt-4o-mini-tts` (voice: `nova`) — 서버에서 mp3 합성, 디스크 캐시(`./media/audio/{report_id}.mp3`), 프론트는 `<audio>` 태그로 재생. 엔드포인트 `GET /api/reports/{id}/audio`
  - 이전 프로토타입: 브라우저 내장 Web Speech API(`speechSynthesis`)였으나 목소리가 인위적이라 교체
  - Lazy 합성: 리포트 생성 시점이 아니라 실제 재생 요청 순간에 합성 → 미청취 리포트 비용 절감
  - 원자적 쓰기(`.mp3.tmp` → `os.replace`)로 부분 파일 방지
- **확장:** ElevenLabs / Google Cloud TTS / CLOVA Voice 등으로 교체 시 `services/tts.py` 내부만 수정(엔드포인트 계약 불변)

#### UI 구성
```
┌─────────────────────────────────────────────────────┐
│  🎧 라디오 모드                                      │
│                                                     │
│  ▶ 오늘의 브리핑 전체 듣기         ──○───── 3:42 / 8:15 │
│    정치 ✓ → 경제 (재생 중) → 스포츠 → IT            │
│                                                     │
│  [⏮] [⏸] [⏭]    🔊 ━━━━━━○━━━ 볼륨               │
└─────────────────────────────────────────────────────┘
```

#### 기능
- 개별 브리핑 재생: 카드별 ▶ 버튼
- 전체 연속 재생: 대시보드 상단 "오늘의 브리핑 전체 듣기"
- 카테고리 간 자연스러운 연결 멘트 (LLM이 생성)
- 재생/일시정지/다음 카테고리 건너뛰기 컨트롤

#### 면접 어필 포인트
> "같은 데이터를 채널 특성에 맞게 다른 톤으로 생성합니다. 텍스트 브리핑은 문어체로, 라디오 스크립트는 구어체로 — 이것이 프롬프트 엔지니어링의 힘입니다."

---

## 6. 유저 플로우

> 💡 **2026-04-19 변경**: 로그인/온보딩 단계를 제거 — 백엔드 기동 시 데모 유저(`user_id=1`, `시연용 사용자 <demo@briefbot.local>`, 6카테고리 + web/email 채널 활성)가 자동 생성되고 프론트는 `user_id=1`을 고정 사용. 시연 시간 단축과 "주의를 핵심 기능(브리핑 생성/라디오)에 집중"시키기 위함. 이메일 수신자나 Slack Webhook은 `/dashboard/settings`에서 실시간 변경 가능.

```
앱 진입 (`/`)
    │
    ▼ (자동 /dashboard 리다이렉트)
대시보드
  ├─ 최신 리포트 카드 리스트
  ├─ "지금 브리핑 받기" 버튼 (면접 시연용)
  ├─ 🎧 라디오 모드 (전체 듣기 / 개별 듣기)
  └─ ⚙️ 설정 (카테고리/주기/이메일 주소/Slack webhook 조정)
```

---

## 7. DB 스키마

> 4/17 후속 재설계: 단일 `briefings` 테이블을 **`reports`(카테고리 단위) + `articles`(기사 단위)** 2테이블로 분리. 이유: 분야별 리포트 카드(라디오 스크립트 1개 + 대표 기사 3건)라는 UI 단위와 1:N으로 자연스럽게 대응되도록. `source_articles` JSON blob / `raw_analysis` / `importance_score` / `title` 같은 사용되지 않는 컬럼은 제거. `send_logs`는 `briefing_id` FK 대신 `user_id`로 전환(다채널 배치 발송을 한 번에 기록).

```sql
-- 유저 (데모 모드: user_id=1이 부팅 시 자동 시딩)
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 유저별 설정 (1:1)
CREATE TABLE settings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    categories      TEXT NOT NULL,       -- JSON: ["정치","경제","사회","국제","스포츠","IT/과학"]
    schedule_cron   TEXT,                -- cron 표현식 (데모 기간 스케줄러 비활성)
    channels        TEXT NOT NULL,       -- JSON: {"web":true,"slack":"webhook_url","email":"user@email.com"}
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 카테고리 단위 리포트 (1 유저 : N 카테고리, 카테고리당 라디오 1개)
CREATE TABLE reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    category      TEXT NOT NULL,          -- "정치" | "경제" | ...
    radio_script  TEXT,                   -- Step2 구어체 스크립트 (실패 시 NULL)
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 기사 단위 요약 (리포트 1건당 2-3 rows)
CREATE TABLE articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    report_id     INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    category      TEXT NOT NULL,
    title         TEXT NOT NULL,          -- 최대 500자
    summary       TEXT NOT NULL,          -- Step1 3줄 요약 (실패 시 fallback)
    link          TEXT NOT NULL,          -- 원문 URL
    source        TEXT,                   -- 언론사
    published_at  DATETIME,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 발송 로그 (다채널 배치: briefing_id FK 대신 user_id + channel로 기록)
CREATE TABLE send_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    channel    TEXT NOT NULL,             -- "web" | "slack" | "email"
    status     TEXT NOT NULL,             -- "success" | "failed"
    error_msg  TEXT,
    sent_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 8. API 엔드포인트

| Method | Endpoint | 설명 | 상태 |
|--------|----------|------|------|
| GET | `/api/users/{user_id}` | 유저 정보 조회 (로그인 제거로 POST 미노출) | ✅ |
| GET | `/api/settings/{user_id}` | 유저 설정 조회 | ✅ |
| PUT | `/api/settings/{user_id}` | 유저 설정 저장/수정 (upsert) | ✅ |
| GET | `/api/reports?user_id=&category=&limit=` | 카테고리별 **최신 리포트 1건** 리스트 반환 (대시보드 그리드용) | ✅ |
| GET | `/api/reports/{report_id}` | 리포트 상세 (articles 포함) | ✅ |
| GET | `/api/reports/articles/{article_id}` | 개별 기사 상세 | ✅ |
| POST | `/api/reports/generate?user_id={id}` | 즉시 리포트 생성 (동기, 전체 카테고리) | ✅ |
| GET | `/api/reports/generate/stream?user_id={id}` | **SSE 진행 스트림** — `start/category_start/collected/clustered/summarizing_article/synthesizing_radio/category_done/done` 이벤트 | ✅ |
| POST | `/api/send?user_id={id}` | 최신 리포트 전체를 활성 채널(web/slack/email)로 일괄 발송 | ✅ |
| GET | `/api/health` | 헬스 체크 | ✅ |

> 💡 4/17 후속 재설계: ① `briefings` 네임스페이스 전부 제거 → `reports` 로 교체(한 카테고리 = 한 리포트 = 기사 3건 + 라디오). ② 상세 페이지(`/dashboard/briefing/[id]`)가 제거되면서 개별 상세 조회는 백엔드에만 남겨두고 프론트에서는 호출하지 않음(리포트 목록 + 기사 link로 원문 이동). ③ 생성 API는 `GET /stream`을 추가해 SSE로 진행 상황을 푸시하고, `handleGenerate`는 SSE 완료 후 자동으로 `POST /api/send` 를 체이닝해 "버튼 한 번 → 생성 + 발송" 플로우를 완성. ④ `POST /api/users`는 온보딩 제거로 더 이상 프론트에서 호출되지 않아 표에서 제거(라우터는 남아 있음).

---

## 9. 프로젝트 디렉토리 구조

```
briefBot/
├── backend/                            ✅
│   ├── main.py                         # FastAPI 앱, CORS, 라우터 등록, 데모 유저 시딩, 스케줄러 주석처리(데모)
│   ├── config.py                       # pydantic-settings (OPENAI_API_KEY, SMTP_*, GEMINI_* 레거시)
│   ├── database.py                     # SQLAlchemy engine/session, Base
│   ├── models.py                       # User, Setting, Report, Article, SendLog
│   ├── schemas.py                      # Pydantic: ReportOut / ArticleOut / ReportGenerateResponse 등
│   ├── routers/
│   │   ├── users.py                    ✅ GET /api/users/{id}
│   │   ├── settings.py                 ✅ PUT/GET /api/settings/{user_id}
│   │   ├── reports.py                  ✅ GET list/detail, GET articles/{id}, POST /generate, GET /generate/stream (SSE)
│   │   └── send.py                     ✅ POST /api/send (활성 채널 일괄)
│   ├── pipeline/
│   │   ├── collector.py                ✅ GoogleRSSClient (feedparser)
│   │   ├── preprocessor.py             ✅ TF-IDF + 코사인 유사도 클러스터링 + 대표 기사 선정
│   │   ├── analyzer.py                 ✅ OpenAIAnalyzer (기본) + GeminiAnalyzer (레거시)
│   │   └── service.py                  ✅ generate_reports_for_user(db, user_id, on_progress)
│   ├── prompts/
│   │   ├── article_summary.py          ✅ Step1 기사별 3줄 요약 프롬프트
│   │   └── radio_script.py             ✅ Step2 카테고리별 구어체 라디오 스크립트 프롬프트
│   ├── dispatcher/                     ✅ web.py, slack.py, email_sender.py, service.py
│   ├── scheduler.py                    ✅ (데모 기간 main.py lifespan에서 비활성)
│   ├── scripts/                        # seed / ad-hoc 유지보수 스크립트
│   ├── briefbot.db                     # 실행 시 자동 생성
│   ├── .env, .env.example
│   ├── requirements.txt
│   └── CLAUDE.md                       # 백엔드 전용 개발 가이드
├── frontend/                           ✅ (온보딩/상세 페이지 제거 후 3 routes)
│   ├── app/
│   │   ├── layout.tsx                  ✅ Sonner Toaster 마운트
│   │   ├── page.tsx                    ✅ /dashboard 로 redirect (로그인 제거)
│   │   └── dashboard/
│   │       ├── page.tsx                ✅ CategoryReportGrid + ProgressPanel + 생성+발송 체이닝
│   │       └── settings/page.tsx       ✅ 카테고리/주기/채널/AI 모델(OpenAI gpt-5-nano) 설정
│   ├── components/
│   │   ├── dashboard/
│   │   │   ├── dashboard-header.tsx
│   │   │   ├── radio-player-bar.tsx               ✅ HTMLAudioElement + OpenAI TTS mp3 스트림
│   │   │   ├── quick-actions.tsx                   ✅ "지금 리포트 받기" + 카테고리 필터
│   │   │   ├── category-report-grid.tsx            ✅ 카테고리 카드 + 기사 요약 + ▶ 외부 재생 트리거
│   │   │   └── generation-progress-panel.tsx       ✅ SSE 단계별 진행 렌더
│   │   └── ui/                                     # shadcn (수정 자제)
│   ├── lib/
│   │   ├── types.ts                    ✅ 백엔드 schemas.py와 1:1 매핑 (Report/Article)
│   │   ├── api.ts                      ✅ reports.list/get/generate/generateStream, settings, send
│   │   ├── storage.ts                  ✅ DEMO_USER_ID=1 고정 반환
│   │   ├── schedule.ts                 ✅ SchedulePreset → cron 변환
│   │   ├── categories.ts               ✅ 카테고리 ID ↔ 한글 매핑
│   │   └── briefing-display.ts         ✅ 출처/시간 포맷터
│   ├── .env.local, .env.example        ✅ NEXT_PUBLIC_API_URL=http://localhost:8000
│   └── CLAUDE.md                       # 프론트 전용 개발 가이드
├── plan.md                             # 이 문서 (설계 소스 오브 트루스)
├── CLAUDE.md                           # 루트 가이드 (하위 CLAUDE.md로 위임)
└── docs/
```

---

## 10. 개발 일정 (D-6)

| 날짜 | 할 일 | 산출물 | 상태 |
|------|-------|--------|------|
| **4/15 (화)** | 아키텍처 확정 | 이 문서 | ✅ |
| **4/16 (수)** | v0.app UI 프로토타입 수령 | `frontend/` (mock 기반) | ✅ |
| **4/17 오전 (목, Day 1)** | 폴더 재배치 + FastAPI 뼈대 + 수집/전처리/LLM 분석 파이프라인 + DB 저장 + E2E | `backend/` 전체, `gemini-2.5-flash-lite` 적용, `curl POST /api/briefings/generate`로 실제 3건 생성 확인 | ✅ |
| **4/17 오후 (목, Day 2)** | mock 제거 + `lib/{types,api,storage,schedule,categories,briefing-display}.ts` 추가 + 온보딩/대시보드/상세/설정 4개 페이지 실 API 연동 + Sonner toast + `tsc --noEmit` + `next build` 통과 + API E2E 스모크 테스트 | `frontend/lib/*`, `app/**/*`, `components/dashboard/**` 전면 수정 | ✅ |
| **4/17 밤 (목, Day 3 조기 완료)** | Slack/이메일 dispatcher + APScheduler + 라디오 바 Web Speech API 연동 | `dispatcher/`, `scheduler.py`, `radio-player-bar.tsx` 수정 | ✅ |
| **4/17 후속 (목→금 새벽)** | LLM을 OpenAI `gpt-5-nano`로 교체, briefings → reports+articles 재설계, SSE 진행 스트리밍, 상세 페이지 제거·CategoryReportGrid·생성+발송 체이닝 | `analyzer.py`, `models.py`, `schemas.py`, `routers/reports.py`, `lib/api.ts`, `category-report-grid.tsx`, `generation-progress-panel.tsx` | ✅ |
| **4/19 (일, Day 4)** | 로그인/온보딩 제거(데모 간소화), 데모 유저 부팅 시딩, 스케줄러 의도적 비활성, plan.md 재정합 | `main.py`(lifespan 시딩 + scheduler 주석), `frontend/app/page.tsx`(redirect), `storage.ts` 축소, `plan.md` §2~§12 갱신 | ✅ |
| **4/20 (월)** | SMTP 앱 비밀번호 발급 + `.env` 입력, 실기기 리허설(생성→발송→라디오 재생), README/제출 패키징 | `backend/.env`, `README.md`, 데모 영상/스크린샷 | ⬜ |
| **4/21 (화)** | 최종 점검 → 18:00까지 제출 | GitHub 링크 or 압축파일 | ⬜ |

**Day 1–4 누적 검증 결과 (2026-04-19 기준)**
- `curl POST /api/reports/generate?user_id=1` → OpenAI `gpt-5-nano` 호출로 카테고리별 Report + Articles 생성, SQLite 저장, `radio_script` 포함
- `GET /api/reports/generate/stream?user_id=1` → `data: {"type":"start",...}` 부터 `data: {"type":"done",...}`까지 SSE 이벤트 정상 흐름
- `POST /api/send?user_id=1` → 활성 채널(web / email / slack) 별 결과 반환 + `send_logs` 기록
- `pnpm exec tsc --noEmit` → pass (0 errors)
- `pnpm exec next build` → pass, **3 routes** (`/` → redirect → `/dashboard`, `/dashboard`, `/dashboard/settings`)
- 남은 실기기 검증: ① Gmail SMTP 앱 비밀번호 기입 후 실제 메일 수신, ② 브라우저 Chrome/Safari에서 OpenAI TTS mp3 재생(첫 재생 합성 후 캐시 hit 확인), ③ (선택) Slack Webhook으로 Block Kit 메시지 수신

---

## 11. 면접 발표 키 포인트 (메모)

### 킬 메시지
> "가벼운 모델의 한계를 알고 있기 때문에, 모델한테 다 맡기지 않고 **코드가 할 수 있는 건 코드가 하고, 모델은 모델만 할 수 있는 일(자연어 이해/생성)에만 집중**시켰습니다"

### 어필 포인트
- 프롬프트/컨텍스트/하네스 엔지니어링 3단 구조
- 멀티모델 폴백 (Claude Haiku → Gemini Flash)
- 다중 소스 수집 (네이버 + NewsAPI + Google RSS)
- 채널 추상화 (웹/Slack/이메일 3채널 지원)
- 라디오 모드 — 같은 데이터를 채널 특성에 맞게 다른 톤으로 생성 (프롬프트 엔지니어링 활용 사례)
- 기자 관점 분석 기능 (서울신문 맞춤)

### 예상 질문 대비
- Q: 왜 이 모델을 선택했나? → Haiku는 빠르고 저렴, 요약에 강함. Flash는 무료 폴백.
- Q: 실시간성은 어떻게 보장? → 스케줄러 + 즉시 생성 API 이중 구조
- Q: 클러스터링을 왜 코드로? → 임베딩 API 비용 절감 + LLM 토큰 절약
- Q: 확장성은? → 수집 소스 추가 = 새 Client 클래스만 구현, 채널 추가도 동일
- Q: 라디오 모드 TTS 품질은? → OpenAI `gpt-4o-mini-tts` (voice: `nova`)로 합성한 mp3를 서버에서 캐시 후 스트림. 초기 Web Speech API 프로토타입이 인위적이라 교체. 확장은 `services/tts.py` 내부만 바꾸면 ElevenLabs/CLOVA로 전환 가능

---

## 12. 자격증 (Resume용)

**Certifications**
- Engineer Big Data Analysis — Korea Data Agency (KData)
- AICE (AI Certificate for Everyone) — KT
- SW Development Level 5 (NCS) — HRDKorea

---

## 변경 이력

| 날짜 | 변경 내용 |
|------|-----------|
| 2026-04-15 | 초안 작성 — 아키텍처, 기술 스택, 파이프라인, 일정 |
| 2026-04-16 | 라디오 모드 추가 — TTS 재생, 구어체 스크립트 생성, AudioFormatter, RadioPlayer |
| 2026-04-17 | **Day 1 (백엔드) 완료** — `b_ydy857XxdS6/` → `frontend/` rename, `backend/` 신규 생성. FastAPI 앱 + SQLAlchemy 모델(users/settings/briefings/send_logs) + pydantic schemas + 4개 라우터 완성. Google News RSS 단일 소스 수집기(`feedparser`, 24h/20건 컷), TF-IDF + 코사인 유사도(0.6) 클러스터링 전처리, Gemini `gemini-2.5-flash-lite` 기반 Step1 JSON 추출 + Step2-A 3줄 브리핑 + Step2-B 라디오 스크립트 LLM 하네스(재시도 2회, `response_mime_type=application/json`, 중요도 재계산). `POST /api/briefings/generate`로 E2E 동작(실제 브리핑 3건 생성) 확인. |
| 2026-04-17 | **Day 2 (프론트) 완료** — `lib/types.ts`(백엔드 schemas와 1:1), `lib/api.ts`(AbortController 타임아웃 + `BriefBotApiError` + 네임스페이스 API), `lib/storage.ts`(SSR-safe localStorage), `lib/schedule.ts`(preset→cron), `lib/categories.ts`(ID↔한글), `lib/briefing-display.ts`(포맷터) 신규. `app/layout.tsx`에 Sonner Toaster 마운트. 온보딩 `CompletionStep`을 `createUser → saveSettings → setUserId → /dashboard` 오케스트레이션으로 전환. 대시보드 `mockBriefings` 제거, 실 API `list/generate` 연동, "지금 브리핑 받기" 버튼에 `toast.promise` 바인딩. 브리핑 상세 `getBriefing` + 같은 카테고리 관련 브리핑. 설정 페이지는 기존 설정 로드/저장/초기화 + 포트 8000 이슈로 포트 변경도 대응 가능. `tsc --noEmit` pass, `next build` pass(4 routes). |
| 2026-04-17 | **기술 스택 축소 반영** — API 키 미발급 상황으로 `Claude Haiku (메인) → Gemini Flash (폴백)` 멀티모델 체인을 `Gemini 2.5 Flash Lite 단일`로 축소. `네이버 검색 API + NewsAPI.org + Google News RSS` 다중 소스를 `Google News RSS 단일`로 축소. 이들은 분석/하네스 구조를 훼손하지 않는 "소스/모델 차원의 축소"이므로 키 발급 시 Client/폴백 한 개씩만 추가하면 복원 가능 — 플러그인 구조는 유지됨. |
| 2026-04-17 | **아키텍처 보조 정리** — `CLAUDE.md`를 루트(인덱스 역할) + `backend/CLAUDE.md` + `frontend/CLAUDE.md` 3개로 분리(토큰 절감). `routers/send.py`는 Day 3 구현 예정으로 표시. `POST /api/settings` + `PUT /api/settings/{id}` 조합을 `PUT /api/settings/{user_id}` 단일 upsert로 통합. |
| 2026-04-19 | **Day 4 (로그인 제거 — 데모 간소화)** — 온보딩 5단계(Welcome/Category/Schedule/Channel/Completion)를 전부 제거하고 `app/page.tsx`는 `/dashboard`로 곧바로 `redirect`. `components/onboarding/` 폴더 삭제(6개 컴포넌트). `lib/storage.ts`의 `getUserId()`를 항상 `DEMO_USER_ID=1`을 반환하도록 축소, `setUserId/clearUserId`와 localStorage 의존 제거. `backend/main.py` lifespan에 `_ensure_demo_user()` 추가 — 부팅 시마다 `user_id=1`을 `시연용 사용자 <demo@briefbot.local>` + 6개 카테고리 + `schedule_cron="0 8 * * *"` + `channels={web:true, email:"demo@briefbot.local"}` 상태로 멱등 보장(id=1에 다른 계정이 있으면 덮어쓰기 + 동일 email을 가진 stray 유저 정리). `/dashboard/settings`의 로그아웃/데이터 초기화 버튼은 의미를 잃어 제거. 이 변경은 users/settings 스키마를 건드리지 않아 추후 다중 유저 복원 시 온보딩 컴포넌트만 복구하면 됨. `tsc --noEmit` pass, `next build` pass(3 routes: `/`, `/dashboard`, `/dashboard/settings`). |
| 2026-04-17 | **Day 3 (채널 발송 + 스케줄러 + TTS) 완료** — `backend/dispatcher/{web,slack,email_sender,service}.py` 및 `backend/routers/send.py` 실 구현. `SlackSender`는 Block Kit JSON(header + summary section + context + 원문 링크 섹션), `EmailSender`는 SMTP + 반응형 HTML(Gmail App Password 대응), `WebSender`는 DB 저장 확인 no-op. `dispatch_briefing()`이 `Setting.channels` JSON(`{web, slack, email}`)을 파싱해 활성 채널만 호출하고 각 결과를 `send_logs`에 기록. `backend/scheduler.py`의 APScheduler `BackgroundScheduler`(tz=Asia/Seoul)를 `main.py` lifespan에서 기동/종료, 기존 `Setting.schedule_cron`을 전부 `CronTrigger.from_crontab()`으로 등록, `PUT /api/settings/{user_id}`에서 `upsert_user_job()`으로 잡 갱신(remove→add). 프론트 `radio-player-bar.tsx`는 `window.speechSynthesis`로 재구현 — 한국어 voice 자동 선택(`ko-KR` 우선, fallback 기본 음성 + 경고), `onend` 체이닝으로 전체 듣기 모드, Skip Forward/Backward, Pause/Resume, Volume, 카테고리 진행 상황이 `briefings`에서 파생. 대시보드에서 `isPlaying/currentTime/volume` 외부 상태 제거(컴포넌트 내부화). `GEMINI_MODEL` 기본값을 `gemini-2.5-flash-lite`로 수정(갭 분석 C-1), `main.py`에 `logging.basicConfig(INFO)` 추가(m-1). `tsc --noEmit` pass, `next build` pass. 백엔드 스모크: 스케줄러 기동 로그 + `PUT settings` 후 `scheduler: upserted user_id=1 cron=*/5 * * * *` 확인, `POST /api/send/{id}` 404/200 모두 정상, Slack Block Kit/Email HTML 렌더 검증. 남은 검증은 시연 시점의 실제 Slack webhook/Gmail/브라우저 TTS 재생. |
| 2026-04-17 (후속) | **LLM 스택 교체 — OpenAI gpt-5-nano** — Gemini 2.5 Flash Lite 단일 모델에서 **OpenAI `gpt-5-nano`** 기본 LLM으로 전환. `backend/pipeline/analyzer.py`에 `OpenAIAnalyzer` 클래스 신설(`openai` SDK `chat.completions`, gpt-5 family 제약으로 `temperature` 파라미터 미지정 = default 1.0). `GeminiAnalyzer`는 레거시로 파일에 공존(주석 `# Gemini (legacy fallback)`). `config.py`에 `OPENAI_API_KEY` / `OPENAI_MODEL` 추가(`backend/.env.example` 반영), `requirements.txt`에 `openai` 추가. `pipeline/service.py`의 기본 analyzer가 `OpenAIAnalyzer`로 교체. 프론트 `/dashboard/settings` AI 모델 라벨도 "OpenAI gpt-5-nano"로 갱신. |
| 2026-04-17 (후속) | **데이터 모델 재설계 — Reports + Articles 분리** — 단일 `briefings` 테이블 구조를 **`reports`(카테고리 단위, 라디오 스크립트 1개) + `articles`(리포트당 기사 2-3 rows, 3줄 요약)** 2테이블로 분리. `models.py`에서 `Briefing` 제거, `Report` / `Article` SQLAlchemy 모델 신규 작성(cascade delete, `report.articles` relationship). `send_logs` FK를 `briefing_id` → `user_id`로 전환해 다채널 배치 발송을 단일 row로 기록. `source_articles` JSON blob, `raw_analysis`, `importance_score`, `title` 등 사용되지 않는 컬럼 일괄 제거. 개발 DB는 재생성(`briefbot.db` 삭제 → lifespan create_all). `schemas.py`는 `ReportOut / ArticleOut / ReportGenerateResponse`로 교체, 프론트 `lib/types.ts`를 Pydantic과 1:1 재매핑. |
| 2026-04-17 (후속) | **Analyzer 2단 구조로 축소** — 3단 프롬프트(Step1 JSON 추출 / Step2-A 텍스트 브리핑 / Step2-B 라디오)를 **2단(`summarize_article` 기사별 3줄 요약 → `synthesize_radio` 카테고리별 구어체 스크립트)**으로 축소. `prompts/briefing.py`, `prompts/extract.py` 삭제, `prompts/article_summary.py` 신규. 중요도 점수/감성/`_recompute_importance` 규칙 기반 보정 제거(UI에서 소비하지 않음). `analyzer.summarize_article`은 3줄 요약 길이 검증 + 2회 재시도 + RSS summary degraded fallback(`_fallback_summary`). `analyzer.synthesize_radio`는 실패 시 `radio_script=None`으로 graceful. |
| 2026-04-17 (후속) | **API 네임스페이스 교체 — /api/briefings/* → /api/reports/* + SSE** — `routers/briefings.py` 삭제, `routers/reports.py` 신설(`GET /api/reports` 카테고리 최신 1건만 리스트로 반환, `GET /{report_id}`, `GET /articles/{article_id}`, `POST /generate`). 진행 상황 표시용 **`GET /api/reports/generate/stream`** SSE 엔드포인트 추가(`StreamingResponse`, `text/event-stream`, 파이프라인을 background thread에서 실행하며 progress 이벤트를 thread-safe queue로 푸시). 이벤트 타입: `start / category_start / collected / clustered / summarizing_article / synthesizing_radio / category_done / done / error`. 프론트 `lib/api.ts`에 `reports.generateStream()` 추가(fetch streaming + NDJSON 파싱 스타일로 onEvent 콜백), 대시보드 `GenerationProgressPanel`이 실시간 단계 카드로 렌더. 생성 완료 후 자동으로 `POST /api/send`를 체이닝하여 "지금 리포트 받기 버튼 한 번으로 생성+발송". |
| 2026-04-17 (후속) | **프론트 UX 재설계 — 상세 페이지 제거 + 분야별 리포트 카드** — 상세 경로(`/dashboard/briefing/[id]/`)와 5개 상세 섹션 컴포넌트(`briefing/{summary,radio-script,analysis,source-articles,related-briefings,briefing-header}.tsx`) 일괄 삭제. 대신 대시보드에서 카테고리별 리포트 카드를 펼치면 3줄 요약 + 원문 링크가 바로 보이는 **`CategoryReportGrid`** 컴포넌트로 대체(`components/dashboard/category-report-grid.tsx`, `generation-progress-panel.tsx` 신규). `RadioPlayerBar`에 카테고리 외부 재생 트리거(`externalCategory`, `onPlayingCategoryChange`) prop 추가 — 카드에서 ▶ 누르면 라디오 바가 해당 카테고리를 재생. `quick-actions.tsx`는 "지금 리포트 받기" 버튼 하나로 단일화. 이 재설계로 "브리핑 → 리포트" 용어 정리 + UI depth 1단계 축소. |
| 2026-04-17 (후속) | **스케줄러 의도적 비활성화 (데모 비용 통제)** — `main.py` lifespan에서 `start_scheduler()/stop_scheduler()` 호출과 `from scheduler import ...` import를 모두 주석처리. 시연 윈도(4/19~4/21)에 APScheduler cron이 트리거해 예상치 못한 LLM 비용이 발생하지 않도록 차단. 코드/등록 로직은 `backend/scheduler.py`에 완성 상태로 유지 — 주석 해제 한 줄이면 복원 가능. |
| 2026-04-19 | **Day 4 (로그인 제거 — 데모 간소화)** 상세 기록은 위 항목 참고. 이 변경과 함께 plan.md §2/§3/§4/§5.3/§7/§8 전면 갱신(4/17 후속 재설계를 문서에 반영 — 2026-04-19 업데이트). |