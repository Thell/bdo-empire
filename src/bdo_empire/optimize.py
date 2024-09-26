import os
import json
from typing import List

from pulp import HiGHS, LpVariable, lpSum, LpProblem, LpMaximize

from bdo_empire.generate_graph_data import Arc, Node, NodeType as NT
from bdo_empire.generate_graph_data import generate_graph_data
from bdo_empire.generate_workerman_data import generate_workerman_data
from bdo_empire.generate_reference_data import get_reference_data


def filter_arcs(v, groupflow, arcs):
    return [
        var
        for arc in arcs
        for key, var in arc.vars.items()
        if key.startswith("groupflow_") and (key == groupflow or v.isLodging)
    ]


def link_in_out_by_group(prob: LpProblem, v: Node, in_arcs: List[Arc], out_arcs: List[Arc]):
    all_inflows = []
    f = v.vars["f"]
    for group in v.groups:
        groupflow_key = f"groupflow_{group.id}"
        inflows = filter_arcs(v, groupflow_key, in_arcs)
        outflows = filter_arcs(v, groupflow_key, out_arcs)
        prob += lpSum(inflows) == lpSum(outflows), f"balance_{groupflow_key}_at_{v.name()}"
        all_inflows.append(inflows)
    prob += f == lpSum(all_inflows), f"flow_{v.name()}"
    prob += f <= v.ub * v.vars["x"], f"x_{v.name()}"


def create_problem(config, G):
    """Create the problem and add the variables and constraints."""

    prob = LpProblem(config["name"], LpMaximize)

    # Variables
    # Create cost ∈ ℕ₀ 0 <= cost <= budget
    cost = LpVariable("cost", 0, config["budget"], "Integer")

    # Create node variables.
    for v in G["V"].values():
        # x ∈ {0,1} for each node indicating if node is in solution and cost calculation.
        v.vars["x"] = LpVariable(f"x_{v.name()}", 0, 1, "Binary")
        # f ∈ ℕ₀ for each node such that 0 <= f <= ub for cost calculation and performance.
        v.vars["f"] = LpVariable(f"flow_{v.name()}", 0, v.ub, "Integer")

    # Create arc variables.
    for arc in G["E"].values():
        # Group specific f ∈ ℕ₀ vars for each arc 0 <= f <= ub
        for group in set(arc.source.groups).intersection(set(arc.destination.groups)):
            key = f"groupflow_{group.id}"
            ub = arc.ub if arc.source.type in [NT.group, NT.𝓢, NT.𝓣, NT.lodging] else group.ub
            cat = "Binary" if arc.source.type in [NT.𝓢, NT.plant] else "Integer"
            arc.vars[key] = LpVariable(f"{key}_on_{arc.name()}", 0, ub, cat)

    # Objective: Maximize prizes ∑v(p)x for group specific values for all binary plant inflows.
    prize_values = [
        round(plant.group_prizes[group.id]["value"], 2) * arc.vars[f"groupflow_{group.id}"]
        for plant in G["P"].values()
        for group in plant.groups
        for arc in plant.inbound_arcs
    ]
    prob += lpSum(prize_values), "ObjectiveFunction"

    # Constraints
    # Group specific plant exclusivity enforced by plant's 0<=f<=ub bounds at variable creation.

    # Cost var is defined with ub = budget so this is ∑v(𝑐)x <= budget
    prob += cost == lpSum(v.cost * v.vars["x"] for v in G["V"].values()), "TotalCost"

    # Group specific lodging exclusivity, each lodging's 0<=f<=ub enforces correct selection.
    for group in G["G"].values():
        vars = [lodge.vars["x"] for lodge in G["L"].values() if lodge.groups[0] == group]
        prob += lpSum(vars) <= 1, f"lodging_{group.id}"

    # Group specific f⁻ == f⁺
    for v in G["V"].values():
        if v.type not in [NT.𝓢, NT.𝓣]:
            link_in_out_by_group(prob, v, v.inbound_arcs, v.outbound_arcs)

    # Group specific f⁻𝓣 == f⁺𝓢
    link_in_out_by_group(prob, G["V"]["𝓣"], G["V"]["𝓣"].inbound_arcs, G["V"]["𝓢"].outbound_arcs)
    prob += G["V"]["𝓢"].vars["x"] == 1, "x_source"

    # Active node neighborhood constraints.
    for node in G["V"].values():
        if node.type in [NT.S, NT.T]:
            continue

        in_neighbors = [arc.source.vars["x"] for arc in node.inbound_arcs]
        out_neighbors = [arc.destination.vars["x"] for arc in node.outbound_arcs]

        # All nodes should be 2-degree.
        if node.isWaypoint:
            # Waypoint in/out neighbors are the same.
            prob += lpSum(in_neighbors) - 2 * node.vars["x"] >= 0
        else:
            prob += lpSum(in_neighbors) + lpSum(out_neighbors) - 2 * node.vars["x"] >= 0

        # Every active node must have at least one active outbound neighbor
        prob += lpSum(out_neighbors) >= node.vars["x"]

    return prob


def solve_with_highspy(prob, options_dict, queue, results, process_index):
    from random import randint

    options_dict["random_seed"] = randint(0, 2147483647)
    print(f"Process {process_index} starting using {options_dict}")
    solver = HiGHS()
    solver.optionsDict = options_dict
    prob.solve(solver)
    results[process_index] = prob.to_dict()
    queue.put(process_index)
    return


def solve_par(prob, options_dict, config):
    import multiprocessing

    manager = multiprocessing.Manager()
    processes = []
    queue = multiprocessing.Queue()
    results = manager.list(range(config["solver"]["num_processes"]))

    for i in range(config["solver"]["num_processes"]):
        p = multiprocessing.Process(
            target=solve_with_highspy, args=(prob, options_dict, queue, results, i)
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


def optimize(config, prices, modifiers, lodging, outpath):
    datapath = os.path.join(os.path.dirname(__file__), "data")
    ref_data = get_reference_data(datapath, prices, modifiers, lodging)
    ref_data["config"] = config
    graph_data = generate_graph_data(ref_data)

    print(
        f"\nSolving:  graph with {len(graph_data['V'])} nodes and {len(graph_data['E'])} arcs"
        f"\n  Using:  budget of {config["budget"]}"
        f"\n   With:  {config["solver"]["num_processes"]} processes."
    )

    print("Creating mip problem...")
    prob = create_problem(config, graph_data)
    print("Solving mip problem...")

    options_dict = {k: v for k, v in config["solver"].items() if k != "num_processes"}

    if config["solver"]["num_processes"] == 1:
        print(f"Single process starting using {config["solver"]}")
        solver = HiGHS()
        solver.optionsDict = options_dict
        prob.solve(solver)
    else:
        prob = solve_par(prob, options_dict, config)

    print("Creating workerman json...")
    workerman_json = generate_workerman_data(prob, lodging, ref_data, graph_data)
    outfile = os.path.join(outpath, "optimized_empire.json")
    with open(outfile, "w") as json_file:
        json.dump(workerman_json, json_file, indent=4)
    print("workerman json written to:", outfile)
    print("Completed.")
