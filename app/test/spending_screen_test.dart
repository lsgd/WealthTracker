import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/models/spending.dart';
import 'package:wealth_tracker/presentation/providers/spending_provider.dart';
import 'package:wealth_tracker/presentation/screens/spending_screen.dart';

SpendingReport _report({String mode = 'normalized'}) => SpendingReport(
      mode: mode,
      baseCurrency: 'EUR',
      categories: const ['Rent', 'Groceries', 'Uncategorized'],
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

void main() {
  group('SpendingScreen', () {
    testWidgets('renders the latest month breakdown by default',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      expect(find.text('Breakdown · 2026-08'), findsOneWidget);
      expect(find.text('Monthly spending'), findsOneWidget);
      // Categories present in the newest month appear in its legend rows.
      expect(find.text('Rent'), findsWidgets);
    });

    testWidgets('previous-month arrow moves the breakdown back', (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(_report()));
      await tester.pumpAndSettle();

      await tester.tap(find.byIcon(Icons.chevron_left));
      await tester.pumpAndSettle();

      expect(find.text('Breakdown · 2026-07'), findsOneWidget);
      // Next arrow is enabled again once we are off the latest month.
      final next = tester.widget<IconButton>(
        find.ancestor(
          of: find.byIcon(Icons.chevron_right),
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
      await tester.tap(find.byIcon(Icons.chevron_left));
      await tester.pumpAndSettle();
      expect(find.text('Uncategorized'), findsWidgets);

      await tester.tap(find.text('Uncat.'));
      await tester.pumpAndSettle();
      expect(find.text('Uncategorized'), findsNothing);
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
