import '../../core/config/api_config.dart';
import '../datasources/api_client.dart';
import '../models/holdings.dart';
import '../models/simulation.dart';
import '../models/wealth_summary.dart';

class WealthRepository {
  final ApiClient _apiClient;

  WealthRepository(this._apiClient);

  /// Fetch the current wealth summary.
  Future<WealthSummary> getSummary() async {
    final response = await _apiClient.get(ApiConfig.wealthSummaryPath);
    return WealthSummary.fromJson(response.data as Map<String, dynamic>);
  }

  /// Fetch wealth history for charting.
  Future<List<WealthHistoryPoint>> getHistory({
    required int days,
    required String granularity,
  }) async {
    final response = await _apiClient.get(
      ApiConfig.wealthHistoryPath,
      queryParameters: {
        'days': days,
        'granularity': granularity,
      },
    );
    final data = response.data as Map<String, dynamic>;
    final history = data['history'] as List<dynamic>? ?? [];
    return history
        .map((json) =>
            WealthHistoryPoint.fromJson(json as Map<String, dynamic>))
        .toList();
  }

  /// Current per-asset holdings, merged by ISIN across accounts. Only brokers
  /// that report positions (IBKR, Morgan Stanley) contribute; empty otherwise.
  Future<HoldingsReport> getHoldings() async {
    final response = await _apiClient.get(ApiConfig.wealthHoldingsPath);
    return HoldingsReport.fromJson(response.data as Map<String, dynamic>);
  }

  /// Run the Monte Carlo wealth projection.
  ///
  /// [params] must contain ONLY what the user explicitly changed: the server
  /// persists sent parameters as profile overrides, an empty-string value
  /// clears an override, and unsent parameters resolve stored-override-first,
  /// then derived fresh from the user's data (so e.g. an untouched
  /// start_wealth keeps following the actual balances).
  Future<SimulationResult> getSimulation(
      {Map<String, String> params = const {}}) async {
    final response = await _apiClient.get(
      ApiConfig.wealthSimulationPath,
      queryParameters: params,
    );
    return SimulationResult.fromJson(response.data as Map<String, dynamic>);
  }
}
