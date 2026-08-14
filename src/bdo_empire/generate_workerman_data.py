# generate_workerman_data.py

import copy
from collections import Counter

import rustworkx as rx
from highspy import Highs
from loguru import logger
from rustworkx import PyDiGraph
from tabulate import tabulate

import bdo_empire.data_store as ds
from bdo_empire.api_common import (
    CALPHEON_KEY,
    FARMING_WORKER_SILVER_PER_DAY,
    FARMING_WORKER_SILVER_PER_DAY_KEY,
    FENCE_1_KEY,
    SUPER_ROOT,
    extract_base_empire,
)
from bdo_empire.api_exploration_graph import get_fence
from bdo_empire.api_rx_pydigraph import subgraph_stable


def generate_workerman_json(workers, data, lodging):
    """Populate and return a standard 'dummy' instance of the workerman dict."""
    region_strings = ds.read_strings_csv("Regioninfo.csv")
    lodgingP2W = {}
    for region_key, town_key in data["affiliated_town_region"].items():
        if not data["exploration"][town_key]["is_worker_npc_town"]:
            continue
        townname = region_strings[region_key]
        lodgingP2W[region_key] = lodging[townname]["bonus"]
    workerman_json = {
        "activateAncado": False,
        "lodgingP2W": lodgingP2W,
        "userWorkers": workers,
        "farmingEnable": False,
        "farmingProfit": 0,
        "farmingBareProfit": 0,
        "grindTakenList": data["force_active_node_ids"],
    }
    return workerman_json


def make_workerman_worker(town_id: int, origin_id: int, worker_data: dict, stash_id: int):
    """Populate and return a 'dummy' instance of a workerman user worker dict."""
    if origin_id >= FENCE_1_KEY and origin_id <= FENCE_1_KEY + 9:
        job = "farming"
    else:
        job = {"kind": "plantzone", "pzk": int(origin_id), "storage": stash_id}

    worker = {
        "tnk": town_id,
        "charkey": str(worker_data["charkey"]),
        "label": f"{int(worker_data['value'])}",
        "level": 40,
        "wspdSheet": worker_data["wspd"],
        "mspdSheet": worker_data["mspd"],
        "luckSheet": worker_data["luck"],
        "skills": [int(s) for s in worker_data.get("skills", [])],
        "job": job,
    }
    return worker


def trace_flow(G: PyDiGraph, model: Highs, vars: dict, data: dict):
    flow_eps = 1e-6

    x = vars["x"]
    x_t_r = vars["x_t_r"]
    f_r = vars["f_r"]

    # Root -> nodes that participate in positive flow
    root_flow_nodes: dict[int, set[int]] = {}
    root_flow_arcs: dict[int, list[tuple[int, int, float]]] = {}

    for (r, i, j), flow_var in f_r.items():
        value = model.variableValue(flow_var)
        if value <= flow_eps:
            continue

        root_flow_nodes.setdefault(r, set()).update((i, j))
        root_flow_arcs.setdefault(r, []).append((i, j, value))

    logger.info("=== FLOW TRACE ===")

    for r in sorted(root_flow_nodes):
        flow_nodes = root_flow_nodes[r]

        logger.info(
            f"root={G[r]['waypoint_key']} flow_nodes={len(flow_nodes)} flow_arcs={len(root_flow_arcs[r])}"
        )

        missing_x = [n for n in flow_nodes if round(model.variableValue(x[n])) != 1]

        if missing_x:
            logger.error(
                f"Flow node(s) without x=1: {[(n, G[n]['waypoint_key'], model.variableValue(x[n])) for n in missing_x]}"
            )

    assignments: list[tuple[int, int]] = []

    key_list = list(x_t_r.keys())
    for idx, var in enumerate(x_t_r.values()):
        if round(model.variableValue(var)) == 1:
            assignments.append(key_list[idx])

    logger.info(f"assigned terminal/root pairs= {len(assignments)}")

    for t, r in assignments:
        flow_adj: dict[int, list[int]] = {}

        for rr, i, j, value in (
            (rr, i, j, v) for rr, arcs in root_flow_arcs.items() if rr == r for i, j, v in arcs
        ):
            flow_adj.setdefault(i, []).append(j)

        seen = {t}
        stack = [t]

        while stack:
            cur = stack.pop()

            for nxt in flow_adj.get(cur, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)

        if r not in seen:
            logger.error(
                f"FLOW REACHABILITY FAILURE terminal={G[t]['waypoint_key']} root={G[r]['waypoint_key']}"
            )

            logger.error(
                f"terminal transit bounds= { {G[k]['waypoint_key']: v for k, v in G[t]['transit_bounds'].items()} }"
            )

            logger.error(
                f"root transit bounds={ {G[k]['waypoint_key']: v for k, v in G[r]['transit_bounds'].items()} }",
            )

    return {
        "root_flow_nodes": root_flow_nodes,
        "root_flow_arcs": root_flow_arcs,
    }


