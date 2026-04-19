# BriefBot 뉴스 수집 · 클러스터링 파이프라인 상세

> 최종 업데이트: 2026-04-20 (Day 5 — 다중 소스 확장)
> 대상 코드: `backend/pipeline/collector.py`, `backend/pipeline/preprocessor.py`, `backend/pipeline/service.py`, `backend/config.py`

이 문서는 "지금 리포트 받기" 버튼을 눌렀을 때 뉴스가 **어떤 API를 거쳐 · 어떤 기준으로 선별되어 · 어떻게 묶여서 · 무엇이 LLM에 전달되는지**를 한 곳에 정리한다.

---

## 0. TL;DR

```
사용자 카테고리 6개(정치/경제/사회/국제/스포츠/IT/과학)
  └─ 각 카테고리마다:
       ① 3개 RSS 소스 병렬 호출 (Google News + 연합뉴스 + 서울신문), 키 불필요
       ② 소스별 최근 24시간 & 최대 20건으로 컷 → MultiSourceCollector에서 URL dedupe
       ③ 제목 TF-IDF → 코사인 유사도 ≥ 0.6 로 그리디 클러스터링 (같은 사건 다른 출처 자동 병합)
       ④ 클러스터 중 "출처가 많은 이슈"를 우선, 각 클러스터의 최신·출처 다양성 대표 기사 선택
       ⑤ 카테고리 전체에서 기사 3건을 뽑아 (pick_top_articles)
       ⑥ 기사 3건 각각 OpenAI gpt-5-nano로 3줄 요약
       ⑦ 요약 3개 + 기사 메타를 한 번 더 gpt-5-nano에 태워 카테고리용 라디오 스크립트 1개 생성
       ⑧ Report 1행 + Article 3행을 DB에 저장, 대시보드 카드로 렌더
```

**조회수 기준 아님.** 조회수는 RSS 피드가 API로 제공하지 않는다. 대신 "**피드 상단에 올라오는 순서(= 편집권 반영된 최신성)**"와 "**같은 이슈를 다룬 언론사 수(= 클러스터 크기, 다수 소스로 교차 검증)**"를 중요도 신호로 사용한다.

---

## 1. 소스: 3개 RSS 병렬 수집 (Day 5 확장)

### 왜 다중 소스?
- 단일 소스(Google News RSS)는 aggregator로서 이미 여러 국내 언론사를 커버하지만, **Google News 자체가 다운/레이트리밋 걸리면 전체 파이프라인이 멈추는 단일 장애점**이었다 (Day 5 실기기 검증 중 1/6 카테고리만 성공한 사례).
- 국내 공영 통신사(연합뉴스)와 과제 주최사(서울신문)의 RSS를 직접 추가해 **소스 다양성 + 가용성**을 동시에 확보. 한 소스가 실패해도 나머지로 진행.
- 과제 주최사인 서울신문 RSS를 1차 수집원에 포함시킨 것 자체가 테마적 의미 포인트.

### 엔드포인트

| 소스 | 클래스 | URL 템플릿 | 키 | 비고 |
|---|---|---|---|---|
| Google News | `GoogleRSSClient` | `https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko` | ❌ | aggregator (한겨레/조선/경향/중앙 등 자동 포함) |
| 연합뉴스 | `YonhapRSSClient` | `https://www.yna.co.kr/rss/{slug}.xml` | ❌ | 공영 통신사 직접 피드. IT/과학은 `industry.xml`로 대체 |
| 서울신문 | `SeoulNewsRSSClient` | `https://www.seoul.co.kr/xml/rss/rss_{slug}.xml` | ❌ | 과제 주최사 직접 피드. IT/과학 전용 피드 없어 skip |

`MultiSourceCollector`가 3개를 순차 호출하고 URL 기반 dedupe 후 TF-IDF 단계로 전달. 공용 `_fetch_rss_url()` 헬퍼가 20초 timeout + 최대 3회 재시도 + 선형 backoff 적용.

