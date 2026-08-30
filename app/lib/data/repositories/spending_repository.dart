import '../../core/config/api_config.dart';
import '../datasources/api_client.dart';
import '../models/ai_categorization.dart';
import '../models/spending.dart';
import '../models/transactions.dart';

/// Comparable form of a category name: lowercased, with the diacritics folded
/// onto their base letters.
///
/// Dart has no locale-aware collator, and a plain compareTo works on code
/// units — "Ärzte" would sort after "Zoo" and "eBay" after "Transport", which
/// is not where anyone looks for them.
String categorySortKey(String name) {
  const folds = {
    'ä': 'a', 'à': 'a', 'á': 'a', 'â': 'a', 'å': 'a',
    'ö': 'o', 'ò': 'o', 'ó': 'o', 'ô': 'o', 'ø': 'o',
    'ü': 'u', 'ù': 'u', 'ú': 'u', 'û': 'u',
    'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
    'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i',
    'ç': 'c', 'ñ': 'n', 'ß': 'ss',
  };
  final lower = name.toLowerCase();
  final buffer = StringBuffer();
  for (final char in lower.split('')) {
    buffer.write(folds[char] ?? char);
  }
  return buffer.toString();
}

/// A classification change, plus the rule it now contradicts (if any).
///
/// A rule that mislabels one booking mislabels every future one of the same
/// merchant, so the server names it and the UI can offer to fix that too.
typedef Classified = ({TransactionRecord transaction, CategoryRule? staleRule});

class SpendingRepository {
  final ApiClient _apiClient;

  SpendingRepository(this._apiClient);