def generate_graph(G: PyDiGraph, model: Highs, vars: dict, data: dict):
    """Sub graph G to the solution graph using only transitted nodes from terminal, root paths."""
    # Since the Highs model is not setup to reduce the cost as well as maximize the value, we
    # do it manually here.

    terminal_sets = {}

    # # Debugging code for reachability issues post CP reduction 06/04/26 patch and the
    # # generate_graph reductions to the root transit layers...
    # trace_results = trace_flow(G, model, vars, data)
    # root_flow_nodes = trace_results["root_flow_nodes"]
    # root_flow_arcs = trace_results["root_flow_arcs"]

    # First we need to add farm fences for the stable subgraphing.
    farm_r = vars["farm_r"]
    active_graph_fence_ids = []
    if farm_r:
        fence_ids = data["farm_fence_keys"]
        farmingWorkerSilerPerDay = data["farmingWorkerSilverPerDay"]
        num_farm_fences = data["num_farm_fences"]

        roots_assigned_fences = []
        for r, v in vars["farm_r"].items():
            count = round(model.variableValue(v))
            roots_assigned_fences.extend([r] * count)

        num_assigned_fences = len(roots_assigned_fences)
        if num_assigned_fences > num_farm_fences:
            logger.error(f"Too many assigned fences: {len(roots_assigned_fences)} > {len(fence_ids)}")
            raise ValueError("Too many assigned fences... model is broken.")
        elif num_assigned_fences < num_farm_fences:
            unassigned_count = len(fence_ids) - num_assigned_fences
            logger.warning(f"There are {unassigned_count} unassigned fences.")

        ref_fence_node = get_fence({})
        for r, f in zip(roots_assigned_fences, fence_ids):
            fence_node = copy.deepcopy(ref_fence_node)
            fence_node["waypoint_key"] = f
            fence_node["region_key"] = G[r]["region_key"]
            fence_node["prizes"] = {r: farmingWorkerSilerPerDay}

            fence_node_id = G.add_node(fence_node)
            active_graph_fence_ids.append(fence_node_id)
            G.add_edge(fence_node_id, r, None)
            G.add_edge(r, fence_node_id, None)

            terminal_sets[fence_node_id] = r

    key_list = list(vars["x_t_r"].keys())
    for i, t_var in enumerate(vars["x_t_r"].values()):
        if round(model.variableValue(t_var)) == 1:
            terminal, root = key_list[i]
            terminal_sets[terminal] = root

    # Filter non-used nodes from the solution nodes using all terminal -> root paths.
    active_graph_indices = [i for i, x_var in vars["x"].items() if round(model.variableValue(x_var)) == 1]

    # Ensures that all fence assigned roots are active.
    active_graph_indices.extend(terminal_sets.keys())
    active_graph_indices.extend(terminal_sets.values())

    # # Debugging - resolve non-reachable t,r assignment resulting from the root transit layer reduction.
    # flow_nodes = set()
    # for nodes in root_flow_nodes.values():
    #     flow_nodes.update(nodes)
    # selected_nodes = set(active_graph_indices)
    # missing = flow_nodes - selected_nodes
    # extra = selected_nodes - flow_nodes

    subG = subgraph_stable(active_graph_indices, G)
    used_active_nodes = set()
    for terminal, root in terminal_sets.items():
        # Since the HiGHs solution is a tree we can just use hops of 1.
        path = rx.dijkstra_shortest_paths(subG, terminal, root, default_weight=1)
        assert root in path, f"No path from {subG[terminal]['waypoint_key']} to {subG[root]['waypoint_key']}"
        used_active_nodes.update(path[root])
    subG.remove_nodes_from(set(subG.node_indices()) - used_active_nodes)

    # At this point the super root, if present, is still in the graph but won't be used.
    super_root_index = None
    for i in G.node_indices():
        if G[i]["waypoint_key"] == SUPER_ROOT:
            super_root_index = i
    if super_root_index is not None:
        subG.remove_node(super_root_index)

    return subG, terminal_sets


