# initialize_workerman_data.py

import json
from os import makedirs, path
from urllib import error, request


def download_json_file(filename, outpath):
    outpath = path.join(outpath, f"{filename}")
    if filename in ["plantzone_drops.json", "skills.json"]:
        filename = f"manual/{filename}"
    raw_url = f"https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/data/{filename}"

    try:
        request.urlretrieve(raw_url, outpath)
    except error.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        return False
    except Exception as err:
        print(f"An error occurred: {err}")
        return False
    return True


def get_last_commit_hash():
    import certifi
    import ssl

    context = ssl.create_default_context(cafile=certifi.where())
    url = "https://api.github.com/repos/shrddr/workermanjs/branches/main"
    with request.urlopen(url, context=context) as response:
        data = json.load(response)
        return data["commit"]["sha"]


def extract_tk2tnk_from_js(outpath):
    import json
    import re

    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/src/stores/game.js"
    try:
        with request.urlopen(url) as response:
            js_content = response.read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching the file: {e}")
        return False

    # re to match the _tk2tnk dictionary
    dict_pattern = re.compile(r"this\._tk2tnk\s*=\s*{([^}]*)}", re.DOTALL)
    match = dict_pattern.search(js_content)
    # Since shrddr's comments in the source indicating reading this from the bss in the future...
    if not match:
        print("Dictionary not found, check the source file!")
        return False

    dict_content = match.group(1).strip()
    pair_pattern = re.compile(r"(\d+)\s*:\s*(\d+)")
    tk2tnk_dict = {}
    for line in dict_content.splitlines():
        pair_match = pair_pattern.search(line)
        if pair_match:
            key, value = int(pair_match.group(1)), int(pair_match.group(2))
            tk2tnk_dict[key] = str(value)
    tnk2tk_dict = {v: str(k) for k, v in tk2tnk_dict.items()}

    out_dict = {"tk2tnk": tk2tnk_dict, "tnk2tk": tnk2tk_dict}
    outpath = path.join(outpath, "town_node_translate.json")
    with open(outpath, "w") as json_file:
        json.dump(out_dict, json_file, indent=4)

    return True


def extract_town_names(outpath):
    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/data/loc.json"
    try:
        with request.urlopen(url) as response:
            content = response.read().decode("utf-8")
            json_data = json.loads(content)
    except Exception as e:
        print(f"Error fetching the file: {e}")
        return False

    json_data = json_data["en"]["town"]
    outpath = path.join(outpath, "warehouse_to_townname.json")
    with open(outpath, "w") as json_file:
        json.dump(json_data, json_file, indent=4)

    return json_data


def generate_warehouse_to_town_names(filepath, town_names):
    with open(f"{filepath}/town_node_translate.json", "r") as f:
        translator = json.load(f)

    out_dict = {}
    for k, v in town_names.items():
        out_dict[translator["tk2tnk"][k]] = v

    outpath = path.join(filepath, "townnames.json")
    with open(outpath, "w") as json_file:
        json.dump(out_dict, json_file, indent=4)


def initialize_workerman_data(filepath, last_sha):
    makedirs(filepath, exist_ok=True)

    filelist = [
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
    for filename in filelist:
        print(f"Getting `{filename}`...", end="")
        if download_json_file(filename, filepath):
            print("complete.")
        else:
            print("failed.")
            return False

    print("Generating `town_node_translate.json`...", end="")
    if extract_tk2tnk_from_js(filepath):
        print("complete.")
    else:
        print("failed.")
        return False

    print("Extracting town name list...", end="")
    town_names = extract_town_names(filepath)
    if town_names:
        print("complete.")
    else:
        print("failed.")
        return False

    print("Generating warehouse to town name list...", end="")
    generate_warehouse_to_town_names(filepath, town_names)
    print("complete.")

    with open(path.join(filepath, "git_commit.txt"), "w") as file:
        file.write(last_sha)

    return True


def initialize():
    filepath = path.join(path.dirname(__file__), "data")
    filenames = [
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
        "town_node_translate.json",
        "townnames.json",
        "warehouse_to_townname.json",
    ]

    print(f"Checking workerman data files in {filepath}...")

    last_sha = get_last_commit_hash()
    filename = path.join(filepath, "git_commit.txt")

    if not path.isfile(filename):
        print(filename, "does not exist.")
        initialized = initialize_workerman_data(filepath, last_sha)
    else:
        with open(filename, "r") as file:
            current_sha = file.read()
        initialized = current_sha == last_sha
        if not initialized:
            print("Updating workerman data files...")
            initialized = initialize_workerman_data(filepath, last_sha)

    if initialized and not all([path.isfile(path.join(filepath, f)) for f in filenames]):
        print("All required data files do not exist yet. Downloading...")
        initialized = initialize_workerman_data(filepath, last_sha)

    print("Initialized?", initialized)
    return initialized
