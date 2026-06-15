# generate_graph.data.py

from typing import Any

import rustworkx as rx
from bidict import bidict
from loguru import logger
from rustworkx import PyDiGraph

from bdo_empire.api_common import FARMING_WORKER_SILVER_PER_DAY_KEY
from bdo_empire.api_exploration_graph import get_all_pairs_path_lengths
from bdo_empire.api_rx_pydigraph import subgraph_stable


def prep_graph_nodes(solver_graph: PyDiGraph, data: dict[str, Any]) -> int | None:
    """Prepare a copy of the exploration graph for the HiGHS model."""
    logger.info("Preparing graph nodes...")

    super_root_index = setup_super_terminals(solver_graph, data)

    node_key_by_index = bidict({i: solver_graph[i]["waypoint_key"] for i in solver_graph.node_indices()})
    root_indices = [
        node_key_by_index.inv[t]
        for t in data["affiliated_town_region"].values()
        if data["exploration"][t]["is_worker_npc_town"]
    ]
    solver_graph.attrs = {"node_key_by_index": node_key_by_index, "root_indices": root_indices}

    logger.debug(f"Found {len(root_indices)} root indices:")
    logger.trace(f"(index, waypoint): {[(i, solver_graph[i]['waypoint_key']) for i in root_indices]}")

    setup_terminals(solver_graph, data)
    setup_roots(solver_graph, data)
    setup_node_transit_bounds(solver_graph, data, super_root_index)
    return super_root_index


def setup_super_terminals(solver_graph: PyDiGraph, data: dict[str, Any]) -> int | None:
    """Injects the superroot node into the graph"""
    # Super terminals require the super root for connection via any basetown.
    # Flow is _into_ super root with no flow out to prevent worker flow routing shortcuts
    super_root_index = None

    if data["force_active_node_ids"]:
        logger.info("  setting up super-terminals...")
        from bdo_empire.api_rx_pydigraph import inject_super_root

        for node in solver_graph.nodes():
            node["is_super_terminal"] = node["waypoint_key"] in data["force_active_node_ids"]

        node_key_by_index = bidict({i: solver_graph[i]["waypoint_key"] for i in solver_graph.node_indices()})
        solver_graph.attrs = {"node_key_by_index": node_key_by_index}
        super_root_index = inject_super_root({}, solver_graph, flow_direction="inbound")
        solver_graph[super_root_index]["is_super_terminal"] = False
        solver_graph[super_root_index]["ub"] = len(data["force_active_node_ids"])

    return super_root_index


def setup_terminals(solver_graph: PyDiGraph, data: dict[str, Any]) -> list[int]:
    """Prepares terminals with top_n root values."""
    # The top_n root values per terminal retain their value and all others are set at zero value.
    top_n = data["config"]["top_n"]
    logger.info(f"  setting up plant zones with {top_n} highest valued base towns per plant...")

    node_key_by_index = solver_graph.attrs["node_key_by_index"]
    terminal_indices = []

    for i in solver_graph.node_indices():
        node = solver_graph[i]
        if not node["is_workerman_plantzone"]:
            continue

        terminal_indices.append(i)
        waypoint_key = node["waypoint_key"]

        prizes = data["plant_values"][waypoint_key]
        prizes = sorted(prizes.items(), key=lambda x: x[1]["value"], reverse=True)
        prizes = dict(prizes[:top_n])

        values = {}
        # NOTE: Prize keys are affiliated town regions not waypoint keys, so translate!
        for warehouse_key, prize_data in prizes.items():
            value = int(prize_data["value"])
            if value == 0:
                break
            root_key = data["affiliated_town_region"][warehouse_key]
            root_index = node_key_by_index.inv[root_key]
            values[root_index] = value
        node["prizes"] = values
        if not values:
            logger.warning(f"⚠️ No plantzone drop data for: {node['waypoint_key']}")

    town_to_region_map = {int(town): region for region, town in data["affiliated_town_region"].items()}
    for terminal_index in sorted(terminal_indices):
        node = solver_graph[terminal_index]
        prizes = node["prizes"]
        for root, prize in prizes.items():
            town = solver_graph[root]["waypoint_key"]
            region = town_to_region_map[int(town)]
            logger.trace(f"{node['waypoint_key']:>5} {region:>5} {town:>5} {prize:>5}")

    solver_graph.attrs["terminals"] = terminal_indices
    return terminal_indices


