import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/models/account.dart';
import 'package:wealth_tracker/data/datasources/api_client.dart';
import 'package:wealth_tracker/data/models/broker.dart';
import 'package:wealth_tracker/data/models/transactions.dart';
import 'package:wealth_tracker/data/repositories/spending_repository.dart';
import 'package:wealth_tracker/presentation/providers/accounts_provider.dart';
import 'package:wealth_tracker/presentation/providers/spending_provider.dart';
import 'package:wealth_tracker/presentation/widgets/transactions_tab.dart';

const _broker = Broker(code: 'zkb', name: 'ZKB');

const _accounts = [
  Account(
    id: 7,
    name: 'Giro',
    broker: _broker,
    accountType: 'checking',
    currency: 'EUR',
    isManual: false,
    syncEnabled: true,
    status: 'active',
  ),
  Account(
    id: 8,
    name: 'Cash',
    broker: _broker,
    accountType: 'savings',
    currency: 'EUR',
    isManual: true,
    syncEnabled: false,
    status: 'active',
  ),
];

const _records = [
  TransactionRecord(
    id: 11,
    account: 7,
    bookingDate: '2026-08-02',
    amount: '-25.50',
    currency: 'EUR',
    counterparty: 'Migros',
    description: 'Groceries',
    categoryName: 'Groceries',
    category: 1,
  ),
  TransactionRecord(
    id: 12,
    account: 8,
    bookingDate: '2026-08-01',
    amount: '-500.00',
    currency: 'EUR',
    counterparty: 'Eigenübertrag',
    description: 'Sparen',
    isTransfer: true,
  ),
];

class _FakeTransactionsNotifier extends TransactionsNotifier {
  final TransactionsState _fixed;
  int loadMoreCalls = 0;
  _FakeTransactionsNotifier(this._fixed);

  @override
  Future<TransactionsState> build() async => _fixed;

  @override
  Future<void> loadMore() async => loadMoreCalls++;
}

Widget _harness({
  List<TransactionRecord> records = _records,
  int? totalCount,
}) =>
    ProviderScope(
      overrides: [
        accountsProvider.overrideWith((ref) async => _accounts),
        transactionsProvider.overrideWith(() => _FakeTransactionsNotifier(
              TransactionsState(
                results: records,
                totalCount: totalCount ?? records.length,
                page: 1,
              ),
            )),
        categoriesProvider.overrideWith((ref) async => const [
              TransactionCategory(id: 1, name: 'Groceries'),
              TransactionCategory(id: 2, name: 'Rent'),
            ]),
      ],
      child: const MaterialApp(home: Scaffold(body: TransactionsTab())),
    );

/// Repository whose classification answers with a rule that now disagrees.
class _StaleRuleRepository extends SpendingRepository {
  _StaleRuleRepository() : super(_UnusedApiClient());

  int updateRuleCalls = 0;
  int? updatedCategoryId;

  static const rule = CategoryRule(
    id: 5, matchText: 'netflix', category: 9, categoryName: 'Subscriptions');

  @override
  Future<Classified> classifyTransaction(int id, {required int? categoryId}) async =>
      (
        transaction: _records.first.copyWith(category: categoryId, categoryName: 'Rent'),
        staleRule: rule,
      );

  @override
  Future<CategoryRule> updateRule(int ruleId,
      {int? categoryId, int? spreadMonths, bool? isTransfer}) async {
    updateRuleCalls++;
    updatedCategoryId = categoryId;
    return rule;
  }
}

class _UnusedApiClient implements ApiClient {
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnimplementedError('the fake answers before reaching the network');
}

