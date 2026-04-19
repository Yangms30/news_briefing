# CLAUDE.md — backend/

This file provides guidance to Claude Code when working in the **backend/** directory.

## 개발 명령어

```bash
cd backend
python3 -m venv venv && source venv/bin/activate   # 최초 1회
pip install -r requirements.txt                    # 최초 1회
cp .env.example .env                               # .env에 OPENAI_API_KEY 입력 (필수), SMTP_* (Day 5)
uvicorn main:app --reload                          # http://localhost:8000
```

- 포트 8000이 점유 중이면 `--port 8765` 등으로 변경 (검증 시 충돌 이력 있음).
- 테스트 프레임워크 미도입 — 수동 검증은 `python -c "from ..."` + `curl` 조합.
- DB 스키마 변경 후에는 `briefbot.db` 삭제 → 재기동(`main.py` lifespan에서 `Base.metadata.create_all` + 데모 유저 시딩으로 재구성).
- 스케줄러는 `main.py` lifespan에서 **의도적 주석 처리** 상태 (데모 기간 LLM 비용 통제). 주석 해제 한 줄이면 복원 가능.

## 파이프라인 2단 구조 ("프롬프트/컨텍스트/하네스 엔지니어링")

> Day 3 재설계: 기존 3단(`_step1_extract`(JSON) + `_step2_briefing` + `_step2_radio`) 구조를 **"기사 단위 요약 + 카테고리 단위 라디오"** 2단으로 축소. 분야별 리포트(카테고리당 기사 3건 + 라디오 1개) 데이터 모델과 1:N 정합. 중요도/감성 등 UI에서 소비되지 않는 필드는 제거.

```
collector.py ──▶ preprocessor.py ──▶ analyzer.py ──▶ service.py ──▶ DB
(RSS 수집)        (TF-IDF 클러스터링)   (OpenAI + 하네스)    (오케스트레이션)
```

- **`pipeline/collector.py`** — Google News RSS만 사용 (`feedparser`). 카테고리→쿼리 매핑은 `CATEGORY_QUERIES` 상수. 네이버/NewsAPI는 미발급이라 클라이언트 클래스가 없음. 추가 소스가 필요하면 같은 인터페이스(`RawArticle` 반환)로 새 Client 추가.
- **`pipeline/preprocessor.py`** — LLM 호출 없음. 제목을 TF-IDF 벡터화 후 코사인 유사도 ≥ `CLUSTER_THRESHOLD`(0.6)로 그리디 클러스터링. 클러스터당 대표 기사 2~3건(최신순 + 출처 다양성). 노이즈 제거는 `NOISE_PATTERNS` 정규식.
- **`pipeline/analyzer.py`** — **여기에만 LLM 호출 집중.** 기본 `OpenAIAnalyzer` (`gpt-5-nano`). `GeminiAnalyzer`는 레거시 폴백 클래스로 보존. 2단 호출:
  1. `summarize_article(category, article)` — 기사별 3줄 한국어 요약(문어체). 길이 ≥ 30자 검증 + `LLM_MAX_RETRIES`회 재시도 → 실패 시 `RawArticle.summary` 기반 RSS fallback.
  2. `synthesize_radio(category, articles_with_summary)` — 30초~1분 분량 카테고리별 구어체 라디오 스크립트 (숫자/약어 한글 변환 포함). 실패 시 `radio_script=None`으로 graceful 저장.
  - **gpt-5 family 제약**: `temperature` 파라미터 전달 불가 (기본 1.0 강제). 톤 제어는 프롬프트에서만.
- **`pipeline/service.py`** — `generate_reports_for_user(db, user_id, on_progress=None)`가 공개 진입점. `on_progress(dict)` 콜백으로 카테고리별/기사별 진행 이벤트 스트림. 라우터(`POST /api/reports/generate` 동기 + `GET /api/reports/generate/stream` SSE)와 스케줄러에서 공유.

## TTS 서비스 (`services/tts.py`)

라디오 스크립트를 **OpenAI `gpt-4o-mini-tts`** (voice: `nova`)로 mp3 합성.
- 캐시: `./media/audio/{report_id}.mp3` (`AUDIO_CACHE_DIR` 환경변수로 변경 가능, 기본 `./media/audio`)
- Lazy: 리포트 생성 시점이 아니라 `GET /api/reports/{id}/audio` 호출 시에 합성 (미청취 리포트 비용 절감)
- 원자적 쓰기: `.mp3.tmp` → `os.replace`로 부분 쓰기 방지
- 실패 시 `TTSUnavailable` 예외 → 라우터가 503으로 매핑 (`OPENAI_API_KEY` 누락 / OpenAI 에러 / 빈 `radio_script`)
- **Day 3 → Day 4 교체**: 초기엔 프론트에서 Web Speech API(브라우저 내장)를 사용했으나 실기기에서 음성이 인위적이어서 교체. `services/tts.py` 한 레이어만 수정하면 ElevenLabs / CLOVA Voice 등으로 추가 교체 가능.

## 프롬프트 분리 (`prompts/`)

프롬프트 텍스트는 `prompts/{article_summary,radio_script}.py`에 `*_SYSTEM`, `*_USER_TEMPLATE` 상수로 격리. 프롬프트 변경은 **이 파일만 수정**하고 `analyzer.py`는 건드리지 않는 것이 원칙. 2단 구조로 축소되면서 `prompts/extract.py`, `prompts/briefing.py`는 제거됨.

## DB 모델 (`models.py`)

5개 테이블: `users`, `settings`, `reports`, `articles`, `send_logs`.

- **`reports`** (카테고리 단위): `user_id`, `category`, `radio_script`, `created_at`. 1 유저 × N 카테고리.
- **`articles`** (기사 단위): `report_id` FK, `title`, `summary`(LLM 3줄 요약), `link`, `source`, `published_at`. `Report.articles` relationship + `cascade="all, delete-orphan"` — 리포트 삭제 시 기사 동반 삭제.
- **Day 3 재설계**: 이전 `briefings` 단일 테이블(기사 blob 포함)을 `reports` + `articles`로 분리. UI 단위(카테고리 카드)와 1:N 자연 대응. `send_logs.briefing_id` → `user_id`로 변경(다채널 배치 발송 1 row 기록).
- `Setting.categories`, `Setting.channels`는 **JSON 문자열**로 저장 (SQLite 단순성 유지). 라우터의 `_to_out` 헬퍼에서 파싱.
- `User.email`만 unique. 로그인 개념 없음 — 데모 유저(id=1)가 부팅 시 자동 시딩(`main.py` lifespan + `scripts/seed.py`). 프론트는 `lib/storage.ts`의 `DEMO_USER_ID=1` 고정 사용.

## LLM 모델 제약 (중요)

메인은 **`OPENAI_MODEL=gpt-5-nano`** (`.env`). 이유:
- 경량/저비용 OpenAI 계열. `gpt-5` family는 `temperature`/`top_p` 등 샘플링 파라미터 전달 불가 (기본 1.0 고정) — 톤 제어는 프롬프트에서만.
- `OpenAIAnalyzer`가 `client.chat.completions.create`로 호출. 재시도/검증은 `analyzer.py` 내 `_call_with_retry()` 패턴 준수.

**레거시 폴백**: `GeminiAnalyzer` 클래스와 `GEMINI_MODEL=gemini-2.5-flash-lite` 설정은 코드에 보존. Gemini로 롤백 시 `service.py`에서 `analyzer = GeminiAnalyzer()`로 교체하면 바로 동작. (Gemini 2.0 Flash는 이 프로젝트 무료 티어 limit: 0, 1.5 Flash는 API 404 — 2.5 Flash Lite만 동작 검증됨.)

**TTS**: `OPENAI_TTS_MODEL=gpt-4o-mini-tts`, `OPENAI_TTS_VOICE=nova`. `services/tts.py`만 사용, 다른 곳에서 참조 X.

Claude/네이버/NewsAPI 키는 여전히 미발급. 키가 추가되면 `plan.md` §2의 다중 소스를 본래 설계대로 확장 가능 (`analyzer.py`에 폴백 클라이언트 추가, `collector.py`에 Client 클래스 추가).

## 규약

- 새 라우터는 `routers/`에 파일 추가 후 `main.py`의 `app.include_router(...)`에 등록.
- 새 파이프라인 단계나 LLM 호출을 추가할 때는 **하네스 원칙 준수**: 출력 검증 → 재시도 → 실패 시 graceful 스킵. 전체 파이프라인이 한 클러스터 실패로 멈추면 안 됨 (`service.py` 참고).
- `.env`는 `.gitignore`에 포함. 키 노출 시 즉시 회전.
- 코드 식별자/주석/로그는 영어 유지 (UI 텍스트/프롬프트만 한국어).
