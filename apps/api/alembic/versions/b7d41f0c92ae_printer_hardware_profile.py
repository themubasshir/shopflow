"""Printer hardware profile: model, density, feed distance and capabilities.

Phase 2D-3 prepares real-printer acceptance. The queue already carried the
raster calibration (dot width + DPI); this revision adds the rest of the
hardware identity an installer has to record before a device is signed off:

* ``device_model``  — vendor/model string for the acceptance checklist.
* ``density``       — 1..8 print-density level (4 is neutral, the previous
  threshold, so existing rows rasterize exactly as before).
* ``feed_dots``     — ESC ``d`` feed distance after the raster, in dots.
* ``capabilities``  — JSONB flags (``raster``/``character``); only raster is
  implemented by the agent.

``print_jobs`` snapshots ``density`` and ``feed_dots`` next to the existing
``dots_width``/``dpi`` so a later printer edit cannot change an in-flight job.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d41f0c92ae"
down_revision: str = "04a62d5abb9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("printers", sa.Column("device_model", sa.String(length=120), nullable=True))
    op.add_column(
        "printers",
        sa.Column("density", sa.Integer(), server_default="4", nullable=False),
    )
    op.add_column(
        "printers",
        sa.Column("feed_dots", sa.Integer(), server_default="90", nullable=False),
    )
    op.add_column(
        "printers",
        sa.Column("capabilities", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.create_check_constraint("density_range", "printers", "density BETWEEN 1 AND 8")
    op.create_check_constraint("feed_dots_range", "printers", "feed_dots BETWEEN 0 AND 255")

    op.add_column(
        "print_jobs",
        sa.Column("density", sa.Integer(), server_default="4", nullable=False),
    )
    op.add_column(
        "print_jobs",
        sa.Column("feed_dots", sa.Integer(), server_default="90", nullable=False),
    )
    op.create_check_constraint("density_range", "print_jobs", "density BETWEEN 1 AND 8")
    op.create_check_constraint("feed_dots_range", "print_jobs", "feed_dots BETWEEN 0 AND 255")


def downgrade() -> None:
    op.drop_constraint("feed_dots_range", "print_jobs", type_="check")
    op.drop_constraint("density_range", "print_jobs", type_="check")
    op.drop_column("print_jobs", "feed_dots")
    op.drop_column("print_jobs", "density")

    op.drop_constraint("feed_dots_range", "printers", type_="check")
    op.drop_constraint("density_range", "printers", type_="check")
    op.drop_column("printers", "capabilities")
    op.drop_column("printers", "feed_dots")
    op.drop_column("printers", "density")
    op.drop_column("printers", "device_model")
