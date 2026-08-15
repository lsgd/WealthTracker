// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'spending.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_SpendingMonth _$SpendingMonthFromJson(Map<String, dynamic> json) =>
    _SpendingMonth(
      month: json['month'] as String,
      income: (json['income'] as num).toDouble(),
      expenses: (json['expenses'] as num).toDouble(),
      net: (json['net'] as num).toDouble(),
      byCategory:
          (json['by_category'] as Map<String, dynamic>?)?.map(
            (k, e) => MapEntry(k, (e as num).toDouble()),
          ) ??
          const <String, double>{},
    );

Map<String, dynamic> _$SpendingMonthToJson(_SpendingMonth instance) =>
    <String, dynamic>{
      'month': instance.month,
      'income': instance.income,
      'expenses': instance.expenses,
      'net': instance.net,
      'by_category': instance.byCategory,
    };

_SpendingReport _$SpendingReportFromJson(Map<String, dynamic> json) =>
    _SpendingReport(
      mode: json['mode'] as String,
      baseCurrency: json['base_currency'] as String,
      categories:
          (json['categories'] as List<dynamic>?)
              ?.map((e) => e as String)
              .toList() ??
          const <String>[],
      months:
          (json['months'] as List<dynamic>?)
              ?.map((e) => SpendingMonth.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <SpendingMonth>[],
    );

Map<String, dynamic> _$SpendingReportToJson(_SpendingReport instance) =>
    <String, dynamic>{
      'mode': instance.mode,
      'base_currency': instance.baseCurrency,
      'categories': instance.categories,
      'months': instance.months,
    };
