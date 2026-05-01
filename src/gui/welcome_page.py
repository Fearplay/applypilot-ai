"""Landing screen with quick-start instructions and a 'Use sample data' shortcut."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class WelcomePage(QWidget):
    start_clicked = Signal()
    load_sample_clicked = Signal()
    open_settings_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(18)

        title = QLabel("ApplyPilot AI")
        title.setStyleSheet("font-size: 32px; font-weight: 700; color: #e8e8ee;")
        layout.addWidget(title)

        subtitle = QLabel("Job URL to Tailored Resume &amp; Cover Letter")
        subtitle.setStyleSheet("font-size: 16px; color: #a8a8b3;")
        layout.addWidget(subtitle)

        intro = QLabel(
            "Paste a job URL, drop your CV (optionally a LinkedIn export and a "
            "GitHub username), and the app will produce an ATS-friendly resume, "
            "a tailored cover letter, a match report, interview prep and a skill "
            "gap plan."
            "<br><br>"
            "Every claim in the generated documents must be backed by evidence "
            "from your inputs - the app will ask you clarifying questions instead "
            "of inventing experience."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setStyleSheet("color: #c2c5cf; font-size: 14px;")
        layout.addWidget(intro)

        steps = QFrame()
        steps.setObjectName("StepsCard")
        steps.setStyleSheet(
            "#StepsCard { background: #2a2d35; border-radius: 10px; padding: 14px;"
            " border: 1px solid #3a3d45; }"
            "QLabel { color: #c2c5cf; }"
        )
        steps_layout = QVBoxLayout(steps)
        for i, text in enumerate(
            [
                "Paste the job URL or the description text",
                "Upload your CV (PDF / DOCX / TXT) and optional LinkedIn / GitHub",
                "Answer clarifying questions if anything is missing",
                "Review the match report",
                "Edit and export the tailored resume + cover letter",
            ],
            start=1,
        ):
            steps_layout.addWidget(QLabel(f"<b>{i}.</b> &nbsp; {text}"))
        layout.addWidget(steps)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        start = QPushButton("Start a new application")
        start.setMinimumHeight(38)
        start.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        start.clicked.connect(self.start_clicked.emit)
        start.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none;"
            " border-radius: 6px; font-weight: 600; padding: 8px 18px; }"
            "QPushButton:hover { background: #2c7df0; }"
        )
        buttons.addWidget(start)

        sample = QPushButton("Try with sample data")
        sample.setMinimumHeight(38)
        sample.clicked.connect(self.load_sample_clicked.emit)
        buttons.addWidget(sample)

        settings = QPushButton("AI provider settings...")
        settings.setMinimumHeight(38)
        settings.clicked.connect(self.open_settings_clicked.emit)
        buttons.addWidget(settings)

        layout.addLayout(buttons)
        layout.addStretch(1)


__all__ = ["WelcomePage"]
