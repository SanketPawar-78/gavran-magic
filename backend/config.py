import os
from dotenv import load_dotenv

load_dotenv(override=True)

class Config:
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/gavran_magic')
    
    # Enforce secure JWT Secret
    _jwt_secret = os.getenv('JWT_SECRET')
    if not _jwt_secret or _jwt_secret == 'your_jwt_secret_key':
        if os.getenv('FLASK_ENV') == 'production':
            raise ValueError("No JWT_SECRET set for Flask application in production")
        _jwt_secret = 'dev_jwt_secret_key_change_me'
    JWT_SECRET = _jwt_secret

    SHIPROCKET_EMAIL = os.getenv('SHIPROCKET_EMAIL')
    SHIPROCKET_PASSWORD = os.getenv('SHIPROCKET_PASSWORD')
    SHIPROCKET_BASE_URL = "https://apiv2.shiprocket.in/v1/external"
    DEBUG = os.getenv('FLASK_ENV') != 'production'
