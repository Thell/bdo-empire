# initialize.py

import importlib.resources
import json
from urllib import request

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


def get_data_dir():
    with importlib.resources.as_file(
        importlib.resources.files("initialize").joinpath("data")
    ) as data_dir:
        return data_dir


def is_data_file(filename):
    return get_data_dir().joinpath(filename).is_file()


def request_content(url):
    import certifi
    import ssl

    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with request.urlopen(url, context=context) as response:
            content = response.read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching content: {e}")
        raise
    return content


def request_json_data_file(url, filename):
    content = request_content(url)
    write_json_data_file(filename, content)


def write_json_data_file(filename, data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            raise ValueError("Data is a string but not valid JSON")
    with get_data_dir().joinpath(filename).open("w", encoding="utf-8") as data_file:
        json.dump(data, data_file, indent=4)


def download_json_file(filename):
    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/data"
    if filename in ["plantzone_drops.json", "skills.json"]:
        url = f"{url}/manual/{filename}"
    else:
        url = f"{url}/{filename}"
    request_json_data_file(url, filename)


def get_last_commit_hash():
    url = "https://api.github.com/repos/shrddr/workermanjs/branches/main"
    content = request_content(url)
    json_data = json.loads(content)
    return json_data["commit"]["sha"]


def extract_tk2tnk_from_js():
    import re

    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/src/stores/game.js"
    js_content = request_content(url)

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
    write_json_data_file("town_node_translate.json", json_data)


def extract_town_names():
    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/data/loc.json"
    json_content = request_content(url)
    json_data = json.loads(json_content)
    json_data = json_data["en"]["town"]
    write_json_data_file("warehouse_to_townname.json", json_data)
    return json_data


def generate_warehouse_to_town_names(town_names):
    with open(get_data_dir().joinpath("town_node_translate.json"), "r") as data_file:
        translator = json.load(data_file)
    json_data = {translator["tk2tnk"][k]: v for k, v in town_names.items()}
    write_json_data_file("townnames.json", json_data)


def initialize_workerman_data(last_sha):
    for filename in workerman_data_filenames:
        print(f"Getting `{filename}`...", end="")
        download_json_file(filename)
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

    get_data_dir().joinpath("git_commit.txt").write_text(last_sha)


def initialize():
    # Any error in initialization is fatal and is raised via urllib.

    print("Checking data files...")

    filename = "git_commit.txt"
    last_sha = get_last_commit_hash()
    current_sha = get_data_dir().joinpath(filename).read_text() if is_data_file(filename) else None
    all_data_filenames = workerman_data_filenames + local_data_filenames

    if last_sha != current_sha or not all(is_data_file(f) for f in all_data_filenames):
        initialize_workerman_data(last_sha)

    print("Initialized...")
    return True
