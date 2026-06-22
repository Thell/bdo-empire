# main.py

import ast
import json
from enum import Enum
from math import inf
from pathlib import Path
from threading import Thread
from tkinter import ACTIVE, DISABLED, END, NORMAL, Listbox, filedialog

import customtkinter as ctk
from CTkToolTip import CTkToolTip as ctktt
from psutil import cpu_count

from bdo_empire.api_common import set_logger
from bdo_empire.generate_graph_data import generate_graph_data
from bdo_empire.generate_reference_data import generate_reference_data, get_region_lodging_bounds_costs
from bdo_empire.generate_workerman_data import generate_workerman_data
from bdo_empire.optimize_highspy import optimize as optimize_highspy
from bdo_empire.solver_highspy import SolverController

optimize_config = {
    "name": "Empire",
    "budget": 0,
    "top_n": 6,
    "nearest_n": 7,
    "max_waypoint_ub": 30,
    "solver_config": {},
}


solver_config = {
    "num_processes": max(1, cpu_count(logical=False) - 1),  # concurrent HiGHs processes
    "mip_rel_gap": 1e-4,
    "mip_feasibility_tolerance": 1e-4,
    "primal_feasibility_tolerance": 1e-4,
    "random_seed": 0,
    "time_limit": inf,
    "mip_improvement_timeout": inf,
    "mip_heuristic_run_root_reduced_cost": True,
    "threads": 1,  # HiGHs internal parallelism
    "log_to_console": False,  # HiGHs logger callback is distinct from console logging.
}

solver_config_descriptions = {
    "num_processes": "Number of processes to use.",
    "mip_rel_gap": "Relative gap tolerance between MIP objective and upper bound.",
    "mip_feasibility_tolerance": "Tolerance for MIP feasibility.",
    "primal_feasibility_tolerance": "Tolerance for primal feasibility.",
    "random_seed": "Random seed.",
    "time_limit": "Global time limit regardless of MIP improvement.",
    "mip_improvement_timeout": "MIP timeout after last improvement.",
    "mip_heuristic_run_root_reduced_cost": "Run MIP reduced cost heuristic on root node. (Recommend 'False' on sub 300 budget empires.)",
}


lodging_specifications = {
    "Velia": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "Heidel": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "Glish": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Calpheon City": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "Olvia": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Keplan": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Port Epheria": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Trent": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Iliya Island": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 0},
    "Altinova": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 8},
    "Tarif": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Valencia City": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "Shakatu": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Sand Grain Bazaar": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Ancado Inner Harbor": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 0},
    "Arehaza": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Old Wisdom Tree": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Grána": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "Duvencrune": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "O'draxxia": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 9},
    "Eilton": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Dalbeol Village": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Nampo's Moodle Village": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Nopsae's Byeot County": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Asparkan": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Muzgar": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Yukjo Street": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Godu Village": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Bukpo": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Hakinza Sanctuary": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
}


def try_parse_int(val, default=0):
    try:
        return int(val.strip())
    except (ValueError, AttributeError):
        return default


class WidgetState(Enum):
    Ready = 0
    Required = 1
    Optional = 2
    Waiting = 3
    Running = 4
    Error = 5


def get_version():
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("bdo-empire")
    except PackageNotFoundError:
        return "dev"


class EmpireOptimizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"Empire Optimizer - {get_version()}")
        # Each row is 40 pixels and padding is 10
        self.geometry("720x400")

        self.data_state = WidgetState.Required
        self.cp_state = WidgetState.Required
        self.prices_state = WidgetState.Required
        self.lodging_state = WidgetState.Optional
        self.modifiers_state = WidgetState.Optional
        self.forced_taken_state = WidgetState.Optional
        self.outpath_state = WidgetState.Required
        self.optimize_state = WidgetState.Waiting
        self.baseempire_state = WidgetState.Optional

        self.config_entries = {}
        self.forced_taken_entries = {}
        self.lodging_entries = {}
        self.node_lookup = self.load_node_name_lookup()
        self.all_nodes = sorted(self.node_lookup.items(), key=lambda x: x[1])

        self.solver_controller = SolverController()

        self.create_widgets()

    def create_widgets(self):
        row = 0

        row += 1
        self.cp_label = ctk.CTkLabel(self, text="CP Limit")
        self.cp_label.grid(row=row, column=0, padx=10, pady=10)
        self.cp_entry = ctk.CTkEntry(self, validate="focusout", validatecommand=self.validate_cp)
        self.cp_entry.bind("<FocusOut>", lambda event: self.validate_cp())
        self.cp_entry.grid(row=row, column=1, padx=10, pady=10)
        self.cp_prepaid_label = ctk.CTkLabel(self, text="")
        self.cp_prepaid_label.grid(row=row, column=2, padx=10, pady=10)
        self.cp_status = ctk.CTkLabel(self, text=self.cp_state.name)
        self.cp_status.grid(row=row, column=3, padx=10, pady=10)

        row += 1
        self.prices_label = ctk.CTkLabel(self, text="Prices")
        self.prices_label.grid(row=row, column=0, padx=10, pady=10)
        self.prices_entry = ctk.CTkEntry(self, width=300)
        self.prices_entry.grid(row=row, column=1, padx=10, pady=10)
        self.prices_button = ctk.CTkButton(self, text="Browse", command=self.browse_prices_file)
        self.prices_button.grid(row=row, column=2, padx=10, pady=10)
        self.prices_status = ctk.CTkLabel(self, text=self.prices_state.name)
        self.prices_status.grid(row=row, column=3, padx=10, pady=10)
        ctktt(self.prices_label, message="Set to file exported from workerman's settings page.")
        ctktt(self.prices_entry, message="Set to file exported from workerman's settings page.")

        row += 1
        self.lodging_button = ctk.CTkButton(self, text="Setup Purchased Lodging", command=self.setup_lodging)
        self.lodging_button.grid(row=row, column=1, padx=0, pady=10)
        self.lodging_status = ctk.CTkLabel(self, text=self.lodging_state.name)
        self.lodging_status.grid(row=row, column=3, padx=0, pady=10)
        ctktt(self.lodging_button, message="Setup pearl shop bonus lodging and workshop reserved lodging.")

        row += 1
        self.forced_taken_button = ctk.CTkButton(
            self, text="Setup Forced Nodes", command=self.setup_forced_taken
        )
        self.forced_taken_button.grid(row=row, column=1, padx=0, pady=10)
        self.forced_taken_status = ctk.CTkLabel(self, text=self.forced_taken_state.name)
        self.forced_taken_status.grid(row=row, column=3, padx=0, pady=10)
        ctktt(
            self.forced_taken_button,
            message="Setup nodes that are forced active (connect to least cost town) e.g. for grinding droprate",
        )

        row += 1
        self.modifiers_label = ctk.CTkLabel(self, text="Modifiers")
        self.modifiers_label.grid(row=row, column=0, padx=10, pady=10)
        self.modifiers_entry = ctk.CTkEntry(self, width=300)
        self.modifiers_entry.grid(row=row, column=1, padx=10, pady=10)
        self.modifiers_button = ctk.CTkButton(self, text="Browse", command=self.browse_modifiers_file)
        self.modifiers_button.grid(row=row, column=2, padx=10, pady=10)
        self.modifiers_status = ctk.CTkLabel(self, text=self.modifiers_state.name)
        self.modifiers_status.grid(row=row, column=3, padx=10, pady=10)
        ctktt(self.modifiers_label, message="Set to file exported from workerman's modifiers page.")
        ctktt(self.modifiers_entry, message="Set to file exported from workerman's modifiers page.")

        row += 1
        self.baseempire_label = ctk.CTkLabel(self, text="Base Empire")
        self.baseempire_label.grid(row=row, column=0, padx=10, pady=10)
        self.baseempire_entry = ctk.CTkEntry(self, width=300)
        self.baseempire_entry.grid(row=row, column=1, padx=10, pady=10)
        self.baseempire_button = ctk.CTkButton(self, text="Browse", command=self.browse_baseempire)
        self.baseempire_button.grid(row=row, column=2, padx=10, pady=10)
        self.baseempire_status = ctk.CTkLabel(self, text=self.baseempire_state.name)
        self.baseempire_status.grid(row=row, column=3, padx=10, pady=10)
        ctktt(self.baseempire_label, message="Set to empire json file exported from workerman.")
        ctktt(self.baseempire_entry, message="Set to empire json file exported from workerman.")

        row += 1
        self.outpath_label = ctk.CTkLabel(self, text="Output Path")
        self.outpath_label.grid(row=row, column=0, padx=10, pady=10)
        self.outpath_entry = ctk.CTkEntry(self, width=300)
        self.outpath_entry.grid(row=row, column=1, padx=10, pady=10)
        self.outpath_button = ctk.CTkButton(self, text="Browse", command=self.browse_outpath)
        self.outpath_button.grid(row=row, column=2, padx=10, pady=10)
        self.outpath_status = ctk.CTkLabel(self, text=self.outpath_state.name)
        self.outpath_status.grid(row=row, column=3, padx=10, pady=10)

        row += 1
        self.optimize_stop_button = ctk.CTkButton(
            self, text="Stop", command=self.stop_optimization, state=DISABLED
        )
        self.optimize_stop_button.grid(row=row, column=0, padx=10, pady=10)
        self.optimize_button = ctk.CTkButton(self, text="Optimize", command=self.optimize, state=DISABLED)
        self.optimize_button.grid(row=row, column=1, padx=10, pady=10)
        self.config_button = ctk.CTkButton(self, text="Config Solver", command=self.config_solver)
        self.config_button.grid(row=row, column=2, padx=10, pady=10)
        self.optimize_status = ctk.CTkLabel(self, text=self.optimize_state.name)
        self.optimize_status.grid(row=row, column=3, padx=10, pady=10)
        ctktt(self.optimize_stop_button, message="Stop solver and use current solution.")
        ctktt(self.optimize_button, message="Start solver using options from config.")
        ctktt(self.config_button, message="Configure solver options.")

    def themed_listbox(self, master):
        appearance = ctk.get_appearance_mode()
        theme = ctk.ThemeManager.theme

        def resolve_color(val):
            # If it's a list (light/dark pair), pick the appropriate one
            return val[1] if appearance == "Dark" else val[0]

        bg = resolve_color(theme["CTkFrame"]["fg_color"])
        fg = resolve_color(theme["CTkLabel"]["text_color"])
        select_bg = resolve_color(theme["CTkButton"]["fg_color"])
        select_fg = resolve_color(theme["CTkButton"]["text_color"])

        lb = Listbox(
            master,
            bg=bg,
            fg=fg,
            selectbackground=select_bg,
            selectforeground=select_fg,
            highlightthickness=0,
            borderwidth=0,
        )
        return lb

    def browse_prices_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if file_path:
            self.prices_entry.delete(0, ctk.END)
            self.prices_entry.insert(0, file_path)
            self.validate_prices(file_path)

    def browse_modifiers_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if file_path:
            self.modifiers_entry.delete(0, ctk.END)
            self.modifiers_entry.insert(0, file_path)
            self.validate_modifiers(file_path)

    def load_node_name_lookup(self):
        import bdo_empire.data_store as ds
        from bdo_empire.api_common import FENCE_1_KEY

        try:
            explore_name_map = ds.read_strings_csv("explore.csv")
            exploration_data = ds.read_json("exploration.json")
            entries = {
                int(node_data["waypoint_key"]): explore_name_map.get(
                    node_data["waypoint_key"], f"Unknown {node_data['waypoint_key']}"
                )
                for node_data in exploration_data.values()
            }

            for i in range(10):
                entries[FENCE_1_KEY + i] = "Farming Fence"

            return entries
        except Exception as e:  # noqa: BLE001
            print(f"Failed to load node names: {e}")
            return {}

    def setup_forced_taken(self):
        forced_taken_window = ctk.CTkToplevel(self)
        forced_taken_window.title("Setup forced_taken Nodes")
        forced_taken_window.geometry("800x500")
        forced_taken_window.update()
        forced_taken_window.grab_set()

        self.search_var = ctk.StringVar()
        self.forced_taken_entries["keys"] = self.forced_taken_entries.get("keys", [])

        # LEFT SIDE
        left_frame = ctk.CTkFrame(forced_taken_window)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(left_frame, text="Search Nodes").pack(anchor="w", padx=5)
        search_box = ctk.CTkEntry(left_frame, textvariable=self.search_var)
        search_box.pack(fill="x", padx=5, pady=5)
        search_box.bind("<KeyRelease>", self.update_forced_taken_filter)

        self.available_listbox = self.themed_listbox(left_frame)
        self.available_listbox.pack(fill="both", expand=True, padx=5, pady=5)
        self.available_listbox.bind("<Double-Button-1>", self.add_selected_node)

        # RIGHT SIDE
        right_frame = ctk.CTkFrame(forced_taken_window)
        right_frame.pack(side="right", fill="y", padx=10, pady=10)

        ctk.CTkLabel(right_frame, text="Selected forced_taken Nodes").pack(anchor="w", padx=5)
        self.selected_listbox = self.themed_listbox(right_frame)
        self.selected_listbox.pack(fill="both", expand=True, padx=5, pady=(5, 0))
        self.selected_listbox.bind("<Double-Button-1>", self.remove_selected_node)

        btn_frame = ctk.CTkFrame(right_frame)
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Import", command=self.import_forced_taken).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Export", command=self.export_forced_taken).pack(side="left", padx=5)

        self.update_forced_taken_filter()
        self.refresh_selected_nodes()

    def select_forced_taken_node(self, _event=None):
        selection = self.available_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        item_text = self.available_listbox.get(index)
        key = int(item_text.split("|")[-1].strip())
        self.forced_taken_entries["keys"].append(key)
        self.available_listbox.delete(index)
        self.selected_listbox.insert(END, item_text)

    def deselect_forced_taken_node(self, _event=None):
        selection = self.selected_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        item_text = self.selected_listbox.get(index)
        key = int(item_text.split("|")[-1].strip())
        self.forced_taken_entries["keys"].remove(key)
        self.selected_listbox.delete(index)
        self.available_listbox.insert(END, item_text)

    def update_forced_taken_filter(self, _event=None):
        search = self.search_var.get().lower()
        self.available_listbox.delete(0, END)

        for key, name in self.all_nodes:
            if key not in self.forced_taken_entries["keys"] and (
                search in name.lower() or search in str(key)
            ):
                self.available_listbox.insert(END, f"{name} | {key}")

    def add_node_to_selected_nodes(self, key: int):
        key_to_label = dict(self.all_nodes)
        if key not in key_to_label:
            return

        if key not in self.forced_taken_entries["keys"]:
            self.forced_taken_entries["keys"].append(key)

        self.forced_taken_entries["keys"].sort(key=lambda k: key_to_label[k])
        self.refresh_selected_nodes()

    def add_selected_node(self, _event):
        selection = self.available_listbox.get(ACTIVE)
        if "|" in selection:
            key = int(selection.split("|")[-1].strip())
            self.add_node_to_selected_nodes(key)

    def remove_selected_node(self, _event):
        selection = self.selected_listbox.get(ACTIVE)
        if "|" in selection:
            key = int(selection.split("|")[-1].strip())
            if key in self.forced_taken_entries["keys"]:
                self.forced_taken_entries["keys"].remove(key)
                self.update_forced_taken_filter()
                self.refresh_selected_nodes()

    def refresh_selected_nodes(self):
        self.selected_listbox.delete(0, END)
        for key in self.forced_taken_entries["keys"]:
            name = self.node_lookup.get(key, "Unknown")
            self.selected_listbox.insert(END, f"{name} | {key}")

        if self.forced_taken_entries["keys"]:
            self.forced_taken_state = WidgetState.Ready
            self.forced_taken_status.configure(text=self.forced_taken_state.name, text_color="green")
        else:
            self.forced_taken_state = WidgetState.Optional
            default_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
            self.forced_taken_status.configure(text=self.forced_taken_state.name, text_color=default_color)

        self.forced_taken_status.update()

    def import_forced_taken(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                keys = json.load(f).get("keys", [])

            self.forced_taken_entries["keys"].clear()
            self.selected_listbox.delete(0, END)

            for key in keys:
                self.add_node_to_selected_nodes(key)

            self.forced_taken_status.configure(text="Imported")
        except Exception:  # noqa: BLE001
            self.forced_taken_status.configure(text="Import Failed")

    def export_forced_taken(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"keys": self.forced_taken_entries["keys"]}, f, indent=2)
            self.forced_taken_status.configure(text="Exported")
        except Exception:  # noqa: BLE001
            self.forced_taken_status.configure(text="Export Failed")

    def setup_lodging(self):
        lodging_window = ctk.CTkToplevel(self)
        lodging_window.title("Initial Lodging Setup")
        lodging_window.geometry("750x600")
        lodging_window.update()
        lodging_window.grab_set()

        scrollable_frame = ctk.CTkScrollableFrame(lodging_window, width=720, height=500)
        scrollable_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10)

        # Bind mouse wheel scrolling for linux (WSL)
        scrollable_frame.bind_all(
            "<Button-4>",
            lambda e: scrollable_frame._parent_canvas.yview("scroll", -1, "units"),  # pylint: disable=protected-access
        )
        scrollable_frame.bind_all(
            "<Button-5>",
            lambda e: scrollable_frame._parent_canvas.yview("scroll", 1, "units"),  # pylint: disable=protected-access
        )

        # Header labels
        ctk.CTkLabel(scrollable_frame, text="Town", font=("Arial", 12, "bold")).grid(
            row=0, column=0, padx=10, pady=5
        )

        bonus_label = ctk.CTkLabel(scrollable_frame, text="Bonus", font=("Arial", 12, "bold"))
        bonus_label.grid(row=0, column=1, padx=10, pady=5)
        ctktt(bonus_label, message="Lodging gained through pearl shop.")

        reserved_label = ctk.CTkLabel(scrollable_frame, text="Reserved", font=("Arial", 12, "bold"))
        reserved_label.grid(row=0, column=2, padx=10, pady=5)
        ctktt(
            reserved_label,
            message="Lodging reserved for workshop use; incurs CP cost if greater than Bonus lodging.",
        )

        cost_label = ctk.CTkLabel(scrollable_frame, text="CP Cost", font=("Arial", 12, "bold"))
        cost_label.grid(row=0, column=3, padx=10, pady=5)
        ctktt(cost_label, message="CP cost for reserved lodging beyond Bonus lodging.")

        ctk.CTkLabel(scrollable_frame, text="Status", font=("Arial", 12, "bold")).grid(
            row=0, column=4, padx=10, pady=5
        )

        # Create entries for each town inside the scrollable frame
        def make_scroll_binder(entry):
            def handler(_e):
                self.check_scroll(entry, scrollable_frame)

            return handler

        def make_validate_handler(var, status_label, prepaid_var, town):
            def handler(_e):
                self.validate_and_refresh_lodging(var, status_label, prepaid_var, town)

            return handler

        self.lodging_entries = {}

        for row, (town, values) in enumerate(lodging_specifications.items(), start=1):
            bonus = values["bonus"]
            reserved = values["reserved"]
            prepaid = values["prepaid"]
            bonus_ub = values["bonus_ub"]

            label = ctk.CTkLabel(scrollable_frame, text=town)
            label.grid(row=row, column=0, padx=10, pady=5)

            bonus_var = ctk.StringVar(value=str(bonus))
            bonus_entry = ctk.CTkEntry(scrollable_frame, textvariable=bonus_var)
            bonus_entry.grid(row=row, column=1, padx=10, pady=5)

            reserved_var = ctk.StringVar(value=str(reserved))
            reserved_entry = ctk.CTkEntry(scrollable_frame, textvariable=reserved_var)
            reserved_entry.grid(row=row, column=2, padx=10, pady=5)

            prepaid_var = ctk.StringVar(value=str(prepaid))
            prepaid_label = ctk.CTkLabel(scrollable_frame, textvariable=prepaid_var)
            prepaid_label.grid(row=row, column=3, padx=10, pady=5)

            status_label = ctk.CTkLabel(scrollable_frame, text="Optional")
            status_label.grid(row=row, column=4, padx=10, pady=5)

            # The ISO_Left_tab is there for linux and Shift-KeyPress-Tab for windows
            for ev in ("<Tab>", "<Shift-KeyPress-Tab>", "<ISO_Left_Tab>"):
                bonus_entry.bind(ev, make_scroll_binder(bonus_entry))
                reserved_entry.bind(ev, make_scroll_binder(reserved_entry))

            bonus_entry.bind("<FocusOut>", make_validate_handler(bonus_var, status_label, prepaid_var, town))
            reserved_entry.bind(
                "<FocusOut>", make_validate_handler(reserved_var, status_label, prepaid_var, town)
            )

            self.lodging_entries[town] = {
                "bonus": bonus_var,
                "reserved": reserved_var,
                "prepaid": prepaid_var,
                "bonus_ub": bonus_ub,
                "status": status_label,
            }
            # Force label refresh for re-open
            self.validate_lodging(bonus_var, status_label, prepaid_var, town)

        # Force label refresh for re-open
        self.recompute_total_prepaid_cp()

        import_button = ctk.CTkButton(lodging_window, text="Import", command=self.import_lodging)
        import_button.grid(row=1, column=0, padx=10, pady=10)
        export_button = ctk.CTkButton(lodging_window, text="Export", command=self.export_lodging)
        export_button.grid(row=1, column=1, padx=10, pady=10)

        lodging_window.protocol("WM_DELETE_WINDOW", lambda: self.save_lodging_data(lodging_window))

    def check_scroll(self, entry, scrollable_frame, ypad=10, top_buffer=40, bottom_buffer=40):
        entry_row = entry.grid_info()["row"]
        entry_widget = scrollable_frame.grid_slaves(row=entry_row, column=1)[0]

        canvas = scrollable_frame._parent_canvas  # pylint: disable=protected-access
        canvas.update_idletasks()
        canvas_height = canvas.winfo_height()
        scroll_top = canvas.canvasy(0)
        scroll_bottom = scroll_top + canvas_height

        widget_y = entry_widget.winfo_y() - ypad
        widget_height = entry_widget.winfo_height() + ypad

        if widget_y < scroll_top + top_buffer:
            target_y = max(0, widget_y - top_buffer)
            canvas.yview_moveto(target_y / scrollable_frame.winfo_height())
        elif (widget_y + widget_height) > scroll_bottom - bottom_buffer:
            target_y = widget_y - (canvas_height - widget_height - bottom_buffer)
            canvas.yview_moveto(target_y / scrollable_frame.winfo_height())

        focused_widget = self.focus_get()
        if focused_widget and focused_widget == entry.tk_focusNext():
            entry.tk_focusNext().focus()
        else:
            entry.tk_focusPrev().focus()

    def recompute_total_prepaid_cp(self):
        prepaid_total = sum(
            spec.get("prepaid", 0)
            for spec in lodging_specifications.values()
            if isinstance(spec.get("prepaid", 0), int)
        )
        if prepaid_total:
            budget_val = try_parse_int(self.cp_entry.get(), default=0)
            total_cp = budget_val + prepaid_total
            self.cp_prepaid_label.configure(
                text=f"+ Prepaid: {prepaid_total} = {total_cp}", text_color="white"
            )
        else:
            self.cp_prepaid_label.configure(text="")

    def validate_and_refresh_lodging(self, entry_var, label_widget, cost_label, town):
        self.validate_lodging(entry_var, label_widget, cost_label, town)
        self.recompute_total_prepaid_cp()

    def validate_lodging(self, entry_var, label_widget, cost_label, town):
        value = entry_var.get()

        if not value.isdigit():
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

        value = int(value)
        if value < 0:
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

        try:
            bonus = int(self.lodging_entries[town]["bonus"].get())  # ty:ignore[unresolved-attribute]
            reserved = int(self.lodging_entries[town]["reserved"].get())  # ty:ignore[unresolved-attribute]
        except ValueError as e:
            print("ValueError:", e)
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

        bonus_ub = lodging_specifications[town].get("bonus_ub", 0)
        has_warning = False
        warning_msg = ""
        if bonus > bonus_ub:
            warning_msg = f"Max bonus should be {bonus_ub}"
            has_warning = True

        try:
            if bonus > 0 or reserved > 0:
                max_ub = optimize_config["max_waypoint_ub"]
                assert isinstance(max_ub, int), "max_waypoint_ub must be an integer"

                tmp_spec = lodging_specifications[town].copy()
                tmp_spec["bonus"] = bonus
                tmp_spec["reserved"] = reserved

                region_data = get_region_lodging_bounds_costs(town, tmp_spec)
                prepaid = region_data["prepaid"]

                # Only update model on valid input and valid computation
                lodging_specifications[town]["bonus"] = bonus
                lodging_specifications[town]["reserved"] = reserved
                lodging_specifications[town]["prepaid"] = prepaid

                cost_label.set(str(prepaid))
                if has_warning:
                    label_widget.configure(text=warning_msg, text_color="orange")
                else:
                    label_widget.configure(text="Valid", text_color="green")

            else:
                # Zero input means valid but no cost
                lodging_specifications[town]["bonus"] = 0
                lodging_specifications[town]["reserved"] = 0
                lodging_specifications[town]["prepaid"] = 0
                cost_label.set("0")
                label_widget.configure(text="Optional", text_color="white")

        except Exception as e:  # noqa: BLE001
            print("Exception in validate_lodging:", e)
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

    def save_lodging_data(self, lodging_window):
        # Defensive sync from UI in case of stray edits or skipped validations
        for town, lodging_vars in self.lodging_entries.items():
            try:
                bonus_value = int(lodging_vars["bonus"].get())  # ty:ignore[unresolved-attribute]
                reserved_value = int(lodging_vars["reserved"].get())  # ty:ignore[unresolved-attribute]
                prepaid_value = int(lodging_vars["prepaid"].get())  # now stored as text variable  # ty:ignore[unresolved-attribute]

                lodging_specifications[town].update({
                    "bonus": bonus_value,
                    "reserved": reserved_value,
                    "prepaid": prepaid_value,
                })
            except ValueError as e:
                print(f"Warning: Could not parse lodging values for {town}: {e}")
                continue

        lodging_window.destroy()

        # Update lodging state only if any values are meaningful
        if any(d["bonus"] > 0 or d["reserved"] > 0 for d in lodging_specifications.values()):
            self.lodging_state = WidgetState.Ready
            self.lodging_status.configure(text=self.lodging_state.name, text_color="green")
        else:
            self.lodging_state = WidgetState.Optional
            self.lodging_status.configure(text=self.lodging_state.name, text_color="white")
        self.lodging_status.update()

    def import_lodging(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if file_path:
            with open(file_path, "r", encoding="utf-8") as file:
                loaded_data = json.load(file)
                lodging_specifications.update(loaded_data)
                for town, value in loaded_data.items():
                    if town in self.lodging_entries:
                        self.lodging_entries[town]["bonus"].set(value["bonus"])  # ty:ignore[unresolved-attribute]
                        self.lodging_entries[town]["reserved"].set(value["reserved"])  # ty:ignore[unresolved-attribute]
                        self.lodging_entries[town]["prepaid"].set(str(value["prepaid"]))  # ty:ignore[unresolved-attribute]
                        self.lodging_entries[town]["bonus_ub"] = value["bonus_ub"]
                        self.validate_lodging(
                            self.lodging_entries[town]["bonus"],
                            self.lodging_entries[town]["status"],
                            self.lodging_entries[town]["prepaid"],
                            town,
                        )
                self.recompute_total_prepaid_cp()
                self.update_optimize_button_state()

    def export_lodging(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")]
        )
        if file_path:
            export_data = {}
            for town, values in self.lodging_entries.items():
                try:
                    bonus = int(values["bonus"].get())  # ty:ignore[unresolved-attribute]
                    reserved = int(values["reserved"].get())  # ty:ignore[unresolved-attribute]
                    prepaid = int(values["prepaid"].get())  # ty:ignore[unresolved-attribute]
                    bonus_ub = values["bonus_ub"]
                    export_data[town] = {
                        "bonus": bonus,
                        "reserved": reserved,
                        "prepaid": prepaid,
                        "bonus_ub": bonus_ub,
                    }
                except ValueError as e:
                    print(f"Skipping {town} due to invalid data: {e}")
                    continue

            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(export_data, file, indent=4)

        self.update_optimize_button_state()

    def browse_outpath(self):
        file_path = filedialog.askdirectory()
        if file_path:
            self.outpath_entry.delete(0, ctk.END)
            self.outpath_entry.insert(0, file_path)
            self.validate_outpath(file_path)

    def browse_baseempire(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if file_path:
            self.baseempire_entry.delete(0, ctk.END)
            self.baseempire_entry.insert(0, file_path)
            self.validate_baseempire(file_path)

    def validate_cp(self):
        entry = self.cp_entry.get()
        if entry.isdigit():
            self.cp_state = WidgetState.Ready
            self.cp_status.configure(text=self.cp_state.name, text_color="green")
            status = True
        elif entry:
            self.cp_state = WidgetState.Error
            self.cp_status.configure(text=self.cp_state.name, text_color="red")
            status = False
        else:
            self.cp_state = WidgetState.Required
            self.cp_status.configure(text=self.cp_state.name)
            status = False

        self.recompute_total_prepaid_cp()
        self.update_optimize_button_state()
        return status

    def validate_prices(self, file_path):
        if Path(file_path).is_file():
            self.prices_state = WidgetState.Ready
            self.prices_status.configure(text=self.prices_state.name, text_color="green")
        else:
            self.prices_state = WidgetState.Error
            self.prices_status.configure(text=self.prices_state.name, text_color="red")
        self.prices_status.update()
        self.update_optimize_button_state()

    def validate_modifiers(self, file_path):
        if Path(file_path).is_file():
            self.modifiers_state = WidgetState.Ready
            self.modifiers_status.configure(text=self.modifiers_state.name, text_color="green")
        else:
            self.modifiers_state = WidgetState.Error
            self.modifiers_status.configure(text=self.modifiers_state.name, text_color="red")
        self.modifiers_status.update()
        self.update_optimize_button_state()

    def validate_outpath(self, file_path):
        if Path(file_path).exists():
            self.outpath_state = WidgetState.Ready
            self.outpath_status.configure(text=self.outpath_state.name, text_color="green")
        else:
            self.outpath_state = WidgetState.Error
            self.outpath_status.configure(text=self.outpath_state.name, text_color="red")
        self.modifiers_status.update()
        self.update_optimize_button_state()

    def validate_baseempire(self, file_path):
        if Path(file_path).is_file():
            self.baseempire_state = WidgetState.Ready
            self.baseempire_status.configure(text=self.baseempire_state.name, text_color="green")
        else:
            self.baseempire_state = WidgetState.Error
            self.baseempire_status.configure(text=self.baseempire_state.name, text_color="red")
        self.baseempire_status.update()
        self.update_optimize_button_state()

    def update_optimize_button_state(self):
        if self.cp_entry.get().isdigit():
            self.cp_state = WidgetState.Ready

        if (
            self.prices_state is WidgetState.Ready
            and self.modifiers_state is not WidgetState.Error
            and self.lodging_state is not WidgetState.Error
            and self.cp_state is WidgetState.Ready
            and self.outpath_state is WidgetState.Ready
        ):
            self.optimize_state = WidgetState.Ready
            self.optimize_button.configure(state=NORMAL)
        else:
            self.optimize_button.configure(state=DISABLED)
        self.optimize_button.update()

    def config_solver(self):
        config_window = ctk.CTkToplevel(self)
        config_window.title("Solver Configuration")
        config_window.geometry("400x320")
        config_window.update()
        config_window.grab_set()

        self.config_entries = {}

        for row, (setting, value) in enumerate(solver_config.items()):
            label = ctk.CTkLabel(config_window, text=setting)
            label.grid(row=row, column=0, padx=10, pady=5)

            entry_var = ctk.StringVar(value=str(value))
            entry = ctk.CTkEntry(config_window, textvariable=entry_var)
            ctktt(entry, message=solver_config_descriptions[setting])
            entry.grid(row=row, column=1, padx=10, pady=5)
            self.config_entries[setting] = entry_var

        config_window.protocol("WM_DELETE_WINDOW", lambda: self.save_config_data(config_window))

    def save_config_data(self, config_window):
        int_fields = ["num_processes", "random_seed"]
        for setting, var in self.config_entries.items():
            value = var.get()
            solver_config[setting] = (
                int(value)
                if setting in int_fields
                else ast.literal_eval(value)
                if value in ["True", "False"]
                else float(value)
            )
        config_window.destroy()

    def _optimize_worker(self):
        print("Begin optimization...")
        from bdo_empire.api_common import FARMING_WORKER_SILVER_PER_DAY_KEY

        self.solver_controller = SolverController()

        self.optimize_state = WidgetState.Running
        self.optimize_status.configure(text=self.optimize_state.name, text_color="green")
        self.optimize_status.update()

        config = optimize_config.copy()
        config["budget"] = int(self.cp_entry.get())
        config["solver"] = solver_config

        prices = json.loads(Path(self.prices_entry.get()).read_text(encoding="utf-8"))["effectivePrices"]
        farming_silver_per_day = json.loads(Path(self.prices_entry.get()).read_text(encoding="utf-8"))[
            FARMING_WORKER_SILVER_PER_DAY_KEY
        ]
        prices[FARMING_WORKER_SILVER_PER_DAY_KEY] = farming_silver_per_day

        modifiers = {}
        if self.modifiers_entry.get():
            data = json.loads(Path(self.modifiers_entry.get()).read_text(encoding="utf-8"))
            modifiers = data.get("regionResources") or data.get("regionModifiers", {})

        forcedTakenList = self.forced_taken_entries.get("keys", [])
        data = generate_reference_data(config, prices, modifiers, lodging_specifications, forcedTakenList)
        data = generate_graph_data(data)
        if self.baseempire_entry.get():
            data["base_empire"] = json.loads(Path(self.baseempire_entry.get()).read_text(encoding="utf-8"))
        else:
            data["base_empire"] = None

        highs_results = optimize_highspy(data, self.solver_controller)
        workerman_json = generate_workerman_data(highs_results, lodging_specifications, data)

        outpath = Path(self.outpath_entry.get())
        outfile = outpath.joinpath("optimized_empire.json")
        with open(outfile, "w", encoding="utf-8") as json_file:
            json.dump(workerman_json, json_file, indent=4)
        print("workerman json written to:", outfile)
        print("Completed.")

        self.optimize_state = WidgetState.Waiting
        self.optimize_status.configure(text=self.optimize_state.name)
        self.optimize_status.update()
        self.optimize_stop_button.configure(state=DISABLED)
        self.optimize_button.configure(state=NORMAL)

    def optimize(self):
        self.optimize_button.configure(state=DISABLED)
        self.optimize_stop_button.configure(state=NORMAL)
        Thread(target=self._optimize_worker, daemon=True).start()

    def stop_optimization(self):
        if self.solver_controller:
            print("Interrupt requested by user.")
            self.solver_controller.stop()


def main():
    config = {"logger": {"level": "INFO", "format": "<level>{message}</level>"}}
    set_logger(config)
    app = EmpireOptimizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
