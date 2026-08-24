"""Gemini-assisted transaction categorization.

Sends a MINIMAL view of uncategorized transactions to the Google Gemini API and
returns category assignments plus reusable substring rules. What leaves the
server per transaction: counterparty name, booking text (description), signed
amount with currency — plus the user's category names. Never sent: account
numbers/IBANs, booking dates, balances, or any user identity. The exact field
list lives in DISCLOSED_FIELDS so the API/UI can show it verbatim.

Every suggestion is only that — persisting anything requires explicit user
confirmation through the apply endpoint.
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'
REQUEST_TIMEOUT = 60

# Max transactions per suggestion request — keeps the prompt (and cost) bounded.
MAX_TRANSACTIONS = 100

# What is transferred to Google, verbatim surfaced in the UI.
DISCLOSED_FIELDS = [
    'Counterparty name of each uncategorized transaction',
    'Booking text / description of each uncategorized transaction',
    'Signed amount and currency of each uncategorized transaction',
    'The names of your existing categories',
]

# Same, for the fix-similar flow (candidates are not necessarily uncategorized).
RELABEL_DISCLOSED_FIELDS = [
    'Counterparty name, booking text, and signed amount of the corrected '
    'transaction and of similar candidate transactions',
    'The current and corrected category names of those transactions',
    'The names of your existing categories',
]

# Same, for rule consolidation — no transaction data leaves the server here.
CONSOLIDATE_DISCLOSED_FIELDS = [
    'The match text, category name, and amortization months of every rule',
    'How many of your transactions each rule currently matches (a number only)',
]

# USD per 1M tokens (input, output), standard tier, as of August 2026
# (https://ai.google.dev/gemini-api/docs/pricing). Prices are not available via
# the API, so this table is maintained manually; unknown models show no price.
# Order-independent: resolved by longest matching prefix.
MODEL_PRICING = {
    'gemini-3.7-flash': (0.75, 3.75),
    'gemini-3.6-flash': (0.75, 3.75),
    'gemini-3.5-flash-lite': (0.30, 2.50),
    'gemini-3.5-flash': (1.50, 9.00),
    'gemini-3.1-flash-lite': (0.25, 1.50),
    'gemini-3.1-pro': (2.00, 12.00),
    'gemini-2.5-pro': (1.25, 10.00),
    'gemini-2.5-flash-lite': (0.10, 0.40),
    'gemini-2.5-flash': (0.30, 2.50),
    'gemini-2.0-flash-lite': (0.075, 0.30),
    'gemini-2.0-flash': (0.10, 0.40),
}


# ListModels advertises `generateContent` for image, speech, robotics and
# computer-use models too, so capability has to be inferred from the model id.
# Anything matching these is not a general text model and must never appear in
# the picker (Nano Banana = the `*-image` models; they would also prefix-match a
# text model's price row and show a wrong price).
_NON_TEXT_MARKERS = (
    'image', 'tts', 'audio', 'live', 'dialog', 'robotics', 'computer-use',
    'embedding', 'aqa', 'vision', 'custom-tool',
)


def is_text_model(model_id: str) -> bool:
    """True for general-purpose text models — the only ones usable for categorization."""
    return model_id.startswith('gemini') and not any(
        marker in model_id for marker in _NON_TEXT_MARKERS
    )


class GeminiError(Exception):
    """A Gemini API call failed; the message is safe to show to the user."""


def _friendly_error(response) -> str:
    try:
        message = response.json()['error']['message']
    except Exception:
        message = response.text[:200]
    if 'API key not valid' in message or 'API_KEY_INVALID' in message:
        return 'The Gemini API key is not valid.'
    return f'Gemini API error ({response.status_code}): {message}'


PRICING_SOURCE_URL = 'https://ai.google.dev/gemini-api/docs/pricing'

# When MODEL_PRICING was last reviewed against Google's published rates. Bump
# this together with the table; the UI shows it so a stale table is visible
# rather than silently trusted.
PRICING_TABLE_UPDATED = '2026-08-14'


def pricing_snapshot(model_id: str, display_name=None) -> dict:
    """The model's listed price plus when this app's price table was reviewed.

    Google exposes no pricing API, so this reads the local table. ``checked_at``
    records when the user last confirmed it (picking a model or hitting refresh).
    """
    from django.utils import timezone

    price = price_for_model(model_id)
    return {
        'model': model_id,
        'display_name': display_name or model_id,
        'input_price_per_1m': price[0] if price else None,
        'output_price_per_1m': price[1] if price else None,
        'checked_at': timezone.now().isoformat(),
        'table_updated': PRICING_TABLE_UPDATED,
    }


def price_for_model(model_id: str):
    """(input_usd, output_usd) per 1M tokens by longest prefix match, or None."""
    best = None
    for prefix, price in MODEL_PRICING.items():
        if model_id.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, price)
    return best[1] if best else None


def list_models(api_key: str) -> list:
    """Fetch the Gemini models usable for text generation, with known prices."""
    try:
        response = requests.get(
            f'{GEMINI_BASE}/models',
            params={'key': api_key, 'pageSize': 200},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise GeminiError(f'Could not reach the Gemini API: {e}')
    if response.status_code != 200:
        raise GeminiError(_friendly_error(response))

    models = []
    seen_labels = set()
    for model in response.json().get('models', []):
        model_id = model.get('name', '').removeprefix('models/')
        if not is_text_model(model_id):
            continue
        if 'generateContent' not in model.get('supportedGenerationMethods', []):
            continue
        price = price_for_model(model_id)
        # Google publishes the same model under several ids (dated snapshots,
        # aliases); one entry per name+price keeps the picker short.
        label = (model.get('displayName', model_id), price)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        models.append({
            'id': model_id,
            'display_name': model.get('displayName', model_id),
            'input_price_per_1m': price[0] if price else None,
            'output_price_per_1m': price[1] if price else None,
        })
    # Priced (i.e. current, known) models first, then alphabetical.
    models.sort(key=lambda m: (m['input_price_per_1m'] is None, m['id']))
    return models


_PROMPT = """You classify personal bank transactions into spending categories.

