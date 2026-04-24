import os
from flask import Flask
from dotenv import load_dotenv
from routes import main_bp
from auth import auth_bp

load_dotenv()

app = Flask(__name__)

tenant_id = os.getenv('AZURE_TENANT_ID', '9274ee3f-9425-4109-a27f-9fb15c10675d')
app.config.from_mapping(
    SECRET_KEY=os.getenv('SECRET_KEY', 'dev-secret-key-please-change'),
    AZURE_TENANT_ID=tenant_id,
    AZURE_CLIENT_ID=os.getenv('AZURE_CLIENT_ID', 'ac61582b-5782-441b-b6f7-7eb16a968c2c'),
    AZURE_CLIENT_SECRET=os.getenv('AZURE_CLIENT_SECRET', ''),
    AZURE_AUTHORITY=f"https://login.microsoftonline.com/{tenant_id}",
    AZURE_REDIRECT_PATH=os.getenv('AZURE_REDIRECT_PATH', '/auth/callback'),
    AZURE_SCOPE=['User.Read'],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1',
)

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)

if __name__ == '__main__':
    app.run(debug=True)