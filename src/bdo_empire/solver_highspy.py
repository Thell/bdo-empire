# solver_highspy.py

import time
from math import inf
from threading import Event, Thread

from highspy import Highs


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


def solve(model: Highs, config: dict, controller: SolverController) -> Highs:
    """Solve a MIP problem using Highs with custom interrupt and timeout controllers."""

    # Non-standard HiGHS options need filtering...
    filtered_options = {"mip_improvement_timeout"}
    options = {k: v for k, v in config.get("solver", {}).items() if k not in filtered_options}
    for option_name, option_value in options.items():
        model.setOptionValue(option_name, option_value)

    # Callback Handlers
    # NOTE: By default the tkinter app intercepts SIGINT and cancels the main thread,
    #       which we don't want to happen just to stop the solver, so the main app is
    #       set to ignore SIGINT. This also means HiGHS won't get a ctrl-c interrupt.
    #       So the only way to stop the solve is to click the stop button, timeout, or
    #       complete the solve.
    model.enableCallbacks()

    def cbMIPInterruptHandler(e):
        nonlocal controller
        if controller.is_interrupted():
            e.interrupt()

    model.cbMipInterrupt.subscribe(cbMIPInterruptHandler)

    mip_improvement_timeout = config.get("mip_improvement_timeout", inf)
    if mip_improvement_timeout > 0 and mip_improvement_timeout < inf:
        timeout_controller = TimeoutTimer(mip_improvement_timeout, controller.stop)
        timeout_controller.start()
    else:
        timeout_controller = None

    if timeout_controller is not None:

        def cbMIPImprovingSolutionHandler(e):
            timeout_controller.reset()

        model.cbMipImprovingSolution.subscribe(cbMIPImprovingSolutionHandler)

    # Solve it!
    try:
        highs_thread = Thread(target=model.solve, daemon=True)
        highs_thread.start()
        while highs_thread.is_alive():
            time.sleep(0.1)
    finally:
        if timeout_controller is not None:
            timeout_controller.shutdown()

    return model
