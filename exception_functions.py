
#================================================
# exception_functions.py
#================================================
"""work 안에서 나는 예외를 한 곳에서 처리한다.

work 이 예외를 그대로 올리면 TaskExecutor 가 TaskExecutionError 로 감싸서
트레이스백 수십 줄이 화면을 덮고, 여러 건을 도는 작업은 그 회차 전체가 중단된다.
여기서 잡아 한 줄로 요약하고 None 을 돌려준다.
"""

#────────────────────────────────────────────────

def error_message(e: Exception) -> str:
    """예외를 사람이 읽을 한 줄로 바꾼다."""
    name = type(e).__name__
    if name == "UniqueViolationError":
        return "중복된 값 — 이미 등록되어 있음"
    if name == "RaiseError":
        return f"DB 거절 — {e}"
    if name in ("InvalidTextRepresentationError", "DataError", "ValueError"):
        return f"올바르지 않은 값 — {e}"
    if name in ("KeyError", "IndexError"):
        return f"입력값 없음 — {e}"
    if name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "HTTPStatusError"):
        return f"연결 실패 — {e}"
    return f"{name} — {e}"


def safe_call(func, *args, label="", **kwargs):
    """func 을 호출하고 예외가 나면 한 줄 찍고 None 을 돌려준다.

    label 을 안 주면 첫 인자(작업 이름)를 그대로 쓴다.
    """
    if not label:
        label = args[0] if args and isinstance(args[0], str) else func.__name__
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"[실패] {label} : {error_message(e)}")
        return None