### 확장 포인트
`collector.py`에 `NaverNewsClient`, `NewsAPIClient` 등 추가 클래스를 같은 `.fetch(category) -> list[RawArticle]` 인터페이스로 만들고 `MultiSourceCollector.__init__`의 기본 clients 목록에 넣으면 파이프라인 변경 없이 소스만 확장 가능.

### 엔드포인트
```
https://news.google.com/rss/search?q={쿼리}&hl=ko&gl=KR&ceid=KR:ko
```
- `hl=ko` — 본문 언어 한국어
- `gl=KR` — 지역 대한민국
- `ceid=KR:ko` — 사용자 지역(Country Edition ID) 한국 한국어판
- 인증 불필요, rate limit 공식 문서 없음(과도 호출 시 Google이 차단 가능 → 카테고리당 한 번만 호출)

### 카테고리 → 쿼리 매핑 (`CATEGORY_QUERIES`)
카테고리 이름을 그대로 검색어로 넣으면 노이즈가 많아서, **주제 키워드 몇 개를 `OR`로 묶어** Google News 검색의 정확도를 올린다.

| 카테고리 | 쿼리 |
|---|---|
| 정치 | `정치 OR 국회 OR 대통령` |
| 경제 | `한국 경제 OR 금리 OR 환율` |
| 사회 | `사회 OR 사건 OR 사고` |
| 국제 | `국제 OR 외신 OR 해외` |
| 스포츠 | `스포츠 OR 야구 OR 축구 OR 손흥민` |
| IT/과학 | `IT OR 인공지능 OR 반도체 OR 과학` |

> 수정 지점: 쿼리를 바꾸고 싶으면 `backend/pipeline/collector.py:16` 의 `CATEGORY_QUERIES` 딕셔너리 한 곳만 고치면 된다.

---

## 2. 수집: `GoogleRSSClient.fetch()`

### 2-1. 호출 순서
```
httpx.Client(timeout=10s, follow_redirects=True).get(
    url,
    headers={"User-Agent": "Mozilla/5.0 BriefBot/0.1"}
)
  └─ feedparser.parse(resp.content)
       └─ feed.entries  ← 이미 "Google News 피드 순서"대로 정렬된 목록
```
- User-Agent를 명시적으로 넣는 이유: 기본 httpx UA로 가면 Google이 빈 피드를 반환하는 경우가 있음.
- `follow_redirects=True`: Google News가 302 리다이렉트 체인을 태울 때 대응.

### 2-2. "어떤 기준으로 20건인가?" — 핵심 질문에 대한 정확한 답
- **Google News RSS 피드 상단부터 순서대로 최대 20건을 취한다.**
- 이 순서는 **Google의 뉴스 큐레이션 알고리즘이 결정**한다. 공개 API 문서상 공식 정렬 기준이 명시돼 있지 않지만 실무 관찰상 대략 `최신성 × 출처 신뢰도 × 검색어 관련도`의 가중 조합이다.
- **조회수(PV) 기준이 아니다.** Google News는 페이지뷰 수치를 RSS로 내보내지 않는다.
- 코드에서 시간 필터가 추가로 적용된다:
  ```python
  cutoff = now(UTC) - timedelta(hours=24)   # config.ARTICLE_HOURS
  if published < cutoff: skip
  ```
  → 발행일 없는 엔트리는 통과시키고, 24시간을 넘은 건 버린다.
- 우선 `feed.entries[: per_category*2]`(기본 40개)를 순회하며 cutoff 필터를 통과한 것만 쌓다가 **20개(`config.COLLECT_PER_CATEGORY`)가 차면 break** 한다. 즉 "Google이 내려준 순서 중 24시간 안에 발행된 가장 위 20개".

### 2-3. 각 엔트리에서 추출하는 필드 (`RawArticle` dataclass)
| 필드 | 소스 | 용도 |
|---|---|---|
| `title` | `entry.title` (HTML 스트립) | 클러스터링 + LLM 프롬프트 |
| `link` | `entry.link` | 프론트 카드 "원문 보기" 버튼 |
| `published` | `entry.published_parsed` → UTC datetime | 24h 필터 + 클러스터 대표 선정 시 최신 정렬 |
| `source` | `entry.source.title` (언론사명) | 대표 기사 선정 시 **출처 다양성** 판단 |
| `summary` | `entry.summary` (HTML 스트립) | LLM 요약 입력 + summarize 실패 시 fallback 텍스트 |

