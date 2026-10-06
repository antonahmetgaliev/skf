"""Date backfilled BWP points by their verdict.

The BWP backfill issued points for old penalties with the day it was run as
the issue date, so penalties from spring 2026 became active again for 90 days
(the run of 2026-09-22). A point issued by publishing a window follows its
verdict within days; one that trails it by more than a month came from the
backfill and is moved back to the verdict's day.

Revision ID: 036
Revises: 035
"""

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE bwp_points p
        SET issued_on = (r.resolved_at AT TIME ZONE 'UTC')::date,
            expires_on = (r.resolved_at AT TIME ZONE 'UTC')::date + 90
        FROM incident_resolutions r
        WHERE r.applied_bwp_point_id = p.id
          AND p.issued_on - (r.resolved_at AT TIME ZONE 'UTC')::date > 30
        """
    )


def downgrade() -> None:
    # The wrong dates are not worth restoring.
    pass
