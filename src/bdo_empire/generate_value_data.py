# generate_value_data.py

from math import ceil
import bdo_empire.data_store as ds


def string_keys_to_ints(d):
    new_dict = {}
    for key, value in d.items():
        if isinstance(key, str) and key.isdigit():
            key = int(key)
        if isinstance(value, dict):
            value = string_keys_to_ints(value)
        new_dict[key] = value
    return dict(list(new_dict.items()))


def get_data_files(data: dict, prices: dict, modifiers: dict) -> dict:
    value_data = data.copy()
    value_data["market_value"] = string_keys_to_ints(prices)
    value_data["modifiers"] = string_keys_to_ints(modifiers)
    value_data["distances_tk2pzk"] = string_keys_to_ints(ds.read_json("distances_tk2pzk.json"))
    value_data["plantzone_drops"] = string_keys_to_ints(ds.read_json("plantzone_drops.json"))
    value_data["worker_skills"] = string_keys_to_ints(ds.read_json("skills.json"))
    value_data["worker_static"] = string_keys_to_ints(ds.read_json("worker_static.json"))
    return value_data


def isGiant(charkey: int, data: dict) -> bool:
    return data["worker_static"][charkey]["species"] in [2, 4, 8]


def skill_bonus(skill_set: list, data: dict) -> dict:
    bonus = {"wspd": 0, "mspd": 0, "luck": 0}
    for sk in skill_set:
        skill_bonuses = data["worker_skills"].get(sk, {})
        bonus["wspd"] += skill_bonuses.get("wspd", 0)
        bonus["wspd"] += skill_bonuses.get("wspd_farm", 0)
        bonus["mspd"] += skill_bonuses.get("mspd", 0)
        bonus["luck"] += skill_bonuses.get("luck", 0)
    return bonus


def worker_stats(worker: dict, skill_set, data: dict) -> dict:
    bonus = skill_bonus(skill_set, data)
    wspd = worker["wspd"] + bonus["wspd"]
    mspd_base = data["worker_static"][worker["charkey"]]["mspd"] / 100
    mspd = mspd_base * ((worker["mspd"] / mspd_base) + bonus["mspd"] / 100)
    luck = worker["luck"] + bonus["luck"]
    return {"wspd": wspd, "mspd": mspd, "luck": luck}


def calcCyclesDaily(
    baseWorkload: float, wspd: float, dist: float, mspd: float, modifier: float
) -> float:
    moveMinutes = 2 * dist / mspd / 60
    activeWorkload = baseWorkload * (2 - modifier / 100)
    workMinutes = ceil(activeWorkload / wspd)
    cycleMinutes = 10 * workMinutes + moveMinutes
    return 24 * 60 / cycleMinutes


def price_bunch(bunch: dict, data: dict) -> float:
    return sum(data["market_value"][k] * q for k, q in bunch.items())


def price_pzd(pzd: dict, luck: float, data: dict) -> float:
    unlucky_price = price_bunch(pzd.get("unlucky", {}), data)
    if "lucky" in pzd:
        lucky_price = price_bunch(pzd["lucky"], data)
        return (luck / 100) * lucky_price + (1 - luck / 100) * unlucky_price
    return unlucky_price


def price_lerp(lucky_price: float, unlucky_price: float, luck: float) -> float:
    return (luck / 100) * lucky_price + (1 - luck / 100) * unlucky_price


def profitPzTownStats(
    pzk: int, _tnk, dist: float, wspd: float, mspd: float, luck: float, is_giant: bool, data: dict
) -> float:
    drop = data["plantzone_drops"][pzk]
    luckyPart = price_bunch(drop["lucky"], data)
    unluckyValue = price_bunch(drop["unlucky"], data)
    luckyValue = unluckyValue + luckyPart
    unluckyValue_gi = price_bunch(drop["unlucky_gi"], data)
    luckyValue_gi = unluckyValue_gi + luckyPart

    rgk = data["exploration"][pzk]["region_group_key"]
    modifier = data["modifiers"].get(rgk, 0)
    if modifier == "":
        modifier = 0

    cycleValue = (
        price_lerp(luckyValue_gi, unluckyValue_gi, luck)
        if is_giant
        else price_lerp(luckyValue, unluckyValue, luck)
    )
    cyclesDaily = calcCyclesDaily(drop["workload"], wspd, dist, mspd, modifier)
    priceDaily = cyclesDaily * cycleValue
    return priceDaily


def profit(
    region: int, plantzone: int, dist: float, worker: dict, skill_set: list, data: dict
) -> float:
    stats = worker_stats(worker, skill_set, data)
    priceDaily = profitPzTownStats(
        plantzone,
        region,
        dist,
        stats["wspd"],
        stats["mspd"],
        stats["luck"],
        isGiant(worker["charkey"], data),
        data,
    )
    return priceDaily


