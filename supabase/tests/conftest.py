"""Fixtures for the database tests. Helpers live in dbtools.py so other test suites can reuse them."""
import uuid

import pytest

from dbtools import Db, Shop, build_database, drop_database


@pytest.fixture(scope="session")
def db_url():
    name = "v4_test_" + uuid.uuid4().hex[:10]
    url = build_database(name)
    yield url
    drop_database(name)


@pytest.fixture
def db(db_url):
    d = Db(db_url)
    yield d
    d.close()


@pytest.fixture
def new_conn(db_url):
    """Factory for extra connections (concurrency tests)."""
    made = []

    def make():
        d = Db(db_url)
        made.append(d)
        return d

    yield make
    for d in made:
        d.close()


@pytest.fixture
def shop(db):
    return Shop(db)


@pytest.fixture
def make_shop(db):
    return lambda: Shop(db)
