#================================================
# files.py
#================================================
"""
문서 원본(/api/documents)과 그림(/api/images)을 로그인한 사람에게만 내려준다.

예전에는 StaticFiles 로 폴더를 통째로 공개해서, 주소만 알면 로그인 없이 원본·그림·뷰어 캐시
(documents/.viewer/*.json)를 받을 수 있었다(보안 점검 missing-authorization.document-operations).

<img src> 나 <a href> 는 Authorization 헤더를 못 싣는다. 그래서 클라이언트가 로그인할 때
같은 토큰을 쿠키(rag_file_token, Path=/api, SameSite=Strict)로도 넣어 두고, 여기서 그 쿠키를
auth.verify 로 확인한다. 웹과 API 가 같은 주소(rag.wsu.ac.kr)라 쿠키가 따라온다.

받은 파일이 브라우저에서 실행되지 않게 한다. 문서에서 뽑은 SVG 나 바꿔 올린 그림에 스크립트가
들어 있어도, 이 주소를 직접 열었을 때 우리 사이트 권한으로 돌지 못한다(보안 점검
upload.active-content-image-replacement).
  - Content-Security-Policy: sandbox — 스크립트·폼·같은 출처 권한을 모두 끈다
  - X-Content-Type-Options: nosniff — 확장자와 다른 형식으로 해석하지 않는다
  - 그림이 아닌 파일(원본 문서, html 등)은 내려받기(attachment)로만 준다
"""

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse, PlainTextResponse

import auth

COOKIE = "rag_file_token"

# 화면에 바로 띄우는 그림 형식. 나머지는 내려받기로만 준다.
_INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/svg+xml"}

_HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=3600",
}


def _resolve(root: Path, rel: str) -> Path | None:
    """요청 경로 -> root 안의 실제 파일. root 밖, 숨김 경로(.viewer 등), 없는 파일이면 None."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts or any(p.startswith(".") for p in parts):
        return None
    try:
        path = (root / Path(*parts)).resolve()
        path.relative_to(root)
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def mount(app, prefix: str, directory: str) -> None:
    """app 에 GET {prefix}/{경로} 를 붙인다."""
    root = Path(directory).resolve()

    async def serve(rel: str, request: Request):
        if auth.verify(request.cookies.get(COOKIE)) is None:
            return PlainTextResponse("로그인이 필요합니다.", status_code=401)
        path = _resolve(root, rel)
        if path is None:
            return PlainTextResponse("파일을 찾을 수 없습니다.", status_code=404)
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        disposition = "inline" if media in _INLINE_TYPES else "attachment"
        headers = {**_HEADERS,
                   "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(path.name)}"}
        return FileResponse(path, media_type=media, headers=headers)

    app.add_api_route(f"{prefix}/{{rel:path}}", serve, methods=["GET"], include_in_schema=False)
