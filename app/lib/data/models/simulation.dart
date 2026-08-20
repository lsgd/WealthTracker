import 'package:freezed_annotation/freezed_annotation.dart';

part 'simulation.freezed.dart';
part 'simulation.g.dart';

/// Percentile band of the Monte Carlo fan at the end of one projection year.
@freezed
abstract class SimulationBand with _$SimulationBand {
  const factory SimulationBand({
    required int year,
    required double p5,
    required double p25,
    required double p50,
    required double p75,
    required double p95,
  }) = _SimulationBand;

  factory SimulationBand.fromJson(Map<String, dynamic> json) =>
      _$SimulationBandFromJson(json);
}

/// One echoed simulation parameter and whether the server derived it
/// (vs. the user having set it explicitly).
@freezed
abstract class SimulationParameter with _$SimulationParameter {
  const factory SimulationParameter({
    required double value,
    required bool derived,
  }) = _SimulationParameter;

  factory SimulationParameter.fromJson(Map<String, dynamic> json) =>
      _$SimulationParameterFromJson(json);
}

@freezed
abstract class SimulationTarget with _$SimulationTarget {
  const factory SimulationTarget({
    required double amount,
    required double probability,
    @JsonKey(name: 'median_reached_year') int? medianReachedYear,
  }) = _SimulationTarget;

  factory SimulationTarget.fromJson(Map<String, dynamic> json) =>
      _$SimulationTargetFromJson(json);
}

/// Result of the Monte Carlo wealth projection, in today's purchasing power.
@freezed
abstract class SimulationResult with _$SimulationResult {
  const factory SimulationResult({
    required int years,
    required int paths,
    @JsonKey(name: 'base_currency') required String baseCurrency,
    required List<SimulationBand> bands,
    required Map<String, SimulationParameter> parameters,
    SimulationTarget? target,
  }) = _SimulationResult;

  factory SimulationResult.fromJson(Map<String, dynamic> json) =>
      _$SimulationResultFromJson(json);
}
