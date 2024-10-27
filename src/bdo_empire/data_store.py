# data_store.py

import importlib.resources
import json
from pathlib import Path
from urllib import request


def path() -> Path:
    with importlib.resources.as_file(importlib.resources.files().joinpath("data")) as path:
        return path


def is_file(filename: str) -> bool:
    return path().joinpath(filename).is_file()


def read_text(filename: str) -> str:
    return path().joinpath(filename).read_text(encoding="utf-8")


def read_strings_csv(filename: str) -> dict:
    import csv

    filepath = path().joinpath(filename)
    with open(filepath, "r", encoding="UTF-8") as f:
        records = {int(entry["Param0"]): entry["String"] for entry in csv.DictReader(f)}
    return records


def read_json(filename: str) -> dict:
    content = read_text(filename)
    return json.loads(content)


def write_json(filename: str, data: dict | str) -> None:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            raise ValueError("Data is a string but not valid JSON")
    with path().joinpath(filename).open("w", encoding="utf-8") as data_file:
        json.dump(data, data_file, indent=4)


def request_content(url: str) -> str:
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


def download_json(filename: str) -> None:
    url = "https://raw.githubusercontent.com/shrddr/workermanjs/refs/heads/main/data"
    if filename in ["plantzone_drops.json", "skills.json"]:
        url = f"{url}/manual/{filename}"
    else:
        url = f"{url}/{filename}"
    content = request_content(url)
    write_json(filename, content)


def download_sha() -> str:
    url = "https://api.github.com/repos/shrddr/workermanjs/branches/main"
    content = request_content(url)
    json_data = json.loads(content)
    return json_data["commit"]["sha"]


def initialized(last_sha: str, filenames: list[str]) -> bool:
    filename = "git_commit.txt"
    current_sha = read_text(filename) if is_file(filename) else None
    return last_sha == current_sha and all(is_file(f) for f in filenames)
