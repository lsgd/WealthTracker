// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'simulation.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_SimulationBand _$SimulationBandFromJson(Map<String, dynamic> json) =>
    _SimulationBand(
      year: (json['year'] as num).toInt(),
      p5: (json['p5'] as num).toDouble(),
      p25: (json['p25'] as num).toDouble(),
      p50: (json['p50'] as num).toDouble(),
      p75: (json['p75'] as num).toDouble(),
      p95: (json['p95'] as num).toDouble(),
    );

Map<String, dynamic> _$SimulationBandToJson(_SimulationBand instance) =>
    <String, dynamic>{
      'year': instance.year,
      'p5': instance.p5,
      'p25': instance.p25,
      'p50': instance.p50,
      'p75': instance.p75,
      'p95': instance.p95,
    };

_SimulationParameter _$SimulationParameterFromJson(Map<String, dynamic> json) =>
    _SimulationParameter(
      value: (json['value'] as num).toDouble(),
      derived: json['derived'] as bool,
    );

Map<String, dynamic> _$SimulationParameterToJson(
  _SimulationParameter instance,
) => <String, dynamic>{'value': instance.value, 'derived': instance.derived};

_SimulationTarget _$SimulationTargetFromJson(Map<String, dynamic> json) =>
    _SimulationTarget(
      amount: (json['amount'] as num).toDouble(),
      probability: (json['probability'] as num).toDouble(),
      medianReachedYear: (json['median_reached_year'] as num?)?.toInt(),
    );

Map<String, dynamic> _$SimulationTargetToJson(_SimulationTarget instance) =>
    <String, dynamic>{
      'amount': instance.amount,
      'probability': instance.probability,
      'median_reached_year': instance.medianReachedYear,
    };

_SimulationResult _$SimulationResultFromJson(Map<String, dynamic> json) =>
    _SimulationResult(
      years: (json['years'] as num).toInt(),
      paths: (json['paths'] as num).toInt(),
      baseCurrency: json['base_currency'] as String,
      bands: (json['bands'] as List<dynamic>)
          .map((e) => SimulationBand.fromJson(e as Map<String, dynamic>))
          .toList(),
      parameters: (json['parameters'] as Map<String, dynamic>).map(
        (k, e) => MapEntry(
          k,
          SimulationParameter.fromJson(e as Map<String, dynamic>),
        ),
      ),
      target: json['target'] == null
          ? null
          : SimulationTarget.fromJson(json['target'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$SimulationResultToJson(_SimulationResult instance) =>
    <String, dynamic>{
      'years': instance.years,
      'paths': instance.paths,
      'base_currency': instance.baseCurrency,
      'bands': instance.bands,
      'parameters': instance.parameters,
      'target': instance.target,
    };
