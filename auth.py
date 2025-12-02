import os
import jwt
import datetime
from functools import wraps
from quart import Blueprint, request, jsonify, abort, current_app
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

auth_bp = Blueprint('auth', __name__)

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key_change_me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def auth_required(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            abort(401, "Authorization header missing")
        
        try:
            scheme, token = auth_header.split()
            if scheme.lower() != 'bearer':
                abort(401, "Invalid authentication scheme")
        except ValueError:
            abort(401, "Invalid authorization header format")

        payload = decode_token(token)
        if not payload:
            abort(401, "Invalid or expired token")
        
        # Optionally, you could attach the user info to the request context here
        # request.user_id = payload.get("sub")
        
        return await f(*args, **kwargs)
    return decorated

@auth_bp.post('/auth/register')
async def register():
    data = await request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        abort(400, "Username and password are required")

    # Check max managers limit (10)
    pool = current_app.config['db_pool']
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM managers")
        if count >= 10:
            abort(403, "Maximum number of managers reached (10)")
        
        # Check if username exists
        exists = await conn.fetchval("SELECT 1 FROM managers WHERE username = $1", username)
        if exists:
            abort(409, "Username already exists")

        hashed_pw = hash_password(password)
        # Create manager with active=False
        await conn.execute(
            "INSERT INTO managers (username, password_hash, active) VALUES ($1, $2, $3)",
            username, hashed_pw, False
        )

    return jsonify({"message": "Manager registered successfully. Please contact admin to activate your account."}), 201

@auth_bp.post('/auth/login')
async def login():
    data = await request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        abort(400, "Username and password are required")

    pool = current_app.config['db_pool']
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash, active FROM managers WHERE username = $1",
            username
        )
        
        if not row:
            abort(401, "Invalid credentials")
        
        if not verify_password(password, row['password_hash']):
            abort(401, "Invalid credentials")
            
        if not row['active']:
            abort(403, "Account is not active. Please contact admin.")
            
        token = create_access_token({"sub": str(row['id']), "username": username})
        
    return jsonify({"access_token": token, "token_type": "bearer"})
