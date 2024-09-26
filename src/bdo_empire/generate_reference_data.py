# generate_reference_data.py

import hashlib
import json

import bdo_empire.data_store as ds
from bdo_empire.generate_value_data import generate_value_data


def get_data_files(data: dict) -> None:
    print("Reading data files...")
    data["all_plantzones"] = ds.read_json("plantzone.json")
    data["plantzone_drops"] = ds.read_json("plantzone_drops.json")
    data["lodging_data"] = ds.read_json("all_lodging_storage.json")
    data["town_to_group"] = ds.read_json("town_node_translate.json")["tnk2tk"]
    data["group_to_town"] = ds.read_json("town_node_translate.json")["tk2tnk"]
    data["group_to_townname"] = ds.read_json("warehouse_to_townname.json")
    data["waypoint_data"] = ds.read_json("exploration.json")
    data["waypoint_links"] = ds.read_json("deck_links.json")


def get_value_data(prices: dict, modifiers: dict, data: dict) -> None:
    print("Generating node values...")
    sha_filename = "values_hash.txt"
    current_sha = ds.read_text(sha_filename) if ds.is_file(sha_filename) else None

    encoded = json.dumps({"p": prices, "m": modifiers}).encode()
    latest_sha = hashlib.sha256(encoded).hexdigest()

    if latest_sha == current_sha:
        print("  ...re-using existing node values data.")
    else:
        generate_value_data(prices, modifiers)
        ds.path().joinpath(sha_filename).write_text(latest_sha)

    data["plant_values"] = ds.read_json("node_values_per_town.json")
    data["plants"] = data["plant_values"].keys()
    data["groups"] = data["plant_values"][list(data["plants"])[0]].keys()
    data["towns"] = [data["group_to_town"][w] for w in data["groups"]]
    data["max_ub"] = len(data["plants"])


def get_lodging_data(lodging: dict, data: dict) -> None:
    print("Generating lodging data...")
    for group, lodgings in data["lodging_data"].items():
        if group not in data["groups"]:
            continue
        townname = data["group_to_townname"][group]
        max_lodging = 1 + lodging[townname] + max([int(k) for k in lodgings.keys()])
        data["lodging_data"][group]["max_ub"] = max_lodging
        data["lodging_data"][group]["lodging_bonus"] = lodging[townname]


def generate_reference_data(config: dict, prices: dict, modifiers: dict, lodging: dict) -> dict:
    data = {}
    data["config"] = config
    get_data_files(data)
    get_value_data(prices, modifiers, data)
    get_lodging_data(lodging, data)
    return data
