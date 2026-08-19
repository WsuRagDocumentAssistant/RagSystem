
#================================================
# main.py
#================================================

from multiprocessing import Queue
from msvcrt import getch

from taskcontroller import work_lst, TaskController,tasks
from taskexecutor import TaskExecutor
import functions

from ragmodul import RagController

#────────────────────────────────────────────────

tasks.update({
    "test_task1": ["test1", "test2"],
    "rag_test" : ["parser", "chunk", "embedded"]
})


if __name__ == "__main__":

    print(tasks)
    print("\n------------------------------------------------------")

    print(work_lst)
    print("\n------------------------------------------------------")




    taskexecutor = TaskExecutor()
    taskcontroller = TaskController(taskexecutor.task_queue)

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


