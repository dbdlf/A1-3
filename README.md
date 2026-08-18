# 무드 페어링 (Mood Pairing)

> 제목도 가수도 모르는 곡을, 문장으로 찾습니다.

**배포 URL — https://mood-pairing-gamma.vercel.app**

지금의 기분·상황·취향을 자유롭게 문장으로 적으면, AI가 그 맥락을 해석해
**실존이 검증된 곡 3~5개**와 **그 순간을 위해 새로 쓰인 짧은 글**을 함께 건네는 웹 서비스입니다.

> 서비스 목적·타겟 사용자·화면 설계·AI 기능의 상세 명세는
> **[서비스 기획서](docs/서비스기획서.md)** 에 별도로 정리되어 있습니다.
> 이 문서는 코드를 받아 **실행하고 배포하는 방법**을 다룹니다.

---

## 서비스 소개

모든 음원 앱의 검색창은 곡명·가수명이라는 **고유명사**를 전제합니다.
그런데 우리가 음악을 찾는 동기는 대개 이름이 아니라 상태입니다.

- "가사는 밝은데 멜로디는 쓸쓸한 곡"
- "후렴에서 터뜨리지 않고 끝까지 눌러 담는 곡"
- "연주자의 해석을 빼고 악보 그대로 친 연주"

말로는 분명히 설명되는데 검색어로는 옮길 수 없는 조건들입니다.
그 문장을 그대로 받는 입구를 만드는 것이 이 서비스의 목적입니다.

### 핵심 설계 — 환각 없는 추천

LLM에게 곡을 추천하게 하면 **존재하지 않는 곡을 실존 가수 이름으로 지어내는** 문제가 생깁니다.
이 서비스는 AI에게 "무엇을 찾을지"만 맡기고, **실존 여부는 실제 음원 데이터베이스가 판정**합니다.

```
사용자 자연어 입력
      │
      ▼
[1] Gemini API  →  무드 해석 + 후보곡 N곡 + 검색 키워드 + 창작 문장
      │            (responseSchema로 JSON 출력 형식 강제)
      ▼
[2] iTunes Search API로 후보곡을 하나씩 대조 (병렬 조회)
      │            검증에 실패한 곡은 버림
      ▼
[3] 통과한 곡만 화면에 → 앨범아트 + 30초 미리듣기 + 음원 링크
```

---

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 프론트엔드 | HTML · CSS · Vanilla JavaScript (프레임워크 미사용) |
| 백엔드 | Vercel Serverless Functions (Python) |
| AI | Google Gemini API (`gemini-3.6-flash`) — responseSchema 구조화 출력 |
| 음원 데이터 | iTunes Search API (API 키 불필요) |
| 데이터 저장 | 브라우저 localStorage (검색 기록 전용, 서버 전송 없음) |
| 배포 | GitHub → Vercel 자동 배포 |

---

## 폴더 구조

프론트엔드(`index.html` · `css/` · `js/`)와 백엔드(`api/`)가 분리되어 있습니다.

```
mood-pairing/
├── index.html            # 화면 전환 방식의 단일 문서 (5개 화면)
├── css/
│   └── style.css         # 전체 스타일 · 반응형 (375 / 768 / 1280px)
├── js/
│   └── main.js           # 화면 전환 라우팅, 입력 검증, fetch, 결과 렌더,
│                         #   30초 미리듣기, 검색 기록(localStorage)
├── api/
│   └── pair.py           # 서버리스 함수 — Gemini 호출 + iTunes 실존 검증
├── docs/
│   ├── 서비스기획서.md      # 기획 문서 (목적 · 타겟 · 화면 · AI 명세)
│   └── screenshots/      # 제출용 증빙 스크린샷
├── dev_server.py         # 로컬 개발용 서버 (배포에는 사용되지 않음)
├── requirements.txt      # Python 의존성 (google-genai)
├── pyproject.toml        # Vercel Python 런타임 진입점 설정
├── vercel.json           # 함수 실행 시간 + 프레임워크 자동감지 해제
├── .env.example          # 환경 변수 템플릿
└── .gitignore
```

---

## 환경 변수 설정

### 필요한 키

| 이름 | 설명 | 필수 |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API 키 | ✅ |

