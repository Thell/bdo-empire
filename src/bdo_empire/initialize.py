# initialize.py

import json
import bdo_empire.data_store as ds


workerman_data_filenames = [
    # Used for node value generation
    "distances_tk2pzk.json",
    "plantzone.json",
    "plantzone_drops.json",
    "skills.json",
    "worker_static.json",
    # Used for empire data generation
    "all_lodging_storage.json",
    "deck_links.json",
    "exploration.json",
    "plantzone.json",
]

local_data_filenames = [
    # Used for empire data generation
    "town_node_translate.json",
    "townnames.json",
    "warehouse_to_townname.json",
]


def extract_tk2tnk_from_js() -> None:
    import re

    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/src/stores/game.js"
    js_content = ds.request_content(url)

    # re to match the _tk2tnk dictionary
    dict_pattern = re.compile(r"this\._tk2tnk\s*=\s*{([^}]*)}", re.DOTALL)
    match = dict_pattern.search(js_content)
    # Since shrddr's comment in game.js indicates reading this from the bss in the future...
    if not match:
        raise ValueError("tk2tnk dictionary not found, check the game.js source file!")

    dict_content = match.group(1).strip()
    pair_pattern = re.compile(r"(\d+)\s*:\s*(\d+)")
    tk2tnk_dict = {}
    for line in dict_content.splitlines():
        pair_match = pair_pattern.search(line)
        if pair_match:
            key, value = int(pair_match.group(1)), int(pair_match.group(2))
            tk2tnk_dict[key] = str(value)
    tnk2tk_dict = {v: str(k) for k, v in tk2tnk_dict.items()}

    json_data = {"tk2tnk": tk2tnk_dict, "tnk2tk": tnk2tk_dict}
    ds.write_json("town_node_translate.json", json_data)


def extract_town_names() -> dict:
    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/data/loc.json"
    json_content = ds.request_content(url)
    json_data = json.loads(json_content)
    json_data = json_data["en"]["town"]
    ds.write_json("warehouse_to_townname.json", json_data)
    return json_data


def generate_warehouse_to_town_names(town_names: dict) -> None:
    translator = ds.read_json("town_node_translate.json")
    json_data = {translator["tk2tnk"][k]: v for k, v in town_names.items()}
    ds.write_json("townnames.json", json_data)


def initialize_workerman_data(last_sha: str) -> None:
    for filename in workerman_data_filenames:
        print(f"Getting `{filename}`...", end="")
        ds.download_json(filename)
        print("complete.")

    print("Generating `town_node_translate.json`...", end="")
    extract_tk2tnk_from_js()
    print("complete.")

    print("Extracting town name list...", end="")
    town_names = extract_town_names()
    print("complete.")

    print("Generating warehouse to town name list...", end="")
    generate_warehouse_to_town_names(town_names)
    print("complete.")

    ds.path().joinpath("git_commit.txt").write_text(last_sha)


def initialize_data() -> None:
    # Any error in initialization is fatal and is raised via urllib.
    print("Checking data files...")
    last_sha = ds.download_sha()
    if not ds.initialized(last_sha, workerman_data_filenames + local_data_filenames):
        initialize_workerman_data(last_sha)
    print("Initialized...")
