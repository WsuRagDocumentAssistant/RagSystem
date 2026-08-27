
#================================================
# main.py
#================================================

from multiprocessing import Queue

from taskcontroller import work_lst, TaskController,tasks
from taskexecutor import TaskExecutor
import functions

#────────────────────────────────────────────────

tasks.update({
    "test_task1": ["test1", "test2"],
})

def print_task():
    for idx, task in enumerate(tasks):
        print(f"[{idx}] {task}", end="\n")


if __name__ == "__main__":


    print_task()
    print("\n------------------------------------------------------")

    taskexecutor = TaskExecutor()
    taskcontroller = TaskController(taskexecutor.get_task_queue())

    taskexecutor.start()
    taskcontroller.start()

    while True:
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

    taskexecutor.stop()
    taskexecutor.join()

    taskcontroller.terminate()
    taskcontroller.join()


