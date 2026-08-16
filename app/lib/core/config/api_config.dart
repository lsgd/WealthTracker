/// API configuration for the wealth tracker app.
/// Server URL is configurable since users can self-host.
class ApiConfig {
  static const Duration connectTimeout = Duration(seconds: 30);
  static const Duration receiveTimeout = Duration(seconds: 30);

  /// Extended timeout for sync operations that may require 2FA approval.
  /// FinTS banks like DKB poll for up to 5 minutes waiting for push approval.
  static const Duration syncTimeout = Duration(minutes: 6);

  /// A Gemini suggestion round covers up to 100 transactions; the model can
  /// take well over the default 30s to answer.
  static const Duration aiSuggestTimeout = Duration(minutes: 3);

  /// API endpoints
  static const String loginPath = '/api/auth/login/';
  static const String refreshPath = '/api/auth/refresh/';
  static const String mePath = '/api/auth/me/';
  static const String saltPath = '/api/auth/salt/';
  static const String newSaltPath = '/api/auth/salt/new/';
  static const String setupEncryptionPath = '/api/auth/setup-encryption/';
  static const String changePasswordPath = '/api/auth/change-password/kek/';
  static const String profilePath = '/api/profile/';
  static const String accountsPath = '/api/accounts/';
  static const String wealthSummaryPath = '/api/wealth/summary/';
  static const String wealthHistoryPath = '/api/wealth/history/';
  static const String deviceRegisterPath = '/api/devices/register/';

  static String accountSnapshotsPath(int accountId) =>
      '/api/accounts/$accountId/snapshots/';

  static String snapshotDetailPath(int snapshotId) =>
      '/api/snapshots/$snapshotId/';

  static String accountSyncPath(int accountId) =>
      '/api/accounts/$accountId/sync/';

  static const String syncAllPath = '/api/accounts/sync/';

  static const String spendingMonthlyPath = '/api/spending/monthly/';
  static const String spendingCategoriesPath = '/api/spending/categories/';
  static const String spendingRulesPath = '/api/spending/rules/';
  static const String spendingRulesReorderPath = '/api/spending/rules/reorder/';
  static const String transactionsPath = '/api/transactions/';
  static const String aiConfigPath = '/api/spending/ai/config/';
  static const String aiModelsPath = '/api/spending/ai/models/';
  static const String aiRefreshPricingPath = '/api/spending/ai/refresh-pricing/';
  static const String aiSuggestPath = '/api/spending/ai/suggest/';
  static const String aiApplyPath = '/api/spending/ai/apply/';

  static String syncTaskStatusPath(String taskId) =>
      '/api/accounts/sync/$taskId/';
}