`_strip_html()`이 `<[^>]+>` 를 날리고 연속 공백을 하나로 합친다.

### 2-4. 실패 시 동작
- 네트워크/파싱 에러는 `logger.warning`으로 기록하고 **빈 리스트 반환**.
- 상위 `service.generate_reports_for_user`는 빈 리스트를 받으면 해당 카테고리를 스킵하고 다음 카테고리로 진행(부분 성공 허용).

---

## 3. 전처리: `preprocessor.cluster_articles()` — TF-IDF + 코사인 유사도

같은 사건을 여러 언론사가 보도한 기사들을 하나로 묶기 위한 단계. LLM 호출이 전혀 없고 순수 NumPy/scikit-learn 연산이라 거의 공짜(밀리초 단위)로 끝난다.

### 3-1. 왜 임베딩이 아니고 TF-IDF?
- OpenAI `text-embedding-3-*` 같은 임베딩 API를 쓰면 토큰 비용이 든다.
- 뉴스는 **제목이 핵심 팩트의 대부분**이고 한국어 토큰 overlap이 크므로, TF-IDF + 코사인 유사도로도 실무적으로 같은 이슈를 잘 묶인다.
- "코드가 할 수 있는 건 코드가 한다"는 프로젝트 설계 철학(하네스 엔지니어링)의 일부.

### 3-2. 단계별 처리
```
입력: 카테고리 1개의 기사 0~20건
  │
  ▼
(1) 노이즈 제거 — `_clean(text)` 에서 정규식으로 제거하는 패턴
    • [○○○ 기자] / (○○○ 기자)
    • 무단전재…금지 / 저작권자…재배포금지
    • 관련기사 / 포토뉴스
    • 연속 공백 → 1칸
  │
  ▼
(2) 토크나이저 — `_tokenize_ko(text)`
    • [\w가-힣]+ 정규식으로 단어 단위 분리
    • 길이 2 이상만 유지(조사 "을/는/이" 등 노이즈 제거)
    • 형태소 분석기(KoNLPy/kiwipiepy) 미사용 — 외부 의존성 최소화
  │
  ▼
(3) TF-IDF 벡터화 — scikit-learn TfidfVectorizer
    • 입력: 제목 배열 (summary 미사용, "사건의 핵심은 제목에 있다" 가정)
    • lowercase=False — 한국어라 대소문자 정규화 불필요
    • tokenizer=_tokenize_ko, token_pattern=None
  │
  ▼
(4) 코사인 유사도 행렬 — sklearn.metrics.pairwise.cosine_similarity
    • N×N 행렬 sim[i][j] = 제목 i와 j의 유사도 (0.0~1.0)
  │
  ▼
(5) 그리디 클러스터링 (Union-Find 대신 단순 이중 루프)
    for i in 0..N:
        if visited[i]: continue
        새 클러스터 시작, i를 멤버로
        for j in i+1..N:
            if sim[i][j] >= 0.6 and not visited[j]:
                j도 같은 클러스터, visited[j]=True
    • threshold = config.CLUSTER_THRESHOLD = 0.6
    • 첫 번째로 발견된 클러스터에 귀속 — transitive 확장은 하지 않음
  │
  ▼
(6) 클러스터 내부 정렬 + 대표 기사 선정 — `_select_representatives(members, max_n=3)`
    • published 내림차순(최신 우선)으로 정렬
    • 출처 중복 제외하며 위에서부터 최대 3개 선택
      (source="연합뉴스" 이미 뽑혔으면 다음 연합뉴스 기사는 skip)
    • 출처 3개 미달 시 그냥 앞 3개
  │
  ▼
(7) 클러스터 컨텍스트 문자열 생성 — `_build_context(reps)`
    "[기사1 | 연합뉴스] {cleaned title}. {cleaned summary}
     [기사2 | 중앙일보] {cleaned title}. {cleaned summary}
     [기사3 | KBS]     {cleaned title}. {cleaned summary}"
    (현 analyzer에서는 이 필드를 직접 사용하지 않지만 디버깅/확장용으로 유지)
  │
  ▼
(8) 클러스터 전체를 size 내림차순 정렬
    → 많은 언론사가 다룬 이슈 = "더 중요한 신호"로 간주
```