def generate_farm_worker(region_key: int, data: dict):
    from bdo_empire.generate_value_data import get_all_region_workers, string_keys_to_ints

    if not data.get("worker_static", False):
        data["worker_static"] = string_keys_to_ints(ds.read_json("worker_static.json"))
    # We always use a 'giant' type worker for farmers...
    workers = get_all_region_workers(data)[region_key]
    for worker in workers.values():
        if worker["isGiant"]:
            return worker

    logger.error(f"Failed to find a 'giant' worker for region {region_key}")
    raise ValueError(f"Failed to find a 'giant' worker for region {region_key}")


def generate_workerman_workers(G: PyDiGraph, terminal_sets: dict, data: dict):
    workerman_user_workers = []
    stash_town_id = CALPHEON_KEY

    for terminal_index, root_index in terminal_sets.items():
        terminal_data = G[terminal_index]
        if terminal_data.get("is_super_terminal", False):
            continue
        root_data = G[root_index]
        terminal_key = terminal_data["waypoint_key"]
        root_key = root_data["waypoint_key"]

        # NOTE: Plant values data is keyed by warehouse keys!
        if terminal_key >= FENCE_1_KEY and terminal_key <= FENCE_1_KEY + 9:
            worker_data = generate_farm_worker(root_data["region_key"], data)
            worker_data["value"] = data.get(FARMING_WORKER_SILVER_PER_DAY_KEY, FARMING_WORKER_SILVER_PER_DAY)
        else:
            prize_data = data["plant_values"][terminal_key][root_data["region_key"]]
            worker_data = prize_data["worker_data"]
            worker_data["value"] = prize_data["value"]

        user_worker = make_workerman_worker(root_key, terminal_key, worker_data, stash_town_id)
        workerman_user_workers.append(user_worker)

    return workerman_user_workers


