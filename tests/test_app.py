from app import create_app


def test_app_factory_creates_app():
    app = create_app("testing")
    assert app is not None
    assert app.config["TESTING"] is True


def test_home_route_works():
    app = create_app("testing")
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
