import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/periods.dart';
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

/// Period size of the report: 'month', 'quarter' or 'year'.
final spendingGranularityProvider =
    NotifierProvider<SpendingGranularityNotifier, String>(
        SpendingGranularityNotifier.new);

class SpendingGranularityNotifier extends Notifier<String> {
  @override
  String build() => 'month';

  /// Switching period size invalidates both the amount of history (12 months
  /// and 12 years are not the same ask) and the selected period, whose label
  /// belongs to the old granularity.
  void set(String value) {
    if (state == value) return;
    state = value;
    ref.read(spendingRangeProvider.notifier).set(defaultHistory(value));
    ref.read(spendingSelectedMonthProvider.notifier).set(null);
  }
}

/// Number of periods the report covers, in the current granularity.
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

/// Period selected for the breakdown; null follows the latest period.
final spendingSelectedMonthProvider =
    NotifierProvider<SpendingSelectedMonthNotifier, String?>(
        SpendingSelectedMonthNotifier.new);

class SpendingSelectedMonthNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  /// Also narrows the transaction list to that period: both tabs are looking
  /// at the same period, and re-picking it by hand was pure friction. The
  /// label carries its own granularity ('2026-Q3'), which the transaction
  /// endpoint understands as well as a month.
  void set(String? value) {
    state = value;
    ref.read(transactionsFilterProvider.notifier).setMonth(value);
  }
}

final spendingReportProvider = FutureProvider<SpendingReport>((ref) async {
  final repository = ref.watch(spendingRepositoryProvider);
  return repository.getMonthly(
    months: ref.watch(spendingRangeProvider),
    mode: ref.watch(spendingModeProvider),
    granularity: ref.watch(spendingGranularityProvider),
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

/// Filter for the transaction list. Default: every account, every month,
/// chronological. [month] is a ``YYYY-MM`` label, null for all months.
typedef TransactionsFilter = ({
  int? accountId,
  bool uncategorizedOnly,
  String? month,
});

final transactionsFilterProvider =
    NotifierProvider<TransactionsFilterNotifier, TransactionsFilter>(
        TransactionsFilterNotifier.new);

class TransactionsFilterNotifier extends Notifier<TransactionsFilter> {
  @override
  TransactionsFilter build() =>
      (accountId: null, uncategorizedOnly: false, month: null);

  void setAccount(int? accountId) => state = (
        accountId: accountId,
        uncategorizedOnly: state.uncategorizedOnly,
        month: state.month,
      );

  void setUncategorizedOnly(bool value) => state = (
        accountId: state.accountId,
        uncategorizedOnly: value,
        month: state.month,
      );

  void setMonth(String? month) => state = (
        accountId: state.accountId,
        uncategorizedOnly: state.uncategorizedOnly,
        month: month,
      );
}

/// Loaded transactions for the current filter, accumulated across pages.
class TransactionsState {
  final List<TransactionRecord> results;
  final int totalCount;
  final int page;
  final bool loadingMore;

  const TransactionsState({
    required this.results,
    required this.totalCount,
    required this.page,
    this.loadingMore = false,
  });

  bool get hasMore => results.length < totalCount;
}

final transactionsProvider =
    AsyncNotifierProvider<TransactionsNotifier, TransactionsState>(
        TransactionsNotifier.new);

class TransactionsNotifier extends AsyncNotifier<TransactionsState> {
  @override
  Future<TransactionsState> build() async {
    // Watching the filter makes any filter change reload from page 1.
    final filter = ref.watch(transactionsFilterProvider);
    final page = await ref.read(spendingRepositoryProvider).getTransactions(
          accountId: filter.accountId,
          uncategorizedOnly: filter.uncategorizedOnly,
          month: filter.month,
        );
    return TransactionsState(
        results: page.results, totalCount: page.count, page: 1);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.loadingMore) return;
    state = AsyncData(TransactionsState(
      results: current.results,
      totalCount: current.totalCount,
      page: current.page,
      loadingMore: true,
    ));
    final filter = ref.read(transactionsFilterProvider);
    try {
      final next = await ref.read(spendingRepositoryProvider).getTransactions(
            accountId: filter.accountId,
            uncategorizedOnly: filter.uncategorizedOnly,
            month: filter.month,
            page: current.page + 1,
          );
      state = AsyncData(TransactionsState(
        results: [...current.results, ...next.results],
        totalCount: next.count,
        page: current.page + 1,
      ));
    } catch (_) {
      // Keep what is shown; the footer button simply becomes tappable again.
      state = AsyncData(TransactionsState(
        results: current.results,
        totalCount: current.totalCount,
        page: current.page,
      ));
    }
  }

  /// A classified transaction changed in place — update it without a reload
  /// so the scroll position and loaded pages survive.
  void replace(TransactionRecord updated) {
    final current = state.value;
    if (current == null) return;
    state = AsyncData(TransactionsState(
      results: [
        for (final t in current.results) t.id == updated.id ? updated : t,
      ],
      totalCount: current.totalCount,
      page: current.page,
    ));
  }
}

/// Gemini configuration (key presence, selected model, price snapshot).
final aiConfigProvider = FutureProvider<AiConfig>((ref) async {
  return ref.watch(spendingRepositoryProvider).getAiConfig();
});
