# solver_highspy.py

from dataclasses import dataclass
from math import inf
import psutil
import queue
import re
from threading import Event
from threading import Lock
from threading import Thread
import time

from highspy import Highs, ObjSense
import numpy as np

TIME_AND_NEWLINE_PATTERN = re.compile(r"(\d+\.\d+s)\n$")


class SolverController:
    """Ties the solver threads to the UI for managing interrupts."""

    def __init__(self):
        self._interrupt_event = Event()

    def stop(self):
        self._interrupt_event.set()

    def is_interrupted(self) -> bool:
        return self._interrupt_event.is_set()


class TimeoutTimer(Thread):
    """Monitors for reset signals, if not received within the timeout period, callback is called."""

    def __init__(self, timeout_seconds: float, callback):
        super().__init__(daemon=True)
        self.timeout_seconds = timeout_seconds
        self.callback = callback
        self.reset_event = Event()
        self.running = True

    def run(self):
        while self.running:
            reset_triggered = self.reset_event.wait(self.timeout_seconds)
            if not self.running:
                break

            if reset_triggered:
                self.reset_event.clear()
            else:
                self.callback()
                self.running = False

    def reset(self):
        if self.running:
            self.reset_event.set()

    def shutdown(self):
        self.running = False
        self.reset_event.set()


@dataclass
class Incumbent:
    id: int
    lock: Lock
    value: float
    solution: np.ndarray
    provided: list[bool]


