// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'transactions.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_TransactionRecord _$TransactionRecordFromJson(Map<String, dynamic> json) =>
    _TransactionRecord(
      id: (json['id'] as num).toInt(),
      account: (json['account'] as num).toInt(),
      bookingDate: json['booking_date'] as String,
      valueDate: json['value_date'] as String?,
      amount: json['amount'] as String,
      currency: json['currency'] as String,
      counterparty: json['counterparty'] as String? ?? '',
      description: json['description'] as String? ?? '',
      source: json['source'] as String? ?? '',
      category: (json['category'] as num?)?.toInt(),
      categoryName: json['category_name'] as String?,
      spreadMonths: (json['spread_months'] as num?)?.toInt() ?? 1,
      isTransfer: json['is_transfer'] as bool? ?? false,
    );

Map<String, dynamic> _$TransactionRecordToJson(_TransactionRecord instance) =>
    <String, dynamic>{
      'id': instance.id,
      'account': instance.account,
      'booking_date': instance.bookingDate,
      'value_date': instance.valueDate,
      'amount': instance.amount,
      'currency': instance.currency,
      'counterparty': instance.counterparty,
      'description': instance.description,
      'source': instance.source,
      'category': instance.category,
      'category_name': instance.categoryName,
      'spread_months': instance.spreadMonths,
      'is_transfer': instance.isTransfer,
    };

_TransactionPage _$TransactionPageFromJson(Map<String, dynamic> json) =>
    _TransactionPage(
      count: (json['count'] as num).toInt(),
      results:
          (json['results'] as List<dynamic>?)
              ?.map(
                (e) => TransactionRecord.fromJson(e as Map<String, dynamic>),
              )
              .toList() ??
          const <TransactionRecord>[],
    );

Map<String, dynamic> _$TransactionPageToJson(_TransactionPage instance) =>
    <String, dynamic>{'count': instance.count, 'results': instance.results};

_TransactionCategory _$TransactionCategoryFromJson(Map<String, dynamic> json) =>
    _TransactionCategory(
      id: (json['id'] as num).toInt(),
      name: json['name'] as String,
    );

Map<String, dynamic> _$TransactionCategoryToJson(
  _TransactionCategory instance,
) => <String, dynamic>{'id': instance.id, 'name': instance.name};

_CategoryRule _$CategoryRuleFromJson(Map<String, dynamic> json) =>
    _CategoryRule(
      id: (json['id'] as num).toInt(),
      matchText: json['match_text'] as String,
      category: (json['category'] as num?)?.toInt(),
      categoryName: json['category_name'] as String?,
      isTransfer: json['is_transfer'] as bool? ?? false,
      spreadMonths: (json['spread_months'] as num?)?.toInt() ?? 1,
      position: (json['position'] as num?)?.toInt() ?? 0,
      isRegex: json['is_regex'] as bool? ?? false,
      direction: json['direction'] as String? ?? 'any',
      minAmount: json['min_amount'] as String?,
      minInclusive: json['min_inclusive'] as bool? ?? true,
      maxAmount: json['max_amount'] as String?,
      maxInclusive: json['max_inclusive'] as bool? ?? false,
    );

Map<String, dynamic> _$CategoryRuleToJson(_CategoryRule instance) =>
    <String, dynamic>{
      'id': instance.id,
      'match_text': instance.matchText,
      'category': instance.category,
      'category_name': instance.categoryName,
      'is_transfer': instance.isTransfer,
      'spread_months': instance.spreadMonths,
      'position': instance.position,
      'is_regex': instance.isRegex,
      'direction': instance.direction,
      'min_amount': instance.minAmount,
      'min_inclusive': instance.minInclusive,
      'max_amount': instance.maxAmount,
      'max_inclusive': instance.maxInclusive,
    };

_RulePreview _$RulePreviewFromJson(Map<String, dynamic> json) => _RulePreview(
  matched: (json['matched'] as num?)?.toInt() ?? 0,
  willClassify: (json['will_classify'] as num?)?.toInt() ?? 0,
  shadowed: (json['shadowed'] as num?)?.toInt() ?? 0,
  alreadyClassified: (json['already_classified'] as num?)?.toInt() ?? 0,
  examples:
      (json['examples'] as List<dynamic>?)
          ?.map((e) => RuleExample.fromJson(e as Map<String, dynamic>))
          .toList() ??
      const <RuleExample>[],
);

Map<String, dynamic> _$RulePreviewToJson(_RulePreview instance) =>
    <String, dynamic>{
      'matched': instance.matched,
      'will_classify': instance.willClassify,
      'shadowed': instance.shadowed,
      'already_classified': instance.alreadyClassified,
      'examples': instance.examples,
    };

_RuleExample _$RuleExampleFromJson(Map<String, dynamic> json) => _RuleExample(
  bookingDate: json['booking_date'] as String?,
  text: json['text'] as String? ?? '',
);

Map<String, dynamic> _$RuleExampleToJson(_RuleExample instance) =>
    <String, dynamic>{
      'booking_date': instance.bookingDate,
      'text': instance.text,
    };
