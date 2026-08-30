import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/models/spending.dart';
import 'package:wealth_tracker/presentation/providers/spending_provider.dart';
import 'package:wealth_tracker/presentation/screens/spending_screen.dart';

SpendingReport _report({
  String mode = 'normalized',
  Map<String, double> budgets = const {},
}) =>
    SpendingReport(
      mode: mode,
      baseCurrency: 'EUR',
      categories: const ['Rent', 'Groceries', 'Uncategorized'],
      budgets: budgets,
      months: const [
        SpendingMonth(
          month: '2026-07',
          income: 3450,
          expenses: 1600,
          net: 1850,
          byCategory: {'Rent': 1250, 'Groceries': 300, 'Uncategorized': 50},
        ),
        SpendingMonth(
          month: '2026-08',
          income: 3450,
          expenses: 1400,
          net: 2050,
          byCategory: {'Rent': 1250, 'Groceries': 150},
        ),
      ],
    );

Widget _harness(SpendingReport report) => ProviderScope(
      overrides: [
        spendingReportProvider.overrideWith((ref) async => report),
      ],
      child: const MaterialApp(home: SpendingScreen()),
    );

/// The page is taller than the default 800x600 test viewport; a tall surface
/// keeps every control laid out and hit-testable without scrolling.
void _useTallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// The breakdown's own stepper — the period bar above it has one too.
Finder _breakdownBack() => find.byIcon(Icons.chevron_left).last;

void main() {
  group('SpendingScreen', () {
    testWidgets('renders the latest period breakdown by default',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      expect(find.text('Breakdown · August 2026'), findsOneWidget);
      expect(find.text('Spending per month'), findsOneWidget);
      // Categories present in the newest month appear in its legend rows.
      expect(find.text('Rent'), findsWidgets);
    });

    testWidgets('previous-period arrow moves the breakdown back',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      await tester.tap(_breakdownBack());
      await tester.pumpAndSettle();

      expect(find.text('Breakdown · July 2026'), findsOneWidget);
      // Next arrow is enabled again once we are off the latest period.
      final next = tester.widget<IconButton>(
        find.ancestor(
          of: find.byIcon(Icons.chevron_right).last,
          matching: find.byType(IconButton),
        ),
      );
      expect(next.onPressed, isNotNull);
    });

    testWidgets('uncategorized filter hides the bucket from the breakdown',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      // Go to the month that has uncategorized spending.
      await tester.tap(_breakdownBack());
      await tester.pumpAndSettle();
      expect(find.text('Uncategorized'), findsWidgets);

      await tester.tap(find.text('Uncat.'));
      await tester.pumpAndSettle();
      expect(find.text('Uncategorized'), findsNothing);
    });

    testWidgets('summary tiles compare the period with its history',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      expect(find.text('Spent'), findsOneWidget);
      expect(find.text('Income'), findsWidgets);
      expect(find.text('Net'), findsOneWidget);
      // 1400 against 1600 the month before, which is also the only month in
      // the trailing average.
      expect(find.text('13% vs last'), findsOneWidget);
      expect(find.text('13% vs avg'), findsOneWidget);
      // Income was unchanged, so its delta reads flat rather than 0%.
      expect(find.text('flat vs last'), findsWidgets);
      // The latest period is still running.
      expect(find.text('so far'), findsNWidgets(3));
    });

    testWidgets('budgets show as a roll-up and per category', (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report(budgets: {'Rent': 1200})));
      await tester.pumpAndSettle();

      // Spent 1400 against a 1200 budget. Rich text matches as both the Text
      // and the RichText it builds, hence findsWidgets.
      expect(find.textContaining('over the', findRichText: true),
          findsWidgets);
      // Rent alone (1250) is 89% of what was spent.
      expect(find.textContaining('Budgets cover 89%'), findsOneWidget);
      // Rent itself is 50 over its own budget.
      expect(find.textContaining('over budget'), findsOneWidget);
    });

    testWidgets('tapping a category opens its history', (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Groceries').last);
      await tester.pumpAndSettle();

      expect(find.text('Average per month'), findsOneWidget);
      expect(find.text('Total (2 months)'), findsOneWidget);
    });

    testWidgets('shows an empty state when there are no months',
        (tester) async {
      await tester.pumpWidget(_harness(const SpendingReport(
        mode: 'normalized',
        baseCurrency: 'EUR',
      )));
      await tester.pumpAndSettle();

      expect(find.text('No transactions yet.'), findsOneWidget);
    });
  });

  group('SpendingReport', () {
    test('average excludes the running month', () {
      // Only 2026-07 (1600) counts; 2026-08 is the partial current month.
      expect(_report().averageExpenses, 1600);
    });
  });
}
