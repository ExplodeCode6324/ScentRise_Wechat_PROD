import os

import bcrypt
import pytest

os.environ.update(
    TESTING="1",
    DATABASE_URL="sqlite:///:memory:",
    JWT_SECRET="test-only-secret-with-more-than-thirty-two-bytes",
    AUTO_CREATE_TABLES="0",
)

from wxcloudrun import app, db  # noqa: E402
from wxcloudrun.model import Admin  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client():
    return app.test_client()


@pytest.fixture()
def app_context():
    with app.app_context():
        yield


@pytest.fixture()
def make_admin(app_context):
    def create(username="admin", password="strong-test-password", role="admin"):
        admin = Admin(
            username=username,
            passwd=bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode(),
            role=role,
            is_active=True,
        )
        db.session.add(admin)
        db.session.commit()
        return admin

    return create


@pytest.fixture()
def login(client, make_admin):
    def perform(username="admin", password="strong-test-password", role="admin"):
        make_admin(username, password, role)
        response = client.post(
            "/api/admin/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200
        return response

    return perform
