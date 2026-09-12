
#================================================
# main.py
#================================================

from multiprocessing import Queue
import multiprocessing
import logging
import os
import queue
import threading

from taskcontroller import work_lst, TaskController,tasks, Task
from taskexecutor import TaskExecutor
#import functions
import functions.data_functions
import functions.user_functions as user_functions
import functions.document_functions as document_functions
import functions.rag_functions
from taskexecutor import TaskExecutionError

#────────────────────────────────────────────────


tasks.update({
    "test_task1": ["test1", "test2"],
    "rag_test" : ["parse_function", "chunk_function"]
})

TIMER_INTERVAL = 60   # 초. api_all_update 를 이 주기로 반복한다

def timer_loop(executor, stop_event):
    """전용 워커에 api_all_update 를 넣고 결과를 받아 찍는다.

    수동 실행과 큐를 나눠 쓴다. 같은 큐를 쓰면 [w] 로 실행한 결과를 기다리는
    동안 타이머 결과가 먼저 도착해 엉뚱한 값이 출력된다.
    결과를 받은 뒤에 다음 주기를 세므로 실행이 주기보다 길어도 겹치지 않는다.
    """
    while not stop_event.is_set():
        executor.task_queue.put(Task(tasks["api_all_update"], None))
        # 실행부가 (task, result) 로 돌려준다
        logger.info("타이머 api_all_update 결과: %s", _unwrap(executor.get_task_result()))
        stop_event.wait(TIMER_INTERVAL)

GATEWAY_TIMEOUT = 600   # 초. 라우터 기본값 60 은 색인에 턱없이 모자란다

# 통신부 워커 수. 기본 1 이다.
#
# 늘리면 요청을 동시에 처리하지만, TaskExecutor 는 스레드가 아니라 프로세스라
# 메모리가 따로다. rag_functions 의 모델 싱글턴(_controller)도 프로세스마다 하나씩
# 생기므로, 워커 둘이 각각 RAG 작업을 잡으면 임베딩·리랭커가 두 벌 올라간다.
# GPU 가 한 장이면 두 벌을 올려도 서로 기다릴 뿐이라 이득도 없다.
#
# 동시 처리가 필요하면 워커를 늘리는 대신 레인을 나누는 게 맞다 — 모델을 쓰지 않는
# 작업(로그인·목록 조회 등)은 get_controller() 를 아예 부르지 않으므로, 그쪽 전용
# 워커를 따로 두면 모델은 한 벌만 유지하면서 무거운 작업에 막히지 않는다.
GATEWAY_WORKERS = int(os.environ.get("RAG_GATEWAY_WORKERS", "1"))

# 정적으로 내보낼 폴더. rag_functions / document_functions 가 파일을 떨구는 곳과 같다.
from utils import IMAGE_DIR, DOCUMENT_DIR

logger = logging.getLogger("bridge")


def _unwrap(outcome):
    """실행부가 돌려주는 (task, result) 에서 결과만 꺼낸다."""
    _task, result = outcome
    return result

# 실행부에 넘긴 요청들. job_id -> 라우터 Task.
_pending: dict = {}
_pending_lock = threading.Lock()


def bridge_submit_loop(controller, stop_event):
    """라우터 큐에서 꺼내 컨트롤러로 넘긴다. 결과를 기다리지 않는다.

    기다리지 않으므로 요청이 실행부에 여러 개 쌓일 수 있다. 짝은 collect 쪽이
    job_id 로 맞춘다.
    """
    from rag_router.shared_queues import SharedQueues
    from rag_router.task.task_result import TaskResult

    task_queue, result_queue = SharedQueues.get_queues()
    logger.info("브릿지 submit 시작")

    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        # 없는 이름은 여기서 막는다. 컨트롤러는 예외를 잡아 print 만 하므로 그대로
        # 넘기면 결과가 영영 안 오고 요청이 타임아웃까지 매달린다.
        if task.task_type not in tasks:
            logger.warning("등록되지 않은 task_type: %s", task.task_type)
            result_queue.put(TaskResult(
                task.job_id, False,
                error=f"아직 지원하지 않는 task_type 입니다: {task.task_type}"))
            continue

        logger.info("수신 job_id=%s task_type=%s", task.job_id, task.task_type)
        with _pending_lock:
            _pending[task.job_id] = task

        # payload 만 보내면 session_id 와 token 을 되찾을 방법이 없다. 요청을 통째로
        # 넘기고, 체인이 그걸 흘려보내며 필요한 단계에서 꺼내 쓴다.
        # job_id 는 결과가 돌아올 때 짝을 맞추는 열쇠다.
        controller.task_queue.put((task.task_type, {
            "job_id": task.job_id,
            "payload": task.payload or {},
            "session_id": task.session_id,
            "token": task.token,
        }))