void main() {
  group('TransactionsTab', () {
    testWidgets('lists transactions of all accounts with account chips',
        (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      expect(find.text('Migros'), findsOneWidget);
      expect(find.text('Eigenübertrag'), findsOneWidget);
      expect(find.text('Transfer'), findsOneWidget);
      // An unclassified row is labelled rather than left blank.
      expect(find.text('Uncategorized'), findsOneWidget);
      // Mixed-account list: each row names its account.
      expect(find.text('Giro'), findsOneWidget);
      expect(find.text('Cash'), findsOneWidget);
    });

    testWidgets('filter bar expands to account picker and uncategorized switch',
        (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      expect(find.text('All accounts'), findsOneWidget);
      await tester.tap(find.text('All accounts'));
      await tester.pumpAndSettle();

      expect(find.byType(DropdownButtonFormField<int?>), findsOneWidget);
      expect(find.byType(DropdownButtonFormField<String?>), findsOneWidget);
      expect(find.text('All periods'), findsOneWidget);
      expect(find.text('Only uncategorized'), findsOneWidget);
    });

    testWidgets('a period picked in Insights filters the list', (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();
      // Same provider the bar chart and the breakdown arrows write to.
      final container = ProviderScope.containerOf(
          tester.element(find.byType(TransactionsTab)));
      container.read(spendingSelectedMonthProvider.notifier).set('2026-07');
      await tester.pumpAndSettle();

      expect(container.read(transactionsFilterProvider).month, '2026-07');
      // And the collapsed filter bar says so rather than filtering silently,
      // spelling the period out the way the period bar does.
      expect(find.textContaining('July 2026'), findsOneWidget);
    });

    testWidgets('scrolling near the end loads the next page', (tester) async {
      final many = [
        for (var i = 0; i < 30; i++) _records.first.copyWith(id: 100 + i),
      ];
      final notifier = _FakeTransactionsNotifier(
        TransactionsState(results: many, totalCount: 150, page: 1),
      );
      await tester.pumpWidget(ProviderScope(
        overrides: [
          accountsProvider.overrideWith((ref) async => _accounts),
          transactionsProvider.overrideWith(() => notifier),
          categoriesProvider.overrideWith((ref) async => const []),
        ],
        child: const MaterialApp(home: Scaffold(body: TransactionsTab())),
      ));
      await tester.pumpAndSettle();
      expect(notifier.loadMoreCalls, 0);

      await tester.fling(find.byType(ListView), const Offset(0, -3000), 3000);
      // No pumpAndSettle: the endless-scroll footer spinner animates forever.
      await tester.pump(const Duration(seconds: 1));

      expect(notifier.loadMoreCalls, greaterThan(0));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('tapping a transaction opens the category picker',
        (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Migros'));
      await tester.pumpAndSettle();

      expect(find.text('Category'), findsOneWidget);
      expect(find.text('Rent'), findsOneWidget);
      // The already-assigned category can be cleared again.
      expect(find.text('Remove category'), findsOneWidget);
      // The transfer switch is offered too.
      expect(find.text('Transfer between own accounts'), findsOneWidget);
    });

    testWidgets('the picker offers a spread, but not for a transfer',
        (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Migros'));
      await tester.pumpAndSettle();
      expect(find.text('Spread'), findsOneWidget);
      expect(find.text('/12m'), findsOneWidget);
      // The category list stays reachable next to it.
      expect(find.text('Rent'), findsOneWidget);

      await tester.tapAt(const Offset(10, 10));  // dismiss the sheet
      await tester.pumpAndSettle();

      // A transfer is excluded from spending — there is nothing to amortize.
      await tester.tap(find.text('Eigenübertrag'));
      await tester.pumpAndSettle();
      expect(find.text('Spread'), findsNothing);
    });

    testWidgets('a non-standard spread stays selectable in the picker',
        (tester) async {
      // A rule (or Gemini) can set any number; the segmented control must
      // still be able to show it as the current selection.
      await tester.pumpWidget(_harness(
        records: [_records.first.copyWith(spreadMonths: 4)],
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Migros'));
      await tester.pumpAndSettle();
      // Not the row's badge — the segment that shows it as the current choice.
      expect(
        find.descendant(
          of: find.byType(SegmentedButton<int>),
          matching: find.text('/4m'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('correcting a category offers to fix the rule behind it',
        (tester) async {
      final repo = _StaleRuleRepository();
      await tester.pumpWidget(ProviderScope(
        overrides: [
          accountsProvider.overrideWith((ref) async => _accounts),
          spendingRepositoryProvider.overrideWithValue(repo),
          transactionsProvider.overrideWith(
              () => _FakeTransactionsNotifier(const TransactionsState(
                    results: _records, totalCount: 2, page: 1,
                  ))),
          categoriesProvider.overrideWith((ref) async => const [
                TransactionCategory(id: 1, name: 'Groceries'),
                TransactionCategory(id: 2, name: 'Rent'),
              ]),
        ],
        child: const MaterialApp(home: Scaffold(body: TransactionsTab())),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Migros'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Rent'));
      await tester.pumpAndSettle();

      // The rule that classified it disagrees now, so it is named.
      expect(find.text('Update the rule too?'), findsOneWidget);
      expect(find.textContaining('netflix'), findsOneWidget);
      expect(repo.updateRuleCalls, 0);

      await tester.tap(find.text('Update the rule'));
      await tester.pumpAndSettle();
      expect(repo.updateRuleCalls, 1);
      expect(repo.updatedCategoryId, 2);
    });

    testWidgets('declining leaves the rule alone', (tester) async {
      final repo = _StaleRuleRepository();
      await tester.pumpWidget(ProviderScope(
        overrides: [
          accountsProvider.overrideWith((ref) async => _accounts),
          spendingRepositoryProvider.overrideWithValue(repo),
          transactionsProvider.overrideWith(
              () => _FakeTransactionsNotifier(const TransactionsState(
                    results: _records, totalCount: 2, page: 1,
                  ))),
          categoriesProvider.overrideWith((ref) async => const [
                TransactionCategory(id: 2, name: 'Rent'),
              ]),
        ],
        child: const MaterialApp(home: Scaffold(body: TransactionsTab())),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Migros'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Rent'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Just this one'));
      await tester.pumpAndSettle();

      expect(repo.updateRuleCalls, 0);
    });

    testWidgets('empty list shows a hint', (tester) async {
      await tester.pumpWidget(_harness(records: const []));
      await tester.pumpAndSettle();

      expect(find.text('No transactions yet.'), findsOneWidget);
    });
  });
}
