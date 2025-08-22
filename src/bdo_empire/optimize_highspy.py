# optimize_highspy.py

from highspy import Highs, ObjSense

from bdo_empire.generate_graph_data import Arc, GraphData, Node, NodeType as NT
from bdo_empire.solver_highspy import solve, SolverController

SUPERROOT = 99999


def filter_arcs(v: Node, regionflow: str, arcs: list[Arc]) -> list:
    """Simple arc -> var filter"""
    return [
        var
        for arc in arcs
        for key, var in arc.vars.items()
        if key.startswith("regionflow_") and (key == regionflow or v.isLodging)
    ]


def link_in_out_by_region_highs(model: Highs, v: Node, in_arcs: list[Arc], out_arcs: list[Arc]) -> None:
    """Associate nodes based on the region loads allowed."""
    all_inflows = []
    f = v.vars["f"]
    for region in v.regions:
        regionflow_key = f"regionflow_{region.id}"
        inflows = filter_arcs(v, regionflow_key, in_arcs)
        outflows = filter_arcs(v, regionflow_key, out_arcs)
        model.addConstr(
            model.qsum(inflows) == model.qsum(outflows), name=f"balance_{regionflow_key}_at_{v.name()}"
        )
        all_inflows.extend(inflows)
    model.addConstr(f == model.qsum(all_inflows), name=f"flow_{v.name()}")
    model.addConstr(f <= v.ub * v.vars["x"], name=f"x_{v.name()}")


def create_model(config: dict, G: GraphData) -> Highs:
    """Model as reverse flow problem with assignment and dynamic costs."""

    model = Highs()

    # Variables

    for v in G["V"].values():
        v.vars["x"] = model.addBinary(name=f"x_{v.name()}")
        v.vars["f"] = model.addIntegral(name=f"flow_{v.name()}", ub=v.ub)

    for arc in G["E"].values():
        for region in set(arc.source.regions).intersection(set(arc.destination.regions)):
            key = f"regionflow_{region.id}"
            ub = arc.ub if arc.source.type in [NT.region, NT.𝓢, NT.𝓣, NT.lodging] else region.ub
            if str(SUPERROOT) in key:
                ub = len(G["F"])
            if str(SUPERROOT) not in key and arc.source.type in [NT.𝓢, NT.plant]:
                arc.vars[key] = model.addBinary(name=f"{key}_on_{arc.name()}")
            else:
                arc.vars[key] = model.addIntegral(name=f"{key}_on_{arc.name()}", ub=ub)

    # Objective
    prize_values = [
        int(plant.region_prizes[region.id]["value"]) * arc.vars[f"regionflow_{region.id}"]
        for plant in G["P"].values()
        for region in plant.regions
        for arc in plant.inbound_arcs
        if region.id != str(SUPERROOT)
    ]
    model.setObjective(model.qsum(prize_values), sense=ObjSense.kMaximize)

    # Constraints
    cost = model.addIntegral(name="cost", ub=config["budget"])
    model.addConstr(cost == model.qsum(v.cost * v.vars["x"] for v in G["V"].values()), name="TotalCost")

    for region in G["R"].values():
        l_vars = [lodge.vars["x"] for lodge in G["L"].values() if lodge.regions[0] == region]
        model.addConstr(model.qsum(l_vars) <= 1, name=f"lodging_{region.id}")

    for v in G["V"].values():
        if v.type not in [NT.𝓢, NT.𝓣]:
            link_in_out_by_region_highs(model, v, v.inbound_arcs, v.outbound_arcs)

    link_in_out_by_region_highs(model, G["V"]["𝓣"], G["V"]["𝓣"].inbound_arcs, G["V"]["𝓢"].outbound_arcs)
    model.addConstr(G["V"]["𝓢"].vars["x"] == 1, name="x_source")

    for node in G["V"].values():
        if node.type in [NT.S, NT.T]:
            continue

        in_neighbors = [arc.source.vars["x"] for arc in node.inbound_arcs]
        out_neighbors = [arc.destination.vars["x"] for arc in node.outbound_arcs]
        if node.isWaypoint:
            model.addConstr(model.qsum(in_neighbors) - 2 * node.vars["x"] >= 0)
        else:
            model.addConstr(model.qsum(in_neighbors) + model.qsum(out_neighbors) - 2 * node.vars["x"] >= 0)
        model.addConstr(model.qsum(out_neighbors) >= node.vars["x"])

    # Edge case handling.
    # If region 619 is active it must be connected to a near town.
    # There are three connection paths to select from...
    connect_sets = [[1321, 1327, 1328, 1329, 1376], [1321, 1327, 1328, 1329, 1330, 1375], [1339]]
    connect_vars = []
    for i, connect_set in enumerate(connect_sets):
        x = model.addBinary(name=f"x_region_619_connect_{i}")
        connect_vars.append(x)
        model.addConstr(
            model.qsum([G["V"][f"waypoint_{wp}"].vars["x"] for wp in connect_set]) >= len(connect_set) * x
        )
    model.addConstr(model.qsum(connect_vars) >= G["V"]["region_619"].vars["x"])

    return model


def optimize(data: dict, graph_data: GraphData, controller: SolverController) -> Highs:
    num_threads = data["config"]["solver"]["num_threads"]
    print(
        f"\nSolving:  graph with {len(graph_data['V'])} nodes and {len(graph_data['E'])} arcs"
        f"\n  Using:  budget of {data['config']['budget']}"
        f"\n   With:  {num_threads} processes."
    )

    print("Creating mip problem...")
    model = create_model(data["config"], graph_data)

    print("Solving mip problem...")
    options = {k: v for k, v in data["config"]["solver"].items()}
    for option_name, option_value in options.items():
        # Non-standard HiGHS options need filtering...
        if option_name not in ["num_threads", "mip_improvement_timeout"]:
            model.setOptionValue(option_name, option_value)

    model = solve(model, options, controller)

    return model
