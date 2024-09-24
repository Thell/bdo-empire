import os
import json
from typing import List

from pulp import HiGHS, LpVariable, lpSum, LpProblem, LpMaximize

from bdo_empire.generate_graph_data import Arc, Node, NodeType as NT
from bdo_empire.generate_graph_data import generate_graph_data
from bdo_empire.generate_value_data import generate_value_data
from bdo_empire.generate_workerman_data import generate_workerman_data


def get_reference_data(datapath, prices, modifiers, lodging):
    """Read and prepare data from reference data files."""
    import hashlib

    print("Reading data files...")
    data = {}
    with open(os.path.join(datapath, "plantzone.json")) as datafile:
        data["all_plantzones"] = json.load(datafile).keys()
    with open(os.path.join(datapath, "plantzone_drops.json")) as datafile:
        data["plantzone_drops"] = json.load(datafile)
    with open(os.path.join(datapath, "all_lodging_storage.json")) as datafile:
        data["lodging_data"] = json.load(datafile)
    with open(os.path.join(datapath, "town_node_translate.json")) as datafile:
        data["town_to_group"] = json.load(datafile)["tnk2tk"]
    with open(os.path.join(datapath, "town_node_translate.json")) as datafile:
        data["group_to_town"] = json.load(datafile)["tk2tnk"]
    with open(os.path.join(datapath, "warehouse_to_townname.json")) as datafile:
        data["group_to_townname"] = json.load(datafile)
    with open(os.path.join(datapath, "exploration.json")) as datafile:
        data["waypoint_data"] = json.load(datafile)
    with open(os.path.join(datapath, "deck_links.json")) as datafile:
        data["waypoint_links"] = json.load(datafile)

    print("Generating node values...")
    values_file = os.path.join(datapath, "node_values_per_town.json")
    values_sha_file = os.path.join(datapath, "values_hash.txt")

    encoded = json.dumps({"p": prices, "m": modifiers}, sort_keys=True).encode()
    values_sha = hashlib.sha256(encoded).hexdigest()

    if not os.path.isfile(values_file) or not os.path.isfile(values_sha_file):
        generate_value_data(datapath, prices, modifiers)
        with open(values_sha_file, "w") as file:
            file.write(values_sha)
    else:
        with open(values_sha_file, "r") as file:
            prev_values_sha = file.read()
        if prev_values_sha != values_sha:
            generate_value_data(datapath, prices, modifiers)
            with open(values_sha_file, "w") as file:
                file.write(values_sha)
        else:
            print(" - re-using existing node values data.")

    with open(os.path.join(datapath, "node_values_per_town.json")) as datafile:
        data["plant_values"] = json.load(datafile)

    data["plants"] = data["plant_values"].keys()
    data["groups"] = data["plant_values"][list(data["plants"])[0]].keys()
    data["towns"] = [data["group_to_town"][w] for w in data["groups"]]
    data["max_ub"] = len(data["plants"])

    print("Generating lodging data...")
    for group, lodgings in data["lodging_data"].items():
        if group not in data["groups"]:
            continue
        townname = data["group_to_townname"][group]
        max_lodging = 1 + lodging[townname] + max([int(k) for k in lodgings.keys()])
        data["lodging_data"][group]["max_ub"] = max_lodging
        data["lodging_data"][group]["lodging_bonus"] = lodging[townname]

    return data


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


def solve_par(prob, options, config):
    import multiprocessing
    from random import randint

    manager = multiprocessing.Manager()
    processes = []
    queue = multiprocessing.Queue()
    results = manager.list(range(config["solver"]["num_processes"]))

    def solve_with_highspy(prob, options, queue, results, process_index):
        for i, option in enumerate(options.copy()):
            if "random_seed" in option:
                options[i] = f"random_seed={randint(0, 2147483647)}"
        print(f"Process {process_index} starting using {options}")
        prob.solve(HiGHS(options=options))
        results[process_index] = prob.to_dict()
        queue.put(process_index)

    for i in range(config["solver"]["num_processes"]):
        p = multiprocessing.Process(
            target=solve_with_highspy, args=(prob, options, queue, results, i)
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
    print(modifiers)
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

    options = [
        f"mip_rel_gap={config["solver"]["mip_rel_gap"]}",
        f"mip_feasibility_tolerance={config["solver"]["mip_feasibility_tolerance"]}",
        f"primal_feasibility_tolerance={config["solver"]["primal_feasibility_tolerance"]}",
        f"random_seed={config["solver"]["random_seed"]}",
        f"time_limit={config["solver"]["time_limit"]}",
    ]

    if config["solver"]["num_processes"] == 1:
        prob.solve(HiGHS(options=options))
    else:
        prob = solve_par(prob, options, config)

    print("Creating workerman json...")
    workerman_json = generate_workerman_data(prob, lodging, ref_data, graph_data)
    outfile = os.path.join(outpath, "optimized_empire.json")
    with open(outfile, "w") as json_file:
        json.dump(workerman_json, json_file, indent=4)
    print("workerman json written to:", outfile)
    print("Completed.")