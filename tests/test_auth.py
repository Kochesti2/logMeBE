import pytest
import asyncpg
from app import app
from auth import create_access_token, hash_password

@pytest.fixture
async def client():
    app.config['TESTING'] = True
    async with app.test_app() as test_app:
        yield test_app.test_client()

@pytest.fixture
async def db_pool():
    pool = await asyncpg.create_pool(
        user="test_user",
        password="test_password",
        database="test_db",
        host="localhost",
        port="5432"
    )
    yield pool
    await pool.close()

@pytest.mark.asyncio
async def test_register_manager(client):
    # Ensure clean state
    # Note: In a real test env, we should clean the DB. 
    # Here we rely on the fact that we are running against a test DB or using a fresh one.
    # For this test to work repeatedly, we might need a cleanup fixture.
    pass

@pytest.mark.asyncio
async def test_auth_flow(client):
    # 1. Register a new manager
    username = "test_manager_1"
    password = "password123"
    
    # Clean up if exists
    pool = app.config['db_pool']
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM managers WHERE username = $1", username)

    response = await client.post("/auth/register", json={
        "username": username,
        "password": password
    })
    assert response.status_code == 201
    
    # 2. Try to login (should fail - not active)
    response = await client.post("/auth/login", json={
        "username": username,
        "password": password
    })
    assert response.status_code == 403
    
    # 3. Activate manager manually
    async with pool.acquire() as conn:
        await conn.execute("UPDATE managers SET active = TRUE WHERE username = $1", username)
        
    # 4. Login again (should succeed)
    response = await client.post("/auth/login", json={
        "username": username,
        "password": password
    })
    assert response.status_code == 200
    data = await response.get_json()
    token = data["access_token"]
    assert token is not None
    
    # 5. Access protected endpoint with token
    # Create a dummy user first to delete
    barcode = "9999999999999"
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (barcode, nome, cognome) VALUES ($1, 'Test', 'User') ON CONFLICT DO NOTHING", barcode)

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.delete(f"/users/{barcode}", headers=headers)
    assert response.status_code == 200
    
    # 6. Access protected endpoint without token
    response = await client.delete(f"/users/{barcode}")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_max_managers_limit(client):
    # Create 10 managers directly in DB
    pool = app.config['db_pool']
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM managers") # Clean start
        for i in range(10):
            await conn.execute(
                "INSERT INTO managers (username, password_hash, active) VALUES ($1, $2, $3)",
                f"manager_{i}", "hash", True
            )
            
    # Try to register 11th
    response = await client.post("/auth/register", json={
        "username": "manager_11",
        "password": "password"
    })
    assert response.status_code == 403
    assert "Maximum number of managers reached" in (await response.get_data(as_text=True))

