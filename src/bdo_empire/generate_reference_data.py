# generate_reference_data.py

import json
import os

from bdo_empire.generate_value_data import generate_value_data


def get_reference_data(datapath, prices, modifiers, lodging):
    """Read and prepare data from reference data files."""
    import hashlib

    print("Reading data files...")
    data = {}
    with open(os.path.join(datapath, "plantzone.json")) as datafile:
        data["all_plantzones"] = json.load(datafile).keys()
    with open(os.path.join(datapath, "plantzone_drops.json")) as datafile:
        data["plantzone_drops"] = json.load(datafile)
    with open(os.path.join(datapath, "all_lodging_storage.json")) as datafile:
        data["lodging_data"] = json.load(datafile)
    with open(os.path.join(datapath, "town_node_translate.json")) as datafile:
        data["town_to_group"] = json.load(datafile)["tnk2tk"]
    with open(os.path.join(datapath, "town_node_translate.json")) as datafile:
        data["group_to_town"] = json.load(datafile)["tk2tnk"]
    with open(os.path.join(datapath, "warehouse_to_townname.json")) as datafile:
        data["group_to_townname"] = json.load(datafile)
    with open(os.path.join(datapath, "exploration.json")) as datafile:
        data["waypoint_data"] = json.load(datafile)
    with open(os.path.join(datapath, "deck_links.json")) as datafile:
        data["waypoint_links"] = json.load(datafile)

    print("Generating node values...")
    values_file = os.path.join(datapath, "node_values_per_town.json")
    values_sha_file = os.path.join(datapath, "values_hash.txt")

    encoded = json.dumps({"p": prices, "m": modifiers}, sort_keys=True).encode()
    values_sha = hashlib.sha256(encoded).hexdigest()

    if not os.path.isfile(values_file) or not os.path.isfile(values_sha_file):
        generate_value_data(datapath, prices, modifiers)
        with open(values_sha_file, "w") as file:
            file.write(values_sha)
    else:
        with open(values_sha_file, "r") as file:
            prev_values_sha = file.read()
        if prev_values_sha != values_sha:
            generate_value_data(datapath, prices, modifiers)
            with open(values_sha_file, "w") as file:
                file.write(values_sha)
        else:
            print(" - re-using existing node values data.")

    with open(os.path.join(datapath, "node_values_per_town.json")) as datafile:
        data["plant_values"] = json.load(datafile)

    data["plants"] = data["plant_values"].keys()
    data["groups"] = data["plant_values"][list(data["plants"])[0]].keys()
    data["towns"] = [data["group_to_town"][w] for w in data["groups"]]
    data["max_ub"] = len(data["plants"])

    print("Generating lodging data...")
    for group, lodgings in data["lodging_data"].items():
        if group not in data["groups"]:
            continue
        townname = data["group_to_townname"][group]
        max_lodging = 1 + lodging[townname] + max([int(k) for k in lodgings.keys()])
        data["lodging_data"][group]["max_ub"] = max_lodging
        data["lodging_data"][group]["lodging_bonus"] = lodging[townname]

    return data
