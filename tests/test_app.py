import os
import tempfile

import pytest

from app import app, db, init_db


@pytest.fixture()
def client():
    handle, path = tempfile.mkstemp()

      app.config.update(
        TESTING=True,
        DATABASE=path,
        SECRET_KEY="test",
        CSRF_ENABLED=False,
    )

    with app.app_context():
        init_db()

        db().execute(
            """
            INSERT INTO markets
            (
                question,
                description,
                category,
                closes_at,
                resolution_source
            )
            VALUES(?,?,?,?,?)
            """,
            (
                "Test market?",
                "Test description",
                "Test",
                "2099-01-01T00:00",
                "Test source",
            ),
        )

        db().commit()

    with app.test_client() as test_client:
        yield test_client

    os.close(handle)
    os.unlink(path)


def register(client):
    return client.post(
        "/register",
        data={
            "username": "tester",
            "password": "testpassword123",
        },
        follow_redirects=True,
    )


def test_register(client):
    response = register(client)

    assert response.status_code == 200
    assert b"Your predictions." in response.data


def test_login(client):
    register(client)

    client.post(
        "/logout",
        follow_redirects=True,
    )

    response = client.post(
        "/login",
        data={
            "username": "tester",
            "password": "testpassword123",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Your predictions." in response.data


def test_create_forecast(client):
    register(client)

    response = client.post(
        "/forecast/new",
        data={
            "question": "Will the test pass?",
            "probability": "70",
            "category": "Testing",
            "notes": "Test forecast",
            "resolves_at": "2099-01-01",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Will the test pass?" in response.data
    assert b"70%" in response.data
    assert b"Test forecast" in response.data


def test_resolve_forecast(client):
    register(client)

    client.post(
        "/forecast/new",
        data={
            "question": "Will this resolve?",
            "probability": "80",
            "category": "Testing",
        },
    )

    response = client.post(
        "/forecast/1/resolve",
        data={"outcome": "1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Outcome" in response.data
    assert b"YES" in response.data


def test_market_available_without_forecast(client):
    register(client)

    response = client.get("/market/1")

    assert response.status_code == 200
    assert b"Test market?" in response.data
    assert b"Buy YES" in response.data
    assert b"Buy NO" in response.data


def test_trade_without_forecast(client):
    register(client)

    response = client.post(
        "/market/1/trade",
        data={
            "shares": "2",
            "side": "YES",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Bought 2 YES shares" in response.data
    assert b"2.0 shares" in response.data


def test_results_after_resolution(client):
    register(client)

    client.post(
        "/forecast/new",
        data={
            "question": "Results test?",
            "probability": "75",
            "category": "Testing",
        },
    )

    client.post(
        "/forecast/1/resolve",
        data={"outcome": "1"},
    )

    response = client.get("/profile")

    assert response.status_code == 200
    assert b"Resolved predictions" in response.data
    assert b"0.062" in response.data
