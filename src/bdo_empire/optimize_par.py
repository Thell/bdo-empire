import multiprocessing
from multiprocessing import Queue
from random import randint
from pulp import HiGHS, LpProblem


def solve_par_worker(
    prob: LpProblem, options_dict: dict, queue: Queue, results: list, process_index: int
) -> None:
    options_dict["random_seed"] = randint(0, 2147483647)
    print(f"Process {process_index} starting using {options_dict}")
    solver = HiGHS()
    solver.optionsDict = options_dict
    prob.solve(solver)
    results[process_index] = prob.to_dict()
    queue.put(process_index)
    return


def solve_par(prob: LpProblem, options_dict: dict, num_processes: int) -> LpProblem:
    manager = multiprocessing.Manager()
    processes = []
    queue = multiprocessing.Queue()
    results = manager.list(range(num_processes))

    for i in range(num_processes):
        p = multiprocessing.Process(
            target=solve_par_worker, args=(prob, options_dict, queue, results, i)
        )
        processes.append(p)
        p.start()

    first_process = queue.get()
    for i, process in enumerate(processes):
        if process.is_alive():
            print(f"Terminating process: {i}")
            process.terminate()
        process.join()
    print(f"Using results from process {first_process}")
    result = prob.from_dict(results[first_process])
    return result[1]