def bridge_collect_loop(executor, stop_event):
    """실행부 결과를 job_id 로 짝지어 라우터 큐에 돌려준다."""
    from rag_router.shared_queues import SharedQueues
    from rag_router.task.task_result import TaskResult

    _, result_queue = SharedQueues.get_queues()
    logger.info("브릿지 collect 시작")

    while not stop_event.is_set():
        try:
            outcome = executor.get_task_result(timeout=1.0)
        except queue.Empty:
            continue

        # 실행부가 성공이든 실패든 (task, result) 로 보낸다. job_id 는 그 task 에
        # 실려 있으므로 결과가 어느 순서로 오든 짝이 맞는다.
        done_task, result = outcome
        job_id = (getattr(done_task, "params", None) or {}).get("job_id")

        # job_id 가 없으면 우리가 직접 넣은 작업이다(기동 시 warmup). 돌려보낼 곳이
        # 없으니 결과만 확인하고 버린다. 실패를 조용히 넘기지는 않는다 — 모델 로딩이
        # 실패하면 첫 질의가 올 때까지 모른 채로 있게 된다.
        if job_id is None:
            if isinstance(result, TaskExecutionError):
                logger.error("내부 작업 실패: %s", result.tb)
            else:
                logger.info("워커 준비 완료: %r", result)
            continue

        with _pending_lock:
            task = _pending.pop(job_id, None)

        if task is None:
            logger.error("짝을 못 찾은 결과 (job_id=%s). 버린다: %r", job_id, result)
            continue

        result_queue.put(_to_task_result(task, result, TaskResult))


def _to_task_result(task, result, TaskResult):
    if isinstance(result, TaskExecutionError):
        # traceback 은 로그로만. HTTP 응답에 실으면 내부 구조가 샌다.
        logger.error("job_id=%s 작업 실패: %s", task.job_id, result.tb)
        return TaskResult(task.job_id, False, error=_error_message(result, task))

    # 응답 모양은 각 task 의 마지막 work 이 맞춘다(user_query_output 등). 여기서는
    # 손대지 않는다. dict/list 가 아닌 값을 돌려주면 TaskResponse 가 거부하므로, 그건
    # 그 task 에 출력 work 이 빠졌다는 뜻이다.
    logger.info("완료 job_id=%s", task.job_id)
    return TaskResult(task.job_id, True, data=result)


def _error_message(failure, task) -> str:
    """실패를 클라이언트에게 알릴 문장으로 바꾼다.

    work 이 던진 ValueError 는 "payload 에 query 가 없습니다" 처럼 사용자에게
    보여줄 목적으로 쓴 메시지다. 그것까지 뭉뚱그리면 무엇이 잘못됐는지 알 수 없다.
    그 밖의 예외는 내부 사정이라 한 문장으로 덮는다.
    """
    last = (failure.tb or "").strip().splitlines()[-1:] or [""]
    head, _, detail = last[0].partition(": ")
    if head.strip() == "ValueError" and detail:
        return detail.strip()
    return f"작업 실행에 실패했습니다: {task.task_type}"