### 3-3. 왜 threshold 0.6?
- 0.8로 올리면 같은 사건인데 제목 표현이 다른 기사들(예: "한은 기준금리 인하" vs "한국은행 금리 25bp 내려")을 놓친다.
- 0.4로 내리면 다른 사건이 같은 주제어를 공유한다는 이유로 같이 묶인다(예: "손흥민 골" vs "손흥민 팀 패배").
- 0.6은 본 프로젝트 카테고리 쿼리·한국어 뉴스 제목 길이에서 경험적으로 가장 깔끔하게 갈렸음. 외부 서버에 검증한 값은 아니므로 `.env`의 `CLUSTER_THRESHOLD`로 쉽게 조정 가능.

### 3-4. 엣지 케이스
- 기사 0건 → 빈 리스트 즉시 반환.
- 기사 1건 → 단독 클러스터 1개.
- 전 제목이 공백/노이즈라 TF-IDF vocab이 비면 `ValueError` 발생 → 각 기사를 단독 클러스터로 fallback.

---

## 4. 카테고리 대표 기사 3건 뽑기: `pick_top_articles(clusters, n=3)`

클러스터 여러 개 중에서 "이 카테고리 리포트에 넣을 실제 3개 기사"를 고르는 단계.

### 로직
```
입력: 클러스터 리스트 (size 내림차순 정렬된 상태)
목표: 최종 기사 3건, 가능한 한 서로 다른 언론사

1차 패스 — 각 클러스터에서 1건씩 가져오되 처음 보는 출처 우선
  for cluster in clusters:
      if picked >= 3: break
      for member in cluster.members (최신순):
          if member.source ∈ seen: skip
          picked.append(member); seen.add(source); break

2차 패스 — 1차에서 3건을 못 채웠으면 출처 중복 허용하며 채움
  (이미 뽑힌 link는 제외)

반환: picked[:3]
```

### 결과의 성격
- **클러스터 크기 순 × 출처 다양성** 두 축으로 뽑히기 때문에:
  1. 가장 많은 언론사가 다룬 이슈 1건
  2. 그 다음으로 많이 다뤄진 이슈 1건 (단, 1번과 다른 출처)
  3. 그 다음 이슈 1건 (역시 다른 출처 우선)
- "오늘 이 분야에서 가장 중요한 이슈 3개, 가능하면 서로 다른 신문사 관점"이 의도.
- 여기까지 왔을 때 LLM 호출은 **아직 0회**. 모든 선별이 코드에서 끝났다.

---

## 5. LLM 호출 단계: `analyzer.OpenAIAnalyzer`

카테고리당 기사 3건이 확정되면 이제 **LLM을 딱 4회 호출**한다(카테고리 단위로).

### 5-1. Step 1 — 기사별 3줄 요약 (×3 회)
```python
for article in top_articles:  # 3 iterations
    user_prompt = ARTICLE_SUMMARY_USER_TEMPLATE.format(
        category="경제",
        title=article.title,
        source=article.source or "출처 미상",
        body=(article.summary or article.title),
    )
    resp = openai.chat.completions.create(
        model="gpt-5-nano",
        messages=[
            {"role": "system", "content": ARTICLE_SUMMARY_SYSTEM},
            {"role": "user",   "content": user_prompt},
        ],
        # temperature 미지정 (gpt-5 family는 default 1.0 고정)
    )
```
- 검증: 응답 길이 ≥ 30자 체크 → 짧으면 **최대 2회 재시도**.
- 전부 실패 시 `_fallback_summary()` — RSS summary를 문장 단위로 3줄로 쪼개 반환.
- SSE 이벤트: `summarizing_article` 이벤트로 프론트 Progress Panel에 "2/3 기사 요약 중..." 표시.

