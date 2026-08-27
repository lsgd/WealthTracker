"""Transaction classification: category rules and transfer detection.

Both operations are idempotent and respect user overrides — a transaction with
``category_manual`` (or ``transfer_manual``) set is never touched here.
"""
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

# Two entries pair up as a transfer when their booking dates are at most this
# many days apart (bank-side booking lag between the two accounts).
TRANSFER_WINDOW_DAYS = 3


def next_rule_position(user) -> int:
    """Position that appends a new rule after the existing ones."""
    from django.db.models import Max

    from .models import CategoryRule

    highest = CategoryRule.objects.filter(user=user).aggregate(Max('position'))['position__max']
    return 0 if highest is None else highest + 1


def rule_matcher(rule):
    """Predicate haystack -> bool for one rule (substring or regex).

    Haystacks are lowercased ``"{counterparty} {description}"``. A regex that
    no longer compiles (edited outside the validated paths) matches nothing
    instead of taking down the whole run.
    """
    import re

    if rule.is_regex:
        try:
            pattern = re.compile(rule.match_text, re.IGNORECASE)
        except re.error:
            logger.warning('Rule %d has an invalid regex, skipping', rule.id)
            return lambda haystack: False
        return lambda haystack: pattern.search(haystack) is not None
    needle = rule.match_text.lower()
    return lambda haystack: needle in haystack


def first_matching_rule(user, tx):
    """The rule that would classify ``tx`` (first match wins), or None.

    This is the rule an uncategorized future twin of ``tx`` would get — i.e.
    the one a corrective rule must be placed before to take effect.
    """
    haystack = f'{tx.counterparty} {tx.description}'.lower()
    for rule in user.category_rules.select_related('category').order_by('position', 'id'):
        if rule_matcher(rule)(haystack):
            return rule
    return None


class _Draft:
    """A rule that may not exist yet, shaped like one for :func:`rule_matcher`."""

    id = None

    def __init__(self, match_text, is_regex):
        self.match_text = match_text
        self.is_regex = is_regex


def preview_rule(user, match_text, is_regex, is_transfer, rule_id=None) -> dict:
    """What saving this rule would do, without saving it.

    Rules run first-match-wins over transactions that have no category and
    were not classified by hand, so the honest answer is not "how many rows
    contain this text" — it is how many rows this rule would actually claim.
    The counts split that out:

    - ``will_classify``: rows the rule wins and changes.
    - ``shadowed``: rows it matches but an earlier rule claims first — the
      reason a new rule can look like it did nothing.
    - ``already_classified``: rows it matches that already have a category or
      a manual decision, which rules never overwrite.

    An edit (``rule_id``) is simulated in place, so the rule keeps its
    position; a new rule is appended, which is where a saved one would land.
    """
    from .models import Transaction

    draft = _Draft(match_text, is_regex)
    existing = list(user.category_rules.order_by('position', 'id'))
    # Everything ahead of the draft is what can shadow it: for an edit that is
    # the rules before its own position, for a new rule all of them.
    cut = len(existing) if rule_id is None else next(
        (i for i, r in enumerate(existing) if r.id == rule_id), len(existing))
    shadowers = [rule_matcher(r) for r in existing[:cut]]
    matches = rule_matcher(draft)

    counts = {'will_classify': 0, 'shadowed': 0, 'already_classified': 0}
    examples = []
    for tx in (
        Transaction.objects
        .filter(account__user=user)
        .only('counterparty', 'description', 'booking_date', 'amount',
              'currency', 'category', 'category_manual', 'is_transfer',
              'transfer_manual')
        .order_by('-booking_date', '-id')
    ):
        haystack = f'{tx.counterparty} {tx.description}'.lower()
        if not matches(haystack):
            continue
        if tx.category_id is not None or tx.category_manual:
            counts['already_classified'] += 1
            continue
        if any(m(haystack) for m in shadowers):
            counts['shadowed'] += 1
            continue
        if is_transfer and (tx.transfer_manual or tx.is_transfer):
            # A manual not-a-transfer decision wins, and one already marked
            # would not change.
            counts['already_classified'] += 1
            continue
        counts['will_classify'] += 1
        if len(examples) < 3:
            examples.append({
                'booking_date': tx.booking_date,
                'amount': tx.amount,
                'currency': tx.currency,
                'text': f'{tx.counterparty} {tx.description}'.strip(),
            })

    counts['matched'] = (counts['will_classify'] + counts['shadowed']
                         + counts['already_classified'])
    counts['examples'] = examples
    return counts