def solve(model: Highs, config: dict, controller: SolverController) -> Highs:
    if controller is None:
        controller = SolverController()

    timeout_controller = None
    mip_improvement_timeout = config.get("mip_improvement_timeout", None)
    if mip_improvement_timeout is not None and mip_improvement_timeout != inf and mip_improvement_timeout > 0:
        timeout_controller = TimeoutTimer(mip_improvement_timeout, controller.stop)
        timeout_controller.start()

    # Unless specified use physical cores - 1 because when all are used the
    # system operations (like the UI) causes more HiGHs thread context switches
    physical_cpu_count = psutil.cpu_count(logical=False)
    physical_cpu_count = 1 if physical_cpu_count is None else max(2, physical_cpu_count) - 1
    num_threads = config.get("num_threads", physical_cpu_count)
    num_threads = max(num_threads, 1)
    if num_threads > 1:
        model.setOptionValue("threads", 1)  # HiGHs internal threads

    # Reduce the amount of logging (still captures all important messages)
    model.setOptionValue("mip_min_logging_interval", 30)

    # UI provided user options
    options = {k: v for k, v in config.items()}
    for option_name, option_value in options.items():
        # Non-standard HiGHS options need filtering...
        # Don't pass num_threads since we are controlling the concurrent threads from the outside
        # Don't pass mip_improvement_timeout and do_not_use_mip_heuristic since they aren't real HiGHS options
        if option_name not in ["num_threads", "mip_improvement_timeout", "do_not_use_mip_heuristic"]:
            model.setOptionValue(option_name, option_value)

    clones = [model] + [Highs() for _ in range(num_threads - 1)]
    clones[0].HandleUserInterrupt = True
    clones[0].enableCallbacks()

    for i in range(1, num_threads):
        clones[i].passOptions(clones[0].getOptions())
        clones[i].passModel(clones[0].getModel())
        clones[i].setOptionValue("random_seed", i)
        clones[i].HandleUserInterrupt = True
        clones[i].enableCallbacks()

    clone_capture_report = [False] * num_threads
    clone_solution_report = [[] for _ in range(num_threads)]

    obj_sense = clones[0].getObjectiveSense()[1]
    if obj_sense == ObjSense.kMinimize:

        def is_better(a, b):
            return a < b

    else:

        def is_better(a, b):
            return a > b

    incumbent = Incumbent(
        id=0,
        lock=Lock(),
        value=2**31 if obj_sense == ObjSense.kMinimize else -(2**31),
        solution=np.zeros(clones[0].getNumCol()),
        provided=[False] * num_threads,
    )

    # Queues and managers
    incumbent_queue = queue.Queue()
    logging_queue = queue.Queue()
    result_queue = queue.Queue()
    stop_event = Event()

    def logging_manager():
        """Consume logging events and capture final reports into clone_solution_report."""
        # NOTE: Highs will not write anything to the console when the logging callback is enabled.
        # The final report is captured here but written to stdout prior to exiting the main function.
        while not stop_event.is_set():
            try:
                e = logging_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            clone_id = int(e.user_data)

            is_solution_report = e.message.startswith("\nSolving report")
            if is_solution_report:
                # NOTE: all future messages from this thread are part of its solving report
                clone_capture_report[clone_id] = True

            if clone_capture_report[clone_id]:
                message = e.message.replace("Solving report", f"Solving report for thread {clone_id}")
                clone_solution_report[clone_id].append(message)
            elif clone_id == incumbent.id:
                # Only print messages for the incumbent thread
                replacement = r"\1 " + str(clone_id) + r"\n"
                print(TIME_AND_NEWLINE_PATTERN.sub(replacement, e.message), end="")

    def incumbent_manager():
        """Process improved-solution events and update the incumbent state."""
        nonlocal incumbent
        while not stop_event.is_set():
            try:
                e = incumbent_queue.get(timeout=0.025)
            except queue.Empty:
                continue

            value = e.data_out.objective_function_value
            if is_better(value, incumbent.value):
                clone_id = int(e.user_data)
                with incumbent.lock:
                    incumbent.value = value
                    incumbent.solution[:] = e.data_out.mip_solution
                    incumbent.provided = [False] * num_threads
                    incumbent.provided[clone_id] = True
                    incumbent.id = clone_id

                if timeout_controller is not None:
                    timeout_controller.reset()

    def cbLoggingHandler(e):
        logging_queue.put_nowait(e)

    def cbMIPImprovedSolutionHandler(e):
        incumbent_queue.put_nowait(e)

    def cbMIPInterruptHandler(e):
        nonlocal controller
        if controller.is_interrupted():
            e.interrupt()

    def cbMIPUserSolutionHandler(e):
        """Update clones to best solution found so far..."""
        clone_id = int(e.user_data)
        if not incumbent.provided[clone_id] and is_better(
            incumbent.value, e.data_out.objective_function_value
        ):
            # Skip rather than block: the callback will be called again
            if incumbent.lock.acquire(blocking=False):
                e.data_in.user_has_solution = True
                e.data_in.user_solution[:] = incumbent.solution
                incumbent.provided[clone_id] = True
                incumbent.lock.release()

    for i in range(num_threads):
        clones[i].cbLogging.subscribe(cbLoggingHandler, i)
        clones[i].cbMipImprovingSolution.subscribe(cbMIPImprovedSolutionHandler, i)
        clones[i].cbMipInterrupt.subscribe(cbMIPInterruptHandler, i)
        clones[i].cbMipUserSolution.subscribe(cbMIPUserSolutionHandler, i)

    # Main Section
    def worker_task(clone: Highs, i: int):
        clone.solve()
        value = clone.getObjectiveValue()
        if value == incumbent.value or is_better(value, incumbent.value):
            result_queue.put(i)

    # Manager threads must be started first
    Thread(target=logging_manager, daemon=True).start()
    Thread(target=incumbent_manager, daemon=True).start()

    for i in range(num_threads):
        Thread(target=worker_task, args=(clones[i], i), daemon=True).start()
        time.sleep(0.1)

    first_to_finish = None
    while first_to_finish is None:
        try:
            # NOTE: timeout allows for Highs interrupt handling.
            first_to_finish = result_queue.get(timeout=0.1)
        except queue.Empty:
            continue

    # Cancel the other threads, without any further output
    for i in range(num_threads):
        if i != first_to_finish:
            clones[i].silent()
        clones[i].cancelSolve()

    # Allow managers to consume final events before stopping
    time.sleep(0.1)
    stop_event.set()

    # Print solution report
    for message in clone_solution_report[first_to_finish]:
        print(message, end="")
    print()

    if timeout_controller is not None:
        timeout_controller.shutdown()

    return clones[first_to_finish]
