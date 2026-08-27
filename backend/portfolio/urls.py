from django.urls import path

from . import views

urlpatterns = [
    # Financial accounts
    path('accounts/', views.FinancialAccountListCreateView.as_view(), name='account_list'),
    path('accounts/sync/', views.SyncAllAccountsView.as_view(), name='sync_all_accounts'),
    path('accounts/sync/<str:task_id>/', views.SyncTaskStatusView.as_view(), name='sync_task_status'),
    path('accounts/<int:pk>/', views.FinancialAccountDetailView.as_view(), name='account_detail'),
    path('accounts/<int:pk>/sync/', views.AccountSyncView.as_view(), name='account_sync'),
    path('accounts/<int:pk>/auth/', views.AccountAuthView.as_view(), name='account_auth'),
    path('accounts/<int:pk>/credentials/', views.AccountCredentialsView.as_view(), name='account_credentials'),
    # Snapshots
    path('accounts/<int:account_id>/snapshots/', views.AccountSnapshotListCreateView.as_view(), name='snapshot_list'),
    path('snapshots/<int:pk>/', views.AccountSnapshotDetailView.as_view(), name='snapshot_detail'),
    # Transactions
    path('accounts/<int:account_id>/transactions/', views.AccountTransactionListCreateView.as_view(), name='transaction_list'),
    path('transactions/', views.TransactionListView.as_view(), name='transaction_list_all'),
    path('transactions/<int:pk>/', views.TransactionDetailView.as_view(), name='transaction_detail'),
    path('accounts/<int:pk>/transactions/backfill/', views.AccountTransactionBackfillView.as_view(), name='transaction_backfill'),
    path('accounts/<int:pk>/transactions/import-csv/', views.AccountTransactionCsvImportView.as_view(), name='transaction_csv_import'),
    path('transactions/import-csv/', views.TransactionCsvImportView.as_view(), name='transaction_csv_import_auto'),
    # Spending insight: categories, rules, transfer detection, monthly report
    path('spending/categories/', views.TransactionCategoryListCreateView.as_view(), name='category_list'),
    path('spending/categories/<int:pk>/', views.TransactionCategoryDetailView.as_view(), name='category_detail'),
    path('spending/rules/', views.CategoryRuleListCreateView.as_view(), name='rule_list'),
    path('spending/rules/preview/', views.CategoryRulePreviewView.as_view(), name='rule_preview'),
    path('spending/rules/reorder/', views.CategoryRuleReorderView.as_view(), name='rule_reorder'),
    path('spending/rules/replace/', views.CategoryRulesReplaceView.as_view(), name='rule_replace'),
    path('spending/rules/<int:pk>/', views.CategoryRuleDetailView.as_view(), name='rule_detail'),
    path('spending/detect-transfers/', views.DetectTransfersView.as_view(), name='detect_transfers'),
    path('spending/monthly/', views.SpendingMonthlyView.as_view(), name='spending_monthly'),
    # AI categorization (Gemini)
    path('spending/ai/config/', views.AiConfigView.as_view(), name='ai_config'),
    path('spending/ai/models/', views.AiModelsView.as_view(), name='ai_models'),
    path('spending/ai/refresh-pricing/', views.AiRefreshPricingView.as_view(), name='ai_refresh_pricing'),
    path('spending/ai/suggest/', views.AiSuggestView.as_view(), name='ai_suggest'),
    path('spending/ai/relabel/', views.AiRelabelView.as_view(), name='ai_relabel'),
    path('spending/ai/consolidate/', views.AiConsolidateRulesView.as_view(), name='ai_consolidate'),
    path('spending/ai/apply/', views.AiApplyView.as_view(), name='ai_apply'),
    # Account bulk create (discover is in brokers/urls.py to avoid <str:code> catch-all)
    path('accounts/bulk/', views.BulkAccountCreateView.as_view(), name='account_bulk_create'),
    # CSV import
    path('import/csv/', views.CSVImportView.as_view(), name='csv_import'),
    # Wealth dashboard
    path('wealth/summary/', views.WealthSummaryView.as_view(), name='wealth_summary'),
    path('wealth/history/', views.WealthHistoryView.as_view(), name='wealth_history'),
    path('wealth/breakdown/', views.WealthBreakdownView.as_view(), name='wealth_breakdown'),
    path('wealth/holdings/', views.WealthHoldingsView.as_view(), name='wealth_holdings'),
    path('wealth/simulation/', views.WealthSimulationView.as_view(), name='wealth_simulation'),
]
