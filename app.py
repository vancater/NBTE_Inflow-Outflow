import os
import secrets
from flask import Flask
from dotenv import load_dotenv
from routes import main_bp
from auth import auth_bp

load_dotenv()

app = Flask(__name__)

tenant_id = os.getenv('AZURE_TENANT_ID', '9274ee3f-9425-4109-a27f-9fb15c10675d')
app_env = (os.getenv('APP_ENV') or os.getenv('FLASK_ENV') or 'production').strip().lower()
is_development = app_env in {'development', 'dev', 'local'}
secret_key = os.getenv('SECRET_KEY')

if not secret_key:
    if is_development:
        secret_key = secrets.token_urlsafe(32)
    else:
        raise RuntimeError('SECRET_KEY must be set for non-development environments.')

app.config.from_mapping(
    SECRET_KEY=secret_key,
    ENV_NAME=app_env,
    IS_DEVELOPMENT=is_development,
    AZURE_TENANT_ID=tenant_id,
    AZURE_CLIENT_ID=os.getenv('AZURE_CLIENT_ID', 'ac61582b-5782-441b-b6f7-7eb16a968c2c'),
    AZURE_CLIENT_SECRET=os.getenv('AZURE_CLIENT_SECRET', ''),
    AZURE_AUTHORITY=f"https://login.microsoftonline.com/{tenant_id}",
    AZURE_REDIRECT_PATH=os.getenv('AZURE_REDIRECT_PATH', '/auth/callback'),
    AZURE_SCOPE=['User.Read'],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '1') == '1',
    SESSION_COOKIE_NAME=os.getenv('SESSION_COOKIE_NAME', 'inflow_session'),
    ENABLE_LOCAL_AUTH=os.getenv('ENABLE_LOCAL_AUTH', '0') == '1' and is_development,
)

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)


def _validate_security_config():
    if app.config['IS_DEVELOPMENT']:
        return

    if app.config.get('ENABLE_LOCAL_AUTH'):
        raise RuntimeError('ENABLE_LOCAL_AUTH must be disabled outside development.')

    if not app.config.get('AZURE_CLIENT_SECRET'):
        raise RuntimeError('AZURE_CLIENT_SECRET must be set outside development.')

    if not app.config.get('SESSION_COOKIE_SECURE'):
        raise RuntimeError('SESSION_COOKIE_SECURE must be enabled outside development.')


_validate_security_config()


@app.after_request
def apply_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault(
        'Permissions-Policy',
        'camera=(), microphone=(), geolocation=(), payment=(), usb=()'
    )
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
    return response

if __name__ == '__main__':
    app.run(debug=is_development)
