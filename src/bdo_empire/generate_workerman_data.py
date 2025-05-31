# generate_workerman_data.py

from collections import Counter
import locale

import natsort
import networkx as nx
from pulp import LpProblem
from tabulate import tabulate

import bdo_empire.data_store as ds
from bdo_empire.generate_graph_data import GraphData

SUPERROOT = 99999


def get_workerman_json(workers, data, lodging):
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
    worker = {
        "tnk": town_id,
        "charkey": str(worker_data["charkey"]),
        "label": "default",
        "level": 40,
        "wspdSheet": worker_data["wspd"],
        "mspdSheet": worker_data["mspd"],
        "luckSheet": worker_data["luck"],
        "skills": [int(s) for s in worker_data["skills"]],
        "job": {"kind": "plantzone", "pzk": int(origin_id), "storage": stash_id},
    }
    return worker


def order_workerman_workers(graph, user_workers: list[dict], solution_distances):
    """Order user workers into import order for correct workerman paths construction."""

    # Order by shortest origin -> town paths to break ties by nearest nodes.
    distance_indices = zip(list(range(len(solution_distances))), solution_distances)
    distance_indices = sorted(distance_indices, key=lambda x: x[1])
    workerman_user_workers = [user_workers[i] for i, _ in distance_indices]

    # Iterative ordering of user workers by shortest paths with weight removal on used arcs.
    ordered_workers = []
    while workerman_user_workers:
        distances = []
        all_pairs = dict(nx.all_pairs_bellman_ford_path_length(graph, weight="weight"))
        for worker in workerman_user_workers:
            distance = all_pairs[str(worker["tnk"])][str(worker["job"]["pzk"])]
            distances.append(distance)
        min_value = min(distances)
        min_indice = distances.index(min_value)
        worker = workerman_user_workers[min_indice]
        ordered_workers.append(worker)
        workerman_user_workers.pop(min_indice)

        short_path = nx.shortest_path(graph, str(worker["tnk"]), str(worker["job"]["pzk"]), "weight")
        for s, d in zip(short_path, short_path[1:]):
            if graph.edges[(s, d)]["weight"] >= 1:
                for edge in graph.in_edges(d):
                    graph.edges[edge]["weight"] = 0
                break

    return ordered_workers


def generate_graph(graph_data: GraphData, prob):
    graph = nx.DiGraph()
    exclude_keywords = ["lodging", "𝓢", "𝓣"]

    for var_key, var in prob.variablesDict().items():
        if not round(var.varValue) >= 1:
            continue
        if any(keyword in var_key for keyword in exclude_keywords):
            continue
        if not ("regionflow_" in var_key and "_on_" in var_key):
            continue

        tmp = var_key.split("_on_")
        tmp = tmp[1].split("_to_")
        u = tmp[0]
        v = tmp[1]

        source, destination = u, v
        weight = graph_data["V"][source].cost
        # print(f"{source=} => {destination=} => {weight=}")

        source = source.split('_')[-1]
        destination = destination.split('_')[-1]
        graph.add_edge(destination, source, weight=weight)

    isolated = nx.isolates(graph)
    graph.remove_nodes_from(isolated)
    if '99999' in graph.nodes:
        graph.remove_node('99999')
    print(f"All nodes: {sorted([int(v) for v in graph.nodes])}")

    return graph


def extract_solution(prob) -> tuple[dict, dict, dict]:
    lodging_vars = {}
    origin_vars = {}
    waypoint_vars = {}
    for k, v in prob.variablesDict().items():
        if not round(v.varValue) >= 1:
            continue
        # print(f"{k=} => {v.varValue=}")

        if k.startswith("flow_lodging_") and "_to_" not in k:
            lodging_vars[k.replace("flow_", "")] = v
        elif "_on_plant_" in k:
            root, plant = [e for e in k.split("_") if e.isdigit()][:2]
            if int(root) != SUPERROOT:
                origin_vars[plant] = root
        elif k.startswith(("x_waypoint", "x_town")):
            waypoint_vars[k.replace("x_", "")] = v
    return lodging_vars, origin_vars, waypoint_vars


