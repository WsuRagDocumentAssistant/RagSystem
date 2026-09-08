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
