# generate_reference_data.py
from typing import Any
import hashlib
import json

import bdo_empire.data_store as ds
from bdo_empire.generate_value_data import generate_value_data


def set_data_file_values(data: dict) -> None:
    """Reads essential data files and populates the provided data dictionary.

    Loads:
    - "exploration" data from "exploration.json".
    - "all_lodging_storage" data from "all_lodging_storage.json".
    - "region-strings" data from "Regioninfo.csv".

    NOTE: All data keys are set to integers.

    Args:
        data: The dictionary to populate with the loaded data.
    """
    print("Reading data files...")

    data["exploration"] = {int(k): v for k, v in ds.read_json("exploration.json").items()}
    data["lodging_data"] = {int(k): v for k, v in ds.read_json("all_lodging_storage.json").items()}
    data["region_strings"] = {int(k): v for k, v in ds.read_strings_csv("Regioninfo.csv").items()}


def set_data_plant_values(prices: dict, modifiers: dict, data: dict) -> None:
    """Generates or loads data to populate "plant_values" in the provided dictionary.

    Regenerates values based on a hash of the input `prices` and `modifiers`.

    Args:
        prices: A dictionary containing item market prices.
        modifiers: A dictionary containing regional or other relevant modifiers.
        data: The main data dictionary to be populated with "plant_values".
    """
    print("Generating node values...")
    sha_filename = "values_hash.txt"
    current_sha = ds.read_text(sha_filename) if ds.is_file(sha_filename) else None

    encoded = json.dumps({"p": prices, "m": modifiers}).encode()
    latest_sha = hashlib.sha256(encoded).hexdigest()

    if latest_sha == current_sha:
        print("  ...re-using existing node values data.")
    else:
        generate_value_data(prices, modifiers, data)
    ds.path().joinpath(sha_filename).write_text(latest_sha, encoding="utf-8")

    data["plant_values"] = ds.read_json("node_values_per_town.json")


def compute_lodging_bounds_costs(
    region_lodging_data: dict[str, Any], reserved: int, bonus: int, max_waypoint_ub: int
) -> tuple[list[tuple[int, int]], int]:
    """
    Computes lodging bounds and costs for a specific region from the lodging chains.

    Args:
        region_lodging_data: Lodging chains data for a specific region.
        reserved: Amount of lodging reserved for other purposes.
        bonus: Amount of bonus lodging (e.g., from pearl shop).
    """
    # Extract bounds_costs
    bounds_costs = [
        (int(ub), lodging_data[0].get("cost"))
        for ub, lodging_data in region_lodging_data.items()
        if ub not in ["max_ub", "lodging_bonus"]
    ]
    if not bounds_costs:
        raise ValueError("No lodging chains found!")

    # Filter retaining the dominant bounds_costs
    def dominates(current: tuple[int, int], filtered: tuple[int, int]) -> bool:
        return current[0] >= filtered[0] and current[1] <= filtered[1]

    filtered = []
    for bound_cost in bounds_costs:
        while filtered and dominates(bound_cost, filtered[-1]):
            filtered.pop(-1)
        filtered.append(bound_cost)
    if not filtered:
        raise ValueError("No valid lodging chains found!")

    # Adjust bounds for baseline +1 free, bonus and reserved lodgings
    bounds_costs = [(ub + 1 + bonus - reserved, cost) for ub, cost in filtered]

    # Filter retaining 0 <= bounds <= max_ub
    bounds_costs = [(ub, cost) for ub, cost in bounds_costs if 0 <= ub <= max_waypoint_ub]
    if not bounds_costs:
        raise ValueError(
            f"No valid lodging chains found!\n"
            f"\tUsing 0 <= bounds <= {max_waypoint_ub} after adjusting for "
            f"{bonus=} and {reserved=} lodgings!"
        )

    # Capture the cost of reservations from the first bounds cost
    # and adjust all bounds_costs by this 'prepaid' balance
    prepaid = bounds_costs[0][1]
    bounds_costs = [(ub, cost - prepaid) for ub, cost in bounds_costs]

    # print("Computed bounds_costs:", bounds_costs)
    # print("With prepaid of", prepaid)

    return bounds_costs, prepaid


def get_affiliated_town_regions(data: dict|None = None) -> dict:
    """
    """
    if data is None:
        data = {}
        data["exploration"] = ds.read_json("exploration.json")
    return {
        v["region_key"]: k
        for k, v in data["exploration"].items()
        if v["is_worker_npc_town"] or v["is_warehouse_town"]
    }