def optimize_skills(region: int, plantzone: int, dist: float, worker: dict, data: dict):
    max_skills = 9
    w_bonuses = {0: {"skills": [], "profit": 0}}
    w_actions = ["wspd"]
    w_actions.append("wspd_farm")

    w_skills = []
    for key, skill in data["worker_skills"].items():
        if any(act in skill for act in w_actions):
            w_skills.append(
                {
                    "key": key,
                    "amount": skill.get("wspd", 0) + skill.get("wspd_farm", 0),
                    "mspd": skill.get("mspd", 0),
                }
            )

    w_skills.sort(key=lambda x: (x["amount"], x["mspd"]), reverse=True)

    for i in range(1, max_skills + 1):
        temp_skills = [w["key"] for w in w_skills[:i]]
        new_profit = profit(region, plantzone, dist, worker, temp_skills, data)
        w_bonuses[i] = {"skills": temp_skills, "profit": new_profit}

        if all(not data["worker_skills"][sk].get("mspd", 0) for sk in temp_skills):
            mod_skills = temp_skills.copy()
            wm_skills = [ss for ss in w_skills if ss["mspd"] > 0]
            if wm_skills:
                mod_skills[-1] = wm_skills[0]["key"]
                mod_profit = profit(region, plantzone, dist, worker, mod_skills, data)
                if mod_profit > new_profit:
                    w_bonuses[i] = {"skills": mod_skills, "profit": mod_profit}

    ml_actions = ["mspd", "luck"]
    ml_skills = {
        key
        for key, skill in data["worker_skills"].items()
        if any(act in skill for act in ml_actions)
    }

    step_results = [w_bonuses[max_skills]]
    ml_best_skills = []
    for i in range(1, max_skills + 1):
        step_base_skills = w_bonuses[max_skills - i]["skills"] + ml_best_skills
        step_candidates = []

        for sk in ml_skills:
            if sk in w_bonuses[max_skills - i]["skills"]:
                continue
            temp_skills = step_base_skills + [sk]
            new_profit = profit(region, plantzone, dist, worker, temp_skills, data)
            step_candidates.append({"sk": sk, "profit": new_profit})

        if step_candidates:
            step_candidates.sort(key=lambda x: x["profit"], reverse=True)
            step_best_skill = step_candidates[0]["sk"]
            step_skills = step_base_skills + [step_best_skill]
            step_results.append({"skills": step_skills, "profit": step_candidates[0]["profit"]})
            ml_best_skills.append(step_best_skill)
            ml_skills.remove(step_best_skill)
        else:
            ml_best_skills.append(0)

    step_results.sort(key=lambda x: x["profit"], reverse=True)
    return step_results[0]


def makeMedianChar(charkey: int, data: dict) -> dict:
    stat = data["worker_static"][charkey]
    pa_wspd = stat["wspd"]
    pa_mspdBonus = 0
    pa_luck = stat["luck"]

    for _ in range(2, 41):
        pa_wspd += (stat["wspd_lo"] + stat["wspd_hi"]) / 2
        pa_mspdBonus += (stat["mspd_lo"] + stat["mspd_hi"]) / 2
        pa_luck += (stat["luck_lo"] + stat["luck_hi"]) / 2
    pa_mspd = stat["mspd"] * (1 + pa_mspdBonus / 1e6)

    return {
        "wspd": round(pa_wspd / 1e6 * 100) / 100,
        "mspd": round(pa_mspd) / 100,
        "luck": round(pa_luck / 1e4 * 100) / 100,
        "charkey": charkey,
        "isGiant": isGiant(charkey, data),
        "worker_type": stat["species"],
    }


def get_all_region_workers(data):
    region_workers = string_keys_to_ints(ds.read_json("region_workers.json"))
    for region, worker_types in region_workers.items():
        for worker_type, char_key in worker_types.items():
            region_workers[region][worker_type] = makeMedianChar(char_key, data)
    return region_workers


def generate_value_data(prices: dict, modifiers: dict, ref_data: dict) -> None:
    import multiprocessing as mp

    data = get_data_files(ref_data, prices, modifiers)
    region_workers = get_all_region_workers(data)

    tasks = []
    for region_key, town_key in data["affiliated_town_region"].items():
        affiliated_town = data["exploration"][town_key]
        if not affiliated_town["is_worker_npc_town"]:
            continue

        region_worker_types = set(affiliated_town["worker_types"])

        for plantzone_key, distance in data["distances_tk2pzk"][region_key]:
            plantzone = data["exploration"][plantzone_key]
            if not plantzone["is_workerman_plantzone"]:
                continue

            allowed_workers = region_worker_types.intersection(plantzone["worker_types"])
            if workers := {t: region_workers[region_key][t] for t in allowed_workers}:
                tasks.append((region_key, plantzone_key, distance, workers, data))

    with mp.Pool(mp.cpu_count()) as pool:
        results = pool.starmap(optimize_worker, tasks)

    # Reshape output to plantzone keyed dict sorted by value in descending order for 'top_n'.
    output = {}
    for plantzone, region, result_data in results:
        if plantzone not in output:
            output[plantzone] = {}
        output[plantzone][region] = result_data

    for plantzone, region_data in output.copy().items():
        output[plantzone] = dict(
            sorted(region_data.items(), key=lambda x: x[1]["value"], reverse=True)
        )

    ds.write_json("node_values_per_town.json", output)


def optimize_worker(region, plantzone, dist, median_workers, data):
    optimized_workers = {
        worker: optimize_skills(region, plantzone, dist, worker_data, data)
        for worker, worker_data in median_workers.items()
    }
    optimized_worker = max(optimized_workers.items(), key=lambda item: item[1]["profit"])

    result_data = {
        "worker": optimized_worker[0],
        "value": optimized_worker[1]["profit"],
        "worker_data": median_workers[optimized_worker[0]].copy(),
    }
    result_data["worker_data"]["skills"] = [int(s) for s in optimized_worker[1]["skills"].copy()]

    return (plantzone, region, result_data)