Existing categories: {categories}

Transactions (id | counterparty | booking text | signed amount):
{transactions}

For every transaction pick the best fitting existing category, or propose a NEW
concise category name (in the same language/style as the existing ones) when
none fits. Category names are ONE word wherever possible ("Restaurants", not
"Dining & Restaurants") — never join synonyms with "&" or "and"; use a second
word only when it genuinely adds meaning ("Public Transport"). Do not create
near-duplicates of existing categories, and keep the total number of new
categories small — prefer broad categories over merchant-specific ones.
Positive amounts are income; only categorize them when a category clearly
applies (e.g. salary), otherwise omit the transaction.

Additionally propose reusable RULES for recurring merchants: a lowercase
substring of the counterparty or booking text that uniquely identifies the
merchant (e.g. "rewe"), mapped to the category. Rules let the app categorize
future transactions without AI. Only propose a rule when the substring is
specific to that merchant.

Return JSON only:
{{"assignments": [{{"id": <transaction id>, "category": "<name>"}}],
  "rules": [{{"match_text": "<substring>", "category": "<name>"}}]}}"""


_RELABEL_PROMPT = """You fix categorization mistakes in personal bank transactions.

The user just corrected this transaction to the category "{category}":
{example}

Existing categories: {categories}

Candidate transactions (id | counterparty | booking text | signed amount | current category):
{transactions}

List the ids of the candidates that clearly belong to the same merchant or
serve the same purpose as the corrected transaction, and should therefore also
be "{category}". When unsure about a candidate, leave it out — a wrong
correction is worse than a missed one.

If the merchant is recurring, also propose ONE reusable rule: a lowercase
substring of the counterparty or booking text that uniquely identifies it
(e.g. "rewe"), mapped to "{category}". Only propose it when the substring is
specific to that merchant.

Return JSON only:
{{"ids": [<transaction id>, ...],
  "rules": [{{"match_text": "<substring>", "category": "{category}"}}]}}"""


_CONSOLIDATE_PROMPT = """You maintain substring rules that categorize personal bank transactions.

A rule assigns its category to any transaction whose counterparty or booking
text contains the match text (case-insensitive). Rules are evaluated in the
order listed; the first match wins. "matches" is how many of the user's
transactions currently contain the match text; "spread" is over how many months
a matched amount is amortized.

Rules (id | match text | category | spread | matches):
{rules}

Consolidate this list into the smallest equivalent set:
- Merge rules of the SAME category whose match texts point at the same merchant
  or are substrings of one another (e.g. several city-branch variants), keeping
  the shortest match text that still uniquely identifies the merchant.
- Drop rules with 0 matches only when they are clearly typos or superseded by
  another surviving rule; keep deliberate rules for merchants that may appear
  in the future.
- NEVER merge rules that map to different categories, never change a rule's
  category, and never invent new categories.
