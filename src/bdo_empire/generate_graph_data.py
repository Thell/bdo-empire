# generate_graph.data.py

from __future__ import annotations
from enum import IntEnum, auto
from typing import Any, Dict, List, TypedDict

import networkx as nx


class GraphData(TypedDict):
    V: Dict[str, Node]  # All Nodes
    E: Dict[tuple[str, str], Arc]  # All Arcs
    F: Dict[str, Node]  # Force Active Nodes
    R: Dict[str, Node]  # Region Nodes
    L: Dict[str, Node]  # Lodging Nodes
    P: Dict[str, Node]  # Plant Nodes


class NodeType(IntEnum):
    𝓢 = auto()
    plant = auto()
    waypoint = auto()
    town = auto()
    region = auto()
    lodging = auto()
    𝓣 = auto()

    INVALID = auto()

    def __repr__(self):
        return self.name


class Node:
    def __init__(
        self,
        id: str,
        type: NodeType,
        ub: int,
        lb: int = 0,
        cost: int = 0,
        regions: List[Node] = [],
    ):
        self.id = id
        self.type = type
        self.ub = ub
        self.lb = lb
        self.cost = cost
        self.region_prizes: Dict[str, Dict[str, Any]] = {}
        self.regions = regions if regions else []
        self.key = self.name()
        self.inbound_arcs: List[Arc] = []
        self.outbound_arcs: List[Arc] = []
        self.vars = {}
        self.isPlant = type == NodeType.plant
        self.isLodging = type == NodeType.lodging
        self.isTown = type == NodeType.town
        self.isWaypoint = type == NodeType.waypoint
        self.isRegion = type == NodeType.region
        self.isForceActive = False

    def name(self) -> str:
        if self.type in [NodeType.𝓢, NodeType.𝓣]:
            return self.id
        return f"{self.type.name}_{self.id}"

    def inSolution(self):
        x_var = self.vars.get("x", None)
        if x_var is not None:
            return x_var.varValue is not None and round(x_var.varValue) >= 1
        else:
            return False

    def as_dict(self) -> Dict[str, Any]:
        obj_dict = {
            "key": self.name(),
            "name": self.name(),
            "id": self.id,
            "type": self.type.name.lower(),
            "ub": self.ub,
            "lb": self.ub,
            "cost": self.cost,
            "region_prizes": self.region_prizes,
            "regions": [],
            "inbound_arcs": [arc.key for arc in self.inbound_arcs],
            "outbound_arcs": [arc.key for arc in self.outbound_arcs],
            "vars": {},
        }
        for node in self.regions:
            if node is self:
                obj_dict["regions"].append("self")
            else:
                obj_dict["regions"].append(node.name())
        for k, v in self.vars.items():
            obj_dict["vars"][k] = v.to_dict()
        return obj_dict

    def __repr__(self) -> str:
        return f"Node(name: {self.name()}, ub: {self.ub}, lb: {self.lb}, cost: {self.cost}, value: {self.region_prizes})"

    def __eq__(self, other) -> bool:
        return self.name() == other.name()

    def __hash__(self) -> int:
        return hash((self.name()))


class Arc:
    def __init__(self, source: Node, destination: Node, ub: int, cost: int = 0):
        self.source = source
        self.destination = destination
        self.ub = ub
        self.cost = cost
        self.key = (source.name(), destination.name())
        self.type = (source.type, destination.type)
        self.vars = {}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name(),
            "ub": self.ub,
            "type": self.type,
            "source": self.source.name(),
            "destination": self.destination.name(),
            "vars": {k: v.to_dict() for k, v in self.vars.items() if round(v.varValue) > 0},
        }

    def inSolution(self) -> bool:
        return self.source.inSolution() and self.destination.inSolution()

    def name(self) -> str:
        return f"{self.source.name()}_to_{self.destination.name()}"

    def __repr__(self) -> str:
        return f"arc({self.source.name()} -> {self.destination.name()}, ub: {self.ub})"

    def __eq__(self, other) -> bool:
        return (self.source, self.destination) == (other.source, other.destination)

    def __hash__(self) -> int:
        return hash((self.source.name() + self.destination.name()))


