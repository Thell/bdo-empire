import multiprocessing
import random


def solve_with_highspy(lp, seed, queue, process_index):
    lp.solverModel.options["random_seed"] = seed

    try:
        lp.solverModel.run()  # Assumes this is the HiGHSpy solver's run method
        queue.put((process_index, "success"))
    except Exception as e:
        queue.put((process_index, "error", str(e)))


def parallel_highspy_solve(lp, num_processes=8):
    processes = []
    queue = multiprocessing.Queue()

    for i in range(num_processes):
        seed = random.randint(0, 2147483647)
        p = multiprocessing.Process(target=solve_with_highspy, args=(lp, seed, queue, i))
        processes.append(p)
        p.start()

    result = queue.get()
    for process in processes:
        if process.is_alive():
            process.terminate()

    process_index, status = result[0], result[1]
    if status == "success":
        print(f"Process {process_index} finished successfully.")
    else:
        print(f"Process {process_index} encountered an error: {result[2]}")

    return process_index