- Keep the surviving rules in their current relative order (a merged rule takes
  the place of its earliest source). Preserve the largest spread of the merged
  sources.

Return JSON only — the COMPLETE new rule list, in evaluation order:
{{"rules": [{{"match_text": "<substring>", "category": "<existing name>",
  "spread_months": <int>, "sources": [<rule id>, ...]}}]}}"""


def _tx_line(t: dict) -> str:
    return f"{t['id']} | {t['counterparty']} | {t['description']} | {t['amount']} {t['currency']}"


def _generate(api_key: str, model: str, prompt: str) -> tuple:
    """One JSON-mode generateContent call. Returns (parsed, usage)."""
    body = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseMimeType': 'application/json',
            'temperature': 0.1,
        },
    }
    try:
        response = requests.post(
            f'{GEMINI_BASE}/models/{model}:generateContent',
            params={'key': api_key},
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise GeminiError(f'Could not reach the Gemini API: {e}')
    if response.status_code != 200:
        raise GeminiError(_friendly_error(response))

    data = response.json()
    try:
        text = data['candidates'][0]['content']['parts'][0]['text']
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        logger.warning('Gemini returned an unparseable response: %s', e)
        raise GeminiError('Gemini returned an unparseable response — try again or pick another model.')

    usage_meta = data.get('usageMetadata', {})
    input_tokens = usage_meta.get('promptTokenCount', 0)
    output_tokens = usage_meta.get('candidatesTokenCount', 0)
    price = price_for_model(model)
    cost = (
        round(input_tokens * price[0] / 1e6 + output_tokens * price[1] / 1e6, 6)
        if price else None
    )
    usage = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'estimated_cost_usd': cost,
    }
    return parsed, usage


def suggest_categories(api_key: str, model: str, transactions: list, categories: list) -> dict:
    """Ask Gemini for category assignments and rule suggestions.

    ``transactions``: [{'id', 'counterparty', 'description', 'amount', 'currency'}].
    Returns {'assignments': [...], 'rules': [...], 'usage': {...}} — raw
    suggestions, nothing persisted.
    """
    prompt = _PROMPT.format(
        categories=', '.join(categories) if categories else '(none yet)',
        transactions='\n'.join(_tx_line(t) for t in transactions),
    )
    parsed, usage = _generate(api_key, model, prompt)

    return {
        'assignments': [
            a for a in parsed.get('assignments', [])
            if isinstance(a, dict) and 'id' in a and a.get('category')
        ],
        'rules': [
            r for r in parsed.get('rules', [])
            if isinstance(r, dict) and r.get('match_text') and r.get('category')
        ],
        'usage': usage,
    }


def consolidate_rules(api_key: str, model: str, rules: list) -> dict:
    """Ask Gemini for a smaller equivalent rule set.

    ``rules``: [{'id', 'match_text', 'category', 'spread_months', 'matches'}]
    in evaluation order. Returns {'rules': [...], 'usage': {...}} — a proposal,
    nothing persisted.
    """
    lines = '\n'.join(
        f"{r['id']} | {r['match_text']} | {r['category']} | {r['spread_months']} | {r['matches']}"
        for r in rules
    )
    parsed, usage = _generate(api_key, model, _CONSOLIDATE_PROMPT.format(rules=lines))

    return {
        'rules': [
            r for r in parsed.get('rules', [])
            if isinstance(r, dict) and r.get('match_text') and r.get('category')
        ],
        'usage': usage,
    }


def relabel_similar(api_key: str, model: str, example: dict, candidates: list,
                    category: str, categories: list) -> dict:
    """Ask Gemini which candidates share the corrected transaction's merchant/purpose.

    ``example``/``candidates``: {'id', 'counterparty', 'description', 'amount',
    'currency'(, 'current_category')}. Returns {'ids': [...], 'rules': [...],
    'usage': {...}} — raw suggestions, nothing persisted.
    """
    lines = '\n'.join(
        f"{_tx_line(t)} | {t.get('current_category') or '(uncategorized)'}"
        for t in candidates
    )
    prompt = _RELABEL_PROMPT.format(
        category=category,
        example=_tx_line(example),
        categories=', '.join(categories) if categories else '(none yet)',
        transactions=lines,
    )
    parsed, usage = _generate(api_key, model, prompt)

    return {
        'ids': [i for i in parsed.get('ids', []) if isinstance(i, int)],
        'rules': [
            r for r in parsed.get('rules', [])
            if isinstance(r, dict) and r.get('match_text') and r.get('category')
        ],
        'usage': usage,
    }
