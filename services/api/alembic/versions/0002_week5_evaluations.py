"""Add versioned evaluation suites, runs and case results."""

import sqlalchemy as sa
from alembic import op

revision = "0002_week5_evaluations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_case_columns = {
        item["name"] for item in inspector.get_columns("evaluation_cases")
    }
    columns = (
        sa.Column("acting_user_id", sa.String(36), nullable=True),
        sa.Column("expected_sources", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("forbidden_sources", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rubric", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_must_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for column in columns:
        if column.name not in existing_case_columns:
            op.add_column("evaluation_cases", column)
    case_indexes = {item["name"] for item in inspector.get_indexes("evaluation_cases")}
    if "ix_evaluation_cases_acting_user_id" not in case_indexes:
        op.create_index(
            "ix_evaluation_cases_acting_user_id", "evaluation_cases", ["acting_user_id"]
        )
    case_foreign_keys = {
        item["name"] for item in inspector.get_foreign_keys("evaluation_cases")
    }
    if (
        bind.dialect.name != "sqlite"
        and "fk_evaluation_cases_acting_user_id_users" not in case_foreign_keys
    ):
        op.create_foreign_key(
            "fk_evaluation_cases_acting_user_id_users",
            "evaluation_cases",
            "users",
            ["acting_user_id"],
            ["id"],
        )

    existing_tables = set(inspector.get_table_names())
    if "evaluation_suites" not in existing_tables:
        op.create_table(
        "evaluation_suites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "data_classification",
            sa.String(80),
            nullable=False,
            server_default="synthetic-company-neutral",
        ),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "version"),
        )
        op.create_index("ix_evaluation_suites_name", "evaluation_suites", ["name"])
    if "evaluation_runs" not in existing_tables:
        op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("suite_name", sa.String(120), nullable=False),
        sa.Column("suite_version", sa.String(40), nullable=False),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="running"),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gate_passed", sa.Boolean(), nullable=True),
        sa.Column("safe_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_evaluation_runs_suite_name", "evaluation_runs", ["suite_name"])
        op.create_index(
            "ix_evaluation_runs_requested_by_id", "evaluation_runs", ["requested_by_id"]
        )
        op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])
    if "evaluation_case_results" not in existing_tables:
        op.create_table(
        "evaluation_case_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("evaluation_cases.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actual_status", sa.String(40), nullable=False, server_default="failed"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_category", sa.String(80), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("safe_summary", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("run_id", "case_id"),
        )
        op.create_index(
            "ix_evaluation_case_results_run_id", "evaluation_case_results", ["run_id"]
        )
        op.create_index(
            "ix_evaluation_case_results_case_id", "evaluation_case_results", ["case_id"]
        )


def downgrade() -> None:
    op.drop_table("evaluation_case_results")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_suites")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_evaluation_cases_acting_user_id_users",
            "evaluation_cases",
            type_="foreignkey",
        )
    op.drop_index("ix_evaluation_cases_acting_user_id", table_name="evaluation_cases")
    with op.batch_alter_table("evaluation_cases") as batch_op:
        for column in (
            "is_must_pass",
            "ordinal",
            "rubric",
            "forbidden_sources",
            "expected_sources",
            "acting_user_id",
        ):
            batch_op.drop_column(column)
