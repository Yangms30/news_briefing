# Design: Radio Player OpenAI TTS Integration

> **Feature**: `radio-player-openai-tts-integration`
> **Created**: 2026-04-19
> **Status**: Design
> **Plan**: [`docs/01-plan/features/radio-player-openai-tts-integration.plan.md`](../../01-plan/features/radio-player-openai-tts-integration.plan.md)
> **Depends on**: Main 커밋 `31856f3` (OpenAI migration, `config.OPENAI_TTS_*` 선언 완료)

---

## 1. 아키텍처 개요

```
┌────────────────────── Frontend ───────────────────────┐
│ RadioPlayerBar (Client Component, "use client")        │
│   ├─ audioRef: HTMLAudioElement                        │
│   ├─ currentIndex / isPlaying / isPaused / volume      │
│   └─ src = `${API}/api/reports/${id}/audio`            │
│          │                                             │
│          │  GET (audio/mpeg)                           │
│          ▼                                             │
└────────────────────── Backend ────────────────────────┘
   ┌────────────────────────────────────────────────┐
   │ routers/reports.py                             │
   │   GET /api/reports/{id}/audio                  │
   │     └─ tts.synthesize_to_file(report)          │
   │         └─ FileResponse(mp3, audio/mpeg)       │
   │                    │                           │
   │                    ▼                           │
   │ services/tts.py                                │
   │   synthesize_to_file(report) -> Path           │
   │     ├─ cache hit: return existing path         │
   │     └─ cache miss:                             │
   │         OpenAI.audio.speech.create(            │
   │           model = OPENAI_TTS_MODEL,            │
   │           voice = OPENAI_TTS_VOICE,            │
   │           input = radio_script,                │
   │           format = "mp3")                      │
   │         → write atomically to cache dir        │
   └────────────────────────────────────────────────┘
                        │
                        ▼
              ./media/audio/{report_id}.mp3
```

**설계 원칙**
- **하네스**: OpenAI 호출 실패/지연을 엔드포인트 레벨에서 잡고 503으로 내려줌. 파이프라인 교체 없이 독립 경로로 구현 (리포트 생성과 TTS 합성은 분리)
- **Lazy 합성**: 리포트 생성 시점이 아니라 **프론트가 오디오 요청하는 순간** 합성 (미청취 리포트 비용 절감)
- **캐시 = 디스크**: 서버 재기동 후에도 유지. `Report` 테이블에는 아무 필드 추가 안 함 — 파일 존재 여부 = cache 상태

## 2. 파일 단위 변경 목록

### Backend (`/Users/yangminseok/Desktop/Programming/briefBot/backend/`)

| 파일 | 유형 | 변경 요지 |
|---|---|---|
| `services/__init__.py` | NEW | 빈 파일 (패키지화) |
| `services/tts.py` | NEW | `synthesize_to_file(report: Report) -> pathlib.Path` |
| `routers/reports.py` | EDIT | `GET /api/reports/{id}/audio` 라우트 1개 추가 |
| `main.py` | 변경 없음 | `reports` 라우터 이미 include됨 |
| `.gitignore` (backend) | EDIT | `media/audio/` 추가 |
| `requirements.txt` | 변경 없음 | `openai>=1.55.0` 이미 포함 |

### Frontend (`/Users/yangminseok/Desktop/Programming/briefBot/frontend/`)

| 파일 | 유형 | 변경 요지 |
|---|---|---|
| `components/dashboard/radio-player-bar.tsx` | **REWRITE** | `SpeechSynthesis*` 전량 제거, `HTMLAudioElement` 기반 재구성 |
| `lib/api.ts` | EDIT | `getReportAudioUrl(reportId: number): string` 헬퍼 |

### Docs

| 파일 | 유형 | 변경 요지 |
|---|---|---|
| `plan.md` | EDIT | §8 "Web Speech API" → "OpenAI gpt-4o-mini-tts (voice: nova) + mp3 캐시" |
| `README.md` | EDIT | 라디오 섹션 동일 갱신 |
| `backend/CLAUDE.md` | EDIT | TTS 서비스 한 줄 추가 |

