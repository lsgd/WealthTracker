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
    required int category,
    @JsonKey(name: 'category_name') String? categoryName,
    @JsonKey(name: 'spread_months') @Default(1) int spreadMonths,
    @Default(0) int position,
  }) = _CategoryRule;

  factory CategoryRule.fromJson(Map<String, dynamic> json) =>
      _$CategoryRuleFromJson(json);
}
