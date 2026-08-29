import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/presentation/providers/sync_provider.dart';
import 'package:wealth_tracker/presentation/widgets/sync_progress_dialog.dart';

/// Publishes a fixed state, so the dialog can be pumped without a server.
class _FixedSync extends SyncAllNotifier {
  _FixedSync(this._state);

  final SyncAllState _state;

  @override
  SyncAllState build() => _state;
}

Widget _harness(SyncAllState state) => ProviderScope(
      overrides: [syncAllProvider.overrideWith(() => _FixedSync(state))],
      child: const MaterialApp(
        home: Scaffold(body: SyncProgressDialog()),
      ),
    );

void main() {
  group('SyncProgressDialog', () {
    testWidgets('splits accounts into in-progress and finished', (tester) async {
      await tester.pumpWidget(_harness(const SyncAllState(
        isSyncing: true,
        progress: [
          SyncAccountProgress(id: 1, name: 'DKB', state: 'done'),
          SyncAccountProgress(id: 2, name: 'ZKB', state: 'syncing'),
          SyncAccountProgress(id: 3, name: 'IBKR', state: 'waiting'),
        ],
      )));

      expect(find.text('Syncing'), findsOneWidget);
      expect(find.text('In progress (2)'), findsOneWidget);
      expect(find.text('Finished (1)'), findsOneWidget);
      expect(find.text('DKB'), findsOneWidget);
      expect(find.text('ZKB'), findsOneWidget);
    });

    testWidgets('shows what each finished account reported', (tester) async {
      await tester.pumpWidget(_harness(const SyncAllState(
        progress: [
          SyncAccountProgress(
              id: 1, name: 'DKB', state: 'done', message: 'EUR 1,234.00'),
          SyncAccountProgress(
              id: 2, name: 'Swisscard', state: 'error', message: 'Login failed'),
        ],
      )));

      expect(find.text('Sync finished'), findsOneWidget);
      expect(find.text('In progress (0)'), findsNothing);
      expect(find.text('EUR 1,234.00'), findsOneWidget);
      expect(find.text('Login failed'), findsOneWidget);
    });
  });
}