## 3. Backend 상세 설계

### 3.1 `services/tts.py`

```python
# services/tts.py
"""OpenAI TTS (gpt-4o-mini-tts) with filesystem cache.

Cache strategy:
- Path: {AUDIO_CACHE_DIR}/{report_id}.mp3
- Hit: file exists AND size > 0 → return path (no API call)
- Miss: call OpenAI, write to .tmp, os.rename to final (atomic)

Concurrency:
- Atomic rename prevents partial-file reads.
- Duplicate concurrent requests may each call OpenAI once; last writer wins.
  Acceptable: < 1s race window, cost O($0.027) in worst case.
  (No process-wide lock to keep scope minimal.)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from openai import OpenAI, OpenAIError

from config import get_settings
from models import Report

logger = logging.getLogger(__name__)


class TTSUnavailable(RuntimeError):
    """Raised when OpenAI TTS cannot produce audio (config/API errors)."""


def _cache_dir() -> Path:
    cfg = get_settings()
    p = Path(cfg.AUDIO_CACHE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path(report_id: int) -> Path:
    return _cache_dir() / f"{report_id}.mp3"


def synthesize_to_file(report: Report) -> Path:
    """Return an mp3 Path for this report's radio_script.

    Raises:
        TTSUnavailable: missing API key, empty script, or OpenAI error.
    """
    cfg = get_settings()
    if not cfg.OPENAI_API_KEY:
        raise TTSUnavailable("OPENAI_API_KEY not set")

    script = (report.radio_script or "").strip()
    if not script:
        raise TTSUnavailable("radio_script is empty")

    path = _cache_path(report.id)
    if path.exists() and path.stat().st_size > 0:
        logger.info("tts cache hit report_id=%s", report.id)
        return path

    client = OpenAI(api_key=cfg.OPENAI_API_KEY)
    try:
        response = client.audio.speech.create(
            model=cfg.OPENAI_TTS_MODEL,      # "gpt-4o-mini-tts"
            voice=cfg.OPENAI_TTS_VOICE,      # "nova"
            input=script,
            response_format="mp3",
        )
    except OpenAIError as exc:
        logger.exception("openai tts failed report_id=%s", report.id)
        raise TTSUnavailable(f"openai error: {exc}") from exc

    tmp = path.with_suffix(".mp3.tmp")
    try:
        # openai>=1.55.0 supports write_to_file on streamed response
        response.write_to_file(str(tmp))
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    logger.info("tts cache miss → wrote report_id=%s bytes=%s", report.id, path.stat().st_size)
    return path
```

**주요 결정**
- `Path` + atomic rename — SIGINT으로 중단돼도 손상된 mp3가 캐시에 남지 않음
- `TTSUnavailable` — 내부 예외를 한 곳에서 통일. 라우터가 503으로 매핑
- `mkdir(parents=True, exist_ok=True)` — `AUDIO_CACHE_DIR` (`./media/audio`) 자동 생성, 수동 세팅 불필요

### 3.2 `routers/reports.py` 확장

```python
# 기존 import에 추가:
from pathlib import Path
from fastapi.responses import FileResponse
from services.tts import synthesize_to_file, TTSUnavailable

# 기존 _to_out, list_reports, get_report, ... 그대로 유지.
# generate/stream 위/아래 어디든 OK. 아래 위치 제안: get_report 바로 뒤.

@router.get("/{report_id}/audio")
def get_report_audio(report_id: int, db: Session = Depends(get_db)):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(404, "Report not found")
    if not (r.radio_script or "").strip():
        raise HTTPException(404, "Report has no radio_script")
    try:
        path: Path = synthesize_to_file(r)
    except TTSUnavailable as exc:
        raise HTTPException(503, f"TTS unavailable: {exc}")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=f"report-{report_id}.mp3",
        headers={"Cache-Control": "public, max-age=86400"},
    )
```

