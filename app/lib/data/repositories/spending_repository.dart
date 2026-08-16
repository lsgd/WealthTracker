import '../../core/config/api_config.dart';
import '../datasources/api_client.dart';
import '../models/spending.dart';

class SpendingRepository {
  final ApiClient _apiClient;

  SpendingRepository(this._apiClient);

  /// Fetch the month-to-month spending report.
  ///
  /// [mode] is ``normalized`` (yearly bills amortized across their months) or
  /// ``actual`` (raw cash flow per month).
  Future<SpendingReport> getMonthly({
    required int months,
    required String mode,
  }) async {
    final response = await _apiClient.get(
      ApiConfig.spendingMonthlyPath,
      queryParameters: {'months': months, 'mode': mode},
    );
    return SpendingReport.fromJson(response.data as Map<String, dynamic>);
  }
}
