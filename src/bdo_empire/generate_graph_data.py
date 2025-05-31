# generate_graph.data.py

from __future__ import annotations
from enum import IntEnum, auto
from typing import Any, TypedDict

import networkx as nx

SUPERROOT = 99999 # A special region node for force activated nodes

class GraphData(TypedDict):
    """GraphData class is passed to the model creator for the solver."""
    V: dict[str, Node]  # All Nodes
    E: dict[tuple[str, str], Arc]  # All Arcs
    F: dict[str, Node]  # Force Active Nodes
    R: dict[str, Node]  # Region Nodes
    L: dict[str, Node]  # Lodging Nodes
    P: dict[str, Node]  # Plant Nodes


class NodeType(IntEnum):
    """Enum identifying node types for the model creator for the solver."""
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
    """Node class is passed to the model creator for the solver."""
    def __init__(  # pylint: disable=dangerous-default-value
        self,
        id: str,  # pylint: disable=redefined-builtin
        type: NodeType,  # pylint: disable=redefined-builtin
        ub: int,
        lb: int = 0,
        cost: int = 0,
        regions: list[Node] = [],
    ):
        self.id = id
        self.type = type
        self.ub = ub
        self.lb = lb
        self.cost = cost
        self.region_prizes: dict[str, dict[str, Any]] = {}
        self.regions = regions if regions else []
        self.key = self.name()
        self.inbound_arcs: list[Arc] = []
        self.outbound_arcs: list[Arc] = []
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

    def as_dict(self) -> dict[str, Any]:
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
                obj_dict["regions"].append("self") # type: ignore
            else:
                obj_dict["regions"].append(node.name()) # type: ignore
        for k, v in self.vars.items():
            obj_dict["vars"][k] = v.to_dict() # type: ignore
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

    def as_dict(self) -> dict[str, Any]:
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