**응답 계약**

| 상태 | 조건 | 본문 / 헤더 |
|---|---|---|
| 200 | 정상 | `audio/mpeg` mp3 stream. `Cache-Control: public, max-age=86400` (브라우저도 24h 캐시) |
| 404 | Report 없음 | `{"detail": "Report not found"}` |
| 404 | `radio_script` 없음/빈 문자열 | `{"detail": "Report has no radio_script"}` |
| 503 | `TTSUnavailable` (API 키 없음 / OpenAI 에러 / 타임아웃) | `{"detail": "TTS unavailable: ..."}` |

**URL 규약**: `GET /api/reports/{id}/audio` (route prefix는 `main.py`에서 `/api/reports`)

### 3.3 기타

- **`.gitignore` 추가 (backend)**: `media/`  (최상위 `media/` 추가로 충분. `audio/`는 그 하위)
- **`backend/CLAUDE.md`** 파이프라인 섹션 옆에 한 줄:
  > `services/tts.py` — OpenAI gpt-4o-mini-tts로 라디오 스크립트를 mp3로 합성, `./media/audio/{report_id}.mp3` 캐시. 엔드포인트 `GET /api/reports/{id}/audio`에서 lazy 호출.

## 4. Frontend 상세 설계

### 4.1 `lib/api.ts` 추가

```ts
// 기존 API_BASE 등은 유지. 파일 끝에 추가:
export function getReportAudioUrl(reportId: number): string {
  return `${API_BASE}/api/reports/${reportId}/audio`
}
```

### 4.2 `RadioPlayerBar` 재작성 — 상태 모델

```ts
// 기존 Props 대부분 유지. 단 voice/utterRef/tickRef/voicesLoaded 제거.
type Props = {
  reports: Report[]
  isExpanded: boolean
  setIsExpanded: (v: boolean) => void
  externalCategory?: string | null
  onExternalConsumed?: () => void
  onPlayingCategoryChange?: (c: string | null) => void
}

// 내부 상태
const audioRef = useRef<HTMLAudioElement | null>(null)
const [currentIndex, setCurrentIndex] = useState(0)
const [isPlaying, setIsPlaying]   = useState(false)
const [isPaused, setIsPaused]     = useState(false)
const [currentTime, setCurrentTime] = useState(0)
const [duration, setDuration]     = useState(0)
const [volume, setVolume]         = useState(0.75)
const [loadState, setLoadState]   = useState<"idle" | "loading" | "ready" | "error">("idle")
const [errorMessage, setErrorMessage] = useState<string | null>(null)

const playable = useMemo(
  () => reports.filter((r) => (r.radio_script ?? "").trim().length > 0),
  [reports]
)
const current = playable[currentIndex]
```

### 4.3 이벤트 바인딩 (핵심 로직)

```tsx
// 렌더 트리 어딘가에 숨겨진 audio 요소 (UI 아닌, 엔진 전용)
<audio
  ref={audioRef}
  preload="none"
  src={current ? getReportAudioUrl(current.id) : undefined}
  onLoadStart={() => setLoadState("loading")}
  onCanPlay={() => setLoadState("ready")}
  onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
  onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
  onEnded={handleNextOrStop}
  onError={handleAudioError}
  onPlay={() => { setIsPlaying(true); setIsPaused(false) }}
  onPause={() => setIsPaused(true)}
/>
```

**전이 규칙**

| 사용자 액션 | 효과 |
|---|---|
| Play (idle) | `audioRef.current.play()` — 첫 호출은 503 가능, catch로 `errorMessage` 설정 |
| Play (paused) | `audioRef.current.play()` |
| Pause | `audioRef.current.pause()` |
| Skip forward | `currentIndex++` → `src` 교체 → `onLoadedMetadata` 받고 isPlaying이면 자동 play |
| Skip backward | `currentIndex--` 또는 `currentTime=0` (첫 곡이면) |
| Seek (slider) | `audioRef.current.currentTime = value` |
| Volume slider | `audioRef.current.volume = v/100`; state에도 반영 |
| 곡 종료 (`onEnded`) | 다음 인덱스 있으면 자동 재생, 없으면 `isPlaying=false` |
| `onError` | `setLoadState("error")` + `setErrorMessage("재생 실패: 서버 연결 확인")` |

