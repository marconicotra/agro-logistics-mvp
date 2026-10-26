import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]


def _load_revision(revision: str):
    path = ROOT / "migrations" / "versions" / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(revision, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_geography_is_staged_inactive_and_keeps_province_aliases() -> None:
    first = _load_revision("0017_managed_catalogs")
    second = _load_revision("0018_jauregui_geo_localities")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                first.upgrade()
                second.upgrade()
            counts = connection.execute(
                text(
                    "select source, active, count(*) from geographic_catalog "
                    "where source = 'JAUREGUI_LORDA' group by source, active"
                )
            ).all()
            assert counts == [("JAUREGUI_LORDA", 0, 773)]
            assert connection.execute(
                text(
                    "select count(*) from geographic_catalog imported "
                    "join geographic_catalog province on imported.parent_id = province.id "
                    "where imported.source = 'JAUREGUI_LORDA' and imported.kind = 'LOCALITY' "
                    "and imported.georef_id is null and province.kind = 'PROVINCE' and imported.active = 0"
                )
            ).scalar_one() == 773
            aliases = connection.execute(
                text("select name, aliases from geographic_catalog where kind = 'PROVINCE'")
            ).all()
            alias_text = " ".join(f"{name} {value}" for name, value in aliases)
            assert "CABA" in alias_text
            assert "Tierra del Fuego" in alias_text
            with Operations.context(context):
                second.downgrade()
            assert connection.execute(
                text("select count(*) from geographic_catalog where source = 'JAUREGUI_LORDA'")
            ).scalar_one() == 0
            aliases_after_rollback = connection.execute(
                text("select aliases from geographic_catalog where kind = 'PROVINCE'")
            ).all()
            assert "CABA" not in " ".join(str(row[0]) for row in aliases_after_rollback)
            assert "Tierra del Fuego" not in " ".join(str(row[0]) for row in aliases_after_rollback)
    finally:
        engine.dispose()
