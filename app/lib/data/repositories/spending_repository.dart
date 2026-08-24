import '../../core/config/api_config.dart';
import '../datasources/api_client.dart';
import '../models/ai_categorization.dart';
import '../models/spending.dart';
import '../models/transactions.dart';

class SpendingRepository {
  final ApiClient _apiClient;

  SpendingRepository(this._apiClient);

  /// Fetch the month-to-month spending report.
  ///
  /// [mode] is ``normalized`` (yearly bills amortized across their months) or
  /// ``actual`` (raw cash flow per month).
  Future<SpendingReport> getMonthly({
    required int months,
    required String mode,
  }) async {
    final response = await _apiClient.get(
      ApiConfig.spendingMonthlyPath,
      queryParameters: {'months': months, 'mode': mode},
    );
    return SpendingReport.fromJson(response.data as Map<String, dynamic>);
  }

  // ---- transactions --------------------------------------------------------

  Future<TransactionPage> getAccountTransactions(int accountId,
      {int page = 1}) async {
    final response = await _apiClient.get(
      '${ApiConfig.accountsPath}$accountId/transactions/',
      queryParameters: page > 1 ? {'page': page} : null,
    );
    return TransactionPage.fromJson(response.data as Map<String, dynamic>);
  }

  /// All transactions across accounts, newest first. [accountId] restricts to
  /// one account, [uncategorizedOnly] to transactions without a category.
  Future<TransactionPage> getTransactions({
    int? accountId,
    bool uncategorizedOnly = false,
    int page = 1,
  }) async {
    final response = await _apiClient.get(
      ApiConfig.transactionsPath,
      queryParameters: {
        'account': ?accountId,
        if (uncategorizedOnly) 'uncategorized': 1,
        if (page > 1) 'page': page,
      },
    );
    return TransactionPage.fromJson(response.data as Map<String, dynamic>);
  }

  /// Set (or clear, with a null [categoryId]) a transaction's category.
  ///
  /// Allowed on imported transactions too: the bank's own fields stay
  /// read-only, but what they mean is the user's call. The backend marks the
  /// change as manual so rules never overwrite it.
  Future<TransactionRecord> classifyTransaction(
    int transactionId, {
    required int? categoryId,
  }) async {
    final response = await _apiClient.patch(
      '${ApiConfig.transactionsPath}$transactionId/',
      data: {'category': categoryId},
    );
    return TransactionRecord.fromJson(response.data as Map<String, dynamic>);
  }

  /// Mark (or unmark) a transaction as a transfer between own accounts,
  /// excluding it from the spending report. Stored as a manual decision, so
  /// automatic transfer detection never overrides it — needed for transfers
  /// auto-detection cannot pair, e.g. funding a broker that has no
  /// transaction feed.
  Future<TransactionRecord> setTransfer(
    int transactionId, {
    required bool isTransfer,
  }) async {
    final response = await _apiClient.patch(
      '${ApiConfig.transactionsPath}$transactionId/',
      data: {'is_transfer': isTransfer},
    );
    return TransactionRecord.fromJson(response.data as Map<String, dynamic>);
  }

  // ---- categories and rules ------------------------------------------------

  Future<List<TransactionCategory>> getCategories() async {
    final response = await _apiClient.get(ApiConfig.spendingCategoriesPath);
    return _asList(response.data)
        .map((e) => TransactionCategory.fromJson(e))
        .toList();
  }

  Future<TransactionCategory> createCategory(String name) async {
    final response = await _apiClient.post(
      ApiConfig.spendingCategoriesPath,
      data: {'name': name},
    );
    return TransactionCategory.fromJson(response.data as Map<String, dynamic>);
  }

  /// Rename a category. Transactions and rules keep pointing at it.
  Future<TransactionCategory> renameCategory(int categoryId, String name) async {
    final response = await _apiClient.patch(
      '${ApiConfig.spendingCategoriesPath}$categoryId/',
      data: {'name': name},
    );
    return TransactionCategory.fromJson(response.data as Map<String, dynamic>);
  }

  /// Delete a category. Its transactions become uncategorized; rules mapping
  /// to it are deleted with it.
  Future<void> deleteCategory(int categoryId) async {
    await _apiClient.delete('${ApiConfig.spendingCategoriesPath}$categoryId/');
  }

