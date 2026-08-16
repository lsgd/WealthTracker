// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'ai_categorization.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_AiPricing _$AiPricingFromJson(Map<String, dynamic> json) => _AiPricing(
  model: json['model'] as String,
  displayName: json['display_name'] as String,
  inputPricePer1m: (json['input_price_per_1m'] as num?)?.toDouble(),
  outputPricePer1m: (json['output_price_per_1m'] as num?)?.toDouble(),
  checkedAt: json['checked_at'] as String,
  tableUpdated: json['table_updated'] as String?,
);

Map<String, dynamic> _$AiPricingToJson(_AiPricing instance) =>
    <String, dynamic>{
      'model': instance.model,
      'display_name': instance.displayName,
      'input_price_per_1m': instance.inputPricePer1m,
      'output_price_per_1m': instance.outputPricePer1m,
      'checked_at': instance.checkedAt,
      'table_updated': instance.tableUpdated,
    };

_AiConfig _$AiConfigFromJson(Map<String, dynamic> json) => _AiConfig(
  configured: json['configured'] as bool,
  model: json['model'] as String? ?? '',
  pricing: json['pricing'] == null
      ? null
      : AiPricing.fromJson(json['pricing'] as Map<String, dynamic>),
  pricingSourceUrl: json['pricing_source_url'] as String? ?? '',
  disclosedFields:
      (json['disclosed_fields'] as List<dynamic>?)
          ?.map((e) => e as String)
          .toList() ??
      const <String>[],
);

Map<String, dynamic> _$AiConfigToJson(_AiConfig instance) => <String, dynamic>{
  'configured': instance.configured,
  'model': instance.model,
  'pricing': instance.pricing,
  'pricing_source_url': instance.pricingSourceUrl,
  'disclosed_fields': instance.disclosedFields,
};

_AiSuggestion _$AiSuggestionFromJson(Map<String, dynamic> json) =>
    _AiSuggestion(
      transactionId: (json['transaction_id'] as num).toInt(),
      bookingDate: json['booking_date'] as String,
      counterparty: json['counterparty'] as String? ?? '',
      description: json['description'] as String? ?? '',
      amount: json['amount'] as String,
      currency: json['currency'] as String,
      category: json['category'] as String,
      isNewCategory: json['is_new_category'] as bool? ?? false,
    );

Map<String, dynamic> _$AiSuggestionToJson(_AiSuggestion instance) =>
    <String, dynamic>{
      'transaction_id': instance.transactionId,
      'booking_date': instance.bookingDate,
      'counterparty': instance.counterparty,
      'description': instance.description,
      'amount': instance.amount,
      'currency': instance.currency,
      'category': instance.category,
      'is_new_category': instance.isNewCategory,
    };

_AiRuleSuggestion _$AiRuleSuggestionFromJson(Map<String, dynamic> json) =>
    _AiRuleSuggestion(
      matchText: json['match_text'] as String,
      category: json['category'] as String,
      isNewCategory: json['is_new_category'] as bool? ?? false,
    );

Map<String, dynamic> _$AiRuleSuggestionToJson(_AiRuleSuggestion instance) =>
    <String, dynamic>{
      'match_text': instance.matchText,
      'category': instance.category,
      'is_new_category': instance.isNewCategory,
    };

_AiUsage _$AiUsageFromJson(Map<String, dynamic> json) => _AiUsage(
  inputTokens: (json['input_tokens'] as num?)?.toInt() ?? 0,
  outputTokens: (json['output_tokens'] as num?)?.toInt() ?? 0,
  estimatedCostUsd: (json['estimated_cost_usd'] as num?)?.toDouble(),
);

Map<String, dynamic> _$AiUsageToJson(_AiUsage instance) => <String, dynamic>{
  'input_tokens': instance.inputTokens,
  'output_tokens': instance.outputTokens,
  'estimated_cost_usd': instance.estimatedCostUsd,
};

_AiSuggestResponse _$AiSuggestResponseFromJson(Map<String, dynamic> json) =>
    _AiSuggestResponse(
      suggestions:
          (json['suggestions'] as List<dynamic>?)
              ?.map((e) => AiSuggestion.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <AiSuggestion>[],
      rules:
          (json['rules'] as List<dynamic>?)
              ?.map((e) => AiRuleSuggestion.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <AiRuleSuggestion>[],
      sentCount: (json['sent_count'] as num?)?.toInt() ?? 0,
      totalUncategorized: (json['total_uncategorized'] as num?)?.toInt() ?? 0,
      disclosedFields:
          (json['disclosed_fields'] as List<dynamic>?)
              ?.map((e) => e as String)
              .toList() ??
          const <String>[],
      usage: json['usage'] == null
          ? null
          : AiUsage.fromJson(json['usage'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$AiSuggestResponseToJson(_AiSuggestResponse instance) =>
    <String, dynamic>{
      'suggestions': instance.suggestions,
      'rules': instance.rules,
      'sent_count': instance.sentCount,
      'total_uncategorized': instance.totalUncategorized,
      'disclosed_fields': instance.disclosedFields,
      'usage': instance.usage,
    };
