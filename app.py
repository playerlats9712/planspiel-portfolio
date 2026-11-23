"""Self-hosted Planspiel Börse portfolio tracker. Never writes credentials/tokens to disk."""
import os
import time
import sqlite3
import threading
import logging
import secrets
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

import requests
from flask import Flask, jsonify, request, Response, send_file
from werkzeug.exceptions import HTTPException

BASE = 'https://trading.planspiel-boerse.de/stockcontest/services/api'
LOGIN_URL = BASE + '/v-ms7/authenticate'
PORTFOLIO_URL = BASE + '/v-ms1/portfolio/getPortfolioWithItems'
HISTORY_URL = BASE + '/v-ms1/chart/getDepotValues'
EMAIL = os.environ.get('PLANSPIEL_EMAIL', '').strip()
PASSWORD = os.environ.get('PLANSPIEL_PASSWORD', '')
DEPOT_ID = os.environ.get('PLANSPIEL_DEPOT_ID', '').strip()
WEB_USER = os.environ.get('WEB_USER', 'portfolio')
WEB_PASSWORD = os.environ.get('WEB_PASSWORD', '')
POLL_SECONDS = max(30, int(os.environ.get('POLL_SECONDS', '60')))
AUTH_MODE = os.environ.get('API_AUTH_MODE', 'bearer').lower()  # bearer, x-bywo-jen, none
DB_PATH = Path(os.environ.get('DB_PATH', '/home/container/data/portfolio.sqlite3'))
DEFAULT_HEADERS = {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-Angular-Connect-String': '3abab342352e088ab2edde2c495acabd', 'Referer': 'https://trading.planspiel-boerse.de/web/account/depot/portfolio'}
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False
app.secret_key = secrets.token_bytes(32)
state = {'status': 'starting', 'last_success': None, 'error': None, 'value': None, 'positions': [], 'cash': None}
lock = threading.Lock()
SESSION = requests.Session()
TOKEN = None
TOKEN_EXPIRY = 0


def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH), timeout=20)
    connection.execute('CREATE TABLE IF NOT EXISTS ticks (timestamp INTEGER PRIMARY KEY, value REAL NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS seed_history (timestamp INTEGER PRIMARY KEY, value REAL NOT NULL)')
    connection.commit()
    return connection


def authorized(fn):
    @wraps(fn)
    def check(*a, **kw):
        if not WEB_PASSWORD:
            return Response('WEB_PASSWORD is not set. Configure it in Pterodactyl Startup.', 503)
        auth = request.authorization
        if not auth or not (secrets.compare_digest(auth.username or '', WEB_USER) and secrets.compare_digest(auth.password or '', WEB_PASSWORD)):
            return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Portfolio"', 'Cache-Control':'no-store'})
        return fn(*a, **kw)
    return check


def login():
    global TOKEN, TOKEN_EXPIRY
    if not EMAIL or not PASSWORD:
        raise RuntimeError('PLANSPIEL_EMAIL and PLANSPIEL_PASSWORD must be set in Startup')
    payload = {'userName': EMAIL, 'password': PASSWORD}
    response = SESSION.post(LOGIN_URL, json=payload, headers=DEFAULT_HEADERS, timeout=20)
    response.raise_for_status()
    body = response.json()
    if not body.get('success'):
        raise RuntimeError('Login rejected by Planspiel Börse')
    token_obj = body.get('result', {}).get('token', {})
    token = token_obj.get('accessToken')
    if not token:
        raise RuntimeError('No accessToken returned by login')
    TOKEN = token
    TOKEN_EXPIRY = time.time() + 25 * 60
    logging.info('Planspiel Börse login successful')


def api_get(url, params):
    global TOKEN
    if not TOKEN or time.time() > TOKEN_EXPIRY:
        login()
    headers = dict(DEFAULT_HEADERS)
    if AUTH_MODE == 'bearer':
        headers['Authorization'] = 'Bearer ' + TOKEN
    elif AUTH_MODE == 'x-bywo-jen':
        headers['X-ByWo-Jen'] = TOKEN
    elif AUTH_MODE != 'none':
        raise RuntimeError('API_AUTH_MODE must be bearer, x-bywo-jen or none')
    for attempt in range(2):
        response = SESSION.get(url, headers=headers, params=params, timeout=25)
        if response.status_code in (401, 403) and attempt == 0:
            login()
            if AUTH_MODE == 'bearer': headers['Authorization'] = 'Bearer ' + TOKEN
            elif AUTH_MODE == 'x-bywo-jen': headers['X-ByWo-Jen'] = TOKEN
            continue
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get('success') is False:
            raise RuntimeError('Planspiel API reported success=false')
        return data
    raise RuntimeError('Unauthorized after login')


