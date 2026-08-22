import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/models/account.dart';
import 'package:wealth_tracker/data/models/broker.dart';
import 'package:wealth_tracker/data/models/transactions.dart';
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
  _FakeTransactionsNotifier(this._fixed);

  @override
  Future<TransactionsState> build() async => _fixed;
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
      expect(find.text('Only uncategorized'), findsOneWidget);
    });

    testWidgets('load-more footer appears when more pages exist',
        (tester) async {
      await tester.pumpWidget(_harness(totalCount: 150));
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(find.textContaining('Load more'), 200);
      expect(find.text('Load more (2/150)'), findsOneWidget);
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

    testWidgets('empty list shows a hint', (tester) async {
      await tester.pumpWidget(_harness(records: const []));
      await tester.pumpAndSettle();

      expect(find.text('No transactions yet.'), findsOneWidget);
    });
  });
}
