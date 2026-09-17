from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import date

from .domain import CURRENCY, INSTRUMENT, bounded_int, number, shape, text

MAX_RESPONSE_BYTES = 16384
ENDPOINT = 'https://www.alphavantage.co/query'
SYMBOL = re.compile(r'[A-Z0-9][A-Z0-9._-]{0,31}\Z')
ENVIRONMENT_KEY = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}\Z')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError('market provider redirects are disabled')


def request_json(url: str, timeout: float) -> dict:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'www.alphavantage.co'
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.path != '/query'
            or parsed.fragment or len(url) > 4096):
        raise ValueError('unexpected market provider endpoint')
    from .service import decode
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, headers={'Accept': 'application/json',
                                                   'User-Agent': 'Zara/stock-expert'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError('market provider returned a non-success status')
            body = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('market provider read deadline exceeded')
                chunk = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - len(body)))
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError('market response exceeds byte limit')
                if not chunk:
                    break
        return decode(body.decode('utf-8'))
    except Exception:
        raise RuntimeError('market provider transport or JSON failure') from None


class AlphaVantageSource:
    """Use Zara's provider client without its binary-float numeric conversion."""

    def __init__(self, configuration: Mapping, *, client_class=None, config_factory=None) -> None:
        if not isinstance(configuration, Mapping):
            raise ValueError('market_data must be a mapping')
        values = dict(configuration)
        shape(values, {'instruments'}, {'api_key_env', 'timeout_seconds'})
        key = text(values.get('api_key_env', 'ALPHAVANTAGE_API_KEY'), ENVIRONMENT_KEY)
        timeout = bounded_int(values.get('timeout_seconds', 3), 1, 3)
        mappings = values['instruments']
        if not isinstance(mappings, Mapping) or not 1 <= len(mappings) <= 256:
            raise ValueError('configure between 1 and 256 explicit instrument mappings')
        self._instruments = {}
        for instrument, mapping in mappings.items():
            text(instrument, INSTRUMENT)
            if not isinstance(mapping, Mapping):
                raise ValueError('instrument mapping must contain symbol and currency')
            mapping = shape(dict(mapping), {'symbol', 'currency'})
            self._instruments[instrument] = {
                'symbol': text(mapping['symbol'], SYMBOL),
                'currency': text(mapping['currency'], CURRENCY),
            }
        if client_class is None and config_factory is None:
            try:
                from zara.plugins.builtin.market_data import MarketDataClient, MarketProviderConfig
            except ImportError:
                raise RuntimeError('Zara market-data provider client is not installed; requires Zara PR #929') from None
            client_class, config_factory = MarketDataClient, MarketProviderConfig.from_mapping
        elif client_class is None or config_factory is None:
            raise ValueError('both trusted client dependencies must be supplied together')

        class ExactClient(client_class):
            @staticmethod
            def _number(value):
                number(value, signed=True)
                return value

        self._client = ExactClient(config_factory({'provider': 'alpha_vantage',
                                    'endpoint': ENDPOINT, 'api_key_env': key,
                                    'timeout_seconds': timeout}), request_json=request_json)
        self._lock = threading.Lock()

    def fetch(self, instrument: str) -> dict:
        text(instrument, INSTRUMENT)
        if instrument not in self._instruments:
            raise ValueError('instrument is not in the operator-configured market mapping')
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('market request is already in flight')
        try:
            mapping = self._instruments[instrument]
            try:
                quote = self._client.quote(mapping['symbol'])
            except Exception:
                raise RuntimeError('market provider request failed; check credentials, quota and provider status') from None
            if (not isinstance(quote, dict) or quote.get('provider') != 'alpha_vantage'
                    or quote.get('symbol') != mapping['symbol']):
                raise ValueError('market provider response identity mismatch')
            price = quote.get('price')
            number(price, positive=True)
            day = quote.get('trading_day')
            if not isinstance(day, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day):
                raise ValueError('market provider omitted a valid trading date')
            date.fromisoformat(day)
            observation = {
                'instrument': instrument, 'source': 'alpha-vantage-global-quote',
                'effective_at': day + 'T00:00:00+00:00',
                'price': price, 'currency': mapping['currency'],
                'feed': 'historical', 'adjustment': 'unknown', 'price_kind': 'last',
                'timestamp_precision': 'day', 'trading_day': day,
            }
            digest = hashlib.sha256(json.dumps(observation, sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()
            return dict(observation, event_id='av:' + digest)
        finally:
            self._lock.release()
