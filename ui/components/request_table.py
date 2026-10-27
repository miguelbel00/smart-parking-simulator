"""Request lifecycle tracking table component."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ui.components.theme import (
    COLOR_AVAILABLE,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_INFO_BG,
    COLOR_LOG_BG,
    COLOR_OCCUPIED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    font_family,
)
from ui.projection import ParkingProjection, RequestRecord


class RequestTrackingTableWidget(tk.Frame):
    """Table tracking the full lifecycle of every vehicle request in the run.

    Columns:
    - ID (`id`)
    - Placa (`plate`)
    - Puesto autorizado (`authorized_slot`)
    - Puesto ocupado (`occupied_slot`)
    - Estado / Resultado (`state`)
    - Tiempo de espera (`waiting_time`)
    - Motivo (`reason`)

    Retains finished, cancelled, and rejected rows so the user can inspect
    the full run history without relying solely on raw logs.
    """

    COLUMNS = (
        ("id", "ID", 52, "center"),
        ("plate", "Placa", 88, "center"),
        ("authorized_slot", "Puesto Aut.", 86, "center"),
        ("occupied_slot", "Puesto Ocup.", 88, "center"),
        ("state", "Estado / Resultado", 118, "center"),
        ("waiting_time", "Espera", 74, "e"),
        ("reason", "Motivo", 130, "w"),
    )

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
            **kwargs,
        )
        self._row_ids: dict[int, str] = {}

        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 6))

        tk.Label(
            header,
            text="SEGUIMIENTO DE SOLICITUDES (ciclo de vida en tiempo real)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        ).pack(side="left")

        self._lbl_summary = tk.Label(
            header,
            text="0 solicitudes registradas",
            bg=COLOR_BG_PRIMARY,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
            padx=6,
            pady=1,
        )
        self._lbl_summary.pack(side="right")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Parking.Treeview",
            background=COLOR_LOG_BG,
            fieldbackground=COLOR_LOG_BG,
            foreground=COLOR_TEXT_PRIMARY,
            rowheight=23,
            borderwidth=0,
            font=(font_family(self), 8),
        )
        style.configure(
            "Parking.Treeview.Heading",
            background=COLOR_BG_PRIMARY,
            foreground=COLOR_TEXT_MUTED,
            relief="flat",
            font=(font_family(self), 8, "bold"),
        )
        style.map(
            "Parking.Treeview",
            background=[("selected", COLOR_INFO_BG)],
            foreground=[("selected", COLOR_TEXT_PRIMARY)],
        )

        table_frame = tk.Frame(self, bg=COLOR_LOG_BG)
        table_frame.pack(fill="both", expand=True)

        col_ids = tuple(col[0] for col in self.COLUMNS)
        self._tree = ttk.Treeview(
            table_frame,
            columns=col_ids,
            show="headings",
            height=6,
            style="Parking.Treeview",
        )
        self._vscroll = tk.Scrollbar(
            table_frame, orient="vertical", command=self._tree.yview
        )
        self._tree.configure(yscrollcommand=self._vscroll.set)

        for col_id, heading, width, anchor in self.COLUMNS:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=48, anchor=anchor, stretch=True)

        self._tree.pack(side="left", fill="both", expand=True)
        self._vscroll.pack(side="right", fill="y")

        # Color tags per lifecycle state
        self._tree.tag_configure("CREATED", foreground="#cbd5e1")
        self._tree.tag_configure("WAITING", foreground=COLOR_WAITING)
        self._tree.tag_configure("ENTERED", foreground=COLOR_AVAILABLE)
        self._tree.tag_configure("EXITED", foreground="#c084fc")
        self._tree.tag_configure("FINISHED", foreground=COLOR_INFO)
        self._tree.tag_configure("CANCELLED", foreground="#fb923c")
        self._tree.tag_configure("REJECTED", foreground=COLOR_OCCUPIED)

    def upsert_record(self, record: RequestRecord) -> None:
        """Insert or update a single request row in the table."""
        values = record.as_table_row()
        tag = record.state if record.state in {
            "CREATED", "WAITING", "ENTERED", "EXITED", "FINISHED", "CANCELLED", "REJECTED"
        } else "CREATED"
        iid = self._row_ids.get(record.vehicle_id)
        if iid is not None and self._tree.exists(iid):
            self._tree.item(iid, values=values, tags=(tag,))
        else:
            iid = f"req-{record.vehicle_id}"
            self._tree.insert("", "end", iid=iid, values=values, tags=(tag,))
            self._row_ids[record.vehicle_id] = iid
            self._tree.see(iid)
        count = len(self._row_ids)
        self._lbl_summary.config(
            text=f"{count} solicitud{'es' if count != 1 else ''} registrada{'s' if count != 1 else ''}"
        )

    def sync_from_projection(self, projection: ParkingProjection) -> None:
        """Synchronize all rows from `projection.requests` in observation order."""
        existing_ids = set(projection.requests.keys())
        if not existing_ids and self._row_ids:
            self.clear()
            return
        for record in projection.requests.values():
            self.upsert_record(record)

    def rows(self) -> list[tuple[str, ...]]:
        """Return currently displayed table rows in order."""
        return [
            tuple(str(val) for val in self._tree.item(iid, "values"))
            for iid in self._tree.get_children("")
        ]

    def clear(self) -> None:
        """Clear all rows from the table at the start of a new run."""
        for iid in self._tree.get_children(""):
            self._tree.delete(iid)
        self._row_ids.clear()
        self._lbl_summary.config(text="0 solicitudes registradas")


__all__ = ["RequestTrackingTableWidget"]
