# End-to-End API Tests

This directory contains comprehensive end-to-end tests for all API endpoints in the LogMe backend application.

## Test Coverage

### Users API (`test_users_api.py`)
- **GET /users** - 3 tests
  - Retrieve all users successfully
  - Handle empty users list
  - Verify correct sorting
  
- **GET /users/<barcode>** - 3 tests
  - Retrieve existing user
  - Handle non-existent user (404)
  - Validate barcode format (400)
  
- **POST /users** - 4 tests
  - Create valid user
  - Handle missing required fields (400)
  - Handle duplicate barcode (409)
  - Validate barcode format (400)
  
- **DELETE /users/<barcode>** - 3 tests
  - Delete existing user
  - Handle non-existent user (404)
  - Verify cascade deletion of logs
  
- **GET /users/newean** - 3 tests
  - Generate new unique EAN
  - Validate EAN format
  - Verify uniqueness across multiple calls

**Total: 18 tests**

### Logs API (`test_logs_api.py`)
- **GET /logs** - 4 tests
  - Retrieve all logs successfully
  - Filter by barcode
  - Filter by date range
  - Combine multiple filters
  
- **GET /logs/<id>** - 3 tests
  - Retrieve existing log
  - Handle non-existent log (404)
  - Verify event_time serialization
  
- **POST /logs** - 6 tests
  - Create log with valid data
  - Handle missing barcode (400)
  - Handle invalid direction (400)
  - Handle non-existent user (400)
  - Create log with custom event_time
  - Create logs with both CHECKIN and CHECKOUT
  
- **DELETE /logs/<id>** - 3 tests
  - Delete existing log
  - Handle non-existent log (404)
  - Verify user remains after log deletion

**Total: 20 tests**

## Setup

### 1. Install Test Dependencies

```bash
pip install -r requirements-test.txt
```

### 2. Configure Test Database

Copy `.env.test` and update with your test database credentials:

```bash
cp .env.test .env.test.local
# Edit .env.test with your test database settings
```

**Important:** Use a separate test database to avoid affecting production data!

### 3. Create Test Database

```sql
CREATE DATABASE logme_test;
```

The test fixtures will automatically create the necessary tables.

## Running Tests

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_users_api.py -v
pytest tests/test_logs_api.py -v
```

### Run Specific Test Class

```bash
pytest tests/test_users_api.py::TestGetAllUsers -v
```

### Run Specific Test

```bash
pytest tests/test_users_api.py::TestGetAllUsers::test_get_all_users_success -v
```

### Run with Coverage

```bash
pytest tests/ --cov=app --cov-report=html --cov-report=term
```

View the HTML coverage report:
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Test Structure

- **`conftest.py`** - Pytest configuration and shared fixtures
  - Database setup/teardown
  - Test client fixture
  - Sample data fixtures (users, logs)
  - Automatic database cleanup between tests

- **`test_users_api.py`** - Tests for Users API endpoints
- **`test_logs_api.py`** - Tests for Logs API endpoints

## Fixtures

### Database Fixtures
- `db_config` - Database configuration
- `setup_test_db` - Creates database schema
- `clean_db` - Cleans database before each test

### Client Fixture
- `test_client` - HTTP client for making API requests

### Data Fixtures
- `sample_user` - Single test user
- `multiple_users` - Multiple test users
- `sample_log` - Single test log entry
- `multiple_logs` - Multiple test log entries

## Notes

- All tests are async and use `pytest-asyncio`
- Database is automatically cleaned between tests
- Tests use a real database connection (not mocks)
- Each endpoint has at least 3 tests as required
