# api_common.py

from typing import TypedDict
import sys

from loguru import logger
import rustworkx as rx
from rustworkx import PyDiGraph

import data_store as ds

ANCADO_INNER_HARBOR_KEY = 1343
CALPHEON_KEY = 601
GREAT_OCEAN_TERRITORY = 5
OQUILLAS_EYE_KEY = 1727
SUPER_ROOT = 99999


class ResultDict(TypedDict):
    solution_graph: rx.PyDiGraph
    objective_value: int | None


def set_logger(config: dict):
    log_level = config.get("logger", {}).get("level", "INFO")
    log_format = config.get("logger", {}).get("format", "<level>{message}</level>")
    logger.remove()
    logger.add(sys.stdout, colorize=True, level=log_level, format=log_format)
    return logger


def get_clean_exploration_data(config: dict):
    """Read exploration.json from data store and recursively:
    - Remove all entries with an empty link list
    - Remove elements from all link lists that are not in exploration
    - If config.exploration_data.valid_nodes is a non-empty list then only valid nodes are kept
    - If config.exploration_data.omit_great_ocean is true omits all non-routable ocean nodes.
    """
    data = {int(k): v for k, v in ds.read_json("exploration.json").items()}

    valid_nodes = config.get("exploration_data", {}).get("valid_nodes", [])
    assert isinstance(valid_nodes, list)
    if valid_nodes:
        data = {k: v for k, v in data.items() if k in valid_nodes}

    omit_great_ocean = config.get("exploration_data", {}).get("omit_great_ocean", False)
    if omit_great_ocean:
        data = {
            k: v for k, v in data.items() if v["is_base_town"] or v["territory_key"] != GREAT_OCEAN_TERRITORY
        }

    # Recursively remove all non valid entries from link lists and
    # remove all nodes with an empty link list.
    while True:
        valid_keys = {k for k, v in data.items() if v["link_list"]}

        for v in data.values():
            v["link_list"] = [neighbor for neighbor in v["link_list"] if neighbor in valid_keys]

        new_data = {k: v for k, v in data.items() if v["link_list"]}
        if len(new_data) == len(data):
            break
        data = new_data

    return data


def extract_base_empire(G: PyDiGraph, base_empire: dict):
    node_key_by_index = G.attrs["node_key_by_index"]
    prev_terminals_sets = {}

    user_workers = base_empire["userWorkers"]
    for worker in user_workers:
        tnk_value = worker.get("tnk")  # town id (root waypoint_key)
        job_data = worker.get("job", {})
        if job_data is None:
            logger.error(f"Worker for tnk {tnk_value} has no job in base empire data")
            continue
        pzk_value = job_data.get("pzk")  # plantzone id (terminal waypoint_key)
        t = node_key_by_index.inv[pzk_value]
        r = node_key_by_index.inv[tnk_value]
        prev_terminals_sets[t] = r

    return prev_terminals_sets
