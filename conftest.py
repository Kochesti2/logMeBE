"""
Pytest configuration and fixtures for end-to-end API tests.
"""
import asyncio
import os
import pytest
import asyncpg
from dotenv import load_dotenv
from httpx import AsyncClient, ASGITransport

# Load test environment variables
load_dotenv(".env.test")

# Import app after loading test env
import app as app_module


@pytest.fixture
async def db_config():
    """Database configuration for tests."""
    return {
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME"),
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
    }


@pytest.fixture(scope="session")
def _setup_test_db_once():
    """Set up test database schema once for the entire test session."""
    import asyncio
    
    db_cfg = {
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME"),
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
    }
    
    async def setup():
        conn = await asyncpg.connect(**db_cfg)
        
        # Drop and recreate tables to ensure clean state
        await conn.execute("DROP TABLE IF EXISTS log CASCADE")
        await conn.execute("DROP TABLE IF EXISTS users CASCADE")
        
        # Create tables
        await conn.execute("""
            CREATE TABLE users (
                barcode VARCHAR(13) PRIMARY KEY,
                nome VARCHAR(255) NOT NULL,
                cognome VARCHAR(255) NOT NULL
            )
        """)
        
        await conn.execute("""
            CREATE TABLE log (
                id SERIAL PRIMARY KEY,
                barcode VARCHAR(13) NOT NULL,
                direction VARCHAR(10) NOT NULL CHECK (direction IN ('CHECKIN', 'CHECKOUT')),
                event_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (barcode) REFERENCES users(barcode)
            )
        """)
        
        await conn.close()
    
    # Setup - create tables once
    asyncio.run(setup())
    
    yield
    
    # Note: We don't drop tables here to avoid issues during test session
    # Tables will be cleaned by the clean_db fixture between tests


@pytest.fixture
async def setup_test_db(_setup_test_db_once):
    """Ensure test database is set up (depends on session-scoped setup)."""
    yield


@pytest.fixture(autouse=True)
async def clean_db(db_config, setup_test_db):
    """Clean database before each test."""
    conn = await asyncpg.connect(**db_config)
    await conn.execute("DELETE FROM log")
    await conn.execute("DELETE FROM users")
    await conn.close()
    yield


@pytest.fixture
async def app_with_db(db_config):
    """Initialize the app with database pool for testing."""
    # Create database pool for the app
    app_module.pool = await asyncpg.create_pool(**db_config)
    
    yield app_module.app
    
    # Cleanup
    if app_module.pool:
        await app_module.pool.close()
        app_module.pool = None


@pytest.fixture
async def test_client(app_with_db):
    """Create test client for making API requests."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_db),
        base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def sample_user(db_config):
    """Create a sample user in the database."""
    user_data = {
        "barcode": "1234567890123",
        "nome": "Mario",
        "cognome": "Rossi"
    }
    
    conn = await asyncpg.connect(**db_config)
    await conn.execute(
        "INSERT INTO users (barcode, nome, cognome) VALUES ($1, $2, $3)",
        user_data["barcode"],
        user_data["nome"],
        user_data["cognome"]
    )
    await conn.close()
    
    return user_data


@pytest.fixture
async def multiple_users(db_config):
    """Create multiple sample users in the database."""
    users_data = [
        {"barcode": "1111111111111", "nome": "Alice", "cognome": "Bianchi"},
        {"barcode": "2222222222222", "nome": "Bob", "cognome": "Verdi"},
        {"barcode": "3333333333333", "nome": "Charlie", "cognome": "Neri"},
    ]
    
    conn = await asyncpg.connect(**db_config)
    for user in users_data:
        await conn.execute(
            "INSERT INTO users (barcode, nome, cognome) VALUES ($1, $2, $3)",
            user["barcode"],
            user["nome"],
            user["cognome"]
        )
    await conn.close()
    
    return users_data


@pytest.fixture
async def sample_log(db_config, sample_user):
    """Create a sample log entry in the database."""
    log_data = {
        "barcode": sample_user["barcode"],
        "direction": "CHECKIN"
    }
    
    conn = await asyncpg.connect(**db_config)
    log_id = await conn.fetchval(
        "INSERT INTO log (barcode, direction) VALUES ($1, $2) RETURNING id",
        log_data["barcode"],
        log_data["direction"]
    )
    await conn.close()
    
    log_data["id"] = log_id
    return log_data


@pytest.fixture
async def multiple_logs(db_config, sample_user):
    """Create multiple sample log entries in the database."""
    conn = await asyncpg.connect(**db_config)
    
    logs_data = []
    for direction in ["CHECKIN", "CHECKOUT", "CHECKIN"]:
        log_id = await conn.fetchval(
            "INSERT INTO log (barcode, direction) VALUES ($1, $2) RETURNING id",
            sample_user["barcode"],
            direction
        )
        logs_data.append({
            "id": log_id,
            "barcode": sample_user["barcode"],
            "direction": direction
        })
    
    await conn.close()
    return logs_data

