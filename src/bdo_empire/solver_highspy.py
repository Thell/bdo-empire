# solver_highspy.py

from dataclasses import dataclass
from multiprocessing import cpu_count
from threading import Event, Lock, Thread
import queue
import time

from highspy import Highs, kHighsInf, ObjSense
import numpy as np


class SolverController:
    def __init__(self):
        self._interrupt_event = Event()

    def stop(self):
        self._interrupt_event.set()

    def is_interrupted(self) -> bool:
        return self._interrupt_event.is_set()


@dataclass
class Incumbent:
    id: int
    lock: Lock
    value: int
    solution: np.ndarray
    provided: list[bool]


def solve(model: Highs, config: dict, controller: SolverController) -> Highs:
    mip_improvement_timeout = config.get("mip_improvement_timeout", 86400)
    mip_improvement_timer = time.time()
    num_threads = config.get("num_threads", cpu_count())
    result_queue = queue.Queue()

    clones = [model] + [Highs() for _ in range(num_threads - 1)]
    clones[0].HandleUserInterrupt = True
    clones[0].enableCallbacks()

    for i in range(1, num_threads):
        clones[i].passOptions(clones[0].getOptions())
        clones[i].passModel(clones[0].getModel())
        clones[i].setOptionValue("random_seed", i)
        clones[i].HandleUserInterrupt = True
        clones[i].enableCallbacks()

    obj_sense = clones[0].getObjectiveSense()[1]
    incumbent = Incumbent(
        id=0,
        lock=Lock(),
        value=2**31 if obj_sense == ObjSense.kMinimize else -(2**31),
        solution=np.zeros(clones[0].getNumCol()),
        provided=[False] * num_threads,
    )

    thread_log_capture = [[]] * num_threads

    if obj_sense == ObjSense.kMinimize:

        def is_better(a, b):
            return a < b

    else:

        def is_better(a, b):
            return a > b

    def capture_logs(e):
        """Follow and emit the output log of the incumbent..."""
        nonlocal incumbent, thread_log_capture, clones
        thread_id = int(e.user_data)
        if thread_log_capture[thread_id] or e.message.startswith("\nSolving report"):
            with incumbent.lock:
                thread_log_capture[thread_id].append(e.message)
                for clone_id in range(num_threads):
                    if clone_id != thread_id:
                        clones[clone_id].silent()
        elif thread_id == incumbent.id:
            print(e.message, end="")

    def cbMIPImprovedSolutionHandler(e):
        """Update incumbent to best solution found so far..."""
        # Solution gap and gap abs checks limit the locks and incumbent sharing.
        nonlocal incumbent, clones, mip_improvement_timer
        value = e.data_out.objective_function_value
        value = int(value) if value != kHighsInf else value
        if is_better(value, incumbent.value):
            thread_id = int(e.user_data)
            with incumbent.lock:
                mip_improvement_timer = time.time()
                incumbent.value = value
                incumbent.solution[:] = e.data_out.mip_solution
                incumbent.provided = [False] * num_threads
                incumbent.provided[thread_id] = True
                incumbent.id = thread_id
                # print(f"Incumbent supplanted by thread {clone_id} with {e_objective_value}")
                return

    def cbMIPUserSolutionHandler(e):
        nonlocal incumbent
        if incumbent.value == 2**31:
            return
        value = e.data_out.objective_function_value
        value = int(value) if value != kHighsInf else value
        thread_id = int(e.user_data)
        if incumbent.provided[thread_id] is False and is_better(incumbent.value, value):
            with incumbent.lock:
                e.data_in.user_has_solution = True
                e.data_in.user_solution[:] = incumbent.solution
                incumbent.provided[thread_id] = True
                # print(f"Provided incumbent to thread {clone_id} with {e_objective_value}")
                return

    def cbMIPInterruptHandler(e):
        if controller.is_interrupted() or time.time() - mip_improvement_timer >= mip_improvement_timeout:
            e.interrupt()

    for i in range(num_threads):
        clones[i].cbMipImprovingSolution.subscribe(cbMIPImprovedSolutionHandler, i)
        clones[i].cbMipUserSolution.subscribe(cbMIPUserSolutionHandler, i)
        clones[i].cbLogging.subscribe(capture_logs, i)
        clones[i].cbMipInterrupt.subscribe(cbMIPInterruptHandler, i)

    def task(clone: Highs, i: int):
        clone.solve()
        result_queue.put(i)

    for i in range(num_threads):
        Thread(target=task, args=(clones[i], i), daemon=True).start()
        time.sleep(0.1)

    first_to_finish = None
    while first_to_finish is None:
        try:
            first_to_finish = result_queue.get(timeout=0.1)
        except queue.Empty:
            continue

    for i in range(num_threads):
        clones[i].cancelSolve()

    for message in thread_log_capture[first_to_finish]:
        print(message, end="")

    return clones[first_to_finish]
