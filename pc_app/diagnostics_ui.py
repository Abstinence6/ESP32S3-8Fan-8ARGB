"""Read-only, periodic hardware diagnostic dashboard."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView,
)
try:
    from .diagnostics import parse_health
except ImportError:
    from diagnostics import parse_health


class DiagnosticPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Автодіагностика · тільки читання")
        self.controller = controller
        self.records = {}
        root = QVBoxLayout(self)
        line = QHBoxLayout()
        self.label = QLabel("Перевірка не виконувалася")
        line.addWidget(self.label, 1)
        refresh = QPushButton("Перевірити 8 каналів")
        refresh.clicked.connect(self.refresh)
        line.addWidget(refresh)
        save = QPushButton("Експорт діагностики")
        save.clicked.connect(self.export)
        line.addWidget(save)
        root.addLayout(line)
        self.table = QTableWidget(8, 8)
        self.table.setHorizontalHeaderLabels(
            ["Канал", "PWM", "RPM", "TACH", "Джерело", "Вік, мс", "Fail-safe", "Оцінка"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for i in range(8):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            for col in range(1, 8):
                self.table.setItem(i, col, QTableWidgetItem("—"))
        self.table.setMaximumHeight(300)
        root.addWidget(self.table)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh)
        self.poll_timer.start(15000)

    def refresh(self) -> None:
        if self.controller.port:
            self.records.clear()
            self.controller.send("HEALTH")

    def handle_line(self, line: str) -> bool:
        health = parse_health(line)
        if health is None:
            if line == "HEALTH_END":
                count = sum(bool(r.fault or not r.fresh) for r in self.records.values())
                self.label.setText(f"Перевірено {len(self.records)}/8 · проблемні канали: {count}")
                return True
            return False
        self.records[health.channel] = health
        row = health.channel - 1
        for col, value in enumerate((
            f"{health.pwm}%", str(health.rpm), health.tach,
            health.source, str(health.age_ms) if health.age_ms is not None else "—",
            health.failsafe, health.assessment,
        ), 1):
            self.table.setItem(row, col, QTableWidgetItem(value))
        return True

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Експорт стану ESP32",
                                              "fanargb-diagnostics.json", "JSON (*.json)")
        if not path:
            return
        try:
            data = {
                "schema": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
                "fans": [asdict(self.records[i]) for i in sorted(self.records)],
                "hardware_temp": getattr(self.controller, "_last_hwtemp_line", ""),
            }
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.label.setText("Діагностику збережено")
        except OSError as exc:
            self.label.setText(f"Не вдалося зберегти: {exc}")
