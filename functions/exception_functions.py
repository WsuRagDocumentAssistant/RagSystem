
#================================================
# exception_functions.py
#================================================
"""work 안에서 나는 예외를 한 곳에서 처리한다.

work 이 예외를 그대로 올리면 TaskExecutor 가 TaskExecutionError 로 감싸서
트레이스백 수십 줄이 화면을 덮고, 여러 건을 도는 작업은 그 회차 전체가 중단된다.
여기서 잡아 한 줄로 요약하고 None 을 돌려준다.
"""
import logging

from utils import redact_urls

logger = logging.getLogger(__name__)

#────────────────────────────────────────────────

def error_message(e: Exception) -> str:
    """예외를 사람이 읽을 한 줄로 바꾼다.

    메시지 안의 링크는 인증값 파라미터를 뺀다 — httpx 의 HTTPStatusError 는 요청 url 전체
    (serviceKey=... 포함)를 메시지에 넣어서, 외부 API 갱신이 실패할 때마다 키가 로그에 남았다.
    """
    name = type(e).__name__
    text = redact_urls(str(e))
    if name == "UniqueViolationError":
        return "중복된 값 — 이미 등록되어 있음"
    if name == "RaiseError":
        return f"DB 거절 — {text}"
    if name in ("InvalidTextRepresentationError", "DataError", "ValueError"):
        return f"올바르지 않은 값 — {text}"
    if name in ("KeyError", "IndexError"):
        return f"입력값 없음 — {text}"
    if name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "HTTPStatusError"):
        return f"연결 실패 — {text}"
    return f"{name} — {text}"


def safe_call(func, *args, label="", **kwargs):
    """func 을 호출하고 예외가 나면 한 줄 찍고 None 을 돌려준다.

    label 을 안 주면 첫 인자(작업 이름)를 그대로 쓴다.
    """
    if not label:
        label = args[0] if args and isinstance(args[0], str) else func.__name__
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"[실패] {label} : {error_message(e)}")
        return None
