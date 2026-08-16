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
    @Default(<String>[]) List<String> categories,
    @Default(<SpendingMonth>[]) List<SpendingMonth> months,
  }) = _SpendingReport;

  factory SpendingReport.fromJson(Map<String, dynamic> json) =>
      _$SpendingReportFromJson(json);
}

extension SpendingMonthX on SpendingMonth {
  /// First day of this month, parsed from the ``YYYY-MM`` label.
  DateTime get dateTime {
    final parts = month.split('-');
    return DateTime(int.parse(parts[0]), int.parse(parts[1]));
  }
}

extension SpendingReportX on SpendingReport {
  /// Average monthly spending, excluding the running (partial) month.
  double get averageExpenses {
    if (months.isEmpty) return 0;
    final complete = months.length > 1
        ? months.sublist(0, months.length - 1)
        : months;
    final total = complete.fold<double>(0, (sum, m) => sum + m.expenses);
    return total / complete.length;
  }
}
