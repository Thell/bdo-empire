# optimize_highspy.py

from highspy import Highs, ObjSense
from loguru import logger
from rustworkx import PyDiGraph

from bdo_empire.api_common import ANCADO_INNER_HARBOR_KEY, extract_base_empire
from bdo_empire.solver_highspy import SolverController, solve

SUPER_ROOT = 99999


def create_model(
    G: PyDiGraph,
    config: dict,
    prev_terminals_sets: None | dict = None,
) -> tuple[Highs, dict]:
    """Model with assignment and dynamic costs with flow from terminals to roots."""

    model = Highs()

    roots_indices = G.attrs["root_indices"]
    terminal_indices = G.attrs["terminals"]
    super_root_index = None
    super_terminal_indices = []
    for i in G.node_indices():
        if G[i].get("is_super_terminal", False):
            super_terminal_indices.append(i)
        if G[i]["waypoint_key"] == SUPER_ROOT:
            super_root_index = i

    # Variables
    # Node selection for each node in graph to determine if node is in forest.
    x = model.addBinaries(G.node_indices(), name=[f"x_{G[i]['waypoint_key']}" for i in G.node_indices()])

    # Root assignment selector for each terminal (terminal, root) pair
    x_t_r = {}
    for t in terminal_indices:
        tw = G[t]["waypoint_key"]
        for r in G[t]["prizes"]:
            rw = G[r]["waypoint_key"]
            x_t_r[(t, r)] = model.addBinary(name=f"xtr_{tw}_{rw}")
    for t in super_terminal_indices:
        x_t_r[(t, super_root_index)] = model.addBinary()

    # Previous model: allows for iterative optimization (growth of forest)
    # from a given set of terminal, root pairs
    if prev_terminals_sets:
        logger.info("using prev_model")
        for t, r in prev_terminals_sets.items():
            model.addConstr(x_t_r[(t, r)] == 1)
            model.addConstr(x[t] == 1)
            model.addConstr(x[r] == 1)

    # SOS1 - Capacity assignment selector for each root
    # Capacity has step-wise costs and must equal the terminal count assigned to the root.
    # capacity_cost: list[int] => {0, cost_1, cost_2, ...} for 0, 1, 2, ...
    # the zeroth index is the "empty" (non-selected) state for a given root
    c_r = {}
    for r in roots_indices:
        for c in range(len(G[r]["capacity_cost"])):
            c_r[(c, r)] = model.addBinary()

    # # I'm still not positive this is helpful in _most_ instances.
    # # When it helps it is noticeable and when it doesn't it doesn't hurt performance too much.
    # # I wasn't able to determine a pre-processing analysis that would allow for a solid option trigger.
    # # Skip adjacent (e.g., no constr for 0&1, but yes for 0&2)
    # for r in roots_indices:
    #     n = len(G[r]["capacity_cost"])
    #     for c1 in range(n):
    #         for c2 in range(c1 + 2, n):
    #             model.addConstr(c_r[(c1, r)] + c_r[(c2, r)] <= 1)

    # Flow for root on arc (i,j); when root can transit from i to j
    f_r = {}
    for i, j in G.edge_list():
        common_rs = set(G[i]["transit_bounds"]) & set(G[j]["transit_bounds"])
        for r in common_rs:
            ub = min(G[i]["transit_bounds"][r], G[j]["transit_bounds"][r])
            f_r[(r, i, j)] = model.addVariable(lb=0, ub=ub)

    # Objective
    # This is another of those changes where I am not positive on the utility of it.
    # When it helps it is noticeable and when it doesn't it doesn't hurt performance too much.
    # I wasn't able to determine a pre-processing analysis that would allow for a solid option trigger.
    # Scale the prizes for the solver. The runner will use rounding to 1e6 for incumbent promotions.
    prizes = model.qsum(
        x_t_r[(t, r)] * (prize / 1e6) for t in terminal_indices for r, prize in G[t]["prizes"].items()
    )

    # prizes = model.qsum(
    #     x_t_r[(t, r)] * int(prize) for t in terminal_indices for r, prize in G[t]["prizes"].items()
    # )
    model.setObjective(prizes, sense=ObjSense.kMaximize)

    # Hard Budget Constraint
    budget = config["budget"]
    capacity_cost = model.qsum(
        c_r[(c, r)] * cost for r in roots_indices for c, cost in enumerate(G[r]["capacity_cost"])
    )
    node_cost = model.qsum(x[i] * G[i]["need_exploration_point"] for i in G.node_indices())
    model.addConstr(capacity_cost + node_cost <= budget, name="budget")

    # (Terminal, root) assignment constraints

    # Minimum and Maximum bounds on number of terminals assigned
    t_count_ub = round(
        3.98980981766944
        + 0.552618716162738 * budget
        + 2.98921916296481e-7 * budget**3
        - 0.000503850929485882 * budget**2
    )
    logger.info(f"*** Setting min/max terminal count cutoff = [{int(t_count_ub * 0.6)}, {t_count_ub}]")
    model.addConstr(model.qsum(x[t] for t in terminal_indices) >= int(t_count_ub * 0.6))

    # TODO: Recalculate upper bounds post 06/04/26 CP reduction patch with max p2w lodging.
    # model.addConstr(model.qsum(x[t] for t in terminal_indices) <= t_count_ub)

    for r in roots_indices:
        assigned = model.qsum(x_t_r[(t, r)] for t in terminal_indices if (t, r) in x_t_r)
        # Any terminal assigned to root selects root
        model.addConstr(assigned <= G[r]["ub"] * x[r])
    for t in terminal_indices:
        assigned = model.qsum(x_t_r[(t, r)] for r in G[t]["prizes"])
        # Any root assigned by terminal selects terminal
        model.addConstr(x[t] >= assigned)
        # Terminals may be assigned to at most a single root
        model.addConstr(assigned <= 1)
    if super_root_index is not None:
        # Super root must be selected
        model.addConstr(x[super_root_index] == 1)
        # All super terminals must be assigned to super root
        for t in super_terminal_indices:
            model.addConstr(x_t_r[(t, super_root_index)] == 1)
            model.addConstr(x[t] == 1)

    # Ranked basins cuts
    basins = G.attrs.get("basins", {})
    for r, (basin_ts, cut_value, cut_nodes) in basins.items():
        outside_assigned = model.qsum(
            x_t_r[(t, r)] for t in terminal_indices if t not in basin_ts and (t, r) in x_t_r
        )
        model.addConstr(
            outside_assigned <= cut_value * model.qsum(x[b] for b in cut_nodes if b in G.node_indices())
        )

    # Node/flow based constraints
    # All flow is accumulated from terminals to roots
    flow_roots = roots_indices + ([super_root_index] if super_root_index is not None else [])
    terminal_and_roots = set(terminal_indices) | set(super_terminal_indices) | set(flow_roots)

    for i in G.node_indices():
        predecessors = G.predecessor_indices(i)
        successors = G.successor_indices(i)
        neighbors = set(predecessors) | set(successors)
        x_neighbors = [x[j] for j in neighbors]

        # Neighbor selection: redundant for selection but imposes a transitive
        # property to selected nodes to improve solution runtime.
        if i in terminal_and_roots:
            # A selected terminal or root must have at least one selected neighbor
            model.addConstr(model.qsum(x_neighbors) >= 1 * x[i])
        else:
            # A selected intermediate must have at least two selected neighbors
            model.addConstr(model.qsum(x_neighbors) >= 2 * x[i])

        for r in flow_roots:
            if r not in G[i]["transit_bounds"] or G[i]["transit_bounds"][r] == 0:
                continue

            r_ub = G[r]["ub"]
            in_flow = model.qsum(f_r[(r, j, i)] for j in predecessors if (r, j, i) in f_r)
            out_flow = model.qsum(f_r[(r, i, j)] for j in successors if (r, i, j) in f_r)

            # Node selection: any flow selects node
            model.addConstr(in_flow <= r_ub * x[i])
            model.addConstr(out_flow <= r_ub * x[i])

            # Flow
            if i == r:
                if r != super_root_index:
                    # Flow at root: all assigned terminals must be accounted for
                    model.addConstr(out_flow == 0)
                    model.addConstr(
                        in_flow == model.qsum(x_t_r[(t, r)] for t in terminal_indices if (t, r) in x_t_r)
                    )
                    # Capacity at root: capacity cost list has a no-cost 'empty' zeroth index with capacity 0
                    capacity_costs = G[r]["capacity_cost"]
                    # While this could be `== 1` empirical testing suggests `== x[r]` is more effective
                    model.addConstr(model.qsum(c_r[(c, r)] for c in range(len(capacity_costs))) == x[r])
                    model.addConstr(
                        in_flow == model.qsum(c * c_r[(c, r)] for c in range(len(capacity_costs)))
                    )
                else:
                    # Flow at SUPER_ROOT is only allowed for incoming SUPER_TERMINAL transit
                    # Super root has no capacity limit or capacity cost.
                    model.addConstr(out_flow == 0)
                    model.addConstr(in_flow == len(super_terminal_indices))
                    model.addConstr(in_flow == model.qsum(x_t_r[(t, r)] for t in super_terminal_indices))

            elif i in terminal_indices and (i, r) in x_t_r:
                # Flow at terminal: assigned terminals have one unit of out_flow.
                # Terminals are leaf nodes so in_flow is zero
                model.addConstr(out_flow == x_t_r[(i, r)])
                model.addConstr(in_flow == 0)

            elif i in super_terminal_indices and r == super_root_index:
                # Flow at super terminal
                model.addConstr(out_flow - in_flow == 1)

            else:
                # Flow at intermediate node
                model.addConstr(out_flow - in_flow == 0)

    # Ancado Inner Harbor Special Case Handling.
    # If selected for any reason (including farm fences), it must be connected to a near town.
    # There are three connection paths to select from...
    ancado_node_id = G.attrs["node_key_by_index"].inv[ANCADO_INNER_HARBOR_KEY]

    connect_sets_wp = [[1321, 1327, 1328, 1329, 1376], [1321, 1327, 1328, 1329, 1330, 1375], [1339]]
    connect_sets_indices = [
        [G.attrs["node_key_by_index"].inv[i] for i in connect_set] for connect_set in connect_sets_wp
    ]

    connect_vars = []
    for i, connect_set in enumerate(connect_sets_indices):
        connect_var = model.addBinary(name=f"x_ancado_connect_{i}")
        connect_vars.append(connect_var)
        model.addConstr(model.qsum([x[i] for i in connect_set]) >= len(connect_set) * connect_var)
    # If Ancado capacity 0 is not selected, then at least one connection path must be selected.
    model.addConstr(model.qsum(connect_vars) >= 1 - c_r[(0, ancado_node_id)])



def optimize(
    data: dict,
    controller: SolverController,
) -> tuple[Highs, dict]:
    """Create and solve the MIP problem for the given graph and configuration."""
    G = data["solver_graph"]
    assert isinstance(G, PyDiGraph)
    num_processes = data["config"]["solver"]["num_processes"]

    if data["base_empire"] is not None:
        prev_terminals_sets = extract_base_empire(G, data["base_empire"])
    else:
        prev_terminals_sets = {}

    print(
        f"\nSolving:  graph with {G.num_nodes()} nodes and {G.num_edges()} arcs"
        f"\n  Using:  budget of {data['config']['budget']}"
        f"\n   With:  {num_processes} processes."
    )

    print("Creating mip model...")
    model, vars = create_model(G, data["config"], prev_terminals_sets=prev_terminals_sets)

    # Write mip model for debugging
    # print("Writing mip model...")
    # model.writeModel(f"B_{data['config']['budget']}_lta_prices_max_lodging_topn_6_nearestn_7_ub_17.mps")

    print("Solving mip problem...")
    model = solve(model, data["config"], controller)

    return model, vars
