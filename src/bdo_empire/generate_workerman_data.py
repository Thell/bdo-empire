"""Empire Workerman JSON Generation
Parse optimizer output for workerman import.
"""

from collections import Counter
import json
import locale
import os
from pathlib import Path
from typing import Dict, Any

import natsort
import networkx as nx
from pulp import LpProblem
from tabulate import tabulate

from bdo_empire.generate_graph_data import GraphData


def load_solution_data(filestem):
    filepath = Path(os.path.dirname(__file__), "highs_output", "solutions")

    prob_file = filepath.joinpath(f"{filestem}_pulp.json")
    _, prob = LpProblem.fromJson(prob_file)
    print("  Loaded solved model:", prob_file)

    data_file = filepath.joinpath(f"{filestem}_cfg.json")
    with open(data_file, "r") as file:
        config = json.load(file)
    print("Loaded problem config:", data_file)

    return config, prob


def write_workerman_json(filestem, data):
    filepath = Path(os.path.join(os.path.dirname(__file__), "workerman_output"))
    filepath = filepath.joinpath(f"{filestem}_workerman.json")
    with open(filepath, "w") as file:
        json.dump(data, file, indent=4)
        print("\nWorkerman saved:", filepath)


def get_workerman_json(workers, ref_data, lodging):
    """Populate and return a standard 'dummy' instance of the workerman dict."""
    lodgingP2W = {}
    for group in ref_data["groups"]:
        if group in ref_data["group_to_townname"]:
            townname = ref_data["group_to_townname"][group]
            lodgingP2W[group] = lodging[townname]
    workerman_json = {
        "activateAncado": False,
        "lodgingP2W": lodgingP2W,
        "userWorkers": workers,
        "farmingEnable": False,
        "farmingProfit": 0,
        "farmingBareProfit": 0,
        "grindTakenList": [],
    }
    return workerman_json


def make_workerman_worker(town_id: int, origin_id: int, worker_data: Dict[str, Any], stash_id: int):
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


def order_workerman_workers(graph, user_workers: list[Dict[str, Any]], solution_distances):
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


def print_summary(outputs, counts: Dict[str, Any], costs: Dict[str, int], total_value: float):
    """Print town, origin, worker summary report."""
    outputs = natsort.natsorted(outputs, key=lambda x: (x["warehouse"], x["node"]))
    colalign = ("right", "right", "left", "right", "right")
    print(tabulate(outputs, headers="keys", colalign=colalign))
    print("By Town:\n\n", tabulate([[k, v] for k, v in counts["by_groups"].items()]), "\n")
    print("  Lodging cost:", costs["lodgings"])
    print("  Worker Nodes:", counts["origins"], "cost:", costs["origins"])
    print("     Waypoints:", counts["waypoints"], "cost:", costs["waypoints"])
    print("    Total Cost:", sum(c for c in costs.values()))
    print("         Value:", locale.currency(round(total_value), grouping=True, symbol=True)[:-3])


def generate_graph(graph_data: GraphData, prob):
    graph = nx.DiGraph()
    exclude_keywords = ["lodging", "𝓢", "𝓣"]

    for var_key, var in prob.variablesDict().items():
        if not round(var.varValue) >= 1:
            continue
        exclude = any(keyword in var_key for keyword in exclude_keywords)
        if exclude:
            continue

        u, v = None, None
        if "groupflow_" in var_key and "_on_" in var_key:
            tmp = var_key.split("_on_")
            tmp = tmp[1].split("_to_")
            u = tmp[0]
            v = tmp[1]
        else:
            continue

        source, destination = u, v
        weight = graph_data["V"][source].cost
        graph.add_edge(destination.split("_")[1], source.split("_")[1], weight=weight)

    return graph


def generate_workerman_data(prob, lodging, ref_data, graph_data):
    locale.setlocale(locale.LC_ALL, "")

    graph = generate_graph(graph_data, prob)
    all_pairs = dict(nx.all_pairs_bellman_ford_path_length(graph, weight="weight"))

    lodging_vars = {}
    origin_vars = {}
    waypoint_vars = {}
    for k, v in prob.variablesDict().items():
        if not round(v.varValue) >= 1:
            continue
        if k.startswith("flow_lodging_") and "_to_" not in k:
            lodging_vars[k.replace("flow_", "")] = v
        elif "_on_plant_" in k:
            origin_vars[k.split("_")[4]] = k.split("_")[1]
        elif k.startswith("flow_waypoint") and "_to_" not in k:
            waypoint_vars[k.replace("flow_", "")] = v

    calculated_value = 0
    distances = []
    origin_cost = 0
    outputs = []
    town_ids = set()
    workerman_user_workers = []
    root_ranks = []
    stash_town_id = 601
    for k, v in origin_vars.items():
        town_id = ref_data["group_to_town"][v]

        town_ids.add(town_id)
        distances.append(all_pairs[town_id][k])

        origin = graph_data["V"][f"plant_{k}"]
        worker_data = origin.group_prizes[v]["worker_data"]
        user_worker = make_workerman_worker(int(town_id), int(origin.id), worker_data, stash_town_id)
        workerman_user_workers.append(user_worker)

        value = origin.group_prizes[v]["value"]
        worker = origin.group_prizes[v]["worker"]
        root_rank = list(origin.group_prizes.keys()).index(v) + 1
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

    counts: Dict[str, Any] = {"origins": len(origin_vars), "waypoints": len(waypoint_vars)}
    by_groups = {
        str(ref_data["group_to_townname"][k]): v
        for k, v in Counter(origin_vars.values()).most_common()
    }
    counts["by_groups"] = by_groups

    costs = {
        "lodgings": sum(graph_data["V"][k].cost for k in lodging_vars.keys()),
        "origins": origin_cost,
        "waypoints": sum(graph_data["V"][k].cost for k in waypoint_vars.keys()),
    }
    print_summary(outputs, counts, costs, calculated_value)

    workerman_ordered_workers = order_workerman_workers(graph, workerman_user_workers, distances)
    workerman_json = get_workerman_json(workerman_ordered_workers, ref_data, lodging)

    return workerman_json