def apply_rules(user, transactions=None) -> int:
    """Apply the user's category rules. Returns the number of transactions updated.

    First matching rule wins (rules in creation order). Only uncategorized,
    non-manually-classified transactions are considered. A rule with
    ``spread_months`` > 1 also sets the spread on matches that still have the
    default of 1. A transfer rule marks the match as a transfer instead of
    categorizing it — but never against the user's manual transfer decision,
    and a manually-unmarked entry falls through to the later rules.
    """
    from .models import Transaction

    # Explicit ordering: first match wins, and the user controls that order.
    rules = list(user.category_rules.select_related('category').order_by('position', 'id'))
    if not rules:
        return 0

    qs = transactions if transactions is not None else Transaction.objects.filter(
        account__user=user,
    )
    qs = qs.filter(category__isnull=True, category_manual=False)

    # Compile each rule's predicate once, not once per transaction.
    matchers = [(rule, rule_matcher(rule)) for rule in rules]

    updated = []
    for tx in qs:
        haystack = f'{tx.counterparty} {tx.description}'.lower()
        for rule, matches in matchers:
            if not matches(haystack):
                continue
            if rule.is_transfer:
                if tx.transfer_manual:
                    continue  # the user decided otherwise; try later rules
                if not tx.is_transfer:
                    tx.is_transfer = True
                    updated.append(tx)
                break
            tx.category = rule.category
            if rule.spread_months > 1 and tx.spread_months == 1:
                tx.spread_months = rule.spread_months
            updated.append(tx)
            break

    if updated:
        Transaction.objects.bulk_update(
            updated, ['category', 'spread_months', 'is_transfer'])
    return len(updated)


def detect_transfers(user) -> int:
    """Mark transfers between the user's own accounts. Returns entries marked.

    Two signals, either is sufficient:
    - The counterparty IBAN of an entry equals another own account's identifier.
    - An opposite entry exists on another own account: same absolute amount and
      currency, booking dates within TRANSFER_WINDOW_DAYS. Such pairs are linked
      via ``transfer_peer``.
    """
    from .models import FinancialAccount, Transaction

    own_identifiers = {
        ident for ident in FinancialAccount.objects.filter(user=user)
        .exclude(account_identifier='')
        .values_list('account_identifier', flat=True)
    }

    candidates = list(
        Transaction.objects
        .filter(account__user=user, is_transfer=False, transfer_manual=False)
        .order_by('booking_date', 'id')
    )

    marked = set()

    # Signal 1: counterparty account is one of the user's own accounts.
    for tx in candidates:
        if tx.counterparty_account and tx.counterparty_account in own_identifiers:
            tx.is_transfer = True
            marked.add(tx.pk)

    # Signal 2: opposite-amount pairing across accounts. Group by (currency, |amount|)
    # and greedily pair a debit with the nearest-dated credit from another account.
    by_key = {}
    for tx in candidates:
        by_key.setdefault((tx.currency, abs(tx.amount)), []).append(tx)

    window = timedelta(days=TRANSFER_WINDOW_DAYS)
    for group in by_key.values():
        debits = [t for t in group if t.amount < 0 and t.pk not in marked]
        credits = [t for t in group if t.amount > 0 and t.pk not in marked]
        for debit in debits:
            match = next(
                (c for c in credits
                 if c.account_id != debit.account_id
                 and abs(c.booking_date - debit.booking_date) <= window),
                None,
            )
            if match is None:
                continue
            credits.remove(match)
            for tx, peer in ((debit, match), (match, debit)):
                tx.is_transfer = True
                tx.transfer_peer = peer
                marked.add(tx.pk)

    to_save = [t for t in candidates if t.pk in marked]
    if to_save:
        Transaction.objects.bulk_update(to_save, ['is_transfer', 'transfer_peer'])
        logger.info('Marked %d transactions as transfers for %s', len(to_save), user)
    return len(to_save)