  /// Fetch the period-to-period spending report.
  ///
  /// [mode] is ``normalized`` (yearly bills amortized across their months) or
  /// ``actual`` (raw cash flow). [months] counts periods of [granularity]
  /// ('month', 'quarter' or 'year') — 12 quarters, 3 years.
  Future<SpendingReport> getMonthly({
    required int months,
    required String mode,
    String granularity = 'month',
  }) async {
    final response = await _apiClient.get(
      ApiConfig.spendingMonthlyPath,
      queryParameters: {
        'months': months,
        'mode': mode,
        'granularity': granularity,
      },
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

  /// All transactions across accounts, newest first.
  ///
  /// [accountId] restricts to one account, [month] to one period — a
  /// ``YYYY-MM``, ``YYYY-Qn`` or ``YYYY`` label. [uncategorizedOnly] narrows to
  /// transactions still needing a label (transfers are excluded — they are
  /// assigned, not undecided) and [transfersOnly] to the transfers themselves;
  /// [categoryIds] to a set of categories. [search] matches the booking text or
  /// an amount.
  Future<TransactionPage> getTransactions({
    int? accountId,
    bool uncategorizedOnly = false,
    bool transfersOnly = false,
    List<int>? categoryIds,
    String search = '',
    String? month,
    int page = 1,
  }) async {
    final response = await _apiClient.get(
      ApiConfig.transactionsPath,
      queryParameters: {
        'account': ?accountId,
        'month': ?month,
        if (uncategorizedOnly) 'uncategorized': 1,
        if (transfersOnly)
          'category': 'transfer'
        else if (categoryIds != null && categoryIds.isNotEmpty)
          'category': categoryIds.join(','),
        if (search.isNotEmpty) 'search': search,
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
  Future<Classified> classifyTransaction(
    int transactionId, {
    required int? categoryId,
  }) async {
    return _classify(transactionId, {'category': categoryId});
  }

  /// Mark (or unmark) a transaction as a transfer between own accounts,
  /// excluding it from the spending report. Stored as a manual decision, so
  /// automatic transfer detection never overrides it — needed for transfers
  /// auto-detection cannot pair, e.g. funding a broker that has no
  /// transaction feed.
  Future<Classified> setTransfer(
    int transactionId, {
    required bool isTransfer,
  }) async {
    return _classify(transactionId, {'is_transfer': isTransfer});
  }

  /// Amortize one transaction over [spreadMonths] months (1 = no spread).
  ///
  /// The rule-level spread only helps recurring merchants; a one-off yearly
  /// bill (an insurance premium paid once) has no rule to hang it on, and
  /// without this it dwarfs its month in the normalized view.
  Future<Classified> setSpread(
    int transactionId, {
    required int spreadMonths,
  }) async {
    return _classify(transactionId, {'spread_months': spreadMonths});
  }

  Future<Classified> _classify(int transactionId, Map<String, Object?> data) async {
    final response = await _apiClient.patch(
      '${ApiConfig.transactionsPath}$transactionId/',
      data: data,
    );
    final body = response.data as Map<String, dynamic>;
    final stale = body['stale_rule'];
    return (
      transaction: TransactionRecord.fromJson(body),
      staleRule: stale == null
          ? null
          : CategoryRule.fromJson(stale as Map<String, dynamic>),
    );
  }

  // ---- categories and rules ------------------------------------------------

  Future<List<TransactionCategory>> getCategories() async {
    final response = await _apiClient.get(ApiConfig.spendingCategoriesPath);
    return _asList(response.data)
        .map((e) => TransactionCategory.fromJson(e))
        .toList()
      // Sorted here rather than trusting the server's ORDER BY: a byte-wise
      // collation puts "Ärzte" after "Zoo" and "eBay" after "Transport".
      // Sorting at the single fetch point keeps every sheet and list agreeing.
      ..sort((a, b) => categorySortKey(a.name).compareTo(categorySortKey(b.name)));
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
  ///
  /// A rule targets a category or marks matches as transfers, never both —
  /// [categoryId] is required unless [isTransfer].
  Future<CategoryRule> createRule({
    required String matchText,
    int? categoryId,
    bool isTransfer = false,
    int spreadMonths = 1,
    bool isRegex = false,
    String direction = 'any',
    String? minAmount,
    bool minInclusive = true,
    String? maxAmount,
    bool maxInclusive = false,
  }) async {
    final response = await _apiClient.post(
      ApiConfig.spendingRulesPath,
      data: _rulePayload(
        matchText: matchText,
        categoryId: categoryId,
        isTransfer: isTransfer,
        spreadMonths: spreadMonths,
        isRegex: isRegex,
        direction: direction,
        minAmount: minAmount,
        minInclusive: minInclusive,
        maxAmount: maxAmount,
        maxInclusive: maxInclusive,
      ),
    );
    return CategoryRule.fromJson(response.data as Map<String, dynamic>);
  }

  /// Overwrite every editable field of a rule — what the rule editor saves.
  ///
  /// Distinct from [updateRule], which retargets a rule without touching
  /// anything else: correcting one transaction's category must not silently
  /// rewrite the rule's amount conditions.
  Future<CategoryRule> saveRule(
    int ruleId, {
    required String matchText,
    int? categoryId,
    bool isTransfer = false,
    int spreadMonths = 1,
    bool isRegex = false,
    String direction = 'any',
    String? minAmount,
    bool minInclusive = true,
    String? maxAmount,
    bool maxInclusive = false,
  }) async {
    final response = await _apiClient.patch(
      '${ApiConfig.spendingRulesPath}$ruleId/',
      data: _rulePayload(
        matchText: matchText,
        categoryId: categoryId,
        isTransfer: isTransfer,
        spreadMonths: spreadMonths,
        isRegex: isRegex,
        direction: direction,
        minAmount: minAmount,
        minInclusive: minInclusive,
        maxAmount: maxAmount,
        maxInclusive: maxInclusive,
      ),
    );
    return CategoryRule.fromJson(response.data as Map<String, dynamic>);
  }

  Map<String, dynamic> _rulePayload({
    required String matchText,
    required int? categoryId,
    required bool isTransfer,
    required int spreadMonths,
    required bool isRegex,
    required String direction,
    required String? minAmount,
    required bool minInclusive,
    required String? maxAmount,
    required bool maxInclusive,
  }) =>
      {
        'match_text': matchText,
        'is_regex': isRegex,
        'is_transfer': isTransfer,
        // A transfer is excluded from spending, so it carries neither a
        // category nor a spread to amortize.
        'category': isTransfer ? null : categoryId,
        'spread_months': isTransfer ? 1 : spreadMonths,
        'direction': direction,
        'min_amount': minAmount,
        'min_inclusive': minInclusive,
        'max_amount': maxAmount,
        'max_inclusive': maxInclusive,
      };

  /// What a rule would do if it were saved now. Nothing is written.
  Future<RulePreview> previewRule({
    required String matchText,
    bool isRegex = false,
    bool isTransfer = false,
    int? ruleId,
    String direction = 'any',
    String? minAmount,
    bool minInclusive = true,
    String? maxAmount,
    bool maxInclusive = false,
  }) async {
    final response = await _apiClient.post(
      ApiConfig.spendingRulesPreviewPath,
      data: {
        'match_text': matchText,
        'is_regex': isRegex,
        'is_transfer': isTransfer,
        'rule_id': ?ruleId,
        'direction': direction,
        'min_amount': minAmount,
        'min_inclusive': minInclusive,
        'max_amount': maxAmount,
        'max_inclusive': maxInclusive,
      },
    );
    return RulePreview.fromJson(response.data as Map<String, dynamic>);
  }

  /// Change a rule's target. Only the given fields are sent, so correcting a
  /// category never rewrites the rule's spread as a side effect.
  Future<CategoryRule> updateRule(
    int ruleId, {
    int? categoryId,
    int? spreadMonths,
    bool? isTransfer,
  }) async {
    final response = await _apiClient.patch(
      '${ApiConfig.spendingRulesPath}$ruleId/',
      data: {
        if (isTransfer == true) ...{
          'is_transfer': true,
          'category': null,
          'spread_months': 1,
        } else ...{
          'category': ?categoryId,
          'spread_months': ?spreadMonths,
          if (isTransfer == false) 'is_transfer': false,
        },
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

  /// Ask Gemini for suggestions. Nothing is persisted — the result is a
  /// proposal the user confirms via [applyAiSuggestions]. `mode` is 'items'
  /// (per-transaction categories) or 'rules' (reusable rules only) — the two
  /// are separate review flows.
  Future<AiSuggestResponse> suggestCategories({required String mode}) async {
    final response = await _apiClient.post(
      ApiConfig.aiSuggestPath,
      data: {'mode': mode},
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
                'is_transfer': s.isTransfer,
              })
          .toList(),
      'rules': rules
          .map((r) => {
                'match_text': r.matchText,
                'category': r.category,
                'is_regex': r.isRegex,
                'is_transfer': r.isTransfer,
                'replaces_rule_id': r.replacesRuleId,
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
