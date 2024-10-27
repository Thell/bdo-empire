# generate_reference_data.py

import hashlib
import json

import bdo_empire.data_store as ds
from bdo_empire.generate_value_data import generate_value_data


def get_data_files(data: dict) -> None:
    print("Reading data files...")

    data["exploration"] = {int(k): v for k, v in ds.read_json("exploration.json").items()}
    data["lodging_data"] = {int(k): v for k, v in ds.read_json("all_lodging_storage.json").items()}
    data["region_strings"] = {int(k): v for k, v in ds.read_strings_csv("Regioninfo.csv").items()}


def get_value_data(prices: dict, modifiers: dict, data: dict) -> None:
    print("Generating node values...")
    sha_filename = "values_hash.txt"
    current_sha = ds.read_text(sha_filename) if ds.is_file(sha_filename) else None

    encoded = json.dumps({"p": prices, "m": modifiers}).encode()
    latest_sha = hashlib.sha256(encoded).hexdigest()

    if latest_sha == current_sha:
        print("  ...re-using existing node values data.")
    else:
        generate_value_data(prices, modifiers, data)
    ds.path().joinpath(sha_filename).write_text(latest_sha)

    data["plant_values"] = ds.read_json("node_values_per_town.json")


def get_lodging_data(lodging: dict, data: dict) -> None:
    print("Generating lodging data...")
    for region_key, town_key in data["affiliated_town_region"].items():
        if not data["exploration"][town_key]["is_worker_npc_town"]:
            continue
        lodgings = data["lodging_data"][region_key]
        townname = data["region_strings"][region_key]
        max_lodging = 1 + lodging[townname] + max([int(k) for k in lodgings.keys()])
        data["lodging_data"][region_key]["max_ub"] = max_lodging
        data["lodging_data"][region_key]["lodging_bonus"] = lodging[townname]


def generate_reference_data(
    config: dict, prices: dict, modifiers: dict, lodging: dict, force_active_node_ids: list[int]
) -> dict:
    data = {}
    data["config"] = config
    data["force_active_node_ids"] = force_active_node_ids
    get_data_files(data)

    data["max_ub"] = len(
        [v for v in data["exploration"].values() if v["is_workerman_plantzone"]]
    ) + len(force_active_node_ids)

    data["affiliated_town_region"] = {
        v["region_key"]: k
        for k, v in data["exploration"].items()
        if v["is_worker_npc_town"] or v["is_warehouse_town"]
    }

    get_value_data(prices, modifiers, data)
    get_lodging_data(lodging, data)
    return data
