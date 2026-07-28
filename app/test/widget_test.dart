import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:wealth_tracker/app.dart';
import 'package:wealth_tracker/presentation/providers/core_providers.dart';
import 'package:wealth_tracker/services/secure_storage_service.dart';

/// In-memory stand-in so the widget tree never reaches the real
/// flutter_secure_storage platform channel (unavailable under `flutter test`).
/// Returns "nothing configured yet" defaults, which routes the splash screen to
/// the server-config screen after its startup delay.
class _FakeSecureStorage extends SecureStorageService {
  @override
  Future<bool> hasServerUrl() async => false;

  @override
  Future<String?> getServerUrl() async => null;

  @override
  Future<bool> hasTokens() async => false;

  @override
  Future<bool> isBiometricEnabled() async => false;

  @override
  Future<String> getThemeMode() async => 'system';

  @override
  Future<String> getDateFormat() async => 'system';
}

void main() {
  testWidgets('App loads splash screen', (WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          secureStorageProvider.overrideWithValue(_FakeSecureStorage()),
        ],
        child: const WealthApp(),
      ),
    );

    // Verify that splash screen shows app name.
    expect(find.text('Wealth Tracker'), findsOneWidget);

    // The splash schedules a 500ms delay before routing away. Let it fire and
    // let the resulting navigation settle so no timer is pending at teardown.
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
  });
}