if __name__ == "__main__":

    # CUDA 는 fork 된 프로세스에서 다시 초기화될 수 없다. 리눅스의 기본 시작 방식이
    # fork 라, 부모가 CUDA 를 건드린 뒤 워커를 띄우면 리랭커 로딩에서 이렇게 죽는다:
    #   RuntimeError: Cannot re-initialize CUDA in forked subprocess
    # Windows 는 원래 spawn 이라 개발 중에는 드러나지 않고 배포에서만 터진다.
    #
    # 프로세스를 하나라도 만들기 전에 불러야 한다. TaskExecutor / TaskController 는
    # 기본 컨텍스트를 쓰므로 여기서 바꾸면 그대로 따라온다 — 라이브러리는 손댈 필요 없다.
    multiprocessing.set_start_method("spawn", force=True)

    logging.basicConfig(level=logging.INFO,
                        format="[%(name)s] %(levelname)s %(message)s")

    # ── 통신부(HTTP) 전용 ─────────────────────────────
    # 배포는 이 파일이 진입점이다(Dockerfile CMD, containerPort 8000).
    # 워커 여러 개가 같은 큐를 본다. TaskExecutor 는 생성자에서 자기 큐를 만들지만,
    # start() 전에 바꿔 끼우면 그 큐가 자식 프로세스로 함께 넘어간다.
    gwexecutors = [TaskExecutor() for _ in range(GATEWAY_WORKERS)]
    shared_task_queue = gwexecutors[0].get_task_queue()
    shared_result_queue = gwexecutors[0].get_result_queue()
    for ex in gwexecutors[1:]:
        ex.task_queue = shared_task_queue
        ex.result_queue = shared_result_queue
    for ex in gwexecutors:
        ex.start()

    # 워커마다 모델을 미리 올린다. get_controller() 는 실행부 프로세스 안에서만
    # 불려야 해서(모델이 거기 올라간다) 작업으로 넣는 수밖에 없다 — 부모에서 부르면
    # 부모에 올라가고 워커는 자기 것을 또 올린다. 그냥 두면 첫 요청이 모델 로딩
    # 몇십 초를 기다리는데, 그게 모델을 쓰지도 않는 작업일 수 있다.
    #
    # 워커 수만큼 넣지만 어느 워커가 무엇을 집을지는 정해져 있지 않다. 하나가 둘을
    # 집으면 다른 하나는 첫 요청 때 올린다 — 워커가 하나면 정확히 맞는다.
    #
    # 결과는 브릿지가 job_id 없는 것으로 알아보고 흘려보낸다.
    for _ in gwexecutors:
        shared_task_queue.put(Task(["warmup_function"], None))

    gwcontroller = TaskController(shared_task_queue)
    gwcontroller.start()

    stop_bridge = threading.Event()
    threading.Thread(target=bridge_submit_loop,
                     args=(gwcontroller, stop_bridge), daemon=True).start()
    threading.Thread(target=bridge_collect_loop,
                     args=(gwexecutors[0], stop_bridge), daemon=True).start()

    # ── 타이머 전용 ───────────────────────────────────
    timerexecutor = TaskExecutor()
    timerexecutor.start()
    stop_timer = threading.Event()
    threading.Thread(target=timer_loop, args=(timerexecutor, stop_timer), daemon=True).start()

    try:
        from rag_router.gateway import gateway

        # 라우터 기본값이 60초인데 FILE_UPLOAD 는 색인(파싱+임베딩)까지 하느라 몇 분
        # 걸린다. 그대로 두면 작업은 계속 도는데 응답만 timeout 으로 나간다.
        gateway.TIMEOUT_SEC = GATEWAY_TIMEOUT

        # 이미지와 원본 문서를 브라우저가 열 수 있게 내보낸다. 라우터는 /api/task 하나만
        # 갖고 있어서 파일을 줄 통로가 없다 — 라우터 패키지를 고치는 대신 여기서
        # 그쪽 FastAPI 앱에 정적 경로만 얹는다.
        #
        # /api 아래에 둔다. 게이트웨이가 /api 프리픽스만 이 서버로 보내기 때문에,
        # 그 밖의 경로로 두면 요청이 프론트엔드로 흘러가 index.html 이 내려온다
        # (다운로드가 .html 로 받아진다).
        from fastapi.staticfiles import StaticFiles

        os.makedirs(IMAGE_DIR, exist_ok=True)
        os.makedirs(DOCUMENT_DIR, exist_ok=True)
        gateway.app.mount("/api/images", StaticFiles(directory=IMAGE_DIR), name="api/images")
        gateway.app.mount("/api/documents", StaticFiles(directory=DOCUMENT_DIR), name="api/documents")
        logger.info("정적 경로 연결: /api/images -> %s, /api/documents -> %s",
                    IMAGE_DIR, DOCUMENT_DIR)

        gateway.run()          # uvicorn. 블로킹이다
    finally:
        stop_bridge.set()
        stop_timer.set()

        timerexecutor.stop()
        timerexecutor.collect()   # 결과 큐를 비워야 자식이 join 에서 멈추지 않는다
        timerexecutor.join()

        for ex in gwexecutors:
            ex.stop()             # 워커 하나당 종료 신호 하나가 필요하다
        # collect 스레드가 멈춘 뒤라 남은 결과를 아무도 안 꺼낸다. 비우지 않으면
        # 자식이 큐 버퍼를 flush 하지 못해 join 에서 멈춘다.
        while any(ex.is_alive() for ex in gwexecutors):
            try:
                gwexecutors[0].get_task_result(timeout=0.1)
            except queue.Empty:
                pass
        for ex in gwexecutors:
            ex.join()
        gwcontroller.terminate()  # TaskController 에는 정상 종료 신호가 없다
        gwcontroller.join()
