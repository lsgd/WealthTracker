import 'package:freezed_annotation/freezed_annotation.dart';

part 'ai_categorization.freezed.dart';
part 'ai_categorization.g.dart';

/// Snapshot of a model's listed price and when it was last checked.
///
/// Google publishes no pricing API, so prices come from a rate table shipped
/// with the backend; [checkedAt] is when the user last confirmed it.
@freezed
abstract class AiPricing with _$AiPricing {
  const factory AiPricing({
    required String model,
    @JsonKey(name: 'display_name') required String displayName,
    @JsonKey(name: 'input_price_per_1m') double? inputPricePer1m,
    @JsonKey(name: 'output_price_per_1m') double? outputPricePer1m,
    @JsonKey(name: 'checked_at') required String checkedAt,
    @JsonKey(name: 'table_updated') String? tableUpdated,
  }) = _AiPricing;

  factory AiPricing.fromJson(Map<String, dynamic> json) =>
      _$AiPricingFromJson(json);
}

@freezed
abstract class AiConfig with _$AiConfig {
  const factory AiConfig({
    required bool configured,
    @Default('') String model,
    AiPricing? pricing,
    @JsonKey(name: 'pricing_source_url') @Default('') String pricingSourceUrl,
    @JsonKey(name: 'disclosed_fields')
    @Default(<String>[])
    List<String> disclosedFields,
  }) = _AiConfig;

  factory AiConfig.fromJson(Map<String, dynamic> json) =>
      _$AiConfigFromJson(json);
}

/// A proposed category for one transaction. Nothing is stored until the user
/// confirms it.
@freezed
abstract class AiSuggestion with _$AiSuggestion {
  const factory AiSuggestion({
    @JsonKey(name: 'transaction_id') required int transactionId,
    @JsonKey(name: 'booking_date') required String bookingDate,
    @Default('') String counterparty,
    @Default('') String description,
    required String amount,
    required String currency,
    required String category,
    @JsonKey(name: 'is_new_category') @Default(false) bool isNewCategory,
  }) = _AiSuggestion;

  factory AiSuggestion.fromJson(Map<String, dynamic> json) =>
      _$AiSuggestionFromJson(json);
}

/// A proposed reusable rule, so future transactions categorize without AI.
@freezed
abstract class AiRuleSuggestion with _$AiRuleSuggestion {
  const factory AiRuleSuggestion({
    @JsonKey(name: 'match_text') required String matchText,
    required String category,
    @JsonKey(name: 'is_new_category') @Default(false) bool isNewCategory,
  }) = _AiRuleSuggestion;

  factory AiRuleSuggestion.fromJson(Map<String, dynamic> json) =>
      _$AiRuleSuggestionFromJson(json);
}

@freezed
abstract class AiUsage with _$AiUsage {
  const factory AiUsage({
    @JsonKey(name: 'input_tokens') @Default(0) int inputTokens,
    @JsonKey(name: 'output_tokens') @Default(0) int outputTokens,
    @JsonKey(name: 'estimated_cost_usd') double? estimatedCostUsd,
  }) = _AiUsage;

  factory AiUsage.fromJson(Map<String, dynamic> json) =>
      _$AiUsageFromJson(json);
}

@freezed
abstract class AiSuggestResponse with _$AiSuggestResponse {
  const factory AiSuggestResponse({
    @Default(<AiSuggestion>[]) List<AiSuggestion> suggestions,
    @Default(<AiRuleSuggestion>[]) List<AiRuleSuggestion> rules,
    @JsonKey(name: 'sent_count') @Default(0) int sentCount,
    @JsonKey(name: 'total_uncategorized') @Default(0) int totalUncategorized,
    @JsonKey(name: 'disclosed_fields')
    @Default(<String>[])
    List<String> disclosedFields,
    AiUsage? usage,
  }) = _AiSuggestResponse;

  factory AiSuggestResponse.fromJson(Map<String, dynamic> json) =>
      _$AiSuggestResponseFromJson(json);
}
