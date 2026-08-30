import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/datasources/api_client.dart';
import 'package:wealth_tracker/data/models/transactions.dart';
import 'package:wealth_tracker/data/repositories/spending_repository.dart';
import 'package:wealth_tracker/presentation/providers/spending_provider.dart';
import 'package:wealth_tracker/presentation/widgets/rule_dialog.dart';

const _categories = [
  TransactionCategory(id: 1, name: 'Groceries'),
  TransactionCategory(id: 2, name: 'Rent'),
];

/// Records what the dialog asked for instead of reaching the network.
class _FakeRepository extends SpendingRepository {
  _FakeRepository() : super(_UnusedApiClient());

  final previews = <Map<String, Object?>>[];
  Map<String, Object?>? created;
  Map<String, Object?>? saved;

  @override
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
    previews.add({
      'match_text': matchText,
      'is_regex': isRegex,
      'rule_id': ruleId,
      'direction': direction,
      'min_amount': minAmount,
      'max_amount': maxAmount,
    });
    return const RulePreview(
      matched: 5, willClassify: 3, shadowed: 1, alreadyClassified: 1);
  }

  @override
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
    created = {
      'match_text': matchText,
      'category': categoryId,
      'is_transfer': isTransfer,
      'spread_months': spreadMonths,
      'is_regex': isRegex,
      'direction': direction,
      'min_amount': minAmount,
      'min_inclusive': minInclusive,
      'max_amount': maxAmount,
      'max_inclusive': maxInclusive,
    };
    return CategoryRule(id: 1, matchText: matchText, category: categoryId);
  }

  @override
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
    saved = {
      'id': ruleId,
      'match_text': matchText,
      'category': categoryId,
      'is_transfer': isTransfer,
      'is_regex': isRegex,
      'direction': direction,
      'min_amount': minAmount,
      'max_amount': maxAmount,
    };
    return CategoryRule(id: ruleId, matchText: matchText, category: categoryId);
  }
}

class _UnusedApiClient implements ApiClient {
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnimplementedError('the fake answers before reaching the network');
}

Widget _harness(_FakeRepository repository, {CategoryRule? rule,
    String? initialMatchText}) =>
    ProviderScope(
      overrides: [
        spendingRepositoryProvider.overrideWithValue(repository),
      ],
      child: MaterialApp(
        home: Scaffold(
          body: RuleDialog(
            categories: _categories,
            rule: rule,
            initialMatchText: initialMatchText,
          ),
        ),
      ),
    );

void main() {
  group('RuleDialog', () {
    testWidgets('previews what a new rule would do', (tester) async {
      final repository = _FakeRepository();
      await tester.pumpWidget(_harness(repository));

      await tester.enterText(find.byType(TextField).first, 'rewe');
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();

      expect(repository.previews.last['match_text'], 'rewe');
      expect(find.textContaining('Will categorize 3 existing'), findsOneWidget);
      // A rule reporting little is far more often shadowed than wrong, so the
      // reasons are spelled out.
      expect(find.textContaining('claimed by an earlier rule'), findsOneWidget);
    });

    testWidgets('creates a rule with its amount conditions', (tester) async {
      final repository = _FakeRepository();
      await tester.pumpWidget(_harness(repository));

      await tester.enterText(find.byType(TextField).first, 'sbb');
      await tester.tap(find.text('Target'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Rent').last);
      await tester.pumpAndSettle();

      await tester.tap(find.text('Advanced'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Payments'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'At least'), '20');
      await tester.pumpAndSettle();

      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(repository.created, {
        'match_text': 'sbb',
        'category': 2,
        'is_transfer': false,
        'spread_months': 1,
        'is_regex': false,
        'direction': 'payment',
        'min_amount': '20',
        'min_inclusive': true,
        'max_amount': null,
        'max_inclusive': false,
      });
    });

    testWidgets('a transfer rule carries neither category nor spread',
        (tester) async {
      final repository = _FakeRepository();
      await tester.pumpWidget(_harness(repository));

      await tester.enterText(find.byType(TextField).first, 'eigenübertrag');
      await tester.tap(find.text('Target'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Transfer (excluded)').last);
      await tester.pumpAndSettle();

      // The spread control is gone: a transfer is excluded from spending.
      expect(find.text('Spread'), findsNothing);

      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(repository.created?['is_transfer'], true);
      expect(repository.created?['category'], null);
      expect(find.textContaining('mark as transfers'), findsNothing);
    });

    testWidgets('opens an existing rule with its conditions filled in',
        (tester) async {
      final repository = _FakeRepository();
      await tester.pumpWidget(_harness(
        repository,
        rule: const CategoryRule(
          id: 4,
          matchText: 'coop',
          category: 1,
          categoryName: 'Groceries',
          isRegex: true,
          direction: 'payment',
          minAmount: '20.00',
          maxAmount: '99.50',
        ),
      ));
      // Past the preview debounce, which starts as the dialog opens.
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();

      // Trailing zeros are trimmed in a field about to be edited.
      expect(find.widgetWithText(TextField, '20'), findsOneWidget);
      expect(find.widgetWithText(TextField, '99.5'), findsOneWidget);
      // Advanced opens by itself when the rule has something in there.
      expect(find.text('Payments'), findsOneWidget);
      expect(repository.previews.last['rule_id'], 4);

      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(repository.saved?['id'], 4);
      expect(repository.saved?['direction'], 'payment');
      expect(repository.saved?['is_regex'], true);
      expect(repository.saved?['min_amount'], '20');
    });

    testWidgets('refuses a range no amount can satisfy', (tester) async {
      final repository = _FakeRepository();
      await tester.pumpWidget(_harness(repository, initialMatchText: 'coop'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Advanced'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'At least'), '50');
      await tester.enterText(find.widgetWithText(TextField, 'At most'), '10');
      await tester.pumpAndSettle();

      expect(find.textContaining('amount range is empty'), findsOneWidget);
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();
      expect(repository.created, isNull);
    });
  });
}
