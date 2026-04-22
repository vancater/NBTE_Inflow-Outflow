import os
import uuid
import secrets
from functools import wraps
from flask import Blueprint, session, redirect, request, url_for, current_app, flash
import msal

auth_bp = Blueprint('auth', __name__)


def _build_msal_app():
    return msal.ConfidentialClientApplication(
        current_app.config['AZURE_CLIENT_ID'],
        authority=current_app.config['AZURE_AUTHORITY'],
        client_credential=current_app.config['AZURE_CLIENT_SECRET'],
    )


def _build_auth_url():
    state = str(uuid.uuid4())
    session['auth_state'] = state
    return _build_msal_app().get_authorization_request_url(
        current_app.config['AZURE_SCOPE'],
        state=state,
        redirect_uri=url_for('auth.auth_callback', _external=True),
    )


def get_current_user():
    return session.get('user')


def current_user_role():
    user = session.get('user', {})
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    if 'Manager' in roles:
        return 'Manager'
    if 'Staff' in roles:
        return 'Staff'
    return None


def _generate_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def _validate_csrf_token(token):
    stored = session.get('_csrf_token')
    return bool(token and stored and secrets.compare_digest(stored, token))


def csrf_protect(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if request.method == 'POST':
            token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
            if not _validate_csrf_token(token):
                return 'Invalid CSRF token', 400
        return func(*args, **kwargs)
    return wrapper


def auth_disabled():
    return not bool(current_app.config.get('AZURE_CLIENT_SECRET'))


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            if auth_disabled():
                session['user'] = {
                    'name': 'Local Demo User',
                    'email': 'local-demo@example.com',
                    'display_name': 'Local Demo User',
                    'roles': ['Manager'],
                }
            else:
                session['next_url'] = request.url
                return redirect(url_for('auth.login'))
        return func(*args, **kwargs)
    return wrapper


def requires_role(required_role):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if current_user_role() != required_role:
                flash('Access denied. Manager role required.')
                return redirect(url_for('main.dashboard'))
            return func(*args, **kwargs)
        return wrapper
    return decorator


@auth_bp.route('/login')
def login():
    if auth_disabled():
        session['user'] = {
            'name': 'Local Demo User',
            'email': 'local-demo@example.com',
            'display_name': 'Local Demo User',
            'roles': ['Manager'],
        }
        return redirect(url_for('main.dashboard'))
    return redirect(_build_auth_url())


@auth_bp.route('/auth/callback')
def auth_callback():
    if request.args.get('state') != session.get('auth_state'):
        return redirect(url_for('auth.login'))

    if request.args.get('error'):
        error_message = request.args.get('error_description') or request.args.get('error')
        return f"Login error: {error_message}"

    code = request.args.get('code')
    if not code:
        return 'Login failed: no authorization code received.'

    result = _build_msal_app().acquire_token_by_authorization_code(
        code,
        scopes=current_app.config['AZURE_SCOPE'],
        redirect_uri=url_for('auth.auth_callback', _external=True),
    )

    if 'error' in result:
        error_message = result.get('error_description') or result.get('error')
        return f"Login failed: {error_message}"

    claims = result.get('id_token_claims', {})
    roles = claims.get('roles', [])
    if isinstance(roles, str):
        roles = [roles]
    if not roles:
        roles = ['Manager']

    session['user'] = {
        'name': claims.get('name') or claims.get('preferred_username') or claims.get('email'),
        'email': claims.get('preferred_username') or claims.get('email'),
        'display_name': claims.get('name') or claims.get('preferred_username') or claims.get('email'),
        'roles': roles,
    }

    next_url = session.pop('next_url', None)
    return redirect(next_url or url_for('main.dashboard'))


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.app_context_processor
def inject_auth_context():
    return {
        'current_user': get_current_user(),
        'current_role': current_user_role(),
        'csrf_token': _generate_csrf_token,
    }
