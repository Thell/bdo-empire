# main.py

from enum import Enum
import json
from math import inf
from pathlib import Path
from random import randint
from tkinter import DISABLED, NORMAL, filedialog

import customtkinter as ctk
from CTkToolTip import CTkToolTip as ctktt
from psutil import cpu_count

from bdo_empire.generate_graph_data import generate_graph_data
from bdo_empire.generate_reference_data import generate_reference_data
from bdo_empire.generate_reference_data import get_region_lodging_bounds_costs
from bdo_empire.generate_workerman_data import generate_workerman_data
from bdo_empire.optimize import optimize


optimize_config = {
    "name": "Empire",
    "budget": 0,
    "top_n": 4,
    "nearest_n": 5,
    "max_waypoint_ub": 25,
    "solver_config": {}
}


solver_config = {
    "num_processes": max(1, cpu_count(logical=False) - 1), # type: ignore
    "mip_rel_gap": 1e-4,
    "mip_feasibility_tolerance": 1e-4,
    "primal_feasibility_tolerance": 1e-4,
    "time_limit": inf,
    "random_seed": randint(0, 2147483647),
}


lodging_specifications = {
    "Velia": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Heidel": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Glish": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Calpheon City": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Olvia": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Keplan": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Port Epheria": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Trent": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Iliya Island": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 0},
    "Altinova": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 7},
    "Tarif": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Valencia City": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Shakatu": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Sand Grain Bazaar": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Ancado Inner Harbor": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 0},
    "Arehaza": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Old Wisdom Tree": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Grána": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "Duvencrune": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 6},
    "O'draxxia": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 8},
    "Eilton": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Dalbeol Village": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Nampo's Moodle Village": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Nopsae's Byeot County": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Asparkan": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Muzgar": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Yukjo Street": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Godu Village": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
    "Bukpo": {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": 5},
}

# TODO: Implement solver setup for forced investment nodes.
grindTakenList = []


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


class EmpireOptimizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Empire Optimizer")
        self.geometry("660x300")

        self.data_state = WidgetState.Required
        self.prices_state = WidgetState.Required
        self.modifiers_state = WidgetState.Optional
        self.lodging_state = WidgetState.Optional
        self.cp_state = WidgetState.Required
        self.outpath_state = WidgetState.Required
        self.optimize_state = WidgetState.Waiting
        self.lodging_entries = {}
        self.config_entries = {}

        self.create_widgets()

    def create_widgets(self):
        row = 0

        row += 1
        self.cp_label = ctk.CTkLabel(self, text="CP Limit")
        self.cp_label.grid(row=row, column=0, padx=10, pady=10)
        self.cp_entry = ctk.CTkEntry(self, validate="focusout", validatecommand=self.validate_cp)
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
        self.outpath_label = ctk.CTkLabel(self, text="Output Path")
        self.outpath_label.grid(row=row, column=0, padx=10, pady=10)
        self.outpath_entry = ctk.CTkEntry(self, width=300)
        self.outpath_entry.grid(row=row, column=1, padx=10, pady=10)
        self.outpath_button = ctk.CTkButton(self, text="Browse", command=self.browse_outpath)
        self.outpath_button.grid(row=row, column=2, padx=10, pady=10)
        self.outpath_status = ctk.CTkLabel(self, text=self.outpath_state.name)
        self.outpath_status.grid(row=row, column=3, padx=10, pady=10)

        row += 1
        self.optimize_button = ctk.CTkButton(self, text="Optimize", command=self.optimize, state=DISABLED)
        self.optimize_button.grid(row=row, column=1, padx=10, pady=10)
        self.optimize_status = ctk.CTkLabel(self, text=self.optimize_state.name)
        self.optimize_status.grid(row=row, column=3, padx=10, pady=10)
        self.config_button = ctk.CTkButton(self, text="Config Solver", command=self.config_solver)
        self.config_button.grid(row=row, column=2, padx=10, pady=10)

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

    def setup_lodging(self):
        lodging_window = ctk.CTkToplevel(self)
        lodging_window.title("Initial Lodging Setup")
        lodging_window.geometry("700x600")
        lodging_window.update()
        lodging_window.grab_set()

        scrollable_frame = ctk.CTkScrollableFrame(lodging_window, width=670, height=500)
        scrollable_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10)

        # Bind mouse wheel scrolling for linux (WSL)
        scrollable_frame.bind_all(
            "<Button-4>", lambda e: scrollable_frame._parent_canvas.yview("scroll", -1, "units")  # pylint: disable=protected-access
        )
        scrollable_frame.bind_all(
            "<Button-5>", lambda e: scrollable_frame._parent_canvas.yview("scroll", 1, "units")   # pylint: disable=protected-access
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
                self.validate_lodging(var, status_label, prepaid_var, town)
            return handler

        self.lodging_entries = {}
        row = 1
        for town, values in lodging_specifications.items():
            bonus = values["bonus"]
            reserved = values["reserved"]
            prepaid = values["prepaid"]

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
            reserved_entry.bind("<FocusOut>", make_validate_handler(reserved_var, status_label, prepaid_var, town))

            self.lodging_entries[town] = {
                "bonus": bonus_var,
                "reserved": reserved_var,
                "prepaid": prepaid_var,
            }
            row += 1

        import_button = ctk.CTkButton(lodging_window, text="Import", command=self.import_lodging)
        import_button.grid(row=1, column=0, padx=10, pady=10)
        export_button = ctk.CTkButton(lodging_window, text="Export", command=self.export_lodging)
        export_button.grid(row=1, column=1, padx=10, pady=10)

        lodging_window.protocol("WM_DELETE_WINDOW", lambda: self.save_lodging_data(lodging_window))

    def check_scroll(self, entry, scrollable_frame, ypad=10, top_buffer=40, bottom_buffer=40):
        entry_row = entry.grid_info()["row"]
        entry_widget = scrollable_frame.grid_slaves(row=entry_row, column=1)[0]

        canvas = scrollable_frame._parent_canvas # pylint: disable=protected-access
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
            spec.get("prepaid", 0) for spec in lodging_specifications.values()
            if isinstance(spec.get("prepaid", 0), int)
        )
        if prepaid_total:
            budget_val = try_parse_int(self.cp_entry.get(), default=0)
            total_cp = budget_val + prepaid_total
            self.cp_prepaid_label.configure(
                text=f"+ Prepaid: {prepaid_total} = {total_cp}",
                text_color="white"
            )
        else:
            self.cp_prepaid_label.configure(text="")

    def validate_lodging(self, entry_var, label_widget, cost_label, town):
        value = entry_var.get()

        if not value.isdigit():
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

        try:
            bonus = int(self.lodging_entries[town]["bonus"].get())
            reserved = int(self.lodging_entries[town]["reserved"].get())
        except ValueError as e:
            print("ValueError:", e)
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

        bonus_ub = lodging_specifications[town].get("bonus_ub", 0)
        if bonus > bonus_ub:
            label_widget.configure(
                text=f"Max bonus is {bonus_ub}", text_color="orange"
            )
            cost_label.set("—")
            return

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
                label_widget.configure(text="Valid", text_color="green")

            else:
                # Zero input means valid but no cost
                lodging_specifications[town]["bonus"] = 0
                lodging_specifications[town]["reserved"] = 0
                lodging_specifications[town]["prepaid"] = 0
                cost_label.set("0")
                label_widget.configure(text="Valid", text_color="green")

        except Exception as e:
            print("Exception in validate_lodging:", e)
            label_widget.configure(text="Invalid", text_color="red")
            cost_label.set("—")
            return

        # Always refresh total CP label based on valid specs
        self.recompute_total_prepaid_cp()

    def save_lodging_data(self, lodging_window):
        # Defensive sync from UI in case of stray edits or skipped validations
        for town, lodging_vars in self.lodging_entries.items():
            try:
                bonus_value = int(lodging_vars["bonus"].get())
                reserved_value = int(lodging_vars["reserved"].get())
                prepaid_value = int(lodging_vars["prepaid"].get())  # now stored as text variable

                lodging_specifications[town].update({
                    "bonus": bonus_value,
                    "reserved": reserved_value,
                    "prepaid": prepaid_value
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
            self.lodging_state = WidgetState.Required
            self.lodging_status.configure(text=self.lodging_state.name, text_color="gray")

        self.lodging_status.update()

    def import_lodging(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if file_path:
            with open(file_path, "r", encoding="utf-8") as file:
                loaded_data = json.load(file)
                lodging_specifications.update(loaded_data)
                for town, value in loaded_data.items():
                    if town in self.lodging_entries:
                        self.lodging_entries[town]["bonus"].set(value["bonus"])
                        self.lodging_entries[town]["reserved"].set(value["reserved"])
                        self.lodging_entries[town]["prepaid"].set(str(value["prepaid"]))
                self.update_optimize_button_state()

    def export_lodging(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")]
        )
        if file_path:
            export_data = {}
            for town, values in self.lodging_entries.items():
                try:
                    bonus = int(values["bonus"].get())
                    reserved = int(values["reserved"].get())
                    prepaid = int(values["prepaid"].get())
                    export_data[town] = {
                        "bonus": bonus,
                        "reserved": reserved,
                        "prepaid": prepaid
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
        config_window.geometry("400x250")
        config_window.update()
        config_window.grab_set()

        self.config_entries = {}
        row = 0
        for setting, value in solver_config.items():
            label = ctk.CTkLabel(config_window, text=setting)
            label.grid(row=row, column=0, padx=10, pady=5)

            entry_var = ctk.StringVar(value=str(value))
            entry = ctk.CTkEntry(config_window, textvariable=entry_var)
            entry.grid(row=row, column=1, padx=10, pady=5)

            self.config_entries[setting] = entry_var
            row += 1
        config_window.protocol("WM_DELETE_WINDOW", lambda: self.save_config_data(config_window))

    def save_config_data(self, config_window):
        int_fields = ["num_processes", "random_seed"]
        for setting, var in self.config_entries.items():
            value = var.get()
            solver_config[setting] = int(value) if setting in int_fields else float(value)
        config_window.destroy()

    def optimize(self):
        print("Begin optimization...")
        self.optimize_state = WidgetState.Running
        self.optimize_status.configure(text=self.optimize_state.name, text_color="green")
        self.optimize_status.update()

        config = optimize_config.copy()
        config["budget"] = int(self.cp_entry.get())
        config["solver"] = solver_config

        prices = json.loads(Path(self.prices_entry.get()).read_text(encoding="utf-8"))["effectivePrices"]
        modifiers = (
            json.loads(Path(self.modifiers_entry.get()).read_text(encoding="utf-8"))["regionModifiers"]
            if self.modifiers_entry.get()
            else {}
        )

        data = generate_reference_data(config, prices, modifiers, lodging_specifications, grindTakenList)
        graph_data = generate_graph_data(data)
        prob = optimize(data, graph_data)
        workerman_json = generate_workerman_data(prob, lodging_specifications, data, graph_data)

        outpath = Path(self.outpath_entry.get())
        outfile = outpath.joinpath("optimized_empire.json")
        with open(outfile, "w", encoding="utf-8") as json_file:
            json.dump(workerman_json, json_file, indent=4)
        print("workerman json written to:", outfile)
        print("Completed.")

        self.optimize_state = WidgetState.Waiting
        self.optimize_status.configure(text=self.optimize_state.name)
        self.optimize_status.update()


def main():
    app = EmpireOptimizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
