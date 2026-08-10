"""
무드 페어링 — /api/pair  (Vercel Serverless Function, Python)

흐름
  1) 사용자의 자연어 입력을 검증한다.
  2) Gemini에게 무드 해석 + 후보곡 + 검색 키워드 + 창작 문장을 JSON으로 받는다.
  3) 후보곡을 iTunes Search API에 하나씩 대조해 '실제로 있는 곡'만 남긴다.
  4) 검증 통과가 적으면 키워드 검색으로 보충한 뒤 프런트에 돌려준다.

AI는 "무엇을 찾을지"만 정하고, 실존 여부는 실제 음원 데이터가 판정한다.
그래서 없는 곡이 추천되는 일(환각)이 구조적으로 걸러진다.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

MODEL = "gemini-3.6-flash"
MIN_LEN = 10
MAX_LEN = 500
ITUNES = "https://itunes.apple.com/search"
ITUNES_TIMEOUT = 4  # 초

# 위기 표현 감지 — 감정을 자유롭게 적는 서비스라 최소한의 안전 장치를 둔다.
CRISIS_PATTERNS = [
    "자살", "죽고 싶", "죽고싶", "자해", "목숨을 끊", "살기 싫", "살기싫",
    "사라지고 싶", "사라지고싶", "죽어버리", "끝내고 싶", "끝내고싶",
]
CRISIS_MESSAGE = (
    "지금 많이 힘드신 것 같아요. 음악을 골라드리는 것보다, "
    "먼저 이야기를 들어줄 사람과 연결되는 게 나을 것 같습니다."
)

SYSTEM_PROMPT = """당신은 '무드 페어링'의 음악 큐레이터입니다.

사용자는 곡명이나 가수명이 아니라, 지금의 상황·기분·취향을 문장으로 적습니다.
그 문장을 해석해 아래 네 가지를 만듭니다.

1. mood_summary — 사용자의 입력을 한 문장으로 되짚어줍니다. 요약이 아니라 "이렇게 읽었어요"에
   가깝게, 사용자가 명시하지 않은 결까지 짚어주면 좋습니다.

2. candidates — 실제로 존재하는 곡만 후보로 올립니다. artist는 음원 서비스에 등록된 표기를
   그대로 쓰고, title도 원제 그대로 씁니다. 한국 곡이면 한글 표기, 해외 곡이면 원어 표기를 씁니다.
   note에는 "왜 이 곡인가"를 사용자의 조건과 연결해 한 문장으로 씁니다.
   확신이 없는 곡은 올리지 마세요. 지어낸 곡은 검증 단계에서 걸러지고 결과만 빈약해집니다.

3. search_keywords — 사용자가 음원 앱이나 유튜브에 그대로 넣어볼 수 있는 검색어 3개.
   장르·편성·분위기를 조합한, 실제로 검색 결과가 나올 법한 표현으로 씁니다.

4. original_text — 이 순간을 위한 짧은 글 2~3문장. 기존 문학 작품을 인용하지 마세요.
   지금 이 입력을 위해 새로 씁니다. 위로하려 애쓰거나 교훈을 주려 하지 말고,
   사용자가 적은 장면 안에 머무는 글을 쓰세요.