### 4.4 에러/로딩 표시

- **로딩 중** (`loadState === "loading"`): Play 버튼 내부 아이콘을 `<Loader2 className="animate-spin" />`로 교체, 버튼 disable
- **503 / 네트워크 실패**: 카테고리 진행바 아래 빨간 텍스트로 `errorMessage` 표시 + Play 버튼 disable
- **`radio_script` 없는 리포트는 `playable`에서 필터** (기존 로직 유지) → 재생 목록 자체에 안 나옴
- **기존 `warning` (한국어 음성 없음)** 코드 전량 삭제 — Web Speech API 쓰지 않으므로 무관

### 4.5 제거 대상

- `import { SpeechSynthesisUtterance }` 사용부 전체 (현재 코드는 `new SpeechSynthesisUtterance` 생성)
- `pickKoreanVoice`, `voicesLoaded`, `voice`, `onvoiceschanged`, `utterRef`, `tickRef`
- `CHARS_PER_SECOND`, `estimateDuration` (이제 실제 duration을 `HTMLAudioElement`가 제공)
- `startTicking`/`stopTicking` (interval 기반 타이머 → `onTimeUpdate` 이벤트로 대체)
- `speakCurrent` 콜백 전체

## 5. 시퀀스 다이어그램 — 최초 재생 (cache miss)

```
User       Browser             Frontend(RadioPlayerBar)     Backend(/api/reports/:id/audio)    OpenAI
 │ click     │                         │                                  │                         │
 │ Play ────▶│                         │                                  │                         │
 │           │  play()                 │                                  │                         │
 │           ├────────────────────────▶│                                  │                         │
 │           │                         │  GET audio (src)                 │                         │
 │           │                         ├─────────────────────────────────▶│                         │
 │           │                         │                                  │  audio.speech.create    │
 │           │                         │                                  ├────────────────────────▶│
 │           │                         │                                  │                         │
 │           │                         │                                  │◀────mp3 stream──────────┤
 │           │                         │                                  │  write_to_file + rename │
 │           │                         │◀────200 audio/mpeg───────────────┤                         │
 │           │  onCanPlay              │                                  │                         │
 │           │  onLoadedMetadata       │                                  │                         │
 │           │  (buffer plays)         │                                  │                         │
 │ 🔊────────┤                         │                                  │                         │
```

**재재생 (cache hit)**: OpenAI 호출 생략, 파일 바로 stream. 경과 시간 << 1초.

## 6. 에러 플로우

```
frontend play()
   │
   ├─ 200 → 재생 시작 → onTimeUpdate로 진행바 업데이트
   │
   ├─ 404 (Report not found / no radio_script)
   │    → onError → setErrorMessage("해당 리포트는 재생 대상이 아닙니다") → Play disable
   │
   ├─ 503 (TTSUnavailable)
   │    → onError → setErrorMessage("음성 서비스 일시 중단 — 키/서버 확인") → Play disable
   │
   └─ 네트워크 에러 / 5xx
        → onError → setErrorMessage("재생 실패 — 잠시 후 다시 시도") → Play 재시도 가능
```

## 7. 비기능 요구사항

| 항목 | 기준 |
|---|---|
| **첫 재생 지연** | p50 ≤ 5s, p95 ≤ 12s (OpenAI 응답 시간 의존) |
| **캐시 hit 지연** | ≤ 500ms (파일 I/O + HTTP) |
| **동시 재생** | 단일 audio element — 여러 리포트 동시 재생은 의도적으로 차단 (다음 곡으로 전이 시 이전 중단) |
| **자원** | mp3 1개 ≈ 400~600KB. 리포트 6개 기준 ≤ 4MB. 제출 전 누적 최대 30MB 예상 |
| **보안** | 공개 엔드포인트 (현재 시스템 전체가 demo user_id=1 공유이므로 기존 정책과 동일). 민감 정보 아님 |
| **국제화** | 음성 voice="nova" 는 한국어 지원 확인 — 제출 전 실기기 리허설 시 청취 평가 |

