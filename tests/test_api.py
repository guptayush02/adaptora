import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    """Test health check endpoint"""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "endpoints" in data


@pytest.mark.asyncio
async def test_process_simple_prompt():
    """Test processing a simple prompt"""
    payload = {
        "prompt": "What is 2+2?",
        "model": "ollama",
        "temperature": 0.7,
        "user_id": "test_user",
    }

    # This test requires Ollama to be running
    # response = client.post("/api/process", json=payload)
    # assert response.status_code == 200
