#================================================
# convert.py
#================================================
"""값 모양을 바꾸는 함수들.

work 이 아니고, DB·모델·통신부에 의존하지 않는다. 다른 모듈을 import 하지 않으므로
functions 안의 어느 파일에서 가져다 써도 순환이 생기지 않는다.
"""

import json


def from_jsonb(value, default):
    """jsonb 컬럼값 -> 파이썬 객체. asyncpg 가 문자열로 줄 때가 있어 흡수한다.

    VocabRepository 는 dict 를 돌려준다고 적혀 있는데 실제로는 str 이 온다(실측).
    그쪽이 고쳐서 객체로 오게 되어도 이 함수는 그대로 통과한다.

    default 는 값이 없을 때 돌려줄 것이다 — 목록 자리에는 [], 사전 자리에는 {} 를
    준다. 빈 문자열도 없는 것으로 본다("" -> json 'null' -> default).
    """
    if isinstance(value, str):
        value = json.loads(value or "null")
    return default if value is None else value


def static_url(path: str, root: str, prefix: str) -> str | None:
    """서버 로컬 경로 -> 브라우저가 열 수 있는 URL. root 밖이면 None.

    main.py 가 /api/documents 와 /api/images 를 정적 경로로 내보낸다. 그 아래 있는
    파일만 URL 로 바꾼다 — 밖의 경로를 그대로 노출하면 서버 파일이 새어 나간다.

    문서 쪽과 질의 쪽이 같은 규칙으로 URL 을 만들어야 해서 여기로 올렸다.
    """
    from pathlib import Path
    from urllib.parse import quote

    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    return f"{prefix}/" + quote(rel.as_posix())


def local_path(url: str, root: str, prefix: str):
    """브라우저가 받은 URL -> 서버 로컬 경로. static_url 의 반대다. 없으면 None.

    클라이언트가 목록에서 받은 주소를 그대로 돌려보낼 때 쓴다(IMAGE_VECTORIZE 의
    imageUrl 등).

    root 밖을 가리키면 None 이다. 이 값은 클라이언트가 보내는 것이라, 검사 없이
    열면 "/api/images/../../etc/passwd" 같은 것으로 서버 파일을 읽을 수 있다.
    static_url 이 "root 밖이면 URL 을 만들지 않는" 것과 같은 규칙을 반대로 건다.

    urlparse 로 경로만 본다. 클라이언트가 SERVER_URL 을 붙여 절대 주소로 보내도
    같은 결과가 나오게 하려는 것이다.
    """
    from pathlib import Path
    from urllib.parse import unquote, urlparse

    if not url:
        return None

    path = urlparse(url).path
    if not path.startswith(prefix.rstrip("/") + "/"):
        return None

    relative = unquote(path[len(prefix.rstrip("/")) + 1:])
    if not relative:
        return None

    try:
        target = (Path(root) / relative).resolve()
        base = Path(root).resolve()
    except OSError:
        return None

    if base not in target.parents:
        return None
    return target if target.is_file() else None


def resolve_image_path(image_path: str, root: str):
    """DB 의 image_path -> 실제 파일 경로(Path). 없으면 None.

    저장할 때 "images/<문서명>/image7.png" 처럼 넣었으므로 대개 그대로 열린다.
    root(IMAGE_DIR) 가 환경변수로 바뀌었을 때를 대비해 첫 세그먼트를 root 로 바꿔
    한 번 더 찾는다. 세그먼트가 하나뿐인 맨 파일명이면 root/파일명 으로 본다 —
    replace_image_file 이 "/" 없는 옛 경로에는 파일명만 저장한다.

    document_functions 와 rag_functions 가 각자 갖고 있던 것을 여기로 합쳤다.
    한쪽은 못 찾아도 경로를 돌려주고 다른 쪽은 None 을 돌려줘서 의미가 달랐다 —
    없는 경로를 그럴듯하게 돌려주는 쪽이 더 위험해서 None 으로 통일한다.
    """
    from pathlib import Path

    if not image_path:
        return None

    path = Path(image_path)
    if path.is_file():
        return path

    parts = path.parts
    if parts and parts[0] != root:
        candidate = (Path(root).joinpath(*parts[1:]) if len(parts) > 1
                     else Path(root) / path.name)
        if candidate.is_file():
            return candidate
    return None