def setup_roots(solver_graph: PyDiGraph, data: dict[str, Any]):
    """Populate each root node with ub and capacity_cost using precomputed bounds_costs."""
    logger.info("  setting up root lodging costs from precomputed bounds_costs...")
    root_indices = solver_graph.attrs["root_indices"]

    for i in root_indices:
        node = solver_graph[i]
        region_key = node["region_key"]
        lodging = data["lodging_data"][region_key]

        # See generate_reference_data.get_region_lodging_bounds_costs for details
        bounds_costs = lodging["bounds_costs"]
        max_ub = lodging["max_ub"]

        # capacity_cost[cap] = cost for cap in 0..max_ub
        # We keep index 0 = 0 for the model's SOS1
        capacity_cost = [0] * (max_ub + 1)

        prev_cap = 0
        prev_cost = 0
        for cap, cost in bounds_costs:
            cap = min(cap, max_ub)
            # expand capacities to fill (prev_cap+1 .. cap) with this bound's cost
            for idx in range(prev_cap + 1, cap + 1):
                capacity_cost[idx] = cost
            prev_cap = cap
            prev_cost = cost

            if prev_cap >= max_ub:
                break

        # fill any remaining capacities up to max_ub with the last known cost
        for idx in range(prev_cap + 1, max_ub + 1):
            capacity_cost[idx] = prev_cost

        node["ub"] = max_ub
        node["capacity_cost"] = capacity_cost

        logger.debug(
            f"{node['waypoint_key']:>5} region_key: {region_key:>5} ub: {max_ub} costs: {capacity_cost}"
        )

    logger.info(f"  {len(root_indices)} root nodes set up.")


def setup_node_transit_bounds(solver_graph: PyDiGraph, data: dict[str, Any], super_root_index: int | None):
    # The upper bound on transit for any worker town in the nearest_n towns is the minimum of
    # the waypoint_ub and the towns maximum lodging capacity and is set during lodging setup.
    # The upper bound for all other worker towns is zero.
    # In the end a non-root node has _n entries and a root node has _n+1 entries
    nearest_n = data["config"]["nearest_n"]
    logger.info(f"  setting up intermediate nodes for the nearest {nearest_n} towns...")

    all_pairs_path_lengths = get_all_pairs_path_lengths(solver_graph)
    root_indices = solver_graph.attrs["root_indices"]

    root_transit_ub = {i: solver_graph[i]["ub"] for i in root_indices}
    if super_root_index is not None:
        root_transit_ub[super_root_index] = len(data["force_active_node_ids"])

    for i in solver_graph.node_indices():
        node = solver_graph[i]
        if i == super_root_index:
            # Super root does not carry transit for any other root.
            node["transit_bounds"] = {super_root_index: len(data["force_active_node_ids"])}
            continue

        nearest_roots = []
        nearest_n_lim = nearest_n
        for j in root_indices:
            if i == j:
                nearest_roots.append((j, 0))
                nearest_n_lim += 1
                continue
            pair = (i, j) if i < j else (j, i)
            nearest_roots.append((j, all_pairs_path_lengths[pair]))

        nearest_roots = sorted(nearest_roots, key=lambda x: x[1])
        nearest_roots = [i for i, _ in nearest_roots][:nearest_n_lim]

        transit_ubs = {r: root_transit_ub[r] for r in nearest_roots}
        node["transit_bounds"] = transit_ubs
        logger.trace(
            f"{solver_graph[i]['waypoint_key']:>5} { {solver_graph[i]['waypoint_key']: ub for i, ub in transit_ubs.items()} }"
        )


