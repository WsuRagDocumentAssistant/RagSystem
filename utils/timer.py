#================================================
# timer.py
#================================================
"""구간 소요 시간을 로그로 남긴다.

    with timer("초안", req):
        draft = get_controller().answer(...)

블록이 끝나면 '[time] <job> 초안 31.20s' 한 줄이 찍힌다.

함수 전체가 아니라 그 안의 무거운 호출만 감싼다. 함수 전체를 재려면 return 이 여러 개인
함수마다 몸통을 통째로 감싸야 하고, 체인 단위로 재려면 work 을 부르는 곳(TaskController
의 Task)을 고쳐야 하는데 그건 이쪽에서 바꿀 수 없다.

req 를 주면 job_id 앞 8자리를 붙인다. 실행부가 스레드 풀이라 질의 여러 개의 로그가
섞이는데, 이게 있으면 grep 으로 한 질의만 뽑힌다.

로거 이름이 "timer" 라 따로 끌 수 있다: logging.getLogger("timer").setLevel(logging.WARNING)
"""

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("timer")

#────────────────────────────────────────────────


@contextmanager
def timer(label: str, req=None):
    """with 블록이 걸린 시간을 찍는다. 블록 안에서 예외가 나도 찍고, 예외는 그대로 올린다."""
    start = time.perf_counter()                 # time.time() 은 시스템 시각이 바뀌면 튄다
    try:
        yield
    finally:
        seconds = time.perf_counter() - start
        job = str(req.get("job_id") or "-")[:8] if isinstance(req, dict) else "-"
        logger.info("[time] %s %s %.2fs", job, label, seconds)
