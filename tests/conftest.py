import os
import tempfile
import pytest
import database


@pytest.fixture(autouse=True)
def temp_db():
    """Every test gets a fresh temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database.set_db_path(path)
    database.init_db()
    yield path
    os.unlink(path)