### 5-2. Step 2 — 카테고리 라디오 스크립트 (×1 회)
```python
# 3건의 요약을 하나의 블록으로 합침
articles_block = """
[기사1 | 연합뉴스]
제목: …
요약:
(3줄 요약 1)

[기사2 | 중앙일보]
…

[기사3 | KBS]
…
"""

resp = openai.chat.completions.create(
    model="gpt-5-nano",
    messages=[
        {"role": "system", "content": RADIO_SYSTEM},
        {"role": "user",   "content": RADIO_USER_TEMPLATE.format(
            category="경제", n=3, articles_block=articles_block
        )},
    ],
)
```
- 출력은 30초~1분 분량의 구어체 라디오 스크립트 1개(카테고리 오프닝 → 기사 3건 설명 → 마무리 멘트).
- 실패 시 `radio_script=None` 저장(리포트 자체는 유지, 대시보드에서는 요약만 보이고 라디오 버튼은 비활성).

### 5-3. 총 LLM 호출량
| 단위 | 호출 횟수 |
|---|---|
| 카테고리 1개당 | 4회 (summarize ×3 + radio ×1) |
| 6개 카테고리 | 24회 / 사용자 리포트 생성 1회 |
| 재시도 최악의 경우 | summarize는 ×2 재시도 → 카테고리당 최대 7회 |

gpt-5-nano는 입력/출력 단가가 낮아서 6개 카테고리 한 번 생성에 0.0x달러 수준.

---

## 6. DB 영속화: `service.generate_reports_for_user()`

```
for category in [정치, 경제, 사회, 국제, 스포츠, IT/과학]:
    1. collector.fetch(category)        → RawArticle 리스트 (0~20)
    2. cluster_articles(raw, 0.6)       → Cluster 리스트
    3. pick_top_articles(clusters, 3)   → RawArticle 3건
    4. 각 기사에 대해 summarize_article → 3줄 요약 리스트
    5. synthesize_radio(...)            → 라디오 스크립트 or None
    6. INSERT reports (user_id, category, radio_script)
       INSERT articles (report_id, title, summary, link, source, published_at) ×3
db.commit()
```

- 트랜잭션 1회 커밋: 6개 카테고리 전부 처리 후 마지막에 커밋.
- SSE 이벤트 emit 타이밍:
  | 이벤트 | 시점 |
  |---|---|
  | `start` | 함수 진입 직후 |
  | `category_start` | 각 카테고리 시작 |
  | `collected` | RSS 수집 직후 (count 포함) |
  | `clustered` | 클러스터링 직후 (count 포함) |
  | `summarizing_article` | 기사 N/3 요약 시작 |
  | `synthesizing_radio` | 라디오 합성 시작 |
  | `category_done` | 해당 카테고리 DB insert 완료 |
  | `done` | 전체 종료 |
  | `error` | 예외 발생 시 |

프론트 `GenerationProgressPanel`이 이 이벤트를 시간순으로 카드 스트립으로 렌더한다.

---

## 7. 핵심 질문 정리

### Q1. 조회수 기준인가?
**아니다.** Google News RSS는 조회수를 제공하지 않는다. 우리는 "Google News가 피드 상단에 올려 보내주는 순서(최근 24h 내)"를 1차 신호로 삼고, 그 위에 **클러스터 크기(= 같은 이슈를 보도한 언론사 수)**를 2차 신호로 사용해 중요도를 추정한다.

### Q2. 왜 카테고리당 20건인가?
- RSS가 최대 100건 안팎까지 줄 수 있지만, 그중 24시간 내 / 검색어와 강하게 매칭되는 건 보통 20~30건 선이라 경험적으로 충분.
- TF-IDF + 코사인 유사도의 N×N 연산이라 N이 너무 커지면 무거워짐. 20이면 20×20=400 셀로 밀리초 안에 끝남.
- 최종 LLM에는 3건만 가므로 20건 중 17건은 "해당 이슈가 여러 언론사에서 보도됐다는 가중치 신호"로만 기여하고 폐기된다.