def add_arcs(nodes: dict[str, Node], arcs: dict[tuple, Arc], node_a: Node, node_b: Node):
    """Add arcs between a and b."""
    # A safety measure to ensure arc direction.
    if node_a.type > node_b.type:
        node_a, node_b = node_b, node_a

    arc_configurations = {
        (NodeType.𝓢, NodeType.plant): (1, 0),
        (NodeType.𝓢, NodeType.waypoint): (1, 0),
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


def get_sparsified_link_graph(data: dict[str, Any]):
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


def get_link_node_type(node_id: int, data: dict[str, Any]):
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


def get_node(nodes, node_id: str, node_type: NodeType, data: dict[str, Any], **kwargs) -> Node:
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
            if "fixed" in node_id:
                cost = 0
            else:
                cost = data["exploration"][int(node_id)]["need_exploration_point"]
        case NodeType.waypoint | NodeType.town:
            ub = data["config"]["max_waypoint_ub"]
            cost = data["exploration"][int(node_id)]["need_exploration_point"]
        case NodeType.region:
            lodging_data = data["lodging_data"][int(node_id)]
            ub = lodging_data["max_ub"]
            ub = min(ub, data["config"]["max_waypoint_ub"])
            cost = 0
        case NodeType.lodging:
            ub = kwargs.get("ub")
            lb = kwargs.get("lb")
            root = kwargs.get("root")
            cost = kwargs.get("cost")
            assert (ub is not None) and (lb is not None) and (cost is not None) and root, (
                "Lodging nodes require 'ub', 'lb' 'cost' and 'root' kwargs."
            )
            regions = [root]
        case NodeType.𝓣:
            ub = data["max_ub"]
            cost = 0
        case NodeType.INVALID:
            assert node_type is not NodeType.INVALID, "INVALID node type."
            return  # Unreachable: Stops pyright unbound error reporting.

    node = Node(str(node_id), node_type, ub, lb, cost, regions)
    if node.key not in nodes:
        if node.type is NodeType.region:
            node.regions = [node]
        nodes[node.key] = node

    return nodes[node.key]


def process_force_activations(nodes: dict[str, Node], arcs: dict[tuple, Arc], data: dict[str, Any]):
    """ Process forced activation setup.

    - Introduce fixed_${waypoint} for each waypoint in force_active_node_ids between source and the waypoint
    - Introduce region_${SUPERROOT} with links from all basetown nodes and to the sink.
    """
    exploration = data["exploration"]
    num_force_active_nodes = len(data["force_active_node_ids"])

    source_node = get_node(nodes, "𝓢", NodeType.𝓢, data)
    sink_node = get_node(nodes, "𝓣", NodeType.𝓣, data)

    # NOTE: Because super root is a region we must have a lodging specification in data["lodging_data"]
    #       it might be better to do this in the generate_reference_data (?)
    # It will need a single lodging entry with ub == len(G["F"]) and cost 0.
    data["lodging_data"][SUPERROOT] = {
        "max_ub": num_force_active_nodes,
        "bounds_costs": [(num_force_active_nodes, 0)]
    }
    superroot_node = get_node(nodes, str(SUPERROOT), NodeType.region, data, ub=num_force_active_nodes)

    # provide links from _all_ base town nodes to the super root regardlesss if they have lodging.
    for node_key, node in nodes.items():
        if not node.type in [NodeType.waypoint, NodeType.town]:
            continue
        if not exploration[int(node.id)]["is_base_town"]:
            continue
        add_arcs(nodes, arcs, node, superroot_node)

    add_arcs(nodes, arcs, superroot_node, sink_node)

    for node_key, node in nodes.copy().items():
        if not node.isForceActive:
            continue
        print(f"  creating fixed node for {node.name()}.")
        fixed_node = get_node(nodes, f"fixed_{node_key}", NodeType.plant, data)
        add_arcs(nodes, arcs, source_node, fixed_node)
        add_arcs(nodes, arcs, fixed_node, node)


def process_links(nodes: dict[str, Node], arcs: dict[tuple, Arc], data: dict[str, Any]):
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
            if int(start_node.id) in data["force_active_node_ids"]:
                print(f"  processing_links: Setting node {start_node.name()} to force active.")
                start_node.isForceActive = True

            add_arcs(nodes, arcs, start_node, end_node)

            if start_node.isPlant:
                process_plant(nodes, arcs, start_node, data)
            if end_node.isTown:
                process_town(nodes, arcs, end_node, data)


def process_plant(nodes: dict[str, Node], arcs: dict[tuple, Arc], plant: Node, data: dict[str, Any]):
    """Add plant region value nodes and arcs between the source and plant nodes."""
    for i, (region_id, value_data) in enumerate(data["plant_values"][plant.id].items(), 1):
        if i > data["config"]["top_n"]:
            break
        plant.region_prizes[region_id] = value_data

    add_arcs(nodes, arcs, nodes["𝓢"], plant)


def process_town(nodes: dict[str, Node], arcs: dict[tuple, Arc], town: Node, data: dict[str, Any]):
    """Add town region and lodging nodes and arcs between the town and sink nodes."""
    exploration_node = data["exploration"][int(town.id)]
    if not exploration_node["is_worker_npc_town"]:
        return

    region_key = exploration_node["region_key"]

    # NOTE: lodging data is pre-processed to account for base 1 bonus per town
    # and any bonus pearl/loyalty lodging as well as any reserved lodging usage.
    # See the 'lodging bounds' functions in "generate_reference_data.py".
    lodging_data = data["lodging_data"].get(region_key)
    assert lodging_data, f"Error: Lodging data missing for region {region_key}!"
    bounds_costs = lodging_data["bounds_costs"]

    # max_ub is the limiting constraint for total workers in a region
    max_ub = lodging_data["max_ub"]

    region_node = get_node(nodes, region_key, NodeType.region, data, ub=max_ub)
    add_arcs(nodes, arcs, town, region_node)

    # Each bounds_costs pair (lodging, cost) is a unique node in the graph
    # where lodging the limiting constraint for workers at the given cost
    # from the all_lodging_storage chains.
    lb = 0
    for ub, cost in bounds_costs:
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


def nearest_n_towns(data: dict[str, Any], G: GraphData, nearest_n: int):
    """Identify and returns the nearest n towns to any given waypoint node.

    The nearest towns serve as allowable flow constraints for transit routes
    between production nodes and region nodes. Its purpose is to minimize the
    solver search space by constraining to 'realistic' node assignments and routes.
    """
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
                if region.id == str(SUPERROOT):
                    continue
                town_id = data["affiliated_town_region"][int(region.id)]
                distances.append((region, all_pairs[node.id][str(town_id)]))
            nearest_towns_dist[node_id] = sorted(distances, key=lambda x: x[1])[:nearest_n]
            nearest_towns[node_id] = [w for w, _ in nearest_towns_dist[node_id]]

    return nearest_towns


def finalize_regions(data: dict[str, Any], G: GraphData, nearest_n: int):
    """Finalizes the allowable regional flows for all nodes except region and lodging nodes
    which are already self-limited to their own region.
    """
    # All region nodes have now been generated, finalize regions entries
    # When forced nodes are present all waypoints must be able to carry the super root flow
    nearest_towns = nearest_n_towns(data, G, nearest_n)

    for v in G["V"].values():
        if v.type in [NodeType.𝓢, NodeType.𝓣]:
            v.regions = list(G["R"].values())
        elif v.isWaypoint or v.isTown:
            v.regions = list(nearest_towns[v.key])
        elif v.isPlant:
            v.regions = [w for w in G["R"].values() if w.id in v.region_prizes.keys()]

    # ensure super root is a region for all waypoints and for plant nodes of force activated nodes
    # since it wont be in the nearest_n_towns of any node.
    if len(G["F"]):
        super_root_node = G["V"][f"region_{str(SUPERROOT)}"]
        for v in G["V"].values():
            if v.type in [NodeType.waypoint, NodeType.town]:
                v.regions += [super_root_node]
            if v.isForceActive:
                plant_for_force_active = G["P"][f"plant_fixed_{v.key}"]
                plant_for_force_active.regions += [super_root_node]

    return

def generate_graph_data(data):
    """Generate and return a GraphData dict composing the LP empire data."""
    print("Generating graph data...")
    nodes: dict[str, Node] = {}
    arcs: dict[tuple[str, str], Arc] = {}
    data["force_active_node_keys"] = [str(k) for k in data["force_active_node_ids"]]

    get_node(nodes, "𝓢", NodeType.𝓢, data)
    get_node(nodes, "𝓣", NodeType.𝓣, data)
    process_links(nodes, arcs, data)
    process_force_activations(nodes, arcs, data)

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
