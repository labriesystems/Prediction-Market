import os
import tempfile

import pytest

from app import app, init_db


@pytest.fixture()
def client():
    handle, path = tempfile.mkstemp()
    app.config.update(TESTING=True, DATABASE=path, SECRET_KEY="test")
    with app.app_context():
        init_db()
        from app import db
        db().execute("INSERT INTO markets(question,description,category,closes_at,resolution_source) VALUES(?,?,?,?,?)", ("Test question?", "Specific rule", "Test", "2099-01-01T00:00", "Test source"))
        db().commit()
    with app.test_client() as client:
        yield client
    os.close(handle)
    os.unlink(path)


def login(client):
    return client.post("/login", data={"username": "tester"}, follow_redirects=True)


def test_forecast_unlocks_market(client):
    login(client)
    hidden = client.get("/market/1")
    assert b"Market probability" not in hidden.data
    saved = client.post("/market/1/forecast", data={"probability": "70", "rationale": "Evidence"}, follow_redirects=True)
    assert b"Market probability" in saved.data
    assert b"70%" in saved.data


def test_trade_requires_forecast(client):
    login(client)
    response = client.post("/market/1/trade", data={"shares": "1", "side": "YES"})
    assert response.status_code == 403


def test_trade_updates_position(client):
    login(client)
    client.post("/market/1/forecast", data={"probability": "70"})
    result = client.post("/market/1/trade", data={"shares": "2", "side": "YES"}, follow_redirects=True)
    assert b"Bought 2 YES shares" in result.data
    assert b"YES \xc2\xb7 2.0 shares" in result.data