### Q3. 왜 본문이 아니라 제목으로 클러스터링?
- Google News RSS `entry.summary`는 원본 언론사 페이지의 리드 일부를 긁어온 것이라 퀄리티가 들쭉날쭉(광고 섞여 있거나 빈 경우).
- 제목은 Google이 canonical하게 가져오므로 일관성 ↑.
- "같은 이슈인지 판단"하는 목적에는 제목 overlap이 충분.
- 본문까지 쓰면 오히려 관련 없는 이슈가 공통 배경 어휘로 묶일 리스크.

### Q4. 언론사(source)는 어떻게 식별하나?
- `entry.source.title` 필드. Google News RSS가 각 엔트리에 `<source>` 요소로 언론사명을 내려준다.
- 이 값이 없거나 비면 "출처 미상"으로 처리되고 출처 다양성 로직에서 중복 판정에 포함되지 않는다.

### Q5. 중복 제거는 어디서 하나?
- **기사 단위 중복(URL/제목 완전 일치)**: Google News RSS가 이미 같은 기사를 하나만 내리므로 기본적으로 발생 빈도 낮음. 전용 dedupe 로직은 넣지 않았다.
- **이슈 단위 중복(같은 사건, 다른 언론사)**: 이건 "제거"가 아니라 **클러스터링으로 묶어** 대표 기사 2~3건만 뽑는 방식으로 처리.
- **출처 중복 방지**: 대표 기사 선정과 `pick_top_articles` 양쪽 모두 출처 `set` 체크를 통해 같은 언론사 기사가 중복으로 뽑히지 않게 한다.

### Q6. 바꾸고 싶으면 어디를 고치나?
| 바꿀 항목 | 파일 / 변수 |
|---|---|
| 카테고리 쿼리 | `backend/pipeline/collector.py:16` `CATEGORY_QUERIES` |
| 카테고리당 수집량 | `.env` `COLLECT_PER_CATEGORY` (기본 20) |
| 시간 필터 | `.env` `ARTICLE_HOURS` (기본 24) |
| 클러스터 임계값 | `.env` `CLUSTER_THRESHOLD` (기본 0.6) |
| 카테고리당 최종 기사 수 | `service.py`의 `pick_top_articles(..., n=3)` 의 `n` |
| LLM 모델 | `.env` `OPENAI_MODEL` (기본 `gpt-5-nano`) |
| 재시도 횟수 | `.env` `LLM_MAX_RETRIES` (기본 2) |
| 노이즈 패턴 | `preprocessor.py:15` `NOISE_PATTERNS` |
| 프롬프트 | `backend/prompts/article_summary.py`, `backend/prompts/radio_script.py` |

---

## 8. 데이터 흐름 다이어그램

```
┌────────────────────────────────────────────────────────────────┐
│ [Frontend]                                                     │
│   "지금 리포트 받기" 버튼 → api.reports.generateStream(userId)  │
└─────────────────────────────┬──────────────────────────────────┘
                              │ GET /api/reports/generate/stream
                              ▼
┌────────────────────────────────────────────────────────────────┐
│ [Backend · SSE endpoint]                                       │
│   routers/reports.py::generate_stream                          │
│     └─ background thread → service.generate_reports_for_user   │
│         on_progress 콜백 → queue → SSE data: events             │
└─────────────────────────────┬──────────────────────────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
  [카테고리 1]           [카테고리 2]            ... (총 6회 반복)
       │
       ▼
  ┌────────────────────────────────────────────────┐
  │ collector.GoogleRSSClient.fetch(category)       │
  │   - httpx GET news.google.com/rss/search        │
  │   - feedparser.parse                            │
  │   - 24h 필터 + 20건 cap                         │
  │   - RawArticle(title, link, source, published) │
  └──────────────┬─────────────────────────────────┘
                 │ list[RawArticle] (0~20)
                 ▼
  ┌────────────────────────────────────────────────┐
  │ preprocessor.cluster_articles                   │
  │   - TfidfVectorizer(제목)                       │
  │   - cosine_similarity ≥ 0.6                     │
  │   - 그리디 클러스터 + 최신순 + 출처 다양성 대표  │
  │   - 클러스터를 size 내림차순 정렬               │
  └──────────────┬─────────────────────────────────┘
                 │ list[Cluster]
                 ▼
  ┌────────────────────────────────────────────────┐
  │ preprocessor.pick_top_articles(n=3)             │
  │   - 클러스터 크기 × 출처 다양성으로 3건 확정     │
  └──────────────┬─────────────────────────────────┘
                 │ list[RawArticle] (3)
                 ▼
  ┌────────────────────────────────────────────────┐
  │ analyzer.OpenAIAnalyzer                         │
  │   ① summarize_article ×3 (gpt-5-nano)           │
  │   ② synthesize_radio ×1 (gpt-5-nano)            │
  └──────────────┬─────────────────────────────────┘
                 │ (summaries[3], radio_script)
                 ▼
  ┌────────────────────────────────────────────────┐
  │ DB · INSERT                                     │
  │   reports  (1 row per category)                 │
  │   articles (3 rows per report)                  │
  └─────────────────────────────────────────────────┘

       (6 카테고리 반복 후)

  commit → SSE done 이벤트 → 프론트 자동 /api/send 체이닝
```

