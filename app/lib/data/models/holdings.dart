import 'package:freezed_annotation/freezed_annotation.dart';

part 'holdings.freezed.dart';
part 'holdings.g.dart';

/// One instrument, merged by ISIN across all accounts that hold it.
@freezed
abstract class Holding with _$Holding {
  const factory Holding({
    @Default('') String isin,
    @Default('') String symbol,
    required String name,
    @JsonKey(name: 'asset_class') required String assetClass,
    required double quantity,
    @JsonKey(name: 'value_base_currency') required double valueBaseCurrency,
    @JsonKey(name: 'price_base_currency') double? priceBaseCurrency,
    required double percentage,
    required List<String> accounts,
  }) = _Holding;

  factory Holding.fromJson(Map<String, dynamic> json) => _$HoldingFromJson(json);
}

@freezed
abstract class HoldingsReport with _$HoldingsReport {
  const factory HoldingsReport({
    @JsonKey(name: 'base_currency') required String baseCurrency,
    @JsonKey(name: 'as_of') String? asOf,
    required double total,
    required List<Holding> holdings,
  }) = _HoldingsReport;

  factory HoldingsReport.fromJson(Map<String, dynamic> json) =>
      _$HoldingsReportFromJson(json);
}
