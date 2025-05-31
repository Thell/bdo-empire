# optimize.py

from pulp import HiGHS, LpVariable, lpSum, LpProblem, LpMaximize

from bdo_empire.generate_graph_data import Arc, GraphData, Node, NodeType as NT
from bdo_empire.optimize_par import solve_par

SUPERROOT = 99999

def filter_arcs(v: Node, regionflow: str, arcs: list[Arc]) -> list[Arc]:
    return [
        var
        for arc in arcs
        for key, var in arc.vars.items()
        if key.startswith("regionflow_") and (key == regionflow or v.isLodging)
    ]


def link_in_out_by_region(prob: LpProblem, v: Node, in_arcs: list[Arc], out_arcs: list[Arc]) -> None:
    all_inflows = []
    f = v.vars["f"]
    for region in v.regions:
        regionflow_key = f"regionflow_{region.id}"
        inflows = filter_arcs(v, regionflow_key, in_arcs)
        outflows = filter_arcs(v, regionflow_key, out_arcs)
        prob += lpSum(inflows) == lpSum(outflows), f"balance_{regionflow_key}_at_{v.name()}"
        all_inflows.append(inflows)
    prob += f == lpSum(all_inflows), f"flow_{v.name()}"
    prob += f <= v.ub * v.vars["x"], f"x_{v.name()}"


def create_problem(config: dict, G: GraphData) -> LpProblem:
    """Create the problem and add the variables and constraints."""

    prob = LpProblem(config["name"], LpMaximize)

    # Variables
    cost = LpVariable("cost", 0, config["budget"], "Integer")

    for v in G["V"].values():
        v.vars["x"] = LpVariable(f"x_{v.name()}", 0, 1, "Binary")
        v.vars["f"] = LpVariable(f"flow_{v.name()}", 0, v.ub, "Integer")

    for arc in G["E"].values():
        for region in set(arc.source.regions).intersection(set(arc.destination.regions)):
            key = f"regionflow_{region.id}"
            ub = arc.ub if arc.source.type in [NT.region, NT.𝓢, NT.𝓣, NT.lodging] else region.ub
            cat = "Binary" if arc.source.type in [NT.𝓢, NT.plant] else "Integer"
            if str(SUPERROOT) in key:
                cat = "Integer"
                ub = len(G["F"])
            arc.vars[key] = LpVariable(f"{key}_on_{arc.name()}", 0, ub, cat)

    # Objective
    prize_values = [
        round(plant.region_prizes[region.id]["value"], 2) * arc.vars[f"regionflow_{region.id}"]
        for plant in G["P"].values()
        for region in plant.regions
        for arc in plant.inbound_arcs
        if region.id != str(SUPERROOT)
    ]
    prob += lpSum(prize_values), "ObjectiveFunction"

    # Constraints
    prob += lpSum(v.cost * v.vars["x"] for v in G["V"].values()) <= cost, "TotalCost"

    for region in G["R"].values():
        lodging_vars = [lodge.vars["x"] for lodge in G["L"].values() if lodge.regions[0] == region]
        prob += lpSum(lodging_vars) <= 1, f"lodging_{region.id}"

    for v in G["V"].values():
        if v.type not in [NT.𝓢, NT.𝓣]:
            link_in_out_by_region(prob, v, v.inbound_arcs, v.outbound_arcs)

    link_in_out_by_region(prob, G["V"]["𝓣"], G["V"]["𝓣"].inbound_arcs, G["V"]["𝓢"].outbound_arcs)
    prob += G["V"]["𝓢"].vars["x"] == 1, "x_source"

    for node in G["V"].values():
        if node.type in [NT.S, NT.T]:
            continue

        in_neighbors = [arc.source.vars["x"] for arc in node.inbound_arcs]
        out_neighbors = [arc.destination.vars["x"] for arc in node.outbound_arcs]
        if node.isWaypoint:
            prob += lpSum(in_neighbors) - 2 * node.vars["x"] >= 0
        else:
            prob += lpSum(in_neighbors) + lpSum(out_neighbors) - 2 * node.vars["x"] >= 0
        prob += lpSum(out_neighbors) >= node.vars["x"]

    # Force activated flow...
    if len(G["F"]):
        plants_for_fixed = [G["P"][f"plant_fixed_{v.key}"] for v in G["F"].values()]
        for plant in plants_for_fixed:
            # Force flow from source to plant
            for arc in plant.inbound_arcs:
                prob += arc.vars[f"regionflow_{str(SUPERROOT)}"] == 1
            prob += plant.vars["x"] == 1

    # Edge case handling.
    # If region 619 is active it must be connected to a near town.
    # There are three connection paths to select from...
    connect_sets = [[1321, 1327, 1328, 1329, 1376], [1321, 1327, 1328, 1329, 1330, 1375], [1339]]
    connect_vars = []
    for i, connect_set in enumerate(connect_sets):
        x = LpVariable(f"x_region_619_connect_{i}", 0, 1, "Binary")
        connect_vars.append(x)
        prob += lpSum([G["V"][f"waypoint_{wp}"].vars["x"] for wp in connect_set]) >= len(connect_set) * x
    prob += lpSum(connect_vars) >= G["V"]["region_619"].vars["x"]

    return prob


def optimize(data: dict, graph_data: GraphData) -> LpProblem:
    num_processes = data["config"]["solver"]["num_processes"]
    print(
        f"\nSolving:  graph with {len(graph_data['V'])} nodes and {len(graph_data['E'])} arcs"
        f"\n  Using:  budget of {data['config']['budget']} and {len(data['force_active_node_ids'])} forced active nodes."
        f"\n   With:  {num_processes} processes."
    )

    print("Creating mip problem...")
    prob = create_problem(data["config"], graph_data)
    print("Solving mip problem...")

    options = {k: v for k, v in data["config"]["solver"].items() if k != "num_processes"}

    if num_processes == 1:
        print(f"Single process starting using {options}")
        if options["log_file"]:
            options["log_file"] = options["log_file"].as_posix()
        solver = HiGHS()
        solver.optionsDict = options
        prob.solve(solver)
    else:
        prob = solve_par(prob, options, num_processes)

    return prob
