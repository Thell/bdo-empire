# optimize.py

from pulp import HiGHS, LpVariable, lpSum, LpProblem, LpMaximize

from bdo_empire.generate_graph_data import Arc, GraphData, Node, NodeType as NT
from bdo_empire.optimize_par import solve_par


def filter_arcs(v: Node, groupflow: str, arcs: list[Arc]) -> list[Arc]:
    return [
        var
        for arc in arcs
        for key, var in arc.vars.items()
        if key.startswith("groupflow_") and (key == groupflow or v.isLodging)
    ]


def link_in_out_by_group(prob: LpProblem, v: Node, in_arcs: list[Arc], out_arcs: list[Arc]) -> None:
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


def create_problem(config: dict, G: GraphData) -> LpProblem:
    """Create the problem and add the variables and constraints."""

    prob = LpProblem(config["name"], LpMaximize)

    # Variables
    cost = LpVariable("cost", 0, config["budget"], "Integer")

    for v in G["V"].values():
        v.vars["x"] = LpVariable(f"x_{v.name()}", 0, 1, "Binary")
        v.vars["f"] = LpVariable(f"flow_{v.name()}", 0, v.ub, "Integer")

    for arc in G["E"].values():
        for group in set(arc.source.groups).intersection(set(arc.destination.groups)):
            key = f"groupflow_{group.id}"
            ub = arc.ub if arc.source.type in [NT.group, NT.𝓢, NT.𝓣, NT.lodging] else group.ub
            cat = "Binary" if arc.source.type in [NT.𝓢, NT.plant] else "Integer"
            arc.vars[key] = LpVariable(f"{key}_on_{arc.name()}", 0, ub, cat)

    # Objective
    prize_values = [
        round(plant.group_prizes[group.id]["value"], 2) * arc.vars[f"groupflow_{group.id}"]
        for plant in G["P"].values()
        for group in plant.groups
        for arc in plant.inbound_arcs
    ]
    prob += lpSum(prize_values), "ObjectiveFunction"

    # Constraints
    prob += cost == lpSum(v.cost * v.vars["x"] for v in G["V"].values()), "TotalCost"

    for group in G["G"].values():
        vars = [lodge.vars["x"] for lodge in G["L"].values() if lodge.groups[0] == group]
        prob += lpSum(vars) <= 1, f"lodging_{group.id}"

    for v in G["V"].values():
        if v.type not in [NT.𝓢, NT.𝓣]:
            link_in_out_by_group(prob, v, v.inbound_arcs, v.outbound_arcs)

    link_in_out_by_group(prob, G["V"]["𝓣"], G["V"]["𝓣"].inbound_arcs, G["V"]["𝓢"].outbound_arcs)
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

    return prob


def optimize(data: dict, graph_data: GraphData) -> LpProblem:
    num_processes = data["config"]["solver"]["num_processes"]
    print(
        f"\nSolving:  graph with {len(graph_data['V'])} nodes and {len(graph_data['E'])} arcs"
        f"\n  Using:  budget of {data["config"]["budget"]}"
        f"\n   With:  {num_processes} processes."
    )

    print("Creating mip problem...")
    prob = create_problem(data["config"], graph_data)
    print("Solving mip problem...")

    options = {k: v for k, v in data["config"]["solver"].items() if k != "num_processes"}

    if num_processes == 1:
        print(f"Single process starting using {options}")
        solver = HiGHS()
        solver.optionsDict = options
        prob.solve(solver)
    else:
        prob = solve_par(prob, options, num_processes)

    return prob
