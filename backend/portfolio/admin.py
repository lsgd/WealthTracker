from django.contrib import admin

from .models import (
    AccountSnapshot,
    CategoryRule,
    FinancialAccount,
    PortfolioPosition,
    Transaction,
    TransactionCategory,
)


@admin.register(TransactionCategory)
class TransactionCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'user']
    search_fields = ['name', 'user__username']


@admin.register(CategoryRule)
class CategoryRuleAdmin(admin.ModelAdmin):
    list_display = ['match_text', 'category', 'spread_months', 'user']
    search_fields = ['match_text', 'category__name', 'user__username']


@admin.register(FinancialAccount)
class FinancialAccountAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'broker', 'account_type', 'currency', 'status', 'is_manual']
    list_filter = ['broker', 'account_type', 'status', 'is_manual', 'currency']
    search_fields = ['name', 'account_identifier', 'user__username']
    readonly_fields = ['created_at', 'updated_at', 'last_sync_at']


@admin.register(AccountSnapshot)
class AccountSnapshotAdmin(admin.ModelAdmin):
    list_display = ['account', 'balance', 'currency', 'snapshot_date', 'snapshot_source']
    list_filter = ['snapshot_source', 'currency', 'snapshot_date']
    search_fields = ['account__name', 'account__user__username']
    date_hierarchy = 'snapshot_date'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['account', 'booking_date', 'amount', 'currency', 'counterparty', 'source']
    list_filter = ['source', 'currency', 'booking_date']
    search_fields = ['counterparty', 'description', 'external_id', 'account__name']
    date_hierarchy = 'booking_date'
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PortfolioPosition)
class PortfolioPositionAdmin(admin.ModelAdmin):
    list_display = ['name', 'symbol', 'quantity', 'market_value', 'currency', 'asset_class']
    list_filter = ['asset_class', 'currency']
    search_fields = ['name', 'symbol', 'isin']