def add_arcs(nodes: Dict[str, Node], arcs: Dict[tuple, Arc], node_a: Node, node_b: Node):
    """Add arcs between a and b."""
    # A safety measure to ensure arc direction.
    if node_a.type > node_b.type:
        node_a, node_b = node_b, node_a

    arc_configurations = {
        (NodeType.𝓢, NodeType.plant): (1, 0),
        (NodeType.plant, NodeType.waypoint): (1, 0),
        (NodeType.plant, NodeType.town): (1, 0),
        (NodeType.waypoint, NodeType.waypoint): (node_b.ub, node_a.ub),
        (NodeType.waypoint, NodeType.town): (node_b.ub, node_a.ub),
        (NodeType.town, NodeType.town): (node_b.ub, node_a.ub),
        (NodeType.town, NodeType.region): (node_b.ub, 0),
        (NodeType.region, NodeType.lodging): (node_b.ub, 0),
        (NodeType.lodging, NodeType.𝓣): (node_a.ub, 0),
    }

    ub, reverse_ub = arc_configurations.get((node_a.type, node_b.type), (1, 0))

    arc_a = Arc(node_a, node_b, ub=ub)
    arc_b = Arc(node_b, node_a, ub=reverse_ub)

    for arc in [arc_a, arc_b]:
        if arc.key not in arcs and arc.ub > 0:
            arcs[arc.key] = arc
            nodes[arc.source.key].outbound_arcs.append(arc)
            nodes[arc.destination.key].inbound_arcs.append(arc)

            if arc.destination.type is NodeType.lodging:
                arc.destination.regions = [arc.source]


def get_sparsified_link_graph(data: Dict[str, Any]):
    link_graph = nx.Graph()
    for origin_key, origin_data in data["exploration"].items():
        for destination_key in origin_data["link_list"]:
            if destination_key not in data["exploration"]:
                continue
            destination_data = data["exploration"][destination_key]
            if not destination_data["is_plantzone"]:
                link_graph.add_edge(origin_key, destination_key)

    for node, node_data in link_graph.nodes(data=True):
        node_data["type"] = get_link_node_type(node, data)

    # This removes the non-plant non-forced leaf nodes without repeated pruning.
    # Testing showed that doing any other reductions reduces performance.
    removal_nodes = []
    for node, node_data in link_graph.nodes(data=True):
        if (
            nx.degree(link_graph, node) == 1
            and node_data["type"] is not NodeType.plant
            and node not in data["force_active_node_ids"]
        ):
            removal_nodes.append(node)
    if removal_nodes:
        link_graph.remove_nodes_from(removal_nodes)
        removal_nodes = []

    return link_graph


def get_link_node_type(node_id: int, data: Dict[str, Any]):
    """Return the NodeType of the given node_id node."""
    if data["exploration"][node_id]["is_town"]:
        return NodeType.town
    if data["exploration"][node_id]["is_workerman_plantzone"]:
        return NodeType.plant
    return NodeType.waypoint


def get_link_nodes(nodes, origin, destination, data):
    node_a_type = get_link_node_type(origin, data)
    node_b_type = get_link_node_type(destination, data)
    node_a_id, node_b_id = str(origin), str(destination)

    # Ensure arc node order.
    if node_a_type > node_b_type:
        node_a_id, node_b_id = node_b_id, node_a_id
        node_a_type, node_b_type = node_b_type, node_a_type

    return (
        get_node(nodes, node_a_id, node_a_type, data),
        get_node(nodes, node_b_id, node_b_type, data),
    )


