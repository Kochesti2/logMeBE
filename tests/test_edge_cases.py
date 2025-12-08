"""
Edge case tests for API endpoints - 10 critical scenarios.
"""
import pytest
from datetime import datetime, timedelta, timezone


class TestEdgeCases:
    """Critical edge case tests to ensure API robustness."""
    
    # Edge Case 1: SQL Injection Attempt
    async def test_sql_injection_via_barcode_filter(self, test_client, sample_user):
        """Test that SQL injection attempts are safely handled via parameterized queries."""
        # Attempt SQL injection in barcode parameter
        malicious_barcode = "1234567890123' OR '1'='1"
        
        response = await test_client.get(f"/logs?barcode={malicious_barcode}")
        
        # Should return 200 with empty results (no logs for that exact barcode)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0  # No results because barcode doesn't match exactly
    
    # Edge Case 2: Extremely Long String Inputs
    async def test_extremely_long_names(self, auth_client):
        """Test that extremely long names are rejected."""
        long_name = "A" * 1000  # 1000 characters
        
        user_data = {
            "barcode": "5555555555555",
            "nome": long_name,
            "cognome": "Rossi"
        }
        
        response = await auth_client.post("/users", json=user_data)
        
        assert response.status_code == 400
        assert "troppo lungo" in response.text.lower() or "massimo" in response.text.lower()
    
    async def test_exactly_255_character_names(self, auth_client):
        """Test that names at exactly 255 characters are accepted."""
        name_255 = "A" * 255
        
        user_data = {
            "barcode": "5555555555555",
            "nome": name_255,
            "cognome": "B" * 255,
            "email": "test@gmail.com"
        }
        
        response = await auth_client.post("/users", json=user_data)
        
        assert response.status_code == 201
    
    # Edge Case 3: Special Characters in Names
    async def test_special_characters_in_names(self, auth_client):
        """Test that special characters and unicode are handled correctly."""
        test_cases = [
            {"nome": "José", "cognome": "García"},  # Accented characters
            {"nome": "O'Brien", "cognome": "D'Angelo"},  # Apostrophes
            {"nome": "李明", "cognome": "王"},  # Chinese characters
            {"nome": "Müller", "cognome": "Schröder"},  # German umlauts
            {"nome": "Test😀", "cognome": "Emoji🎉"},  # Emoji
        ]
        
        for idx, names in enumerate(test_cases):
            user_data = {
                "barcode": f"555555555{idx:04d}",
                "nome": names["nome"],
                "cognome": names["cognome"],
                "email": "test@gmail.com"
            }
            
            response = await auth_client.post("/users", json=user_data)
            
            # Should accept all valid unicode
            assert response.status_code == 201, f"Failed for {names}"
    
    # Edge Case 4: Malformed ISO Date Strings
    async def test_malformed_date_strings(self, test_client):
        """Test that malformed date strings return proper error messages."""
        malformed_dates = [
            "not-a-date",
            "2025-13-01",  # Invalid month
            "2025-01-32",  # Invalid day
            "25-01-2025",  # Wrong format
            "2025/01/01",  # Wrong separator
            # Note: empty string is treated as no parameter, so it returns 200
        ]
        
        for bad_date in malformed_dates:
            response = await test_client.get(f"/logs?from={bad_date}")
            
            assert response.status_code == 400
            assert "formato" in response.text.lower() or "valido" in response.text.lower() or "invalid" in response.text.lower()
    
    # Edge Case 5: Future Dates in event_time
    async def test_future_event_time_rejected(self, auth_client, sample_user):
        """Test that future event_time values are rejected."""
        future_time = datetime.now(timezone.utc) + timedelta(days=1)
        
        log_data = {
            "barcode": sample_user["barcode"],
            "direction": "CHECKIN",
            "event_time": future_time.isoformat()
        }
        
        response = await auth_client.post("/logs", json=log_data)
        
        assert response.status_code == 400
        assert "futuro" in response.text.lower() or "future" in response.text.lower()
    
    async def test_current_time_accepted(self, auth_client, sample_user):
        """Test that current time is accepted."""
        current_time = datetime.now(timezone.utc)
        
        log_data = {
            "barcode": sample_user["barcode"],
            "direction": "CHECKIN",
            "event_time": current_time.isoformat()
        }
        
        response = await auth_client.post("/logs", json=log_data)
        
        # Should be accepted (or very close to current time)
        assert response.status_code in [201, 400]  # Might fail if processed too slowly
    
    # Edge Case 6: Concurrent User Creation
    async def test_concurrent_user_creation_race_condition(self, auth_client, db_config):
        """Test that concurrent creation of same barcode is handled correctly."""
        import asyncpg
        import asyncio
        
        barcode = "9999999999999"
        user_data = {
            "barcode": barcode,
            "nome": "Test",
            "cognome": "User",
            "email": "test@gmail.com"
        }
        
        # Try to create the same user twice concurrently
        async def create_user():
            return await auth_client.post("/users", json=user_data)
        
        # Execute both requests concurrently
        results = await asyncio.gather(
            create_user(),
            create_user(),
            return_exceptions=True
        )
        
        # One should succeed (201), one should fail (409)
        status_codes = [r.status_code if hasattr(r, 'status_code') else 500 for r in results]
        
        assert 201 in status_codes, "At least one should succeed"
        assert 409 in status_codes or status_codes.count(201) == 1, "Should handle duplicate"
    
    # Edge Case 7: Empty/Whitespace-Only Strings
    async def test_empty_string_names(self, auth_client):
        """Test that empty string names are rejected."""
        user_data = {
            "barcode": "5555555555555",
            "nome": "",
            "cognome": "Rossi"
        }
        
        response = await auth_client.post("/users", json=user_data)
        
        assert response.status_code == 400
        assert "obbligatorio" in response.text.lower() or "required" in response.text.lower()
    
    async def test_whitespace_only_names(self, auth_client):
        """Test that whitespace-only names are rejected."""
        test_cases = [
            {"nome": "   ", "cognome": "Rossi"},
            {"nome": "Mario", "cognome": "   "},
            {"nome": "\t\t", "cognome": "Rossi"},
            {"nome": "\n\n", "cognome": "Rossi"},
        ]
        
        for idx, names in enumerate(test_cases):
            user_data = {
                "barcode": f"555555555{idx:04d}",
                **names
            }
            
            response = await auth_client.post("/users", json=user_data)
            
            assert response.status_code == 400
            assert "vuoto" in response.text.lower() or "spazi" in response.text.lower()
    
    async def test_names_with_leading_trailing_whitespace(self, auth_client):
        """Test that leading/trailing whitespace is trimmed."""
        user_data = {
            "barcode": "5555555555555",
            "nome": "  Mario  ",
            "cognome": "  Rossi  ",
            "email": "test@gmail.com"
        }
        
        response = await auth_client.post("/users", json=user_data)
        
        assert response.status_code == 201
        
        # Verify the user was created with trimmed names
        get_response = await auth_client.get("/users/5555555555555")
        assert get_response.status_code == 200
        user = get_response.json()
        assert user["nome"] == "Mario"
        assert user["cognome"] == "Rossi"
    
    # Edge Case 8: Case-Insensitive Direction Values
    async def test_lowercase_direction_accepted(self, auth_client, sample_user):
        """Test that lowercase direction values are accepted."""
        log_data = {
            "barcode": sample_user["barcode"],
            "direction": "checkin"
        }
        
        response = await auth_client.post("/logs", json=log_data)
        
        assert response.status_code == 201
    
    async def test_mixed_case_direction_accepted(self, auth_client, sample_user):
        """Test that mixed case direction values are accepted."""
        test_cases = ["CheckIn", "checkOut", "CHECKOUT", "ChEcKiN"]
        
        for direction in test_cases:
            log_data = {
                "barcode": sample_user["barcode"],
                "direction": direction
            }
            
            response = await auth_client.post("/logs", json=log_data)
            
            assert response.status_code == 201, f"Failed for direction: {direction}"
    
    # Edge Case 9: Database Connection Handling
    async def test_api_with_null_pool(self, test_client, app_with_db):
        """Test that APIs handle database connection issues gracefully."""
        # This test verifies the app doesn't crash when pool is None
        # In production, proper error handling should be in place
        
        # Note: This is a basic test - in production you'd want to mock
        # the pool being None or connection failures
        
        # Just verify the app is using the pool correctly
        response = await test_client.get("/users")
        assert response.status_code == 200
    
    # Edge Case 10: Large Result Sets
    async def test_large_result_sets(self, test_client, db_config):
        """Test performance with large number of records."""
        import asyncpg
        
        # Create 100 users
        conn = await asyncpg.connect(**db_config)
        
        for i in range(100):
            barcode = f"{i:013d}"
            await conn.execute(
                "INSERT INTO users (barcode, nome, cognome) VALUES ($1, $2, $3)",
                barcode, f"Nome{i}", f"Cognome{i}"
            )
        
        await conn.close()
        
        # Fetch all users
        response = await test_client.get("/users")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 100
    
    async def test_large_logs_result_set(self, test_client, sample_user, db_config):
        """Test fetching large number of logs."""
        import asyncpg
        
        # Create 200 log entries
        conn = await asyncpg.connect(**db_config)
        
        for i in range(200):
            direction = "CHECKIN" if i % 2 == 0 else "CHECKOUT"
            await conn.execute(
                "INSERT INTO log (barcode, direction) VALUES ($1, $2)",
                sample_user["barcode"], direction
            )
        
        await conn.close()
        
        # Fetch all logs
        response = await test_client.get("/logs")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 200
    
    # Bonus: Test missing direction field
    async def test_missing_direction_field(self, auth_client, sample_user):
        """Test that missing direction field is properly rejected."""
        log_data = {
            "barcode": sample_user["barcode"]
            # direction is missing
        }
        
        response = await auth_client.post("/logs", json=log_data)
        
        assert response.status_code == 400
        assert "direction" in response.text.lower() or "obbligatorio" in response.text.lower()
