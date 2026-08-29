
#================================================
# main.py
#================================================

from multiprocessing import Queue
from msvcrt import getch
import threading

from taskcontroller import work_lst, TaskController,tasks, Task
from taskexecutor import TaskExecutor
#import functions
import data_functions
import user_functions
import document_functions
import rag_functions

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
        executor.task_queue.put(Task(tasks["api_all_update"]))
        print()
        print("[타이머] api_all_update 결과 :", executor.get_task_result())
        stop_event.wait(TIMER_INTERVAL)

def print_task():
    for idx, task in enumerate(tasks):
        print(f"[{idx}] {task}", end="\n")


if __name__ == "__main__":


    taskexecutor = TaskExecutor()
    taskcontroller = TaskController(taskexecutor.get_task_queue())

    taskexecutor.start()
    taskcontroller.start()

    timerexecutor = TaskExecutor()          # 타이머 전용 워커 (큐 분리)
    timerexecutor.start()
    stop_timer = threading.Event()
    threading.Thread(target=timer_loop, args=(timerexecutor, stop_timer), daemon=True).start()

    while True:
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
                taskcontroller.task_queue.put(task_name)
                result = taskexecutor.get_task_result()
                print(f"결과 : {result}")

    stop_timer.set()
    timerexecutor.stop()
    timerexecutor.collect()   # 결과 큐를 비워야 자식이 join 에서 멈추지 않는다
    timerexecutor.join()

    taskexecutor.stop()
    taskexecutor.join()

    taskcontroller.terminate()
    taskcontroller.join()