def process_solution(origin_vars: dict, data: dict, graph_data: GraphData, graph: nx.DiGraph):
    all_pairs = dict(nx.all_pairs_bellman_ford_path_length(graph, weight="weight"))
    region_to_town = {v["region_key"]: k for k, v in data["exploration"].items() if v["is_base_town"]}

    calculated_value = 0
    distances = []
    origin_cost = 0
    outputs = []
    town_ids = set()
    workerman_user_workers = []
    root_ranks = []
    stash_town_id = 601
    for k, v in origin_vars.items():
        town_id = region_to_town[int(v)]
        town_ids.add(town_id)
        distances.append(all_pairs[str(town_id)][k])

        origin = graph_data["V"][f"plant_{k}"]
        worker_data = origin.region_prizes[v]["worker_data"]
        user_worker = make_workerman_worker(int(town_id), int(origin.id), worker_data, stash_town_id)
        workerman_user_workers.append(user_worker)

        value = origin.region_prizes[v]["value"]
        worker = origin.region_prizes[v]["worker"]
        root_rank = list(origin.region_prizes.keys()).index(v) + 1
        root_ranks.append(root_rank)

        origin_cost += origin.cost
        calculated_value += value

        output = {
            "warehouse": v,
            "node": origin.id,
            "worker": worker,
            "value": locale.currency(round(value), grouping=True, symbol=True)[:-3],
            "value_rank": root_rank,
        }
        outputs.append(output)

    return calculated_value, distances, origin_cost, outputs, workerman_user_workers


def print_summary(outputs, counts: dict, costs: dict, total_value: float):
    """Print town, origin, worker summary report."""
    outputs = natsort.natsorted(outputs, key=lambda x: (x["warehouse"], x["node"]))
    # colalign = ("right", "right", "left", "right", "right")
    # print(tabulate(outputs, headers="keys", colalign=colalign))
    print(tabulate(outputs, headers="keys"))
    print("By Town:\n\n", tabulate([[k, v] for k, v in counts["by_regions"].items()]), "\n")
    print("  Lodging cost:", costs["lodgings"])
    print("  Worker Nodes:", counts["origins"], "cost:", costs["origins"])
    print("     Waypoints:", counts["waypoints"], "cost:", costs["waypoints"])
    print("    Total Cost:", sum(c for c in costs.values()))
    print("         Value:", locale.currency(round(total_value), grouping=True, symbol=True)[:-3])


def generate_workerman_data(
    prob: LpProblem, lodging: dict, data: dict, graph_data: GraphData
) -> dict:
    print("Creating workerman json...")
    locale.setlocale(locale.LC_ALL, "")

    graph = generate_graph(graph_data, prob)
    lodging_vars, origin_vars, waypoint_vars = extract_solution(prob)
    # print(f"{lodging_vars=}")
    # print(f"{origin_vars=}")
    # print(f"{waypoint_vars=}")

    solution = process_solution(origin_vars, data, graph_data, graph)
    calculated_value, distances, origin_cost, outputs, workerman_user_workers = solution
    workerman_ordered_workers = order_workerman_workers(graph, workerman_user_workers, distances)
    workerman_json = get_workerman_json(workerman_ordered_workers, data, lodging)

    # Filter zero cost waypoints (towns) from waypoints
    waypoint_vars = {k: v for k, v in waypoint_vars.items() if graph_data["V"][k].cost > 0}

    counts: dict = {"origins": len(origin_vars), "waypoints": len(waypoint_vars)}
    counts["by_regions"] = {
        str(data["region_strings"][int(k)]): v
        for k, v in Counter(origin_vars.values()).most_common()
        if int(k) != SUPERROOT
    }
    costs = {
        "lodgings": sum(graph_data["V"][k].cost for k in lodging_vars),
        "origins": origin_cost,
        "waypoints": sum(graph_data["V"][k].cost for k in waypoint_vars),
    }
    # print(f"{counts=}")
    # print(f"{costs=}")
    # print(f"{calculated_value=}\n")

    print_summary(outputs, counts, costs, calculated_value)
    if data["force_active_node_ids"]:
        print(f"There are {len(data['force_active_node_ids'])}",
              "force activated node connections included in waypoints.\n")
    if "town_1343" in waypoint_vars.keys():
        print("Ancado Inner Harbor active (cost 1) and included with waypoints.")

    return workerman_json