def get_node(nodes, node_id: str, node_type: NodeType, data: Dict[str, Any], **kwargs) -> Node:
    """
    Generate, add and return node based on NodeType.

    kwargs `plant` and `region` are required for supply nodes.
    kwargs `ub` is required for region nodes.
    kwargs `ub`, `cost` and `region` are required for lodging nodes.
    """

    regions = []
    lb = 0

    match node_type:
        case NodeType.𝓢:
            ub = data["max_ub"]
            cost = 0
        case NodeType.plant:
            ub = 1
            cost = data["exploration"][int(node_id)]["need_exploration_point"]
        case NodeType.waypoint | NodeType.town:
            ub = data["config"]["waypoint_ub"]
            cost = data["exploration"][int(node_id)]["need_exploration_point"]
        case NodeType.region:
            lodging_data = data["lodging_data"][int(node_id)]
            ub = lodging_data["max_ub"] + lodging_data["lodging_bonus"]
            ub = min(ub, data["config"]["waypoint_ub"])
            cost = 0
        case NodeType.lodging:
            ub = kwargs.get("ub")
            lb = kwargs.get("lb")
            root = kwargs.get("root")
            cost = kwargs.get("cost")
            assert (
                ub and (lb is not None) and (cost is not None) and root
            ), "Lodging nodes require 'ub', 'lb' 'cost' and 'root' kwargs."
            regions = [root]
        case NodeType.𝓣:
            ub = data["max_ub"]
            cost = 0
        case NodeType.INVALID:
            assert node_type is not NodeType.INVALID, "INVALID node type."
            return  # Unreachable: Stops pyright unbound error reporting.

    node = Node(str(node_id), node_type, ub, lb, cost, regions)
    if node.key not in nodes:
        if node_id in data["force_active_node_ids"]:
            node.isForceActive = True
        if node.type is NodeType.region:
            node.regions = [node]
        nodes[node.key] = node

    return nodes[node.key]


def process_links(nodes: Dict[str, Node], arcs: Dict[tuple, Arc], data: Dict[str, Any]):
    """Process all waypoint links and add the nodes and arcs to the graph.

    Calls handlers for plant and town nodes to add plant value nodes and
    region/lodging nodes with their respective source and sink arcs.
    """
    link_graph = get_sparsified_link_graph(data)

    for origin_key, origin_data in data["exploration"].items():
        if not link_graph.has_node(origin_key):
            continue

        for destination_key in origin_data["link_list"]:
            if not link_graph.has_node(destination_key):
                continue

            # `get_link_nodes()` orders the nodes by type.
            start_node, end_node = get_link_nodes(nodes, origin_key, destination_key, data)
            add_arcs(nodes, arcs, start_node, end_node)

            if start_node.isPlant:
                process_plant(nodes, arcs, start_node, data)
            if end_node.isTown:
                process_town(nodes, arcs, end_node, data)


def process_plant(nodes: Dict[str, Node], arcs: Dict[tuple, Arc], plant: Node, data: Dict[str, Any]):
    """Add plant region values and arcs between the source and plant nodes."""
    for i, (region_id, value_data) in enumerate(data["plant_values"][plant.id].items(), 1):
        if i > data["config"]["top_n"]:
            break
        plant.region_prizes[region_id] = value_data

    add_arcs(nodes, arcs, nodes["𝓢"], plant)


