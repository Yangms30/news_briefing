# Plan: Radio Player OpenAI TTS Integration

> **Feature**: `radio-player-openai-tts-integration`
> **Created**: 2026-04-19
> **Owner**: 양민석
> **Status**: Plan
> **Deadline**: 2026-04-21 18:00 (D-2, 서울신문 과제 제출)
> **Predecessor**: [`docs/plan.md`](../../../plan.md) §8 (라디오 브리핑 섹션)

---

## 1. 배경 (Why)

현재 라디오 브리핑 재생 시 **macOS/Chrome 기본 한국어 TTS (Web Speech API)** 를 사용. 실기기에서 확인한 결과 목소리가 부자연스러워 시연 품질이 낮음.

사용자 피드백: *"음성으로 요약해주는 기능의 목소리가 너무 인위적"* — 이미 main 커밋 `31856f3` (Day 3-4)에서 `OPENAI_TTS_MODEL=gpt-4o-mini-tts`, `OPENAI_TTS_VOICE=nova`를 `backend/config.py`에 선언해뒀으나 **실제 호출 경로는 아직 없음** (데드 코드). 프론트는 여전히 `new SpeechSynthesisUtterance()` 사용.

## 2. 목표 (What)

라디오 플레이어의 음성을 **브라우저 내장 TTS → OpenAI `gpt-4o-mini-tts` (voice: "nova")** 로 교체. 리포트별 `radio_script`를 서버에서 mp3로 합성·캐시하고, 프론트는 `<audio>` 태그로 재생.

### 성공 기준 (Definition of Done)

| # | 기준 | 검증 방법 |
|---|---|---|
| 1 | 라디오 재생 버튼 → OpenAI TTS 음성이 재생됨 | 실기기 청취 (macOS + iOS Safari + Chrome) |
| 2 | 동일 리포트 두 번째 재생 시 mp3 캐시 hit, OpenAI 추가 호출 없음 | 백엔드 로그 확인 + Network 탭 |
| 3 | Web Speech API 코드 완전 제거 (`SpeechSynthesisUtterance` 0건) | `grep speechSynthesis frontend/` → 0 hits |
| 4 | OpenAI API 키 없을 때 graceful 실패 (500 대신 503 + 안내 토스트) | `.env`에서 `OPENAI_API_KEY` 비워 테스트 |
| 5 | `plan.md` §8, README 라디오 섹션 반영 (Web Speech API → gpt-4o-mini-tts) | 문서 diff |
| 6 | Day 5 SMTP/리허설 작업과 충돌 없음 | `git status` clean, 머지 후 E2E `generate → send` 정상 |

## 3. 범위 (Scope)

### In Scope
- `backend/services/tts.py` — OpenAI client 래퍼 (mp3 합성 + 파일 캐시)
- `backend/routers/reports.py` 확장 — `GET /api/reports/{id}/audio` mp3 스트리밍 엔드포인트
- `backend/config.py` — 이미 있는 `OPENAI_TTS_MODEL`/`_VOICE`/`AUDIO_CACHE_DIR` 사용
- `frontend/components/dashboard/radio-player-bar.tsx` — `SpeechSynthesis` 전면 제거, `HTMLAudioElement` 기반 재구성 (재생/일시정지/볼륨/진행바/카테고리 전환 모두 유지)
- `frontend/lib/api.ts` — `getReportAudioUrl(reportId)` 헬퍼 추가
- `frontend/lib/types.ts` — `Report` 인터페이스에 `audio_url?: string` 추가 검토 (또는 URL 규약만 문서화)
- `.gitignore` — `backend/media/audio/` 추가
- `plan.md` §8, `README.md`, `backend/CLAUDE.md` 문구 갱신

### Out of Scope
- 음성 선택 UI (voice는 "nova" 고정)
- 실시간 스트리밍 TTS (완성 mp3를 한 번에 다운로드)
- 비-OpenAI fallback (ElevenLabs, Edge TTS 등)
- 프론트 `briefing/radio-script-section.tsx` 재생 버튼 (현 main에선 사용 안 됨, 상세 페이지 제거됨)
- Slack/Email 채널에 mp3 첨부 (제출 범위 아님)
- iOS Safari 자동재생 정책 대응 (사용자 클릭 기반이라 문제 없음, 추가 대응 불필요)

## 4. 제약 조건 (Constraints)

| 제약 | 내용 |
|---|---|
| **시간** | D-2. 오늘 저녁 ~ 내일(4/20) 오전에 끝내고, 4/20 오후는 SMTP + 실기기 리허설로 확보 |
| **비용** | `gpt-4o-mini-tts` 약 $0.015 / 1K chars. 리포트 1개(~300자) × 6 카테고리 = 1,800자 → **$0.027/회 생성**. 캐시 hit 시 무료. 제출 전 리허설 최대 20회 → **$0.54 이내** |
| **모델 메모리** | `gpt-4o-mini-tts`는 TTS 모델이라 메인 `gpt-5-nano`와 무관. `temperature` 파라미터 적용되지 않음 |
| **키** | `OPENAI_API_KEY`는 메인 분석기에서 이미 사용 중 (memory: 발급 완료). 동일 키 공유 |
| **CORS** | 오디오 엔드포인트도 기존 `ALLOWED_ORIGINS` 적용 |
| **브랜치** | 현재 worktree(`claude/admiring-swirles`)는 main 대비 `31856f3` 1개 뒤처짐. **main에서 직접 작업 또는 rebase 후 worktree 작업** (실제 실행 단계에서 결정) |

