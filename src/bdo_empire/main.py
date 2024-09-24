# main.py

import customtkinter as ctk
from CTkToolTip import CTkToolTip as ctktt
from enum import Enum
import json
from tkinter import DISABLED, NORMAL, filedialog
import os

from bdo_empire.initialize import initialize
from bdo_empire.optimize import optimize

purchased_lodging = {
    "Velia": 0,
    "Heidel": 0,
    "Glish": 0,
    "Calpheon City": 0,
    "Olvia": 0,
    "Keplan": 0,
    "Port Epheria": 0,
    "Trent": 0,
    "Iliya Island": 0,
    "Altinova": 0,
    "Tarif": 0,
    "Valencia City": 0,
    "Shakatu": 0,
    "Sand Grain Bazaar": 0,
    "Ancado Inner Harbor": 0,
    "Arehaza": 0,
    "Old Wisdom Tree": 0,
    "Grána": 0,
    "Duvencrune": 0,
    "O'draxxia": 0,
    "Eilton": 0,
    "Dalbeol Village": 0,
    "Nampo's Moodle Village": 0,
    "Nopsae's Byeot County": 0,
    "Muzgar": 0,
    "Yukjo Street": 0,
    "Godu Village": 0,
    "Bukpo": 0,
}


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

        self.create_widgets()

    def create_widgets(self):
        row = 0

        row += 1
        self.cp_label = ctk.CTkLabel(self, text="CP Limit")
        self.cp_label.grid(row=row, column=0, padx=10, pady=10)
        self.cp_entry = ctk.CTkEntry(self, validate="focusout", validatecommand=self.validate_cp)
        self.cp_entry.grid(row=row, column=1, padx=10, pady=10)
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
        self.lodging_button = ctk.CTkButton(
            self, text="Setup Purchased Lodging", command=self.setup_lodging
        )
        self.lodging_button.grid(row=row, column=1, padx=0, pady=10)
        self.lodging_status = ctk.CTkLabel(self, text=self.lodging_state.name)
        self.lodging_status.grid(row=row, column=3, padx=0, pady=10)
        ctktt(self.lodging_button, message="Setup loyalty and pearl shop lodging.")

        row += 1
        self.modifiers_label = ctk.CTkLabel(self, text="Modifiers")
        self.modifiers_label.grid(row=row, column=0, padx=10, pady=10)
        self.modifiers_entry = ctk.CTkEntry(self, width=300)
        self.modifiers_entry.grid(row=row, column=1, padx=10, pady=10)
        self.modifiers_button = ctk.CTkButton(
            self, text="Browse", command=self.browse_modifiers_file
        )
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
        self.optimize_button = ctk.CTkButton(
            self, text="Optimize", command=self.optimize, state=DISABLED
        )
        self.optimize_button.grid(row=row, column=1, padx=10, pady=10)
        self.optimize_status = ctk.CTkLabel(self, text=self.optimize_state.name)
        self.optimize_status.grid(row=row, column=3, padx=10, pady=10)

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
        global purchased_lodging

        def validate_entry(entry_var, label_widget):
            if entry_var.get().isdigit():
                label_widget.configure(text="Valid", text_color="green")
            else:
                label_widget.configure(text="Invalid", text_color="red")

        lodging_window = ctk.CTkToplevel(self)
        lodging_window.title("Purchased Lodging Setup")
        lodging_window.geometry("430x600")

        # Create a scrollable frame for the list of towns
        scrollable_frame = ctk.CTkScrollableFrame(lodging_window, width=400, height=500)
        scrollable_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10)

        # Bind mouse wheel scrolling for linux (WSL)
        scrollable_frame.bind_all(
            "<Button-4>", lambda e: scrollable_frame._parent_canvas.yview("scroll", -1, "units")
        )
        scrollable_frame.bind_all(
            "<Button-5>", lambda e: scrollable_frame._parent_canvas.yview("scroll", 1, "units")
        )

        # Create entries for each town inside the scrollable frame
        self.lodging_entries = {}
        row = 0
        for town, value in purchased_lodging.items():
            label = ctk.CTkLabel(scrollable_frame, text=town)
            label.grid(row=row, column=0, padx=10, pady=5)

            entry_var = ctk.StringVar(value=str(value))
            entry = ctk.CTkEntry(scrollable_frame, textvariable=entry_var)
            entry.grid(row=row, column=1, padx=10, pady=5)

            status_label = ctk.CTkLabel(scrollable_frame, text="Optional")
            status_label.grid(row=row, column=2, padx=10, pady=5)

            entry.bind("<Tab>", lambda e, entry=entry: self.check_scroll(entry, scrollable_frame))

            # I'm not sure if this will work on windows.
            entry.bind(
                "<ISO_Left_Tab>",
                lambda e, entry=entry: self.check_scroll(entry, scrollable_frame),
            )
            # But according to stackoverflow this does.
            entry.bind(
                "<Shift-KeyPress-Tab>",
                lambda e, entry=entry: self.check_scroll(entry, scrollable_frame),
            )

            entry.bind(
                "<FocusOut>", lambda e, var=entry_var, lbl=status_label: validate_entry(var, lbl)
            )

            self.lodging_entries[town] = entry_var
            row += 1

        import_button = ctk.CTkButton(lodging_window, text="Import", command=self.import_lodging)
        import_button.grid(row=1, column=0, padx=10, pady=10)
        export_button = ctk.CTkButton(lodging_window, text="Export", command=self.export_lodging)
        export_button.grid(row=1, column=1, padx=10, pady=10)

        lodging_window.protocol("WM_DELETE_WINDOW", lambda: self.save_lodging_data(lodging_window))

    def check_scroll(self, entry, scrollable_frame, ypad=10, top_buffer=40, bottom_buffer=40):
        entry_row = entry.grid_info()["row"]
        entry_widget = scrollable_frame.grid_slaves(row=entry_row, column=1)[0]

        canvas = scrollable_frame._parent_canvas
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

    def save_lodging_data(self, lodging_window):
        for town, var in self.lodging_entries.items():
            value = var.get()
            purchased_lodging[town] = int(value) if value.isdigit() else 0
        lodging_window.destroy()
        if any(v > 0 for v in purchased_lodging.values()):
            self.lodging_state = WidgetState.Ready
            self.lodging_status.configure(text=self.lodging_state.name, text_color="green")
            self.lodging_status.update()

    def import_lodging(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if file_path:
            with open(file_path, "r") as file:
                loaded_data = json.load(file)
                for town, value in loaded_data.items():
                    if town in self.lodging_entries:
                        self.lodging_entries[town].set(value)

    def export_lodging(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")]
        )
        if file_path:
            lodging_data = {town: var.get() for town, var in self.lodging_entries.items()}
            with open(file_path, "w") as file:
                json.dump(lodging_data, file, indent=4)

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
        self.update_optimize_button_state()
        return status

    def validate_prices(self, file_path):
        if os.path.isfile(file_path):
            self.prices_state = WidgetState.Ready
            self.prices_status.configure(text=self.prices_state.name, text_color="green")
        else:
            self.prices_state = WidgetState.Error
            self.prices_status.configure(text=self.prices_state.name, text_color="red")
        self.prices_status.update()
        self.update_optimize_button_state()

    def validate_modifiers(self, file_path):
        if os.path.isfile(file_path):
            self.modifiers_state = WidgetState.Ready
            self.modifiers_status.configure(text=self.modifiers_state.name, text_color="green")
        else:
            self.modifiers_state = WidgetState.Error
            self.modifiers_status.configure(text=self.modifiers_state.name, text_color="red")
        self.modifiers_status.update()
        self.update_optimize_button_state()

    def validate_outpath(self, file_path):
        if os.path.exists(file_path):
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

    def optimize(self):
        from math import inf
        from random import randint
        from psutil import cpu_count

        print("Begin optimization...")
        self.optimize_state = WidgetState.Running
        self.optimize_status.configure(text=self.optimize_state.name, text_color="green")
        self.optimize_status.update()

        cp_limit = int(self.cp_entry.get())

        config = {}
        config["name"] = "Empire"
        config["budget"] = cp_limit
        config["top_n"] = 4
        config["nearest_n"] = 5
        config["waypoint_ub"] = 25
        config["solver"] = {}
        config["solver"]["num_processes"] = max(1, cpu_count(logical=False) - 1)
        config["solver"]["mip_rel_gap"] = 1e-4
        config["solver"]["mip_feasibility_tolerance"] = 1e-4
        config["solver"]["primal_feasibility_tolerance"] = 1e-4
        config["solver"]["time_limit"] = inf
        config["solver"]["random_seed"] = randint(0, 2147483647)

        # Call optimizer
        with open(self.prices_entry.get(), "r") as file:
            prices = json.load(file)["effectivePrices"]
        if self.modifiers_entry.get():
            with open(self.modifiers_entry.get(), "r") as file:
                modifiers = json.load(file)["regionModifiers"]
        else:
            modifiers = {}

        lodging = purchased_lodging
        outpath = self.outpath_entry.get()

        optimize(config, prices, modifiers, lodging, outpath)

        # If successful reset to waiting
        self.optimize_state = WidgetState.Waiting
        self.optimize_status.configure(text=self.optimize_state.name)
        self.optimize_status.update()
        # Open a popup window stating optimization is complete and to import into workerman.

        # If not successful... well, that sucks.


def main():
    import sys

    if not initialize():
        print("Error acquiring workerman data. Can not start.")
        sys.exit(1)

    app = EmpireOptimizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