규칙
- 사용자가 장르를 지정하지 않았다면 특정 장르에 몰지 말고 폭넓게 고릅니다.
- 사용자가 명시한 조건(가사 유무, 온도, 편성 등)은 반드시 지킵니다.
- 제외 목록에 있는 곡은 절대 다시 올리지 않습니다.
- 모든 텍스트는 한국어로 씁니다."""

# Gemini의 responseSchema는 OpenAPI 3.0 스키마의 부분집합을 쓴다.
# additionalProperties 는 지원 대상이 아니므로 넣지 않는다.
SCHEMA = {
    "type": "object",
    "properties": {
        "mood_summary": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "title": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["artist", "title", "note"],
                "propertyOrdering": ["artist", "title", "note"],
            },
        },
        "search_keywords": {"type": "array", "items": {"type": "string"}},
        "original_text": {"type": "string"},
    },
    "required": ["mood_summary", "candidates", "search_keywords", "original_text"],
    "propertyOrdering": ["mood_summary", "candidates", "search_keywords", "original_text"],
}


# ------------------------------------------------------------------
# iTunes 대조
# ------------------------------------------------------------------

def _norm(s):
    """비교용 정규화 — 괄호/구두점/공백을 지우고 소문자로."""
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s or "")
    s = re.sub(r"[^0-9a-z가-힣]", "", s.lower())
    return s


def _itunes(params):
    url = ITUNES + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "mood-pairing/1.0"})
    with urllib.request.urlopen(req, timeout=ITUNES_TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8")).get("results", [])


def _to_track(item, note=""):
    return {
        "artist": item.get("artistName", ""),
        "title": item.get("trackName", ""),
        "artwork": (item.get("artworkUrl100") or "").replace("100x100", "300x300"),
        "preview_url": item.get("previewUrl") or "",
        "track_url": item.get("trackViewUrl") or "",
        "note": note,
    }


def verify(candidate):
    """후보곡 1개가 실존하는지 iTunes에서 확인한다. 없으면 None."""
    term = "%s %s" % (candidate.get("artist", ""), candidate.get("title", ""))
    try:
        results = _itunes({"term": term, "entity": "song", "limit": 5, "country": "KR"})
    except Exception:
        return None

    want_t, want_a = _norm(candidate.get("title")), _norm(candidate.get("artist"))
    if not want_t:
        return None

    for item in results:
        got_t, got_a = _norm(item.get("trackName")), _norm(item.get("artistName"))
        title_ok = want_t and (want_t in got_t or got_t in want_t)
        artist_ok = want_a and (want_a in got_a or got_a in want_a)
        if title_ok and artist_ok:
            return _to_track(item, candidate.get("note", ""))
    return None


def keyword_fill(keywords, need, seen):
    """검증 통과가 부족할 때 키워드 검색으로 채운다."""
    picked = []
    for kw in keywords[:3]:
        if len(picked) >= need:
            break
        try:
            results = _itunes({"term": kw, "entity": "song", "limit": 6, "country": "KR"})
        except Exception:
            continue
        for item in results:
            key = _norm(item.get("artistName")) + "|" + _norm(item.get("trackName"))
            if key in seen:
                continue
            seen.add(key)
            picked.append(_to_track(item, "‘%s’ 키워드로 찾은 곡이에요." % kw))
            if len(picked) >= need:
                break
    return picked


# ------------------------------------------------------------------
# Gemini 호출
# ------------------------------------------------------------------

def ask_gemini(query, lyrics, count, adjust, exclude):
    lines = ["[사용자 입력]", query, ""]

    if lyrics == "with":
        lines.append("[조건] 가사가 있는 곡만 골라주세요.")
    elif lyrics == "without":
        lines.append("[조건] 가사가 없는 곡(연주곡)만 골라주세요.")

    if adjust:
        lines.append("[조정 요청] 위 입력은 그대로 두고, 이 방향으로 틀어주세요: %s" % adjust)

    if exclude:
        lines.append("[제외] 아래 곡은 이미 보여드렸으니 다시 올리지 마세요.")
        lines.extend("- " + x for x in exclude[:40])

    lines.append("")
    # 검증에서 일부가 걸러지므로 필요한 수의 두 배를 받아둔다.
    lines.append("후보곡은 %d곡 정도 올려주세요." % (count * 2))

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=MODEL,
        contents="\n".join(lines),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=1.0,
            max_output_tokens=3000,
            # 지연에 민감한 화면이라 추론 깊이를 낮춰 응답 속도를 우선한다.
            # (Gemini 3.x 계열은 thinking_budget 대신 thinking_level 을 받는다)
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )

    text = (response.text or "").strip()
    if not text:
        raise ValueError("추천을 만들지 못했어요. 문장을 조금 바꿔서 다시 시도해주세요.")
    return json.loads(text)


# ------------------------------------------------------------------
# 요청 처리
# ------------------------------------------------------------------

def build_response(body):
    query = (body.get("query") or "").strip()
    if len(query) < MIN_LEN:
        return 400, {"message": "조금만 더 자세히 적어주세요. (최소 %d자)" % MIN_LEN}
    if len(query) > MAX_LEN:
        return 400, {"message": "입력이 너무 깁니다. %d자 이내로 줄여주세요." % MAX_LEN}

    if any(p in query for p in CRISIS_PATTERNS):
        return 200, {"safety": CRISIS_MESSAGE}

    if not os.environ.get("GEMINI_API_KEY"):
        return 500, {"message": "서버 설정이 아직 끝나지 않았어요. 잠시 후 다시 시도해주세요."}

    count = body.get("count")
    count = count if count in (3, 5) else 5
    lyrics = body.get("lyrics") if body.get("lyrics") in ("any", "with", "without") else "any"
    adjust = (body.get("adjust") or "").strip()[:120]
    exclude = [str(x)[:120] for x in (body.get("exclude") or [])][:40]

    data = ask_gemini(query, lyrics, count, adjust, exclude)
    candidates = data.get("candidates", [])[:12]
    keywords = [k for k in data.get("search_keywords", []) if isinstance(k, str)][:3]

    # 후보곡 실존 검증 — 여러 개를 병렬로 조회한다.
    with ThreadPoolExecutor(max_workers=6) as pool:
        verified = list(pool.map(verify, candidates))

    tracks, seen = [], set()
    for track in verified:
        if not track:
            continue
        key = _norm(track["artist"]) + "|" + _norm(track["title"])
        if key in seen:
            continue
        seen.add(key)
        tracks.append(track)
        if len(tracks) >= count:
            break

    fallback_used = False
    if len(tracks) < 2 and keywords:
        extra = keyword_fill(keywords, count - len(tracks), seen)
        if extra:
            fallback_used = True
            tracks.extend(extra)

    return 200, {
        "mood_summary": data.get("mood_summary", ""),
        "original_text": data.get("original_text", ""),
        "keywords": keywords,
        "tracks": tracks,
        "fallback_used": fallback_used,
    }


def dispatch(body):
    """요청 본문 → (HTTP 상태, 응답 payload). 배포용 handler와 로컬 dev_server가 공유한다."""
    try:
        return build_response(body)
    except ValueError as e:
        return 400, {"message": str(e)}
    except genai_errors.ClientError as e:
        # 무료 티어는 분당 요청 수 제한이 있어 429가 가장 흔하다.
        if getattr(e, "code", None) == 429:
            return 429, {"message": "잠깐 쉬었다 가야 해요. 1분 뒤에 다시 시도해주세요."}
        return 400, {"message": "요청을 처리하지 못했어요. 문장을 바꿔서 다시 시도해주세요."}
    except genai_errors.ServerError:
        return 502, {"message": "추천 서버와 연결하지 못했어요. 잠시 후 다시 시도해주세요."}
    except Exception:
        return 500, {"message": "지금은 곡을 찾지 못했어요. 잠시 후 다시 시도해주세요."}


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"message": "요청을 읽지 못했어요."})
            return

        status, payload = dispatch(body)
        self._send(status, payload)

    def do_GET(self):
        self._send(405, {"message": "POST로 요청해주세요."})
