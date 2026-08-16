import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/models/ai_categorization.dart';
import 'package:wealth_tracker/data/models/transactions.dart';
import 'package:wealth_tracker/presentation/providers/spending_provider.dart';
import 'package:wealth_tracker/presentation/screens/spending_config_screen.dart';

const _rules = [
  CategoryRule(
      id: 1, matchText: 'rewe', category: 1, categoryName: 'Groceries'),
  CategoryRule(
      id: 2,
      matchText: 'axa',
      category: 2,
      categoryName: 'Insurance',
      spreadMonths: 12,
      position: 1),
];

const _configured = AiConfig(
  configured: true,
  model: 'gemini-3.7-flash',
  pricing: AiPricing(
    model: 'gemini-3.7-flash',
    displayName: 'Gemini 3.7 Flash',
    inputPricePer1m: 0.75,
    outputPricePer1m: 3.75,
    checkedAt: '2026-08-16T10:00:00Z',
  ),
  disclosedFields: ['Counterparty name of each uncategorized transaction'],
);

Widget _harness({
  List<CategoryRule> rules = _rules,
  AiConfig config = _configured,
}) =>
    ProviderScope(
      overrides: [
        categoryRulesProvider.overrideWith((ref) async => rules),
        categoriesProvider.overrideWith((ref) async => const [
              TransactionCategory(id: 1, name: 'Groceries'),
              TransactionCategory(id: 2, name: 'Insurance'),
            ]),
        aiConfigProvider.overrideWith((ref) async => config),
      ],
      child: const MaterialApp(home: SpendingConfigScreen()),
    );

void _useTallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

void main() {
  group('SpendingConfigScreen', () {
    testWidgets('lists rules in evaluation order with their position',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      expect(find.text('rewe'), findsOneWidget);
      expect(find.text('axa'), findsOneWidget);
      // Position labels make first-match-wins visible.
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      // The spread is surfaced on the rule that has one.
      expect(
        find.textContaining('spread over 12 months'),
        findsOneWidget,
      );
    });

    testWidgets('shows the configured Gemini model, price and check date',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      expect(find.text('Gemini 3.7 Flash'), findsOneWidget);
      expect(find.text('\$0.75 in / \$3.75 out per 1M tokens'), findsOneWidget);
      expect(find.textContaining('prices checked'), findsOneWidget);
      // Key/model management stays on the web.
      expect(find.textContaining('managed in the web app'), findsOneWidget);
      expect(find.text('Get suggestions'), findsOneWidget);
    });

    testWidgets('points at the web app when Gemini is not configured',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(
        _harness(config: const AiConfig(configured: false)),
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('web app'), findsOneWidget);
      expect(find.text('Get suggestions'), findsNothing);
    });

    testWidgets('opens the new-rule dialog', (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Add rule'));
      await tester.pumpAndSettle();

      expect(find.text('New rule'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Match text'), findsOneWidget);
      expect(find.text('No spread'), findsOneWidget);

      // The category dropdown offers the existing categories and an inline
      // "create one" entry, so a rule never dead-ends on a missing category.
      await tester.tap(find.byType(DropdownButtonFormField<Object?>));
      await tester.pumpAndSettle();
      expect(find.text('Groceries'), findsWidgets);
      expect(find.text('New category…'), findsOneWidget);
    });

    testWidgets('empty rule list renders a hint instead of the list',
        (tester) async {
      _useTallViewport(tester);
      await tester.pumpWidget(_harness(rules: const []));
      await tester.pumpAndSettle();

      expect(find.text('No rules yet.'), findsOneWidget);
    });
  });
}
