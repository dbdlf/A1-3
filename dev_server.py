"""
로컬 개발용 서버 (배포에는 쓰이지 않습니다).

Vercel CLI(`vercel dev`) 없이 프론트엔드와 /api/pair 를 함께 띄웁니다.
api/pair.py 의 실제 로직(dispatch)을 그대로 호출하므로, 배포 환경과 동일하게 동작합니다.

    python dev_server.py          # http://localhost:8123
    python dev_server.py 3000     # 포트 지정

.env 파일에서 GEMINI_API_KEY 를 읽어 환경 변수로 넣어줍니다.
"""

import json
import os
import pathlib
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent


def load_env():
    """.env 를 읽어 환경 변수에 채운다 (이미 설정된 값은 덮어쓰지 않음)."""
    path = ROOT / ".env"
    if not path.exists():
        print("[dev] .env 가 없습니다. .env.example 을 복사해 키를 채워주세요.")
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

# api/pair.py 를 모듈로 불러온다.
sys.path.insert(0, str(ROOT / "api"))
import pair  # noqa: E402


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/api/pair":
            self.send_error(404, "Not Found")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"message": "요청을 읽지 못했어요."})
            return

        try:
            status, payload = pair.dispatch(body)
        except Exception:
            # dispatch 가 잡지 못한 예외는 개발 중 원인을 봐야 하므로 콘솔에 남긴다.
            traceback.print_exc()
            status, payload = 500, {"message": "지금은 곡을 찾지 못했어요. 잠시 후 다시 시도해주세요."}

        self._json(status, payload)

    def _json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def end_headers(self):
        # 개발 중에는 정적 파일 캐시를 끈다 (수정이 바로 반영되도록).
        if self.command == "GET":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    if not os.environ.get("GEMINI_API_KEY"):
        print("[dev] 경고: GEMINI_API_KEY 가 없습니다. AI 기능이 500으로 실패합니다.")
    print("[dev] http://localhost:%d  (Ctrl+C 로 종료)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), DevHandler).serve_forever()


if __name__ == "__main__":
    main()