---

## 9. 확장 포인트 (현 구조 그대로 가능)

| 확장 | 추가 위치 | 난이도 |
|---|---|---|
| 네이버 뉴스 API 추가 | `collector.py`에 `NaverNewsClient` 클래스(반환: `list[RawArticle]`) + `service.py`에서 두 Client를 병렬 호출 후 concat | 낮음 |
| NewsAPI.org 추가 | 동일 (위와 같음, 영문 검색 지원) | 낮음 |
| 클러스터링을 임베딩 기반으로 | `cluster_articles`만 교체(OpenAI `text-embedding-3-small`), 외부 인터페이스 동일 | 중간(비용 검토 필요) |
| 실시간 수집 주기화 | `backend/scheduler.py`의 APScheduler를 `main.py` lifespan에서 다시 활성화(현재 데모 비용 통제로 주석 처리) | 낮음 |
| 언론사 가중치 추가 | `_select_representatives`의 출처 비교 시 `SOURCE_WEIGHTS` 딕셔너리 참조 | 낮음 |

---

## 10. 관련 파일 · 라인 인덱스

| 목적 | 파일 | 핵심 라인 |
|---|---|---|
| 카테고리 쿼리 매핑 | [backend/pipeline/collector.py](../../backend/pipeline/collector.py) | 16-23 |
| RSS 호출 + 24h 필터 | [backend/pipeline/collector.py](../../backend/pipeline/collector.py) | 60-96 |
| 노이즈 정규식 | [backend/pipeline/preprocessor.py](../../backend/pipeline/preprocessor.py) | 15-22 |
| TF-IDF + 그리디 클러스터링 | [backend/pipeline/preprocessor.py](../../backend/pipeline/preprocessor.py) | 48-94 |
| 클러스터 대표 3건 선정 | [backend/pipeline/preprocessor.py](../../backend/pipeline/preprocessor.py) | 102-116 |
| 카테고리 최종 3건 | [backend/pipeline/preprocessor.py](../../backend/pipeline/preprocessor.py) | 128-167 |
| 오케스트레이션 + SSE emit | [backend/pipeline/service.py](../../backend/pipeline/service.py) | 30-125 |
| OpenAI 호출 | [backend/pipeline/analyzer.py](../../backend/pipeline/analyzer.py) | 50-103 |
| 설정 값 기본치 | [backend/config.py](../../backend/config.py) | 17-19 |

---

## 11. 요약 한 줄

> "Google News RSS가 주는 **카테고리별 최신 20건** → 제목 TF-IDF 코사인 유사도로 **이슈 단위로 묶고** → 클러스터 크기 + 출처 다양성 기준으로 **대표 기사 3건**을 뽑아 → OpenAI gpt-5-nano에 **기사당 3줄 요약 + 카테고리당 라디오 스크립트 1개** 를 생성하는 2단 LLM 파이프라인."
