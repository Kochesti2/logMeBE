"""
End-to-end tests for Users API endpoints.
"""
import pytest


class TestGetAllUsers:
    """Tests for GET /users endpoint."""
    
    async def test_get_all_users_success(self, test_client, multiple_users):
        """Test retrieving all users successfully."""
        response = await test_client.get("/users")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert all("barcode" in user for user in data)
        assert all("nome" in user for user in data)
        assert all("cognome" in user for user in data)
    
    async def test_get_all_users_empty(self, test_client):
        """Test retrieving users when database is empty."""
        response = await test_client.get("/users")
        
        assert response.status_code == 200
        data = response.json()
        assert data == []
    
    async def test_get_all_users_sorted(self, test_client, multiple_users):
        """Test that users are sorted by cognome, nome."""
        response = await test_client.get("/users")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be sorted: Bianchi, Neri, Verdi
        assert data[0]["cognome"] == "Bianchi"
        assert data[1]["cognome"] == "Neri"
        assert data[2]["cognome"] == "Verdi"


class TestGetUser:
    """Tests for GET /users/<barcode> endpoint."""
    
    async def test_get_user_success(self, test_client, sample_user):
        """Test retrieving an existing user."""
        response = await test_client.get(f"/users/{sample_user['barcode']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["barcode"] == sample_user["barcode"]
        assert data["nome"] == sample_user["nome"]
        assert data["cognome"] == sample_user["cognome"]
    
    async def test_get_user_not_found(self, test_client):
        """Test 404 for non-existent user."""
        response = await test_client.get("/users/9999999999999")
        
        assert response.status_code == 404
    
    async def test_get_user_invalid_barcode_format(self, test_client):
        """Test 400 for invalid barcode format."""
        # Too short
        response = await test_client.get("/users/123")
        assert response.status_code == 400
        
        # Non-numeric
        response = await test_client.get("/users/abcdefghijklm")
        assert response.status_code == 400
        
        # Too long
        response = await test_client.get("/users/12345678901234")
        assert response.status_code == 400


class TestCreateUser:
    """Tests for POST /users endpoint."""
    
    async def test_create_user_success(self, auth_client):
        """Test creating a valid user."""
        user_data = {
            "barcode": "5555555555555",
            "nome": "Test",
            "cognome": "User",
            "email": "test@gmail.com",
        }
        
        response = await auth_client.post("/users", json=user_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Utente creato"
        
        # Verify user was created
        get_response = await auth_client.get(f"/users/{user_data['barcode']}")
        assert get_response.status_code == 200
    
    async def test_create_user_missing_fields(self, auth_client):
        """Test 400 for missing required fields."""
        # Missing nome
        response = await auth_client.post("/users", json={
            "barcode": "5555555555555",
            "cognome": "User",
            "email": "test@gmail.com"
        })
        assert response.status_code == 400
        
        # Missing cognome
        response = await auth_client.post("/users", json={
            "barcode": "5555555555555",
            "nome": "Test",
            "email": "test@gmail.com"
        })
        assert response.status_code == 400
        
        # Missing barcode
        response = await auth_client.post("/users", json={
            "nome": "Test",
            "cognome": "User",
            "email": "test@gmail.com"
        })
        assert response.status_code == 400

        #missing email
        response = await auth_client.post("/users", json={
            "barcode": "5555555555555",
            "nome": "Test",
            "cognome": "User"
        })
        assert response.status_code == 400

    async def test_create_user_invalid_email(self, auth_client):
        """Test 400 for missing required fields."""
        # Missing nome
        response = await auth_client.post("/users", json={
            "barcode": "5555555555555",
            "nome": "Test",
            "cognome": "User",
            "email": "testgmail.com"
        })
        assert response.status_code == 400
    
    async def test_create_user_duplicate_barcode(self, auth_client, sample_user):
        """Test 409 for duplicate barcode."""
        user_data = {
            "barcode": sample_user["barcode"],
            "nome": "Different",
            "cognome": "Name",
            "email": "test@gmail.com"
        }
        
        response = await auth_client.post("/users", json=user_data)
        
        assert response.status_code == 409
    
    async def test_create_user_invalid_barcode(self, auth_client):
        """Test 400 for invalid barcode format."""
        # Too short
        response = await auth_client.post("/users", json={
            "barcode": "123",
            "nome": "Test",
            "cognome": "User"
        })
        assert response.status_code == 400
        
        # Non-numeric
        response = await auth_client.post("/users", json={
            "barcode": "abcdefghijklm",
            "nome": "Test",
            "cognome": "User",
            "email": "test@gmail.com"
        })
        assert response.status_code == 400


class TestDeleteUser:
    """Tests for DELETE /users/<barcode> endpoint."""
    
    async def test_delete_user_success(self, auth_client, sample_user):
        """Test deleting an existing user."""
        response = await auth_client.delete(f"/users/{sample_user['barcode']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Utente cancellato"
        
        # Verify user was deleted
        get_response = await auth_client.get(f"/users/{sample_user['barcode']}")
        assert get_response.status_code == 404
    
    async def test_delete_user_not_found(self, auth_client):
        """Test 404 for non-existent user."""
        response = await auth_client.delete("/users/9999999999999")
        
        assert response.status_code == 404
    
    async def test_delete_user_cascade_logs(self, auth_client, sample_user, sample_log, db_config):
        """Test that deleting a user also deletes their logs."""
        import asyncpg
        
        # Verify log exists
        conn = await asyncpg.connect(**db_config)
        log_count_before = await conn.fetchval(
            "SELECT COUNT(*) FROM log WHERE barcode = $1",
            sample_user["barcode"]
        )
        assert log_count_before == 1
        await conn.close()
        
        # Delete user
        response = await auth_client.delete(f"/users/{sample_user['barcode']}")
        assert response.status_code == 200
        
        # Verify logs were deleted
        conn = await asyncpg.connect(**db_config)
        log_count_after = await conn.fetchval(
            "SELECT COUNT(*) FROM log WHERE barcode = $1",
            sample_user["barcode"]
        )
        assert log_count_after == 0
        await conn.close()


class TestGetNewEan:
    """Tests for GET /users/newean endpoint."""
    
    async def test_get_new_ean_success(self, test_client):
        """Test generating a new unique EAN."""
        response = await test_client.get("/users/newean")
        
        assert response.status_code == 200
        data = response.json()
        assert "new_ean" in data
        assert len(data["new_ean"]) == 13
        assert data["new_ean"].isdigit()
    
    async def test_get_new_ean_valid_format(self, test_client):
        """Test that generated EAN has valid format."""
        response = await test_client.get("/users/newean")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be 13 digits
        ean = data["new_ean"]
        assert len(ean) == 13
        assert ean.isdigit()
    
    async def test_get_new_ean_uniqueness(self, test_client, sample_user):
        """Test that generated EAN is unique across multiple calls."""
        eans = set()
        
        # Generate multiple EANs
        for _ in range(5):
            response = await test_client.get("/users/newean")
            assert response.status_code == 200
            data = response.json()
            eans.add(data["new_ean"])
        
        # All should be unique
        assert len(eans) == 5
        
        # None should match the existing user's barcode
        assert sample_user["barcode"] not in eans
