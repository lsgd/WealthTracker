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
  // Manual accounts have no feed, so they must not be offered here.
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

const _page = TransactionPage(
  count: 2,
  results: [
    TransactionRecord(
      id: 11,
      account: 7,
      bookingDate: '2026-08-01',
      amount: '-25.50',
      currency: 'EUR',
      counterparty: 'Migros',
      description: 'Groceries',
      categoryName: 'Groceries',
      category: 1,
    ),
    TransactionRecord(
      id: 12,
      account: 7,
      bookingDate: '2026-08-02',
      amount: '-500.00',
      currency: 'EUR',
      counterparty: 'Eigenübertrag',
      description: 'Sparen',
      isTransfer: true,
    ),
  ],
);

Widget _harness({TransactionPage page = _page}) => ProviderScope(
      overrides: [
        accountsProvider.overrideWith((ref) async => _accounts),
        accountTransactionsProvider(7).overrideWith((ref) async => page),
        categoriesProvider.overrideWith((ref) async => const [
              TransactionCategory(id: 1, name: 'Groceries'),
              TransactionCategory(id: 2, name: 'Rent'),
            ]),
      ],
      child: const MaterialApp(home: Scaffold(body: TransactionsTab())),
    );

void main() {
  group('TransactionsTab', () {
    testWidgets('lists transactions with their category and transfer badge',
        (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      expect(find.text('Migros'), findsOneWidget);
      expect(find.text('Groceries'), findsWidgets);
      expect(find.text('Eigenübertrag'), findsOneWidget);
      expect(find.text('Transfer'), findsOneWidget);
      // An unclassified row is labelled rather than left blank.
      expect(find.text('Uncategorized'), findsOneWidget);
    });

    testWidgets('only offers accounts that have a transaction feed',
        (tester) async {
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      await tester.tap(find.byType(DropdownButtonFormField<int>));
      await tester.pumpAndSettle();

      expect(find.text('Giro'), findsWidgets);
      expect(find.text('Cash'), findsNothing);
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
    });

    testWidgets('empty account shows a hint', (tester) async {
      await tester.pumpWidget(
        _harness(page: const TransactionPage(count: 0)),
      );
      await tester.pumpAndSettle();

      expect(find.text('No transactions for this account.'), findsOneWidget);
    });
  });
}
