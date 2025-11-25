"""
End-to-end tests for Logs API endpoints.
"""
import pytest
from datetime import datetime, timedelta


class TestGetAllLogs:
    """Tests for GET /logs endpoint."""
    
    async def test_get_all_logs_success(self, test_client, multiple_logs):
        """Test retrieving all logs successfully."""
        response = await test_client.get("/logs")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert all("id" in log for log in data)
        assert all("barcode" in log for log in data)
        assert all("direction" in log for log in data)
        assert all("event_time" in log for log in data)
    
    async def test_get_logs_filter_by_barcode(self, test_client, multiple_users, db_config):
        """Test filtering logs by barcode."""
        import asyncpg
        
        # Create logs for different users
        conn = await asyncpg.connect(**db_config)
        await conn.execute(
            "INSERT INTO log (barcode, direction) VALUES ($1, $2)",
            multiple_users[0]["barcode"], "CHECKIN"
        )
        await conn.execute(
            "INSERT INTO log (barcode, direction) VALUES ($1, $2)",
            multiple_users[1]["barcode"], "CHECKOUT"
        )
        await conn.close()
        
        # Filter by first user's barcode
        response = await test_client.get(f"/logs?barcode={multiple_users[0]['barcode']}")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["barcode"] == multiple_users[0]["barcode"]
    
    async def test_get_logs_filter_by_date_range(self, test_client, sample_user, db_config):
        """Test filtering logs by date range."""
        import asyncpg
        from zoneinfo import ZoneInfo
        from urllib.parse import quote
        
        # Create logs with different dates (timezone-aware)
        conn = await asyncpg.connect(**db_config)
        
        tz = ZoneInfo("UTC")
        today = datetime.now(tz)
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)
        
        await conn.execute(
            "INSERT INTO log (barcode, direction, event_time) VALUES ($1, $2, $3)",
            sample_user["barcode"], "CHECKIN", yesterday
        )
        await conn.execute(
            "INSERT INTO log (barcode, direction, event_time) VALUES ($1, $2, $3)",
            sample_user["barcode"], "CHECKOUT", today
        )
        await conn.execute(
            "INSERT INTO log (barcode, direction, event_time) VALUES ($1, $2, $3)",
            sample_user["barcode"], "CHECKIN", tomorrow
        )
        await conn.close()
        
        # Filter by date range (only today) - use ISO format with URL encoding
        from_date = today.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        to_date = today.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
        
        # URL encode the dates to handle + signs properly
        response = await test_client.get(f"/logs?from={quote(from_date)}&to={quote(to_date)}")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["direction"] == "CHECKOUT"
    
    async def test_get_logs_combined_filters(self, test_client, multiple_users, db_config):
        """Test combining multiple filters."""
        import asyncpg
        from zoneinfo import ZoneInfo
        from urllib.parse import quote
        
        # Create logs for different users and dates (timezone-aware)
        conn = await asyncpg.connect(**db_config)
        
        tz = ZoneInfo("UTC")
        today = datetime.now(tz)
        yesterday = today - timedelta(days=1)
        
        await conn.execute(
            "INSERT INTO log (barcode, direction, event_time) VALUES ($1, $2, $3)",
            multiple_users[0]["barcode"], "CHECKIN", today
        )
        await conn.execute(
            "INSERT INTO log (barcode, direction, event_time) VALUES ($1, $2, $3)",
            multiple_users[0]["barcode"], "CHECKOUT", yesterday
        )
        await conn.execute(
            "INSERT INTO log (barcode, direction, event_time) VALUES ($1, $2, $3)",
            multiple_users[1]["barcode"], "CHECKIN", today
        )
        await conn.close()
        
        # Filter by barcode and date - use ISO format with URL encoding
        from_date = today.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        response = await test_client.get(
            f"/logs?barcode={multiple_users[0]['barcode']}&from={quote(from_date)}"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["barcode"] == multiple_users[0]["barcode"]
        assert data[0]["direction"] == "CHECKIN"


class TestGetLog:
    """Tests for GET /logs/<id> endpoint."""
    
    async def test_get_log_success(self, test_client, sample_log):
        """Test retrieving an existing log."""
        response = await test_client.get(f"/logs/{sample_log['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_log["id"]
        assert data["barcode"] == sample_log["barcode"]
        assert data["direction"] == sample_log["direction"]
        assert "event_time" in data
    
    async def test_get_log_not_found(self, test_client):
        """Test 404 for non-existent log."""
        response = await test_client.get("/logs/99999")
        
        assert response.status_code == 404
    
    async def test_get_log_event_time_serialization(self, test_client, sample_log):
        """Test that event_time is properly serialized to ISO format."""
        response = await test_client.get(f"/logs/{sample_log['id']}")
        
        assert response.status_code == 200
        data = response.json()
        
        # event_time should be a valid ISO format string
        event_time = data["event_time"]
        assert isinstance(event_time, str)
        
        # Should be parseable as datetime
        parsed_time = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
        assert isinstance(parsed_time, datetime)


class TestCreateLog:
    """Tests for POST /logs endpoint."""
    
    async def test_create_log_success(self, test_client, sample_user):
        """Test creating a log with valid data."""
        log_data = {
            "barcode": sample_user["barcode"],
            "direction": "CHECKIN"
        }
        
        response = await test_client.post("/logs", json=log_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Log creato"
        assert "id" in data
        
        # Verify log was created
        get_response = await test_client.get(f"/logs/{data['id']}")
        assert get_response.status_code == 200
    
    async def test_create_log_missing_barcode(self, test_client):
        """Test 400 for missing barcode."""
        log_data = {
            "direction": "CHECKIN"
        }
        
        response = await test_client.post("/logs", json=log_data)
        
        assert response.status_code == 400
    
    async def test_create_log_invalid_direction(self, test_client, sample_user):
        """Test 400 for invalid direction."""
        log_data = {
            "barcode": sample_user["barcode"],
            "direction": "INVALID"
        }
        
        response = await test_client.post("/logs", json=log_data)
        
        assert response.status_code == 400
    
    async def test_create_log_nonexistent_user(self, test_client):
        """Test 400 for non-existent user."""
        log_data = {
            "barcode": "9999999999999",
            "direction": "CHECKIN"
        }
        
        response = await test_client.post("/logs", json=log_data)
        
        assert response.status_code == 400
    
    async def test_create_log_with_custom_event_time(self, test_client, sample_user):
        """Test creating a log with custom event_time."""
        from zoneinfo import ZoneInfo
        
        # Use timezone-aware datetime
        tz = ZoneInfo("UTC")
        custom_time = datetime.now(tz) - timedelta(hours=2)
        log_data = {
            "barcode": sample_user["barcode"],
            "direction": "CHECKOUT",
            "event_time": custom_time.isoformat()
        }
        
        response = await test_client.post("/logs", json=log_data)
        
        assert response.status_code == 201
        data = response.json()
        
        # Verify the custom time was used
        get_response = await test_client.get(f"/logs/{data['id']}")
        assert get_response.status_code == 200
        log_data_retrieved = get_response.json()
        
        # Parse and compare times (allowing for small differences due to serialization)
        retrieved_time = datetime.fromisoformat(log_data_retrieved["event_time"].replace('Z', '+00:00'))
        time_diff = abs((retrieved_time.replace(tzinfo=None) - custom_time.replace(tzinfo=None)).total_seconds())
        assert time_diff < 2  # Within 2 seconds
    
    async def test_create_log_both_directions(self, test_client, sample_user):
        """Test creating logs with both CHECKIN and CHECKOUT directions."""
        # Create CHECKIN
        checkin_data = {
            "barcode": sample_user["barcode"],
            "direction": "CHECKIN"
        }
        response = await test_client.post("/logs", json=checkin_data)
        assert response.status_code == 201
        
        # Create CHECKOUT
        checkout_data = {
            "barcode": sample_user["barcode"],
            "direction": "CHECKOUT"
        }
        response = await test_client.post("/logs", json=checkout_data)
        assert response.status_code == 201


class TestDeleteLog:
    """Tests for DELETE /logs/<id> endpoint."""
    
    async def test_delete_log_success(self, test_client, sample_log):
        """Test deleting an existing log."""
        response = await test_client.delete(f"/logs/{sample_log['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Log cancellato"
        
        # Verify log was deleted
        get_response = await test_client.get(f"/logs/{sample_log['id']}")
        assert get_response.status_code == 404
    
    async def test_delete_log_not_found(self, test_client):
        """Test 404 for non-existent log."""
        response = await test_client.delete("/logs/99999")
        
        assert response.status_code == 404
    
    async def test_delete_log_user_remains(self, test_client, sample_user, sample_log):
        """Test that deleting a log doesn't delete the user."""
        # Delete the log
        response = await test_client.delete(f"/logs/{sample_log['id']}")
        assert response.status_code == 200
        
        # Verify user still exists
        user_response = await test_client.get(f"/users/{sample_user['barcode']}")
        assert user_response.status_code == 200
        user_data = user_response.json()
        assert user_data["barcode"] == sample_user["barcode"]