def process_town(nodes: Dict[str, Node], arcs: Dict[tuple, Arc], town: Node, data: Dict[str, Any]):
    """Add town region and lodging nodes and arcs between the town and sink nodes."""
    exploration_node = data["exploration"][int(town.id)]

    # TODO: change this for handling force taken nodes since they can connect to any base town.
    if not exploration_node["is_worker_npc_town"]:
        return

    region_key = exploration_node["region_key"]
    lodging_data = data["lodging_data"].get(region_key, None)
    assert lodging_data, f"Error: Lodging data missing for region {region_key}!"
    lodging_bonus = lodging_data["lodging_bonus"]

    # Region lodging data is ordered in ascending order by lodgings and cost.
    # For each lodging count <= min(max_ub, lodging_bonus) find the lowest cost.

    # lodgings is the list of previous 'best' (lodging, cost) pairs.
    lodgings = [(1 + lodging_bonus, 0)]

    for ub, lodging_data in lodging_data.items():
        if ub in ["max_ub", "lodging_bonus"]:
            continue

        current = (1 + lodging_bonus + int(ub), lodging_data[0].get("cost"))

        # remove previous 'best' (lodging, cost) pairs when dominated and replace with new 'best'
        while lodgings and current[1] <= lodgings[-1][1] and current[0] >= lodgings[-1][0]:
            lodgings.pop(-1)
        lodgings.append(current)

        if current[0] + 1 >= data["config"]["waypoint_ub"]:
            break

    # Each (lodging, cost) pair us a unique node in the graph, lodging is the arc flow constraint.

    region_node = get_node(nodes, region_key, NodeType.region, data, ub=lodgings[-1][0])
    add_arcs(nodes, arcs, town, region_node)

    lb = 0
    for ub, cost in lodgings:
        lodging_node = get_node(
            nodes,
            f"{region_node.id}_for_{ub}",
            NodeType.lodging,
            data,
            ub=ub,
            lb=lb,
            cost=cost,
            root=region_node,
        )
        add_arcs(nodes, arcs, region_node, lodging_node)
        add_arcs(nodes, arcs, lodging_node, nodes["𝓣"])
        lb = ub + 1


def nearest_n_towns(data: Dict[str, Any], G: GraphData, nearest_n: int):
    waypoint_graph = nx.DiGraph()
    for arc in G["E"].values():
        waypoint_graph.add_edge(arc.source.id, arc.destination.id, weight=arc.destination.cost)
    all_pairs = dict(nx.all_pairs_bellman_ford_path_length(waypoint_graph, weight="weight"))

    nearest_towns_dist = {}
    nearest_towns = {}

    for node_id, node in G["V"].items():
        if node.isWaypoint or node.isTown:
            distances = []
            for region in G["R"].values():
                town_id = data["affiliated_town_region"][int(region.id)]
                distances.append((region, all_pairs[node.id][str(town_id)]))
            nearest_towns_dist[node_id] = sorted(distances, key=lambda x: x[1])[:nearest_n]
            nearest_towns[node_id] = [w for w, _ in nearest_towns_dist[node_id]]

    return nearest_towns


def finalize_regions(data: Dict[str, Any], G: GraphData, nearest_n: int):
    # All region nodes have now been generated, finalize regions entries
    nearest_towns = nearest_n_towns(data, G, nearest_n)
    for v in G["V"].values():
        if v.type in [NodeType.𝓢, NodeType.𝓣]:
            v.regions = [w for w in G["R"].values()]
        elif v.isWaypoint or v.isTown:
            v.regions = [w for w in nearest_towns[v.key]]
        elif v.isPlant:
            v.regions = [w for w in G["R"].values() if w.id in v.region_prizes.keys()]


def generate_graph_data(data):
    """Generate and return a GraphData Dict composing the LP empire data."""
    print("Generating graph data...")
    nodes: Dict[str, Node] = {}
    arcs: Dict[tuple[str, str], Arc] = {}

    get_node(nodes, "𝓢", NodeType.𝓢, data)
    get_node(nodes, "𝓣", NodeType.𝓣, data)
    process_links(nodes, arcs, data)

    G: GraphData = {
        "V": dict(sorted(nodes.items(), key=lambda item: item[1].type)),
        "E": dict(sorted(arcs.items(), key=lambda item: item[1].as_dict()["type"])),
        "R": {k: v for k, v in nodes.items() if v.isRegion},
        "P": {k: v for k, v in nodes.items() if v.isPlant},
        "L": {k: v for k, v in nodes.items() if v.isLodging},
        "F": {k: v for k, v in nodes.items() if v.isForceActive},
    }
    finalize_regions(data, G, data["config"]["nearest_n"])

    return G
