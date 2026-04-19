# CLAUDE.md — frontend/

This file provides guidance to Claude Code when working in the **frontend/** directory.

## 개발 명령어

```bash
cd frontend
pnpm install                                       # 최초 1회
pnpm dev                                           # http://localhost:3000
pnpm lint                                          # ESLint
pnpm exec tsc --noEmit                             # 타입 검사 (CI 수준)
pnpm build                                         # 프로덕션 빌드 (3 routes)
```

- **pnpm 필수** (lock 파일이 `pnpm-lock.yaml`). npm/yarn 섞어 쓰면 안 됨.
- API base URL은 `frontend/.env.local`의 `NEXT_PUBLIC_API_URL` (기본 `http://localhost:8000`).

## 폴더 이력

원래 v0.app이 생성한 이름은 `b_ydy857XxdS6`였으나 `frontend/`로 rename됨. 과거 커밋/이슈에서 옛 이름이 보이면 같은 폴더로 해석.

## 라우트 / 페이지 구조 (현행, 3개)

- `/` (`app/page.tsx`) — `/dashboard`로 즉시 redirect. Day 4에 5단계 온보딩 제거(시연 간소화).
- `/dashboard` (`app/dashboard/page.tsx`) — 카테고리 리포트 카드 그리드 + 상단 라디오 플레이어 바 + 카테고리/날짜 필터 + "지금 리포트 받기" 버튼 + SSE 진행 패널.
- `/dashboard/settings` — 카테고리/크론/채널(이메일·Slack) 설정. `PUT /api/settings/{user_id}` upsert.

> Day 3에 상세 페이지 `/dashboard/briefing/[id]`를 제거하고 카드 그리드 안에서 모든 정보를 보여주는 구조로 전환. 상세 페이지용 컴포넌트 디렉토리(`components/briefing/`)도 함께 제거됨.

## 상태 관리 / API 연동

- **전역 상태 라이브러리 없음** (Context/Zustand/Redux 모두 미사용). 각 페이지가 `useState`로 로컬 상태만 관리. 컴포넌트 간 통신은 prop drilling + 콜백.
- **모든 데이터가 실 API 연동됨** (Day 2 완료). `lib/api.ts`의 네임스페이스 API(`api.users`, `api.settings`, `api.reports`, `api.send`)가 단일 진입점. `BriefBotApiError`로 에러 타입 통일.
- **SSE 스트리밍**: `api.reports.generateStream(userId, onEvent)`이 `GET /api/reports/generate/stream`을 구독하고 `GenerateProgressEvent` 유니온 타입으로 디스패치. 생성 완료(`type: "done"`) 후 자동으로 `api.send.dispatch()` 체이닝.
- **로그인 개념 없음** (Day 4 단순화). `lib/storage.ts`의 `DEMO_USER_ID = 1` 상수를 `getUserId()`로 반환. 부팅 시 백엔드 lifespan에서 데모 유저 시딩.

## UI 라이브러리 / 스타일

- **shadcn/ui** (Radix UI 기반) — `components/ui/`에 60+ 컴포넌트 이미 설치됨. 새 컴포넌트는 `pnpm dlx shadcn@latest add <name>`. 설정(`components.json`): `style: new-york`, `baseColor: neutral`, CSS variables 활성화, 아이콘은 `lucide-react`.
- **Tailwind 4** + OKLCH 컬러 변수 (`app/globals.css`), **다크모드 기본**. CSS-in-JS 없음. 클래스 병합은 `lib/utils.ts`의 `cn()` (clsx + tailwind-merge).
- **Framer Motion** — 카드 호버/리스트 모션 등 미세 애니메이션에만 사용 (온보딩 제거 후 사용처 축소).
- **Sonner** — 토스트 (`toast.success`/`toast.error` 직접 호출).
- 폼은 `react-hook-form` + `zod` (의존성 설치됨, 설정 페이지에서 사용).

## 컴포넌트 분류

- `components/ui/` — shadcn/ui (수정 자제, 필요 시 wrapper 작성).
- `components/dashboard/` — `dashboard-header`, `radio-player-bar`, `category-report-grid`, `quick-actions`, `generation-progress-panel`.
- `components/theme-provider.tsx` — 루트 테마 컨텍스트.

> `components/onboarding/` 및 `components/briefing/` 디렉토리는 각각 Day 4(온보딩 제거) / Day 3(상세 페이지 제거) 때 삭제됨.

## 라디오 플레이어 (`components/dashboard/radio-player-bar.tsx`)

- **Day 4 교체**: 이전엔 `window.speechSynthesis` (Web Speech API)였으나 실기기에서 음성이 인위적이라 **OpenAI `gpt-4o-mini-tts`** 백엔드로 교체.
- 현재 구현: `useRef<HTMLAudioElement>` + `<audio>` 태그. `src`는 `getReportAudioUrl(report.id)` = `GET /api/reports/{id}/audio` (서버에서 mp3 합성 + 디스크 캐시).
- 이벤트: `onLoadedMetadata`/`onTimeUpdate`/`onEnded`/`onError`/`onPlay`/`onPause`. 카테고리 종료 시 자동 다음 곡 전환.
- 외부 제어: `externalCategory` (카드에서 특정 카테고리 재생 요청), `externalPauseSignal` (카드에서 일시정지 요청 — counter 증가로 감지), `onPlayingCategoryChange` (카드 UI 동기화).

## 규약

- 모든 페이지/컴포넌트는 `"use client"` 사용 (RSC 미사용 — v0.app 생성 기조 유지).
- UI 텍스트는 한국어 (서울신문 과제 대상). 코드 식별자/주석/로그는 영어.
- 새 도메인 컴포넌트는 `components/dashboard/`에 추가. 공통 UI는 `components/ui/` 외부에 두지 말 것.
- 백엔드 응답 타입은 `backend/schemas.py`(Pydantic)와 1:1 매핑이 원칙. `lib/types.ts`에 미러링 후 `lib/api.ts`에서 정형화.
- SSE 이벤트 타입(`GenerateProgressEvent`)이 바뀌면 `lib/types.ts` + `components/dashboard/generation-progress-panel.tsx`를 함께 수정.
