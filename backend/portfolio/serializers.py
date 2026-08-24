from rest_framework import serializers

from brokers.serializers import BrokerSerializer

from .models import (
    AccountSnapshot,
    CategoryRule,
    FinancialAccount,
    PortfolioPosition,
    Transaction,
    TransactionCategory,
)


class PortfolioPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioPosition
        fields = [
            'id', 'symbol', 'isin', 'name', 'quantity',
            'price_per_unit', 'market_value', 'currency',
            'cost_basis', 'asset_class'
        ]


class AccountSnapshotSerializer(serializers.ModelSerializer):
    positions = PortfolioPositionSerializer(many=True, read_only=True)

    class Meta:
        model = AccountSnapshot
        fields = [
            'id', 'balance', 'currency', 'balance_base_currency',
            'base_currency', 'exchange_rate_used', 'snapshot_date',
            'snapshot_source', 'positions', 'created_at'
        ]
        read_only_fields = ['id', 'balance_base_currency', 'base_currency',
                           'exchange_rate_used', 'created_at']


class AccountSnapshotCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating manual snapshots."""
    class Meta:
        model = AccountSnapshot
        fields = ['balance', 'currency', 'snapshot_date']

    def create(self, validated_data):
        validated_data['snapshot_source'] = 'manual'
        return super().create(validated_data)


class TransactionCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionCategory
        fields = ['id', 'name']


class CategoryRuleSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()

    class Meta:
        model = CategoryRule
        fields = [
            'id', 'match_text', 'category', 'category_name', 'spread_months',
            'position', 'is_regex', 'is_transfer',
        ]
        read_only_fields = ['position']

    def get_category_name(self, rule):
        return rule.category.name if rule.category else None

    def validate_category(self, category):
        request = self.context.get('request')
        if category and request and category.user_id != request.user.id:
            raise serializers.ValidationError('Category not found')
        return category

    def validate(self, attrs):
        # Python's `re` is the engine that runs the rule — its compile is the
        # authoritative check (the web UI pre-validates with JS RegExp, whose
        # dialect differs slightly).
        import re
        is_regex = attrs.get('is_regex', getattr(self.instance, 'is_regex', False))
        match_text = attrs.get('match_text', getattr(self.instance, 'match_text', ''))
        if is_regex:
            try:
                re.compile(match_text)
            except re.error as e:
                raise serializers.ValidationError(
                    {'match_text': f'Invalid regular expression: {e}'})
        # Exactly one target: a category, or the transfer flag.
        is_transfer = attrs.get(
            'is_transfer', getattr(self.instance, 'is_transfer', False))
        category = attrs.get('category', getattr(self.instance, 'category', None))
        if is_transfer and category is not None:
            raise serializers.ValidationError(
                'A transfer rule cannot also assign a category')
        # Rules are first-match-wins, so a second rule with the same match
        # text can never fire — reject it instead of growing dead entries.
        request = self.context.get('request')
        if match_text and request:
            clashing = CategoryRule.objects.filter(
                user=request.user, match_text__iexact=match_text,
            )
            if self.instance is not None:
                clashing = clashing.exclude(pk=self.instance.pk)
            if clashing.exists():
                raise serializers.ValidationError(
                    {'match_text': f'A rule for “{match_text}” already exists.'})
        # A transfer is excluded from spending entirely, so amortizing it over
        # several months is meaningless — keep the data honest.
        spread = attrs.get(
            'spread_months', getattr(self.instance, 'spread_months', 1))
        if is_transfer and spread and spread > 1:
            raise serializers.ValidationError(
                {'spread_months': 'A transfer rule cannot spread over months'})
        if not is_transfer and category is None:
            raise serializers.ValidationError(
                {'category': 'Pick a category (or make it a transfer rule)'})
        return attrs


class TransactionSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id', 'account', 'booking_date', 'value_date', 'amount', 'currency',
            'counterparty', 'counterparty_account', 'description', 'source',
            'external_id', 'category', 'category_name', 'spread_months',
            'is_transfer', 'created_at'
        ]
        read_only_fields = [
            'id', 'account', 'source', 'external_id', 'category',
            'category_name', 'spread_months', 'is_transfer', 'created_at'
        ]


class TransactionClassificationSerializer(serializers.ModelSerializer):
    """Classification-only updates — allowed on every transaction, including
    imported ones (the bank's facts stay read-only; what they *mean* is the
    user's). Setting a field flips the matching ``*_manual`` flag so rule
    application and transfer detection keep their hands off afterwards.
    """

    class Meta:
        model = Transaction
        fields = ['category', 'spread_months', 'is_transfer']

    def validate_category(self, category):
        request = self.context.get('request')
        if category and request and category.user_id != request.user.id:
            raise serializers.ValidationError('Category not found')
        return category

    def update(self, instance, validated_data):
        if 'category' in validated_data:
            instance.category_manual = True
        if 'is_transfer' in validated_data:
            instance.transfer_manual = True
        return super().update(instance, validated_data)


class TransactionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating manual transactions.

    ``currency`` may be omitted — the view defaults it to the account currency.
    """
    class Meta:
        model = Transaction
        fields = [
            'booking_date', 'value_date', 'amount', 'currency',
            'counterparty', 'counterparty_account', 'description'
        ]
        extra_kwargs = {'currency': {'required': False}}

    def create(self, validated_data):
        import uuid
        validated_data['source'] = 'manual'
        validated_data['dedup_key'] = f'manual:{uuid.uuid4().hex}'
        return super().create(validated_data)


class ManualTransactionUpdateSerializer(TransactionClassificationSerializer):
    """Full update for manual transactions: financial fields plus classification."""

    class Meta(TransactionClassificationSerializer.Meta):
        fields = [
            'booking_date', 'value_date', 'amount', 'currency', 'counterparty',
            'counterparty_account', 'description', 'category', 'spread_months',
            'is_transfer'
        ]


class FinancialAccountSerializer(serializers.ModelSerializer):
    broker = BrokerSerializer(read_only=True)
    broker_code = serializers.SlugRelatedField(
        slug_field='code',
        queryset=BrokerSerializer.Meta.model.objects.filter(is_active=True),
        write_only=True,
        source='broker'
    )
    latest_snapshot = AccountSnapshotSerializer(read_only=True)
    ebics_credential = serializers.SerializerMethodField()

    class Meta:
        model = FinancialAccount
        fields = [
            'id', 'name', 'broker', 'broker_code', 'account_identifier',
            'account_type', 'currency', 'is_manual', 'status',
            'sync_enabled', 'last_sync_at', 'last_sync_error', 'notes',
            'latest_snapshot', 'ebics_credential', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'status', 'last_sync_at', 'last_sync_error',
                           'created_at', 'updated_at']

    def get_ebics_credential(self, obj):
        if obj.ebics_credential_id:
            c = obj.ebics_credential
            return {'id': c.id, 'label': c.label, 'state': c.state}
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # An EBICS account cannot actually auto-sync until the bank has activated
        # the subscriber's key exchange (credential state == 'active'). Until then,
        # present it to the client as a manual-entry account: reporting sync as
        # effectively disabled hides the (guaranteed-to-fail) Sync button and lets
        # the app surface the account in its "needs a snapshot" prompt, exactly
        # like a manual account. Once the credential is active the real value
        # passes through unchanged.
        cred = data.get('ebics_credential')
        if cred and cred.get('state') != 'active':
            data['sync_enabled'] = False
        return data

    def update(self, instance, validated_data):
        old_broker_id = instance.broker_id
        account = super().update(instance, validated_data)

        # Security: changing the broker (incl. switching to/from manual) must never
        # carry stored credentials across. Drop them entirely so the user has to
        # re-enter them, even if they later migrate back to the original broker.
        if account.broker_id != old_broker_id:
            account.encrypted_credentials = None
            account.pending_auth_state = None
            account.last_sync_error = ''
            account.status = 'active' if account.is_manual else 'pending_auth'
            account.save(update_fields=[
                'encrypted_credentials', 'pending_auth_state',
                'last_sync_error', 'status',
            ])
        return account


class FinancialAccountCreateSerializer(serializers.ModelSerializer):
    broker_code = serializers.SlugRelatedField(
        slug_field='code',
        queryset=BrokerSerializer.Meta.model.objects.filter(is_active=True),
        source='broker'
    )
    credentials = serializers.JSONField(write_only=True, required=False)
    ebics_credential_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = FinancialAccount
        fields = [
            'name', 'broker_code', 'account_identifier', 'account_type',
            'currency', 'is_manual', 'sync_enabled', 'credentials',
            'ebics_credential_id', 'notes'
        ]

    def create(self, validated_data):
        # Remove credentials - they will be encrypted by the view using KEK
        credentials = validated_data.pop('credentials', None)

        # Link to a shared EBICS subscriber credential (validated for ownership).
        ebics_credential_id = validated_data.pop('ebics_credential_id', None)
        if ebics_credential_id is not None:
            from brokers.models import EbicsCredential
            request = self.context.get('request')
            user = getattr(request, 'user', None)
            try:
                validated_data['ebics_credential'] = EbicsCredential.objects.get(
                    pk=ebics_credential_id, user=user,
                )
            except EbicsCredential.DoesNotExist:
                raise serializers.ValidationError(
                    {'ebics_credential_id': 'EBICS credential not found'}
                )

        account = FinancialAccount.objects.create(**validated_data)

        # If credentials provided, encrypt them using KEK from request context
        if credentials:
            request = self.context.get('request')
            if request:
                from core.kek_auth import KEKAuthenticationMixin
                mixin = KEKAuthenticationMixin()
                account.encrypted_credentials = mixin.encrypt_account_credentials(
                    request, credentials
                )
                account.save()
        return account
