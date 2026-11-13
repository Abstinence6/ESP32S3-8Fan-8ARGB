"""Local NWinfo provider controls: no fake sensors, safe stale-data semantics."""
from __future__ import annotations
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QGridLayout, QLabel, QPushButton, QVBoxLayout


PROVIDERS = {
    "CPU": "CPU · ядра/пакет",
    "GPU": "GPU · відеокарта",
    "SMART": "SMART · SSD/HDD",
    "DIMM": "DIMM · пам'ять",
    "INTEL": "Intel · PCH/GT",
    "ZEN": "AMD Zen · Tdie/CCD",
    "DISK": "Диски · IOPS/Latency",
}


class SensorManagerPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Менеджер джерел NWinfo")
        self.controller = controller
        sampler = controller.sensor_sampler
        stored = str(controller.settings.value("nwinfoProviders", ""))
        enabled = set(stored.split(",")) if stored else set(PROVIDERS)
        root = QVBoxLayout(self)
        note = QLabel(
            "Окреме опитування джерел. Проблемні драйвери отримують "
            "збільшені інтервали повторних спроб; дані старші 7 с не керують вентиляторами."
        )
        note.setWordWrap(True)
        note.setMinimumWidth(0)
        root.addWidget(note)
        row = QGridLayout()
        self.checkboxes = {}
        for index, (name, label) in enumerate(PROVIDERS.items()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(name in enabled)
            checkbox.setEnabled(name in sampler.permitted_providers)
            checkbox.toggled.connect(self._changed)
            row.addWidget(checkbox, index // 2, index % 2)
            self.checkboxes[name] = checkbox
        root.addLayout(row)
        second = QHBoxLayout()
        scan = QPushButton("Повторити опитування всіх")
        scan.clicked.connect(self.force_scan)
        second.addWidget(scan)
        second.addStretch()
        root.addLayout(second)
        self.status = QLabel("Активні джерела: —")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        root.addWidget(self.status)
        self._changed()

    def _changed(self, *_args) -> None:
        selected = {
            name for name, checkbox in self.checkboxes.items()
            if checkbox.isChecked() and checkbox.isEnabled()
        }
        self.controller.settings.setValue("nwinfoProviders", ",".join(sorted(selected)))
        self.controller.sensor_sampler.set_enabled(selected)
        self.status.setText("Активні: " + (", ".join(sorted(selected)) if selected else "жодного"))
        self.controller.sensor_sampler.refresh_all()

    def force_scan(self) -> None:
        self.controller.sensor_sampler.refresh_all()
        self.controller.refresh_temperatures()
