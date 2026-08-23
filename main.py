
#================================================
# main.py
#================================================

from multiprocessing import Queue
from msvcrt import getch

from taskcontroller import work_lst, TaskController,tasks
from taskexecutor import TaskExecutor
#import functions
#import session_functions
import rag_functions
from embedded.hf_utils import download_model
#────────────────────────────────────────────────

tasks.update({
    "test_task1": ["test1", "test2"],
    "레그실행" : ["parse_function", "chunk_function", "embed_function", "save_function"],
    "레그청킹" : ["parse_function", "chunk_function"] ,  # 모델·DB 없이 확인용
    "레그검색" : ["embed_query_function", "hybrid_search_function", "build_context_function", "rerank_function"],
})

def print_task():
    for idx, task in enumerate(tasks):
        print(f"[{idx}] {task}", end="\n")


if __name__ == "__main__":
    download_model
    print_task()
    print("\n------------------------------------------------------")




    taskexecutor = TaskExecutor()
    taskcontroller = TaskController(taskexecutor.get_task_queue())

    taskexecutor.start()
    taskcontroller.start()

    while True:
        print("[q] 종료")
        print("[w] task 입력")
        print("메뉴 입력 : ", end="")
        
        key = getch()

        match key:
            case b"q":
                break

            case b"w":
                task_name = input("이름 입력")
                taskcontroller.task_queue.put(task_name)
                result = taskexecutor.get_task_result()
                print(f"결과 : {result}")

    taskexecutor.stop()
    taskexecutor.join()

    taskcontroller.terminate()   # TaskController에는 정상 종료 신호가 없어 강제 종료
    taskcontroller.join()


