import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/ai_categorization.dart';
import '../../data/models/spending.dart';
import '../../data/models/transactions.dart';
import '../../data/repositories/spending_repository.dart';
import 'core_providers.dart';

final spendingRepositoryProvider = Provider<SpendingRepository>((ref) {
  return SpendingRepository(ref.watch(apiClientProvider));
});

/// Report mode: 'normalized' (yearly bills spread) or 'actual' (raw cash flow).
final spendingModeProvider =
    NotifierProvider<SpendingModeNotifier, String>(SpendingModeNotifier.new);

class SpendingModeNotifier extends Notifier<String> {
  @override
  String build() => 'normalized';

  void set(String value) => state = value;
}

/// Number of months the report covers.
final spendingRangeProvider =
    NotifierProvider<SpendingRangeNotifier, int>(SpendingRangeNotifier.new);

class SpendingRangeNotifier extends Notifier<int> {
  @override
  int build() => 12;

  void set(int value) => state = value;
}

/// Whether uncategorized spending is included in the charts.
final spendingShowUncategorizedProvider =
    NotifierProvider<SpendingShowUncategorizedNotifier, bool>(
        SpendingShowUncategorizedNotifier.new);

class SpendingShowUncategorizedNotifier extends Notifier<bool> {
  @override
  bool build() => true;

  void set(bool value) => state = value;
}

/// Month selected for the breakdown; null follows the latest month.
final spendingSelectedMonthProvider =
    NotifierProvider<SpendingSelectedMonthNotifier, String?>(
        SpendingSelectedMonthNotifier.new);

class SpendingSelectedMonthNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void set(String? value) => state = value;
}

final spendingReportProvider = FutureProvider<SpendingReport>((ref) async {
  final repository = ref.watch(spendingRepositoryProvider);
  return repository.getMonthly(
    months: ref.watch(spendingRangeProvider),
    mode: ref.watch(spendingModeProvider),
  );
});

/// The user's spending categories.
final categoriesProvider =
    FutureProvider<List<TransactionCategory>>((ref) async {
  return ref.watch(spendingRepositoryProvider).getCategories();
});

/// Auto-categorization rules, in evaluation order (first match wins).
final categoryRulesProvider = FutureProvider<List<CategoryRule>>((ref) async {
  return ref.watch(spendingRepositoryProvider).getRules();
});

/// Account whose transactions are listed; null until accounts have loaded.
final transactionsAccountProvider =
    NotifierProvider<TransactionsAccountNotifier, int?>(
        TransactionsAccountNotifier.new);

class TransactionsAccountNotifier extends Notifier<int?> {
  @override
  int? build() => null;

  void set(int? value) => state = value;
}

/// First page of transactions for an account.
final accountTransactionsProvider =
    FutureProvider.family<TransactionPage, int>((ref, accountId) async {
  return ref.watch(spendingRepositoryProvider).getAccountTransactions(accountId);
});

/// Gemini configuration (key presence, selected model, price snapshot).
final aiConfigProvider = FutureProvider<AiConfig>((ref) async {
  return ref.watch(spendingRepositoryProvider).getAiConfig();
});
