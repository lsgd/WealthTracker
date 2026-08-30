import 'package:freezed_annotation/freezed_annotation.dart';

part 'spending.freezed.dart';
part 'spending.g.dart';

/// One calendar month of the spending report.
///
/// [byCategory] maps category name -> amount spent in the report's base
/// currency. In normalized mode these are amortized slices, so a yearly bill
/// contributes one twelfth per month instead of spiking a single one.
@freezed
abstract class SpendingMonth with _$SpendingMonth {
  const factory SpendingMonth({
    required String month,
    required double income,
    required double expenses,
    required double net,
    @JsonKey(name: 'by_category')
    @Default(<String, double>{})
    Map<String, double> byCategory,
  }) = _SpendingMonth;

  factory SpendingMonth.fromJson(Map<String, dynamic> json) =>
      _$SpendingMonthFromJson(json);
}

@freezed
abstract class SpendingReport with _$SpendingReport {
  const factory SpendingReport({
    required String mode,
    @JsonKey(name: 'base_currency') required String baseCurrency,
    // 'month', 'quarter' or 'year'. The entries in [months] are periods of
    // this size; the field keeps its name for the clients that predate the
    // other granularities.
    @Default('month') String granularity,
    @Default(<String>[]) List<String> categories,
    @Default(<SpendingMonth>[]) List<SpendingMonth> months,
    // Per category, already scaled from the monthly budget to one period of
    // this granularity. Categories without a budget are absent.
    @Default(<String, double>{}) Map<String, double> budgets,
  }) = _SpendingReport;

  factory SpendingReport.fromJson(Map<String, dynamic> json) =>
      _$SpendingReportFromJson(json);
}

extension SpendingReportX on SpendingReport {
  /// Average spending per period, excluding the running (partial) one.
  double get averageExpenses {
    if (months.isEmpty) return 0;
    final complete = months.length > 1
        ? months.sublist(0, months.length - 1)
        : months;
    final total = complete.fold<double>(0, (sum, m) => sum + m.expenses);
    return total / complete.length;
  }
}