def reduce_bounds_via_transit_layer_pruning(G: PyDiGraph) -> None:
    """
    Limits transit upper bounds by performing Pruning on the root-specific subgraphs.
    This effectively eliminates dead-end branches in the potential flow network for each root.
    """
    logger.info("Reducing bounds via root-specific pruning (RSP)...")

    from bdo_empire.api_common import SUPER_ROOT

    # Setup protected nodes
    flow_roots = G.attrs["root_indices"].copy()
    protected_nodes = set(G.attrs["terminals"]) | set(flow_roots)
    for i in G.node_indices():
        if G[i].get("is_super_terminal", False):
            protected_nodes.add(i)
        if G[i]["waypoint_key"] == SUPER_ROOT:
            protected_nodes.add(i)

    # Remove root transit bounds from disconnected transit layer components
    for r in flow_roots:
        # node_map maps from subgraph node index to global graph node index
        subG, node_map = G.subgraph_with_nodemap([i for i in G.node_indices() if r in G[i]["transit_bounds"]])
        node_map = bidict(node_map)
        subg_r = node_map.inv[r]

        cc = rx.weakly_connected_components(subG)
        logger.trace(f"Found {len(cc)} transit layer components for root {G[r]['waypoint_key']}")
        for c in cc:
            if subg_r in c:
                continue
            logger.trace(f"  removing transit layer component: {[subG[i]['waypoint_key'] for i in c]}")
            for i in c:
                G[node_map[i]]["transit_bounds"].pop(r, None)

    # Isolate each root transit layer and prune "transit_bounds" leaf nodes
    for r in flow_roots:
        transit_nodes = {
            i
            for i in G.node_indices()
            if r in G[i].get("transit_bounds", {}) and G[i]["transit_bounds"][r] > 0
        }
        if not transit_nodes:
            continue
        orig_transit_node_count = len(transit_nodes)

        subG = subgraph_stable(transit_nodes, G)
        assert isinstance(subG, PyDiGraph)

        # Recursively remove leaf nodes from transit subgraph
        removed_transit_nodes = set()

        while removal_nodes := [
            v
            for v in transit_nodes
            if len(set(subG.predecessor_indices(v)) | set(subG.successor_indices(v))) == 1
            and v not in protected_nodes
        ]:
            # Debugging: Leaf identification
            for v in removal_nodes:
                neighbors = set(subG.predecessor_indices(v)) | set(subG.successor_indices(v))
                logger.trace(
                    f"Pruning: node {G[v]['waypoint_key']} (root {G[r]['waypoint_key']}) with neighbors: {[G[n]['waypoint_key'] for n in neighbors]} [protected: {v in protected_nodes}]"
                )
            subG.remove_nodes_from(removal_nodes)
            removed_transit_nodes.update(removal_nodes)
            transit_nodes -= set(removal_nodes)

        # Remove transit bounds from removed leaf nodes in the primary graph
        for i in removed_transit_nodes:
            G[i]["transit_bounds"].pop(r, None)

        if removed_transit_nodes:
            removed_count = len(removed_transit_nodes)
            logger.debug(
                f"  removed {removed_count} of {orig_transit_node_count} leaf nodes from root {r} transit layer..."
            )


def generate_graph_data(data: dict[str, Any]) -> dict[str, Any]:
    """Generate and return a GraphData Dict composing the LP empire data."""
    print("Generating graph data...")

    G = data["exploration_graph"].copy()
    super_root_index = prep_graph_nodes(G, data)

    # Per transit layer NTD1 leaf and unreachable node pruning
    reduce_bounds_via_transit_layer_pruning(G)

    if super_root_index is not None:
        # insert super root transit bounds to all remaining nodes
        ub = G[super_root_index].get("transit_bounds", {}).get(super_root_index, None)
        if ub is None:
            logger.error(f"Super root index {super_root_index} exists but is missing transit bounds!")
            raise ValueError
        for i in G.node_indices():
            if i == super_root_index:
                continue
            G[i]["transit_bounds"][super_root_index] = ub

    # Remove edges from terminals from predecessors since modelling is done via flow from terminals to roots
    terminal_indices = G.attrs["terminals"]
    for t in terminal_indices:
        preds = G.predecessor_indices(t)
        for p in preds:
            G.remove_edge(p, t)
            assert G.has_edge(t, p), f"Removed edge {p} -> {t} but terminal is not connected via {t} -> {p}!"

    G.attrs["farm_fence_keys"] = data["farm_fence_keys"]
    G.attrs["num_farm_fences"] = data["num_farm_fences"]
    G.attrs["farm_fence_value"] = data[FARMING_WORKER_SILVER_PER_DAY_KEY]

    num_roots = len(G.attrs["root_indices"])
    roots_count = sum(1 for i in G.node_indices() if G[i]["is_base_town"])
    logger.info(f"  Generated graph with {num_roots} roots and {roots_count} basetowns...")

    data["solver_graph"] = G
    return data
