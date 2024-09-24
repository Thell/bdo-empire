"""Empire Node Value Generation
Generate the workers and skillsets to maximize node valuations per town.
"""

import json
from math import ceil
from os import path


def isGiant(charkey, data):
    return data["worker_static"][str(charkey)]["species"] in [2, 4, 8]


def skill_bonus(skill_set, data):
    bonus = {"wspd": 0, "mspd": 0, "luck": 0}
    for sk in skill_set:
        skill_bonuses = data["worker_skills"].get(sk, {})
        bonus["wspd"] += skill_bonuses.get("wspd", 0)
        bonus["wspd"] += skill_bonuses.get("wspd_farm", 0)
        bonus["mspd"] += skill_bonuses.get("mspd", 0)
        bonus["luck"] += skill_bonuses.get("luck", 0)
    return bonus


def worker_stats(worker, skill_set, data):
    bonus = skill_bonus(skill_set, data)
    wspd = worker["wspd"] + bonus["wspd"]
    mspd_base = data["worker_static"][str(worker["charkey"])]["mspd"] / 100
    mspd = mspd_base * ((worker["mspd"] / mspd_base) + bonus["mspd"] / 100)
    luck = worker["luck"] + bonus["luck"]
    return {"wspd": wspd, "mspd": mspd, "luck": luck}


def calcCyclesDaily(baseWorkload, wspd, dist, mspd, modifier):
    # const activeWorkload = baseWorkload * (2 - this.productivity(rgk))
    # const workMinutes = Math.ceil(activeWorkload / wspd)
    # const cycleMinutes = 10 * workMinutes + moveMinutes
    # ret = 24 * 60 / cycleMinutes
    moveMinutes = 2 * dist / mspd / 60
    activeWorkload = baseWorkload * (2 - modifier / 100)
    workMinutes = ceil(activeWorkload / wspd)
    cycleMinutes = 10 * workMinutes + moveMinutes
    return 24 * 60 / cycleMinutes


def price_bunch(bunch, data):
    return sum(data["market_value"][k] * q for k, q in bunch.items())


def price_pzd(pzd, luck, data):
    unlucky_price = price_bunch(pzd.get("unlucky", {}), data)
    if "lucky" in pzd:
        lucky_price = price_bunch(pzd["lucky"], data)
        return (luck / 100) * lucky_price + (1 - luck / 100) * unlucky_price
    return unlucky_price


def price_lerp(lucky_price, unlucky_price, luck):
    if lucky_price is None:
        return unlucky_price
    return (luck / 100) * lucky_price + (1 - luck / 100) * unlucky_price


def profitPzTownStats(pzk, tnk, dist, wspd, mspd, luck, is_giant, data):
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


def profit(town, plantzone, dist, worker, skill_set, data):
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


def makeMedianChar(charkey, data):
    ret = {}
    stat = data["worker_static"][str(charkey)]
    pa_wspd = stat["wspd"]
    pa_mspdBonus = 0
    pa_luck = stat["luck"]

    for i in range(2, 41):
        pa_wspd += (stat["wspd_lo"] + stat["wspd_hi"]) / 2
        pa_mspdBonus += (stat["mspd_lo"] + stat["mspd_hi"]) / 2
        pa_luck += (stat["luck_lo"] + stat["luck_hi"]) / 2

    pa_mspd = stat["mspd"] * (1 + pa_mspdBonus / 1e6)

    ret["wspd"] = round(pa_wspd / 1e6 * 100) / 100
    ret["mspd"] = round(pa_mspd) / 100
    ret["luck"] = round(pa_luck / 1e4 * 100) / 100
    ret["charkey"] = charkey
    ret["isGiant"] = isGiant(charkey, data)

    return ret


def medianGoblin(tnk, data):
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
    return makeMedianChar(7572, data)


def medianGiant(tnk, data):
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
    return makeMedianChar(7571, data)


def medianHuman(tnk, data):
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
    return makeMedianChar(7573, data)


def optimize_skills(town, plantzone, dist, worker, data):
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


def generate_value_data(datapath, prices, modifiers):
    data = {}
    data["market_value"] = prices
    data["modifiers"] = modifiers

    with open(path.join(datapath, "plantzone.json")) as datafile:
        data["plantzone"] = json.load(datafile)
    with open(path.join(datapath, "plantzone_drops.json")) as datafile:
        data["plantzone_drops"] = json.load(datafile)
    with open(path.join(datapath, "skills.json")) as datafile:
        data["worker_skills"] = json.load(datafile)
    with open(path.join(datapath, "worker_static.json")) as datafile:
        data["worker_static"] = json.load(datafile)
    with open(path.join(datapath, "distances_tk2pzk.json")) as datafile:
        data["distances_tk2pzk"] = json.load(datafile)

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

    for plantzone, warehouse_data in output.copy().items():
        output[plantzone] = dict(
            sorted(warehouse_data.items(), key=lambda x: x[1]["value"], reverse=True)
        )

    with open(path.join(datapath, "node_values_per_town.json"), "w") as file:
        json.dump(output, file, indent=4)

    return True