## 5. 리스크 & 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| OpenAI TTS 지연 (5~10초) | 첫 재생 UX 저하 | 프론트에서 "음성 준비 중…" 로딩 표시. 리포트 생성 직후 **사전 warm-up 호출** 선택적으로 검토 (필수 아님) |
| 동시 요청 중복 합성 | 같은 리포트 mp3를 여러 번 생성 | 파일 존재 체크(`os.path.exists`) 선행. race condition은 임시 파일 → rename 패턴으로 방지 |
| 캐시 디스크 증가 | `media/audio/` 누적 | 파일명 `{report_id}.mp3` 고정. 리포트 삭제 시 cascade로 mp3 삭제 (models.py에 훅 추가, 또는 삭제 API에서 처리) |
| `OPENAI_API_KEY` 누락 | 500 에러 | 503 + `{"error": "TTS_UNAVAILABLE"}` 반환, 프론트에서 "음성 서비스 일시 중단" 토스트 + 재생 버튼 disable |
| 프론트 자동 테스트 없음 | 수동 회귀 누락 가능 | 실기기 체크리스트를 `docs/02-design/` 설계 문서에 명시 |
| 마감 지연 | 제출 실패 | 구현 막히면 **Day 5 오전까지만 시도, 실패 시 Web Speech API 롤백** 옵션 유지. 로직 교체는 프론트 파일 1개라 rollback 용이 |

## 6. 구현 단계 (High-Level)

> 상세 구조는 Design 단계(`/pdca design`)에서 확정. 여기서는 단계만 목록화.

1. **Phase 1 — Backend TTS 서비스**
   - `backend/services/__init__.py`, `backend/services/tts.py` 생성
   - `synthesize(text: str, report_id: int) -> Path` 함수 (캐시 hit → 경로 반환, miss → OpenAI 호출 → 저장 → 경로 반환)
   - 에러 처리 + 로깅

2. **Phase 2 — Audio 엔드포인트**
   - `backend/routers/reports.py`에 `GET /api/reports/{id}/audio`
   - 리포트 조회 → `radio_script` 존재 확인 → `tts.synthesize` → `FileResponse(media_type="audio/mpeg")`
   - 404 / 503 분기

3. **Phase 3 — Frontend 교체**
   - `frontend/components/dashboard/radio-player-bar.tsx` 재작성:
     - `SpeechSynthesisUtterance` 관련 코드/훅/ref 전부 삭제
     - `audioRef = useRef<HTMLAudioElement>()` + `<audio>` 요소
     - `src`는 `reports[currentIndex]`의 audio URL. `onended`/`onerror`/`ontimeupdate`로 상태 동기화
     - 볼륨 / skip / seek / 카테고리 진행 UI 유지
   - `frontend/lib/api.ts`에 `getReportAudioUrl(id)` 헬퍼

4. **Phase 4 — 문서 갱신**
   - `plan.md` §8 "Web Speech API" → "OpenAI gpt-4o-mini-tts (voice: nova) + mp3 캐시"
   - `README.md` 라디오 섹션 동일 갱신
   - `backend/CLAUDE.md`에 TTS 파이프라인 한 줄 추가

5. **Phase 5 — 실기기 리허설**
   - `.env` `OPENAI_API_KEY` 확인
   - 서버 재기동 → `POST /api/reports/generate` → 6개 카테고리 mp3 생성 로그
   - 두 번째 재생 → 캐시 hit 로그
   - macOS Chrome / Safari / 아이폰 모바일에서 재생 확인
   - 키 삭제 테스트로 503 fallback 확인

## 7. 관련 문서

- **상위 설계**: `plan.md` §8 (라디오 브리핑), §10 (일정)
- **커밋 히스토리**: `31856f3` Day 3-4 (OpenAI migration) — config만 추가된 상태
- **메모리 노트**:
  - `smtp_setup_pending.md` (Day 5 남은 작업, 본 plan과 병행)
  - `gemini_model_constraint.md` (temperature 불가 등 LLM 제약; TTS 모델은 해당 없음)
  - `demo_flow_preference.md` ("지금 리포트 받기" 한 번으로 생성+발송 체이닝) — 본 TTS 변경은 이 흐름 변경 없음
- **다음 단계**: `/pdca design radio-player-openai-tts-integration`

## 8. 의사결정 기록

| 결정 | 대안 | 선택 이유 |
|---|---|---|
| Voice = "nova" 고정 | shimmer, alloy, echo 등 | 한국어 발음 테스트는 여유 없음. `config.py`에 이미 "nova" 명시되어 있으므로 그대로 채택. 제출 후 개선 여지 |
| mp3 파일 캐시 | 메모리 캐시(LRU) | 서버 재기동 후에도 유지되어야 함. 6개 리포트 × ~480KB ≈ 3MB로 디스크 부담 미미 |
| `<audio>` 태그 + `HTMLAudioElement` | Web Audio API | 재생/일시정지/볼륨만 필요. Web Audio는 오버엔지니어링 |
| 동기 합성 (블로킹) | 비동기 job queue | 30초 이내 완료 예상. APScheduler/Celery 도입은 제출 범위 초과 |
| iOS 자동재생 대응 | - | 사용자 클릭 트리거라 불필요 |

---

**다음 액션**: `/pdca design radio-player-openai-tts-integration`