def get_value():
    if not DEPOT_ID.isdigit():
        raise RuntimeError('PLANSPIEL_DEPOT_ID must be numeric')
    data = api_get(PORTFOLIO_URL, {'portfolioId': DEPOT_ID, 'withItems': 'true', 'withOrderIds': 'true'})
    # Response observed in user's HAR: {portfolio:{value,credit,...}, items:[...]}
    root = data.get('result', data) if isinstance(data, dict) else {}
    portfolio = root.get('portfolio') or {}
    value = portfolio.get('value')
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError('Portfolio response does not contain a positive portfolio.value')
    positions = []
    for row in root.get('items', []):
        inst = row.get('instrument') or {}
        positions.append({'name': inst.get('name', ''), 'isin': inst.get('isin', ''), 'quantity': row.get('quantity'), 'value': row.get('currentValue')})
    return round(float(value), 4), positions, portfolio.get('availableCredit')


def import_history():
    if not DEPOT_ID.isdigit(): return
    data = api_get(HISTORY_URL, {'portfolioId': DEPOT_ID})
    if isinstance(data, dict): data = data.get('result', data.get('data', []))
    if not isinstance(data, list): return
    with database() as db:
        for row in data:
            if isinstance(row, list) and len(row) >= 2 and isinstance(row[0], (float, int)) and isinstance(row[1], (float, int)):
                ts = int(row[0] / 1000) if row[0] > 100000000000 else int(row[0])
                if row[1] > 0: db.execute('INSERT OR IGNORE INTO seed_history (timestamp,value) VALUES (?,?)', (ts, float(row[1])))
        db.commit()


def collector():
    last_history = 0
    while True:
        try:
            if time.time() - last_history > 6 * 3600:
                try:
                    import_history()
                    last_history = time.time()
                except Exception as ex:
                    logging.warning('Historical data unavailable: %s', type(ex).__name__)
            value, positions, cash = get_value()
            now = int(time.time())
            with database() as db:
                db.execute('INSERT OR REPLACE INTO ticks(timestamp,value) VALUES (?,?)', (now, value))
                db.commit()
            with lock:
                state.update(status='ok', last_success=now, error=None, value=value, positions=positions, cash=cash)
            logging.info('Portfolio refreshed (%d positions)', len(positions))
        except Exception as ex:
            # Never print raw API response or requests, which may contain tokens/personal information
            logging.warning('Collector error: %s', type(ex).__name__)
            with lock:
                state.update(status='error', error=f'{type(ex).__name__}: {str(ex)[:130] if isinstance(ex, (ValueError, RuntimeError)) else "remote API or network error"}')
        time.sleep(POLL_SECONDS)


def candles_for(rows):
    groups = defaultdict(list)
    for ts, val in rows:
        groups[int(ts) // 900 * 900].append((int(ts), float(val)))
    candles = []
    for ts, values in sorted(groups.items()):
        values.sort()
        vals = [v for _, v in values]
        candles.append({'time': ts, 'open': vals[0], 'high': max(vals), 'low': min(vals), 'close': vals[-1], 'samples': len(vals)})
    return candles


@app.after_request
def headers(resp):
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    return resp


@app.route('/')
@authorized
def home(): return send_file('/opt/portfolio/index.html')


@app.route('/api/status')
@authorized
def status():
    with lock: data = dict(state)
    data['poll_seconds'] = POLL_SECONDS
    return jsonify(data)


@app.route('/api/candles')
@authorized
def candles():
    with database() as db:
        rows = db.execute('SELECT timestamp,value FROM ticks ORDER BY timestamp DESC LIMIT 30000').fetchall()
        history = db.execute('SELECT timestamp,value FROM seed_history ORDER BY timestamp DESC LIMIT 2000').fetchall()
    return jsonify({'candles': candles_for(reversed(rows)), 'history': [{'time': t, 'value': v} for t,v in reversed(history)], 'note': 'OHLC candles are sampled portfolio values, not exchange OHLC. Historical snapshots are shown separately.'})


if __name__ == '__main__':
    database().close()
    threading.Thread(target=collector, daemon=True).start()
    port = int(os.environ.get('SERVER_PORT', os.environ.get('PORT', '8080')))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
