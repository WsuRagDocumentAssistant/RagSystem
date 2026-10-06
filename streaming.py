#================================================
# streaming.py
#================================================
"""
실행부(TaskExecutor) → 통신부(Router) 스트리밍 통로.

질의 답변은 LLM 이 다 쓰고 나서야 결과 큐로 나간다(TE → LLM → TE → 결과 큐 → Router).
그 사이 사용자는 수십 초 동안 빈 말풍선을 본다. 그래서 LLM 이 쓰는 조각을 결과를 기다리지
않고 스트리밍 큐로 바로 보낸다.

    TE ── LLM ──▶ 스트리밍 큐 ──▶ Router ──▶ 클라이언트   (조각·진행 단계, 여러 번)
       └────────▶ 결과 큐 ──────▶ Router ──▶ 클라이언트   (완성된 답, 한 번)

짝은 job_id 로 맞춘다. 요청 봉투(req)에 통신부가 붙인 job_id 가 있으므로 work 은
emit(req, ...) 만 부르면 된다. Router 는 그 job_id 를 기다리는 WebSocket 요청으로 넘긴다.

스트리밍 큐는 프로세스 사이를 건너야 해서 Process 를 만들 때 넘겨야 한다(작업처럼 큐에
실어 보낼 수 없다). 그래서 실행부를 한 겹 감싸, 실행부 프로세스가 시작할 때 이 모듈에 큐를
꽂는다(StreamExecutor). 큐가 없는 프로세스(타이머 실행부, 메뉴 실행)에서는 emit 이 아무것도
하지 않는다.

조각은 버려져도 된다. 완성된 답은 결과 큐로 따로 가고 클라이언트는 그것으로 말풍선을 덮어쓴다.
"""

import logging

from taskexecutor import TaskExecutor

logger = logging.getLogger(__name__)

_queue = None


def bind(stream_queue) -> None:
    """이 프로세스의 스트리밍 큐를 정한다. StreamExecutor 가 실행부 프로세스 안에서 부른다."""
    global _queue
    _queue = stream_queue


def emit(req, type_: str, **data) -> None:
    """요청(req)을 기다리는 클라이언트에게 중간 이벤트 {type, ...data} 를 보낸다.

    req 에 job_id 가 없으면(통신부를 거치지 않은 작업) 보내지 않는다. 실패해도 작업은 계속한다 —
    조각 하나 못 보냈다고 답변을 멈출 이유가 없다.
    """
    job_id = req.get("job_id") if isinstance(req, dict) else None
    if _queue is None or not job_id:
        return
    try:
        _queue.put((job_id, {"type": type_, **data}))
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"[stream] 보내기 실패: {type(e).__name__} - {e}")


def stage(req, name: str, message: str) -> None:
    """진행 단계를 알린다. 예: stage(req, "draft", "초안 작성 중")"""
    emit(req, "stage", stage=name, message=message)


class StreamExecutor(TaskExecutor):
    """시작할 때 스트리밍 큐를 꽂는 실행부. 나머지는 TaskExecutor 그대로다."""

    def __init__(self, stream_queue, max_workers: int = 1):
        super().__init__(max_workers=max_workers)
        self.stream_queue = stream_queue

    def run(self) -> None:
        bind(self.stream_queue)
        super().run()
