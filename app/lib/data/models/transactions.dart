import 'package:freezed_annotation/freezed_annotation.dart';

part 'transactions.freezed.dart';
part 'transactions.g.dart';

/// A booked transaction on an account.
///
/// [amount] arrives as a decimal string from the API (DRF DecimalField) and is
/// kept verbatim; use [value] for arithmetic and formatting.
@freezed
abstract class TransactionRecord with _$TransactionRecord {
  const factory TransactionRecord({
    required int id,
    required int account,
    @JsonKey(name: 'booking_date') required String bookingDate,
    @JsonKey(name: 'value_date') String? valueDate,
    required String amount,
    required String currency,
    @Default('') String counterparty,
    @Default('') String description,
    @Default('') String source,
    int? category,
    @JsonKey(name: 'category_name') String? categoryName,
    @JsonKey(name: 'spread_months') @Default(1) int spreadMonths,
    @JsonKey(name: 'is_transfer') @Default(false) bool isTransfer,
  }) = _TransactionRecord;

  factory TransactionRecord.fromJson(Map<String, dynamic> json) =>
      _$TransactionRecordFromJson(json);
}

extension TransactionRecordX on TransactionRecord {
  double get value => double.tryParse(amount) ?? 0;
  bool get isExpense => value < 0;
}

/// A page of an account's transactions.
@freezed
abstract class TransactionPage with _$TransactionPage {
  const factory TransactionPage({
    required int count,
    @Default(<TransactionRecord>[]) List<TransactionRecord> results,
  }) = _TransactionPage;

  factory TransactionPage.fromJson(Map<String, dynamic> json) =>
      _$TransactionPageFromJson(json);
}

@freezed
abstract class TransactionCategory with _$TransactionCategory {
  const factory TransactionCategory({
    required int id,
    required String name,
  }) = _TransactionCategory;

  factory TransactionCategory.fromJson(Map<String, dynamic> json) =>
      _$TransactionCategoryFromJson(json);
}

/// An auto-categorization rule. Rules are evaluated in [position] order and the
/// first match wins, so order is meaningful.
@freezed
abstract class CategoryRule with _$CategoryRule {
  const factory CategoryRule({
    required int id,
    @JsonKey(name: 'match_text') required String matchText,
    /// Null for transfer rules (see [isTransfer]).
    int? category,
    @JsonKey(name: 'category_name') String? categoryName,
    /// Marks matches as transfers instead of assigning a category.
    @JsonKey(name: 'is_transfer') @Default(false) bool isTransfer,
    @JsonKey(name: 'spread_months') @Default(1) int spreadMonths,
    @Default(0) int position,
    @JsonKey(name: 'is_regex') @Default(false) bool isRegex,
    /// 'any', 'payment' (amount < 0) or 'income' (amount > 0). Direction and
    /// size are independent facts about a transaction, so they are separate
    /// conditions — the bounds below carry no sign.
    @Default('any') String direction,
    /// Bounds on the amount WITHOUT its sign, as decimal strings ("20.00"),
    /// null for no bound.
    @JsonKey(name: 'min_amount') String? minAmount,
    @JsonKey(name: 'min_inclusive') @Default(true) bool minInclusive,
    @JsonKey(name: 'max_amount') String? maxAmount,
    @JsonKey(name: 'max_inclusive') @Default(false) bool maxInclusive,
  }) = _CategoryRule;

  factory CategoryRule.fromJson(Map<String, dynamic> json) =>
      _$CategoryRuleFromJson(json);
}

extension CategoryRuleX on CategoryRule {
  /// Human reading of the amount conditions, or null when there are none.
  String? get amountCondition {
    // Trailing zeros are noise in a condition read at a glance.
    String trim(String value) {
      final number = double.tryParse(value);
      return number == null ? value : _trimZeros(number);
    }

    final parts = [
      if (direction == 'payment') 'payments',
      if (direction == 'income') 'income',
      if (minAmount != null) '${minInclusive ? '≥' : '>'} ${trim(minAmount!)}',
      if (maxAmount != null) '${maxInclusive ? '≤' : '<'} ${trim(maxAmount!)}',
    ];
    return parts.isEmpty ? null : parts.join(', ');
  }
}

String _trimZeros(double value) =>
    value == value.roundToDouble() && value.abs() < 1e15
        ? value.toStringAsFixed(0)
        : value.toString();

/// What a rule would do to the transactions already imported, answered before
/// it is saved.
///
/// The useful number is not how many bookings contain the text: rules never
/// overwrite an existing category, and first-match-wins means an earlier rule
/// can claim a row first. Both are counted separately, because a rule that
/// reports zero is far more often shadowed than wrong.
@freezed
abstract class RulePreview with _$RulePreview {
  const factory RulePreview({
    @Default(0) int matched,
    @JsonKey(name: 'will_classify') @Default(0) int willClassify,
    @Default(0) int shadowed,
    @JsonKey(name: 'already_classified') @Default(0) int alreadyClassified,
    @Default(<RuleExample>[]) List<RuleExample> examples,
  }) = _RulePreview;

  factory RulePreview.fromJson(Map<String, dynamic> json) =>
      _$RulePreviewFromJson(json);
}

@freezed
abstract class RuleExample with _$RuleExample {
  const factory RuleExample({
    @JsonKey(name: 'booking_date') String? bookingDate,
    @Default('') String text,
  }) = _RuleExample;

  factory RuleExample.fromJson(Map<String, dynamic> json) =>
      _$RuleExampleFromJson(json);
}