def print_summary(
    G: PyDiGraph,
    terminal_sets: dict,
    lodging_specifications: dict,
    workers: list,
    model: Highs,
    vars: dict,
    data: dict,
):
    """Print town, origin, worker summary report."""

    region_strings = data["region_strings"]
    exploration_strings = data["exploration_strings"]

    ##### Prep the terminal sets to ensure no special handling is needed.
    # Sort terminal_sets by root, then terminal value.
    terminal_sets = {t: r for t, r in sorted(terminal_sets.items(), key=lambda item: (item[1], item[0]))}

    # Remove any terminal sets that are already in the base empire.
    if data["base_empire"] is not None:
        prev_terminals_sets = extract_base_empire(G, data["base_empire"])
        terminal_sets = {t: r for t, r in terminal_sets.items() if t not in prev_terminals_sets}

    # Remove any super terminal, super root pairs.
    terminal_sets = {t: r for t, r in terminal_sets.items() if not G[t].get("is_super_terminal")}

    ##### Worker summary section
    # The first tabulated summary is each terminal, root pair with worker, value and value rank.
    #
    # warehouse  node          task                       worker     value    value_rank
    # ---------  ------------  -----------------------  --------  --------  ------------
    # Velia      Bartali Farm  Chicken Meat Production   7571 🐢  10472035             1

    species_to_symbol = (
        dict.fromkeys([0, 3, 5, 6], "👺") | dict.fromkeys([2, 4, 8], "🐢") | dict.fromkeys([1, 7, 9], "👨")
    )
    chatKey_to_species_symbol_map = {
        char_key: species_to_symbol.get(species, "")
        for species_data in ds.read_json("region_workers.json").values()
        for species, char_key in species_data.items()
    }

    table_rows = []
    for terminal, root in terminal_sets.items():
        terminal_data = G[terminal]
        terminal_key = terminal_data["waypoint_key"]
        root_data = G[root]
        root_region_key = root_data["region_key"]

        is_farm = terminal_key >= FENCE_1_KEY and terminal_key <= FENCE_1_KEY + 9
        if is_farm:
            worker_data = generate_farm_worker(root_region_key, data)
            worker_data["value"] = data.get(FARMING_WORKER_SILVER_PER_DAY_KEY, FARMING_WORKER_SILVER_PER_DAY)
        else:
            prize_data = data["plant_values"][terminal_key][root_region_key]
            worker_data = prize_data["worker_data"]

        worker = worker_data["charkey"]
        worker = f"{worker} {chatKey_to_species_symbol_map[worker]}"

        node_str = "Farming Fence" if is_farm else exploration_strings[terminal_data["link_list"][0]]
        task_str = "Cultivation" if is_farm else exploration_strings[terminal_key]

        table_rows.append({
            "warehouse": region_strings[root_region_key],
            "node": node_str,
            "task": task_str,
            "worker": worker,
            "value": G[terminal]["prizes"][root],
            "value_rank": list(G[terminal]["prizes"]).index(root) + 1,
        })

    if data["base_empire"] is not None:
        print("\nExtension to base empire:\n")
    print(tabulate(table_rows, headers="keys"))
    print()

    ##### Region capacity summary section
    # The second tabulated summary is the total number of origins per region (ie: capacity count used),
    # ordered by the most used region.
    #
    # warehouse              used  purchased  cost
    # ---------------------  ----  ---------  ----
    # Bukpo                     3
    # Velia                     2
    # Glish                     1

    capacity_used = Counter(terminal_sets.values())
    capacity_costs = {r: G[r]["capacity_cost"][c] for r, c in capacity_used.items()}

    table_rows = []
    for root in capacity_used:
        root_region_key = G[root]["region_key"]
        warehouse_name = region_strings.get(root_region_key, root_region_key)

        spec = lodging_specifications.get(warehouse_name, {"bonus": 0, "reserved": 0})
        used = capacity_used[root]
        cost = capacity_costs[root]

        table_rows.append({
            "warehouse": warehouse_name,
            "bonus": spec["bonus"],
            "reserved": spec["reserved"],
            "used": used,
            "cost": cost,
            "prepaid": spec["prepaid"],
        })

    table_rows = sorted(table_rows, key=lambda x: x["used"], reverse=True)
    if data["base_empire"] is not None:
        print("\nExtension to base empire:\n")
    print(tabulate(table_rows, headers="keys"))
    print()

    ##### Final quick cost summary section
    # The third tabulated summary is the total number of origins, waypoints and lodging cost.
    #
    # Lodging cost: 1
    # Worker Nodes: 8 cost: 8
    #    Waypoints: 9 cost: 11
    #   Total Cost: 20
    #  Total Value: 10472035

    waypoints = {
        i: G[i]["need_exploration_point"]
        for i in G.node_indices()
        if i not in terminal_sets and G[i]["need_exploration_point"] > 0
    }

    counts: dict = {
        "origins": len(terminal_sets),
        "waypoints": len(waypoints),
    }

    total_capacity_cost = sum(capacity_costs.values())
    total_terminal_cost = sum(G[t]["need_exploration_point"] for t in terminal_sets)
    costs = {
        "lodgings": total_capacity_cost,
        "origins": total_terminal_cost,
        "waypoints": sum(waypoints.values()),
    }

    total_terminal_value = sum(G[t]["prizes"][r] for t, r in terminal_sets.items())

    if data["base_empire"] is not None:
        print("\nExtension to base empire:\n")
        print("  Added Lodging cost:", costs["lodgings"])
        print("  Added Worker Nodes:", counts["origins"], "cost:", costs["origins"])
        print("     Added Waypoints: Unknown (depends on base empire routing)")
        print("   Added Total Value:", total_terminal_value)
    else:
        print("  Lodging cost:", costs["lodgings"])
        print("  Worker Nodes:", counts["origins"], "cost:", costs["origins"])
        print("     Waypoints:", counts["waypoints"], "cost:", costs["waypoints"])
        print("    Total Cost:", sum(c for c in costs.values()))
        print("   Total Value:", total_terminal_value)
    print()
    if data["force_active_node_ids"]:
        print(
            f"There are {len(data['force_active_node_ids'])}",
            "force activated node connections included in waypoints.\n",
        )
    print()


def generate_workerman_data(highs_results: tuple[Highs, dict], lodging_specs: dict, data: dict) -> dict:
    print("Creating workerman json...\n")

    model, vars = highs_results
    G = data["solver_graph"]
    solution_subG, terminal_sets = generate_graph(G, model, vars, data)
    assert isinstance(solution_subG, PyDiGraph)

    workers = generate_workerman_workers(solution_subG, terminal_sets, data)
    workerman_json = generate_workerman_json(workers, data, lodging_specs)

    print_summary(solution_subG, terminal_sets, lodging_specs, workers, model, vars, data)

    return workerman_json