  Future<List<CategoryRule>> getRules() async {
    final response = await _apiClient.get(ApiConfig.spendingRulesPath);
    return _asList(response.data).map((e) => CategoryRule.fromJson(e)).toList();
  }

  /// Create a rule; the backend appends it last and applies it retroactively to
  /// still-uncategorized transactions.
  Future<CategoryRule> createRule({
    required String matchText,
    required int categoryId,
    int spreadMonths = 1,
  }) async {
    final response = await _apiClient.post(
      ApiConfig.spendingRulesPath,
      data: {
        'match_text': matchText,
        'category': categoryId,
        'spread_months': spreadMonths,
      },
    );
    return CategoryRule.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> deleteRule(int ruleId) async {
    await _apiClient.delete('${ApiConfig.spendingRulesPath}$ruleId/');
  }

  /// Persist the evaluation order (first match wins).
  Future<List<CategoryRule>> reorderRules(List<int> ids) async {
    final response = await _apiClient.post(
      ApiConfig.spendingRulesReorderPath,
      data: {'ids': ids},
    );
    return _asList(response.data).map((e) => CategoryRule.fromJson(e)).toList();
  }

  // ---- AI categorization ---------------------------------------------------

  Future<AiConfig> getAiConfig() async {
    final response = await _apiClient.get(ApiConfig.aiConfigPath);
    return AiConfig.fromJson(response.data as Map<String, dynamic>);
  }

  /// Ask Gemini for category suggestions. Nothing is persisted — the result is
  /// a proposal the user confirms via [applyAiSuggestions].
  Future<AiSuggestResponse> suggestCategories() async {
    final response = await _apiClient.post(
      ApiConfig.aiSuggestPath,
      data: {},
      timeout: ApiConfig.aiSuggestTimeout,
    );
    return AiSuggestResponse.fromJson(response.data as Map<String, dynamic>);
  }

  /// After a manual re-categorization: ask Gemini which similar transactions
  /// should get the same category. Nothing is persisted — the result is a
  /// proposal the user confirms via [applyAiSuggestions].
  Future<AiSuggestResponse> relabelSimilar(int transactionId) async {
    final response = await _apiClient.post(
      ApiConfig.aiRelabelPath,
      data: {'transaction_id': transactionId},
      timeout: ApiConfig.aiSuggestTimeout,
    );
    return AiSuggestResponse.fromJson(response.data as Map<String, dynamic>);
  }

  /// Persist only what the user ticked.
  Future<Map<String, dynamic>> applyAiSuggestions({
    required List<AiSuggestion> assignments,
    required List<AiRuleSuggestion> rules,
  }) async {
    final response = await _apiClient.post(ApiConfig.aiApplyPath, data: {
      'assignments': assignments
          .map((s) => {
                'transaction_id': s.transactionId,
                'category': s.category,
              })
          .toList(),
      'rules': rules
          .map((r) => {
                'match_text': r.matchText,
                'category': r.category,
                'place_before_rule_id': r.placeBeforeRuleId,
              })
          .toList(),
    });
    return response.data as Map<String, dynamic>;
  }

  /// Ask Gemini for a smaller equivalent rule set. Only rule metadata leaves
  /// the server; the proposal is confirmed via [replaceRules].
  Future<AiConsolidateResponse> consolidateRules() async {
    final response = await _apiClient.post(
      ApiConfig.aiConsolidatePath,
      data: {},
      timeout: ApiConfig.aiSuggestTimeout,
    );
    return AiConsolidateResponse.fromJson(response.data as Map<String, dynamic>);
  }

  /// Atomically replace the whole rule set with [rules] (in evaluation order).
  Future<void> replaceRules(List<AiConsolidatedRule> rules) async {
    await _apiClient.post(ApiConfig.spendingRulesReplacePath, data: {
      'rules': [
        for (final r in rules)
          {
            'match_text': r.matchText,
            'category': r.category,
            'spread_months': r.spreadMonths,
          },
      ],
    });
  }

  /// DRF returns plain lists for the unpaginated endpoints, but tolerate a
  /// paginated envelope so a server-side pagination change cannot break this.
  List<Map<String, dynamic>> _asList(dynamic data) {
    if (data is List) return data.cast<Map<String, dynamic>>();
    if (data is Map && data['results'] is List) {
      return (data['results'] as List).cast<Map<String, dynamic>>();
    }
    return const [];
  }
}