def region_key_from_townname(townname: str, data: dict[str, Any] | None = None) -> int:
    """Translates a town name into its corresponding region key using Regioninfo strings.

    Args:
        townname: The name of the town to be translated.
        data: The main data dictionary containing essential data files.

    Reads directly from Regioninfo.csv when data is None
    """
    region_strings = ds.read_strings_csv("Regioninfo.csv") if data is None else data["region_strings"]
    affiliated_town_regions = get_affiliated_town_regions(data)
    region_key = next((rk for rk, name in region_strings.items() if name == townname and rk in affiliated_town_regions), None)
    if not region_key:
        raise ValueError(f"Town name {townname} not found in Regioninfo.csv")
    return region_key


def set_lodging_bounds_costs(lodging_specifications: dict, data: dict) -> None:
    """Generates lodging bounds and costs data for each region and updates the provided data dict entry.

    For each applicable town, this function calculates and stores:
    - `bounds_costs`: Viable lodging options (capacity, adjusted cost).
    - `prepaid`: The CP cost of the first available lodging option.
    - `max_ub`: The maximum capacity from the processed `bounds_costs`.
    - `bonus`: The user-inputted bonus lodging for the town.
    - `reserved`: The user-inputted reserved lodging for the town.

    Args:
        lodging: User-specified bonus and reserved lodging per town.
        data: Main application data containing essential data, modified in-place.
    """
    print("Generating lodging data...")
    lodging_data = data["lodging_data"]
    region_strings = data["region_strings"]
    affiliated_towns = data["affiliated_town_region"]
    exploration_data = data["exploration"]
    max_waypoint_ub = data["config"]["max_waypoint_ub"]

    for region_key, town_key in affiliated_towns.items():
        if not exploration_data[town_key]["is_worker_npc_town"]:
            continue

        lodging_chains = lodging_data[region_key]
        townname = region_strings[region_key]

        bonus = lodging_specifications[townname]["bonus"]
        bonus_ub = lodging_specifications[townname]["bonus_ub"]
        lodging_ub = int(list(lodging_chains.keys())[-1])
        reserved = lodging_specifications[townname]["reserved"]

        effective_lodging_ub = 1 + lodging_ub + bonus_ub - reserved
        solver_lodging_ub = min(max_waypoint_ub, effective_lodging_ub)

        bounds_costs, prepaid = compute_lodging_bounds_costs(lodging_chains, reserved, bonus, solver_lodging_ub)

        lodging_chains.update(
            {
                "bonus": bonus,
                "bounds_costs": bounds_costs,
                "max_ub": bounds_costs[-1][0],
                "prepaid": prepaid,
                "reserved": reserved,
            }
        )


def get_region_lodging_bounds_costs(town: str, lodging_specification: dict) -> dict:
    """Generate and return the lodging bounds and costs data for a single town (by name)."""
    region_key = str(region_key_from_townname(town))
    if not region_key:
        raise ValueError(f"Town name, {town}, not found in Regioninfo.csv")

    all_lodging_data = ds.read_json("all_lodging_storage.json")
    if region_key not in all_lodging_data:
        raise ValueError(f"No lodging data found for region {region_key} (town {town})")

    bonus = lodging_specification["bonus"]
    reserved = lodging_specification["reserved"]
    bonus_ub = lodging_specification["bonus_ub"]

    lodging_chains = all_lodging_data[region_key]
    lodging_ub = int(list(lodging_chains.keys())[-1])

    effective_lodging_ub = 1 + lodging_ub + bonus_ub - reserved

    bounds_costs, prepaid = compute_lodging_bounds_costs(lodging_chains, reserved, bonus, effective_lodging_ub)

    max_ub = bounds_costs[-1][0]

    return {
        "bounds_costs": bounds_costs,
        "lodgings": lodging_chains,
        "lodging_bonus": bonus,
        "lodging_reserved": reserved,
        "max_ub": max_ub,
        "prepaid": prepaid,
        "region_key": region_key,
    }


def generate_reference_data(
    config: dict, prices: dict, modifiers: dict, lodging: dict, force_active_node_ids: list[int]
) -> dict:
    """Assembles the main data dictionary for empire optimization.

    Initializes and populates a dictionary with core configuration,
    market-derived plant values, lodging information, and static game data
    (exploration nodes, regions, base lodging).

    Args:
        config: Dictionary with general configuration for the optimization.
        prices: Dictionary of item market prices for plant value calculation.
        modifiers: Dictionary of regional/other modifiers for plant values.
        lodging: Dictionary detailing user-specified lodging.
        force_active_node_ids: List of exploration node IDs to be pre-activated.

    Returns:
        dict: A comprehensive data dictionary ready for graph generation.
    """
    data = {}
    data["config"] = config
    data["force_active_node_ids"] = force_active_node_ids
    set_data_file_values(data)

    data["max_ub"] = len([v for v in data["exploration"].values() if v["is_workerman_plantzone"]]) + len(
        force_active_node_ids
    )

    data["affiliated_town_region"] = get_affiliated_town_regions(data)

    set_data_plant_values(prices, modifiers, data)
    set_lodging_bounds_costs(lodging, data)
    return data
