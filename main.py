
#================================================
# main.py
#================================================

from multiprocessing import Queue
import logging
import queue
import sys
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
        print()
        print("[타이머] api_all_update 결과 :", executor.get_task_result())
        stop_event.wait(TIMER_INTERVAL)

GATEWAY_TIMEOUT = 600   # 초. 라우터 기본값 60 은 색인에 턱없이 모자란다
BRIDGE_TIMEOUT = 1800   # 초. GATEWAY_TIMEOUT 보다 길게 잡는다

logger = logging.getLogger("bridge")


def bridge_loop(controller, executor, stop_event):
    """라우터 큐와 작업 큐를 잇는다. Gateway 와 같은 프로세스의 스레드로 돈다.

    라우터의 큐는 queue.Queue 라 프로세스 경계를 못 넘는다(_thread.lock 은 pickle
    이 안 된다). 그래서 여기서 꺼내 mp 큐로 옮기고, 결과를 다시 라우터 큐에 넣는다.

    한 번에 요청 하나만 처리한다. 결과 큐에는 job_id 가 없어 FIFO 로만 짝을 맞출
    수 있기 때문이다. 동시 처리를 하려면 실행부가 결과에 job_id 를 실어 줘야 한다.
    """
    from rag_router.shared_queues import SharedQueues
    from rag_router.task.task_result import TaskResult

    task_queue, result_queue = SharedQueues.get_queues()
    logger.info("브릿지 시작 (직렬, 타임아웃 %d초)", BRIDGE_TIMEOUT)

    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        logger.info("수신 job_id=%s task_type=%s", task.job_id, task.task_type)
        result_queue.put(_run_one(task, controller, executor, TaskResult))


def _run_one(task, controller, executor, TaskResult):
    # 없는 이름은 여기서 막는다. 컨트롤러는 예외를 잡아 print 만 하므로 그대로
    # 넘기면 결과가 영영 안 오고 요청이 타임아웃까지 매달린다.
    if task.task_type not in tasks:
        logger.warning("등록되지 않은 task_type: %s", task.task_type)
        return TaskResult(task.job_id, False,
                          error=f"아직 지원하지 않는 task_type 입니다: {task.task_type}")

    try:
        # payload 만 보내면 session_id 와 token 을 되찾을 방법이 없다. 요청을 통째로
        # 넘기고, 체인이 그걸 흘려보내며 필요한 단계에서 꺼내 쓴다.
        controller.task_queue.put((task.task_type, {
            "payload": task.payload or {},
            "session_id": task.session_id,
            "token": task.token,
        }))
        result = executor.get_task_result(timeout=BRIDGE_TIMEOUT)
    except queue.Empty:
        logger.error("job_id=%s 결과 없음(%d초). 이후 응답이 어긋날 수 있음",
                     task.job_id, BRIDGE_TIMEOUT)
        return TaskResult(task.job_id, False, error=f"{BRIDGE_TIMEOUT}초 내에 끝나지 않았습니다.")
    except Exception as e:                        # noqa: BLE001
        logger.exception("job_id=%s 브릿지 오류", task.job_id)
        return TaskResult(task.job_id, False, error=f"{type(e).__name__}: {e}")

    if isinstance(result, TaskExecutionError):
        # traceback 은 로그로만. HTTP 응답에 실으면 내부 구조가 샌다.
        logger.error("job_id=%s 작업 실패\n%s", task.job_id, result.tb)
        return TaskResult(task.job_id, False, error=f"작업 실행에 실패했습니다: {task.task_type}")

    # 응답 모양은 각 task 의 마지막 work 이 맞춘다(user_query_output 등). 여기서는
    # 손대지 않는다. dict 이 아닌 값을 돌려주면 TaskResponse 가 거부하므로, 그건
    # 그 task 에 출력 work 이 빠졌다는 뜻이다.
    logger.info("완료 job_id=%s", task.job_id)
    return TaskResult(task.job_id, True, data=result)


def print_task():
    for idx, task in enumerate(tasks):
        print(f"[{idx}] {task}", end="\n")


def menu_loop(taskcontroller, taskexecutor, stop_event):
    """터미널에서 직접 태스크를 돌려보는 통로.

    컨테이너(docker CMD python main.py)에는 stdin 이 없어 input() 이 EOF 로 즉시
    돌아온다. 그래서 tty 일 때만 띄운다.

    통신부와 실행부를 따로 쓴다. 같은 결과 큐를 보면 HTTP 요청의 결과를 메뉴가
    가져가 버린다(타이머를 따로 둔 것과 같은 이유).
    """
    while not stop_event.is_set():
        print_task()
        print("\n------------------------------------------------------")
        print("[q] 종료")
        print("[w] task 입력")

        key = input("메뉴 입력: ")

        match key:
            case "q":
                break

            case "w":
                task_name = input("이름 입력: ")
                taskcontroller.task_queue.put((task_name, None))
                result = taskexecutor.get_task_result()
                print(f"결과 : {result}")


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO,
                        format="[%(name)s] %(levelname)s %(message)s")

    # ── 통신부(HTTP) 전용 ─────────────────────────────
    # 배포는 이 파일이 진입점이다(Dockerfile CMD, containerPort 8000).
    gwexecutor = TaskExecutor()
    gwcontroller = TaskController(gwexecutor.get_task_queue())
    gwexecutor.start()
    gwcontroller.start()
    stop_bridge = threading.Event()
    threading.Thread(target=bridge_loop,
                     args=(gwcontroller, gwexecutor, stop_bridge),
                     daemon=True).start()

    # ── 타이머 전용 ───────────────────────────────────
    timerexecutor = TaskExecutor()
    timerexecutor.start()
    stop_timer = threading.Event()
    threading.Thread(target=timer_loop, args=(timerexecutor, stop_timer), daemon=True).start()

    # ── 메뉴 전용 (터미널에서 띄웠을 때만) ──────────────
    taskexecutor = taskcontroller = None
    stop_menu = threading.Event()
    if sys.stdin is not None and sys.stdin.isatty():
        taskexecutor = TaskExecutor()
        taskcontroller = TaskController(taskexecutor.get_task_queue())
        taskexecutor.start()
        taskcontroller.start()
        threading.Thread(target=menu_loop,
                         args=(taskcontroller, taskexecutor, stop_menu),
                         daemon=True).start()

    try:
        from rag_router.gateway import gateway

        # 라우터 기본값이 60초인데 FILE_UPLOAD 는 색인(파싱+임베딩)까지 하느라 몇 분
        # 걸린다. 그대로 두면 작업은 계속 도는데 응답만 timeout 으로 나간다.
        gateway.TIMEOUT_SEC = GATEWAY_TIMEOUT

        gateway.run()          # uvicorn. 블로킹이다
    finally:
        stop_bridge.set()
        stop_timer.set()
        stop_menu.set()

        timerexecutor.stop()
        timerexecutor.collect()   # 결과 큐를 비워야 자식이 join 에서 멈추지 않는다
        timerexecutor.join()

        gwexecutor.stop()
        gwexecutor.collect()
        gwexecutor.join()
        gwcontroller.terminate()  # TaskController 에는 정상 종료 신호가 없다
        gwcontroller.join()

        if taskexecutor is not None:
            taskexecutor.stop()
            taskexecutor.collect()
            taskexecutor.join()
            taskcontroller.terminate()
            taskcontroller.join()