[Google AI Studio](https://aistudio.google.com/apikey)에서 무료로 발급받아 **무료 티어**로 사용합니다.
iTunes Search API는 키가 필요 없습니다.

### 로컬 환경

`.env.example`을 복사해 `.env`를 만들고 실제 키를 채워 넣습니다.

```bash
cp .env.example .env
```

`.env`는 `.gitignore`에 등록되어 있어 커밋되지 않습니다.

### Vercel 배포 환경

Vercel 프로젝트 → **Settings → Environment Variables** 에서 추가합니다.

| 항목 | 값 |
|---|---|
| Key | `GEMINI_API_KEY` |
| Value | 발급받은 키 |
| Environments | `Production and Preview` |

환경 변수는 **배포 시점에 주입**되므로, 이미 배포된 상태에서 추가했다면
**Deployments → 최신 배포 → ⋯ → Redeploy** 를 눌러야 반영됩니다.

> ⚠️ **키를 코드·README·스크린샷에 절대 노출하지 마세요.**
> 이 프로젝트는 키를 서버리스 함수(`api/pair.py`)에서만 읽습니다.
> 브라우저로 전달되는 파일에는 키가 포함되지 않으므로, 저장소가 공개여도 노출되지 않습니다.
> 실수로 커밋했다면 즉시 키를 폐기(revoke)하고 재발급한 뒤 커밋 이력도 정리해야 합니다.
> 키를 지우는 커밋을 추가하는 것만으로는 이전 커밋에 남은 키가 사라지지 않습니다.

---

## 실행 방법

### 로컬 실행

의존성을 설치하고,

```bash
pip install -r requirements.txt
```

포함된 개발 서버를 실행합니다.

```bash
python dev_server.py
```

`http://localhost:8123` 에서 프론트엔드와 `/api/pair` 가 함께 동작합니다.
포트를 바꾸려면 `python dev_server.py 3000` 처럼 인자를 넘기면 됩니다.

`dev_server.py`는 `.env`를 읽어 `api/pair.py`의 실제 처리 함수(`dispatch`)를 그대로 호출하므로,
배포 환경과 동일한 로직으로 동작합니다.

> `python -m http.server` 같은 단순 정적 서버로 열면 화면은 뜨지만 `/api/pair` 호출이 404가 납니다.
>
> **`vercel dev`를 쓰지 않는 이유** — Vercel CLI는 로그인 시 컴퓨터 이름을 HTTP 헤더에 담아
> 보내는데, HTTP 헤더는 Latin-1(0~255)만 담을 수 있어 **컴퓨터 이름이 한글이면 로그인이 실패**합니다
> (`Cannot convert argument to a ByteString ...`). `dev_server.py`가 이 문제를 우회합니다.
> 배포는 GitHub↔Vercel 웹 연동으로 하므로 CLI 없이도 문제없습니다.

### 배포 방법

**최초 1회 연결**

1. [vercel.com/new](https://vercel.com/new) 에서 GitHub 계정을 연결하고 이 저장소를 선택
2. **Settings → Environment Variables** 에 `GEMINI_API_KEY` 등록
3. **Deploy** 클릭

**이후 배포**

```bash
git push origin main
```

`main` 브랜치에 push하면 Vercel이 자동으로 빌드·배포합니다 (보통 40초 내외).

> push해도 배포가 트리거되지 않으면 **Settings → Git → Deploy Hooks** 에서
> `main` 브랜치용 훅을 만들어 해당 URL을 호출하면 수동으로 배포할 수 있습니다.

---

## 알려진 제약

- **Gemini 무료 티어에 분당·일일 요청 제한**이 있습니다. 연속으로 빠르게 검색하면 429 오류가
  날 수 있고, 사용자에게는 "1분 뒤에 다시 시도해주세요"로 안내됩니다.
  정확한 한도는 모델·프로젝트마다 다르므로 [AI Studio 콘솔](https://aistudio.google.com/)에서 확인하세요.
- iTunes Search API에도 요청 빈도 제한이 있습니다(대략 분당 20회 수준으로 알려짐).
  후보곡 검증에 곡당 1회씩 요청하므로 연속 검색 시 결과가 일시적으로 줄 수 있습니다.
- `previewUrl`은 선택 필드라 미리듣기가 없는 곡이 있습니다. 이 경우 재생 버튼이 비활성화됩니다.
- 동명이곡이나 리메이크 버전이 매칭될 수 있습니다. 미리듣기로 확인을 권합니다.

---

## 개인정보 처리

- 검색 기록은 **브라우저 localStorage에만** 저장되며 이 서비스의 서버로 전송되지 않습니다.
- 기록은 **열람 전용**입니다. 다음 검색 추천에 반영되지 않습니다.
- 서비스 화면에서 개별 삭제 · 전체 삭제 · 텍스트 내보내기가 가능합니다.

> ⚠️ 곡을 고르기 위해 **입력한 문장은 Google Gemini API로 전송**됩니다.
> 이 프로젝트는 무료 티어를 사용하며, Google은 무료 티어의 데이터를 제품 개선에
> 활용할 수 있다고 안내하고 있습니다. 이 사실은 서비스 내 FAQ에도 명시되어 있습니다.

---

## 출처

음원 메타데이터, 앨범 아트, 30초 미리듣기는 Apple iTunes Search API를 통해 제공됩니다.