## 8. 테스트 전략 (Zero Script QA)

별도 pytest 스크립트 작성 없이 **수동 + 로그 기반 검증**. 체크리스트:

| # | 시나리오 | 기대 결과 | 확인 방법 |
|---|---|---|---|
| T1 | 신선한 DB + 리포트 생성 → 첫 재생 | 백엔드 로그 `tts cache miss → wrote report_id=X`. mp3 파일 생성됨 | `tail -f` + `ls media/audio/` |
| T2 | 같은 리포트 재재생 | 로그 `tts cache hit report_id=X`. OpenAI 호출 0 | 로그 + OpenAI 대시보드 |
| T3 | `radio_script` 비어있는 리포트 재생 시도 | 404 `no radio_script`, Play 버튼이 애초에 disable (`playable` 필터) | DevTools Network |
| T4 | `.env`에서 `OPENAI_API_KEY` 삭제 → 서버 재기동 → 재생 | 503, 프론트 에러 토스트, Play disable | 의도적 키 제거 |
| T5 | 6개 카테고리 자동 순차 재생 | 곡 종료 시 자동 다음 곡. 마지막 곡 끝나면 isPlaying=false | 육안 |
| T6 | 재생 중 슬라이더 seek | 해당 지점부터 재생 | 육안 |
| T7 | 재생 중 볼륨 슬라이더 | 즉시 반영 | 청음 |
| T8 | iOS Safari (실기기) | 사용자 클릭 기반이므로 자동재생 정책 무관하게 재생 성공 | 실기기 |
| T9 | macOS Chrome | 재생 성공 | 실기기 |
| T10 | Web Speech API 잔존물 0 | `grep -r speechSynthesis frontend/components/` → 0 hits | `grep` |

**로그 포맷** (stdout, INFO): `tts cache hit report_id=12` / `tts cache miss → wrote report_id=12 bytes=487123` / `openai tts failed report_id=12`

## 9. 구현 순서 (Do Phase 진입용)

1. **Backend 먼저** — `.env` 확인 → `services/tts.py` → 라우터 확장 → Postman/curl로 `/api/reports/1/audio` 응답 확인 (mp3 다운로드 성공)
2. **Frontend** — `lib/api.ts` 헬퍼 → `RadioPlayerBar` 재작성 (커밋 전에 `grep speechSynthesis` 자기검증)
3. **문서** — `plan.md` §8, `README.md`, `backend/CLAUDE.md` 한 번에 diff
4. **실기기** — 체크리스트 T1~T10 수동 확인

## 10. 미해결 / 합의 필요

- [ ] **voice="nova" 한국어 품질**: 청취 전까지 확정 불가. 불만족 시 플랜B로 `alloy`/`shimmer` 중 골라 `.env`에서 `OPENAI_TTS_VOICE` 값만 변경 (코드 변경 없음)
- [ ] **미리 warm-up?**: 리포트 생성 완료 시점에 백그라운드로 TTS도 같이 합성해두면 첫 재생이 즉시 시작됨. 하지만 구현 시간 + 미청취 리포트 비용 증가 → **Do 단계에서 스킵**, 추후 개선 여지로 남김
- [ ] **캐시 수명**: 현재는 무한. 리포트 삭제 시 cascade로 mp3 삭제되는 로직은 현재 리포트 삭제 API 자체가 없으므로 불필요. 미래에 추가 시 고려
- [ ] **worktree 동기화**: 이 design 문서는 main에 기록. 실제 구현은 main 또는 별도 브랜치 — Do 단계 직전에 결정 (Plan 문서 §4 참고)

---

**다음 액션**: `/pdca do radio-player-openai-tts-integration`
