# generate_value_data.py

from math import ceil
import bdo_empire.data_store as ds


def get_data_files(data: dict) -> None:
    data["plantzone"] = ds.read_json("plantzone.json")
    data["plantzone_drops"] = ds.read_json("plantzone_drops.json")
    data["worker_skills"] = ds.read_json("skills.json")
    data["worker_static"] = ds.read_json("worker_static.json")
    data["distances_tk2pzk"] = ds.read_json("distances_tk2pzk.json")


def isGiant(charkey: int, data: dict) -> bool:
    return data["worker_static"][str(charkey)]["species"] in [2, 4, 8]


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
    mspd_base = data["worker_static"][str(worker["charkey"])]["mspd"] / 100
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
    if dist == 9999999:
        return 0

    drop = data["plantzone_drops"][str(pzk)]
    luckyPart = price_bunch(drop["lucky"], data)
    unluckyValue = price_bunch(drop["unlucky"], data)
    luckyValue = unluckyValue + luckyPart
    unluckyValue_gi = price_bunch(drop["unlucky_gi"], data)
    luckyValue_gi = unluckyValue_gi + luckyPart

    rgk = data["plantzone"][str(pzk)]["regiongroup"]
    modifier = data["modifiers"].get(str(rgk), 0)
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
    town: str, plantzone: int, dist: float, worker: dict, skill_set: list, data: dict
) -> float:
    stats = worker_stats(worker, skill_set, data)
    priceDaily = profitPzTownStats(
        plantzone,
        town,
        dist,
        stats["wspd"],
        stats["mspd"],
        stats["luck"],
        isGiant(worker["charkey"], data),
        data,
    )
    return priceDaily


def makeMedianChar(charkey: int, data: dict) -> dict:
    stat = data["worker_static"][str(charkey)]
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
    }


def medianGoblin(tnk: int, data: dict) -> dict:
    if tnk == 1623:
        return makeMedianChar(8003, data)  # grana
    if tnk == 1604:
        return makeMedianChar(8003, data)  # owt
    if tnk == 1691:
        return makeMedianChar(8023, data)  # oddy
    if tnk == 1750:
        return makeMedianChar(8035, data)  # eilton
    if tnk == 1781:
        return makeMedianChar(8050, data)  # lotml
    if tnk == 1785:
        return makeMedianChar(8050, data)  # lotml
    if tnk == 1795:
        return makeMedianChar(8050, data)  # lotml
    if tnk == 1857:
        return makeMedianChar(8050, data)  # lotml2
    if tnk == 1858:
        return makeMedianChar(8050, data)  # lotml2
    if tnk == 1853:
        return makeMedianChar(8050, data)  # lotml2
    return makeMedianChar(7572, data)


def medianGiant(tnk: int, data: dict) -> dict:
    if tnk == 1623:
        return makeMedianChar(8006, data)  # grana
    if tnk == 1604:
        return makeMedianChar(8006, data)  # owt
    if tnk == 1691:
        return makeMedianChar(8027, data)  # oddy
    if tnk == 1750:
        return makeMedianChar(8039, data)  # eilton
    if tnk == 1781:
        return makeMedianChar(8058, data)  # lotml
    if tnk == 1785:
        return makeMedianChar(8058, data)  # lotml
    if tnk == 1795:
        return makeMedianChar(8058, data)  # lotml
    if tnk == 1857:
        return makeMedianChar(8058, data)  # lotml2
    if tnk == 1858:
        return makeMedianChar(8058, data)  # lotml2
    if tnk == 1853:
        return makeMedianChar(8058, data)  # lotml2
    return makeMedianChar(7571, data)


def medianHuman(tnk: int, data: dict) -> dict:
    if tnk == 1623:
        return makeMedianChar(8009, data)  # grana
    if tnk == 1604:
        return makeMedianChar(8009, data)  # owt
    if tnk == 1691:
        return makeMedianChar(8031, data)  # oddy
    if tnk == 1750:
        return makeMedianChar(8043, data)  # eilton
    if tnk == 1781:
        return makeMedianChar(8054, data)  # lotml
    if tnk == 1785:
        return makeMedianChar(8054, data)  # lotml
    if tnk == 1795:
        return makeMedianChar(8054, data)  # lotml
    if tnk == 1857:
        return makeMedianChar(8054, data)  # lotml2
    if tnk == 1858:
        return makeMedianChar(8054, data)  # lotml2
    if tnk == 1853:
        return makeMedianChar(8054, data)  # lotml2
    return makeMedianChar(7573, data)


def optimize_skills(town: str, plantzone: int, dist: float, worker: dict, data: dict):
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
        new_profit = profit(town, plantzone, dist, worker, temp_skills, data)
        w_bonuses[i] = {"skills": temp_skills, "profit": new_profit}

        if all(not data["worker_skills"][sk].get("mspd", 0) for sk in temp_skills):
            mod_skills = temp_skills.copy()
            wm_skills = [ss for ss in w_skills if ss["mspd"] > 0]
            if wm_skills:
                mod_skills[-1] = wm_skills[0]["key"]
                mod_profit = profit(town, plantzone, dist, worker, mod_skills, data)
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
            new_profit = profit(town, plantzone, dist, worker, temp_skills, data)
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


def generate_value_data(prices: dict, modifiers: dict) -> None:
    data = {}
    get_data_files(data)
    data["market_value"] = prices
    data["modifiers"] = modifiers

    # Workerman sorts by nearest node to town.
    for town in data["distances_tk2pzk"]:
        data["distances_tk2pzk"][town] = sorted(data["distances_tk2pzk"][town], key=lambda x: x[0])

    output = {}
    for town in data["distances_tk2pzk"].keys():
        if town in ["1375"]:
            continue

        median_workers = {
            "giant": medianGiant(town, data),
            "goblin": medianGoblin(town, data),
            "human": medianHuman(town, data),
        }

        for dist_data in data["distances_tk2pzk"][town]:
            plantzone, dist = dist_data
            if not data["plantzone"][str(plantzone)]["node"]["is_plantzone"]:
                continue
            if data["plantzone"][str(plantzone)]["node"]["kind"] in [12, 13]:
                continue

            optimized_workers = {
                "giant": optimize_skills(town, plantzone, dist, median_workers["giant"], data),
                "goblin": optimize_skills(town, plantzone, dist, median_workers["goblin"], data),
                "human": optimize_skills(town, plantzone, dist, median_workers["human"], data),
            }
            optimized_worker = max(optimized_workers.items(), key=lambda item: item[1]["profit"])

            if str(plantzone) not in output:
                output[str(plantzone)] = {}
            output[str(plantzone)][str(town)] = {}
            output[str(plantzone)][str(town)]["worker"] = optimized_worker[0]
            output[str(plantzone)][str(town)]["value"] = optimized_worker[1]["profit"]
            output[str(plantzone)][str(town)]["worker_data"] = median_workers[
                optimized_worker[0]
            ].copy()
            output[str(plantzone)][str(town)]["worker_data"]["skills"] = [
                int(s) for s in optimized_worker[1]["skills"].copy()
            ]

    # Make the list a plantzone keyed list sorted by value in descending order for 'top_n'
    for plantzone, warehouse_data in output.copy().items():
        output[plantzone] = dict(
            sorted(warehouse_data.items(), key=lambda x: x[1]["value"], reverse=True)
        )

    ds.write_json("node_values_per_town.json", output)
