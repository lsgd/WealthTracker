// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'holdings.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_Holding _$HoldingFromJson(Map<String, dynamic> json) => _Holding(
  isin: json['isin'] as String? ?? '',
  symbol: json['symbol'] as String? ?? '',
  name: json['name'] as String,
  assetClass: json['asset_class'] as String,
  quantity: (json['quantity'] as num).toDouble(),
  valueBaseCurrency: (json['value_base_currency'] as num).toDouble(),
  priceBaseCurrency: (json['price_base_currency'] as num?)?.toDouble(),
  percentage: (json['percentage'] as num).toDouble(),
  accounts: (json['accounts'] as List<dynamic>)
      .map((e) => e as String)
      .toList(),
);

Map<String, dynamic> _$HoldingToJson(_Holding instance) => <String, dynamic>{
  'isin': instance.isin,
  'symbol': instance.symbol,
  'name': instance.name,
  'asset_class': instance.assetClass,
  'quantity': instance.quantity,
  'value_base_currency': instance.valueBaseCurrency,
  'price_base_currency': instance.priceBaseCurrency,
  'percentage': instance.percentage,
  'accounts': instance.accounts,
};

_HoldingsReport _$HoldingsReportFromJson(Map<String, dynamic> json) =>
    _HoldingsReport(
      baseCurrency: json['base_currency'] as String,
      asOf: json['as_of'] as String?,
      total: (json['total'] as num).toDouble(),
      holdings: (json['holdings'] as List<dynamic>)
          .map((e) => Holding.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$HoldingsReportToJson(_HoldingsReport instance) =>
    <String, dynamic>{
      'base_currency': instance.baseCurrency,
      'as_of': instance.asOf,
      'total': instance.total,
      'holdings': instance.holdings,
    };
