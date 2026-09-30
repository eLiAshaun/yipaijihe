import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 在导入 backend 之前把数据库指向临时文件，避免污染 instance/
_TMP = tempfile.mkdtemp(prefix="ypjh_test_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["LLM_API_KEY"] = ""
os.environ["DOUBAO_API_KEY"] = ""


@pytest.fixture(scope="session")
def app():
    from app import create_app

    return create_app()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth(client):
    """注册一个用户并返回带 Authorization 头的字典"""
    import uuid

    name = "u_" + uuid.uuid4().hex[:8]
    res = client.post("/api/auth/register", json={"username": name, "password": "secret123"})
    assert res.status_code == 201
    return {"Authorization": f"Bearer {res.get_json()['token']}", "username": name}
