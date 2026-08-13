import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../services/ms_relay/relay_service.dart';
import '../../services/notification_service.dart';
import 'accounts_provider.dart';
import 'core_providers.dart';
import 'profile_provider.dart';
import 'wealth_provider.dart';

/// Outcome of a completed sync-all run.
class SyncAllResult {
  final int syncedCount;
  final List<Map<String, dynamic>> errors;
  final String? message;

  const SyncAllResult({
    this.syncedCount = 0,
    this.errors = const [],
    this.message,
  });
}

/// State for sync-all operations.
class SyncAllState {
  final bool isSyncing;
  final DateTime? lastSyncTime;

  /// Result of the most recent run; null until a run completes
  /// (or when the run timed out without a final status).
  final SyncAllResult? lastResult;

  const SyncAllState({
    this.isSyncing = false,
    this.lastSyncTime,
    this.lastResult,
  });
}

/// Provider for sync-all operations with notification tracking.
final syncAllProvider =
    NotifierProvider<SyncAllNotifier, SyncAllState>(SyncAllNotifier.new);

class SyncAllNotifier extends Notifier<SyncAllState> {
  @override
  SyncAllState build() {
    _loadLastSyncTime();
    return const SyncAllState();
  }

  Future<void> _loadLastSyncTime() async {
    final notificationService = ref.read(notificationServiceProvider);
    final lastSync = await notificationService.getLastSyncAll();
    if (lastSync != null && state.lastSyncTime == null) {
      state = SyncAllState(
        isSyncing: state.isSyncing,
        lastSyncTime: lastSync,
        lastResult: state.lastResult,
      );
    }
  }

  /// Sync all accounts via background task queue.
  ///
  /// Starts sync (returns immediately), then polls for completion.
  /// Records the sync timestamp for notification suppression.
  Future<void> syncAll() async {
    if (state.isSyncing) return;

    state = SyncAllState(isSyncing: true, lastSyncTime: state.lastSyncTime);

    try {
      final repository = ref.read(accountRepositoryProvider);
      final notificationService = ref.read(notificationServiceProvider);
      final relay = ref.read(relayServiceProvider);

      // Open the phone relay for the sync if any account needs it (e.g. MS).
      final accounts = await ref.read(accountsProvider.future);

      await relay.withRelay(() async {
        final startResult = await repository.syncAllAccounts();
        final taskId = startResult['task_id'] as String?;

        if (taskId == null) {
          // No task created (e.g. no accounts to sync)
          await notificationService.recordSyncAll();
          state = SyncAllState(
            isSyncing: false,
            lastSyncTime: DateTime.now(),
            lastResult: SyncAllResult(
              message: startResult['message'] as String? ?? 'Done',
            ),
          );
          return;
        }

        // Poll for completion
        final result = await _pollTask(repository, taskId);

        await notificationService.recordSyncAll();

        state = SyncAllState(
          isSyncing: false,
          lastSyncTime: DateTime.now(),
          lastResult: result != null ? _parseResult(result) : null,
        );
      }, active: anyNeedsRelay(accounts));
    } catch (e) {
      state = SyncAllState(
        isSyncing: false,
        lastSyncTime: state.lastSyncTime,
        lastResult: SyncAllResult(
          errors: [
            {'name': 'Sync', 'error': e.toString()}
          ],
        ),
      );
    } finally {
      _refreshData();
    }
  }

  /// Extract synced count and per-account errors from a task status payload.
  SyncAllResult _parseResult(Map<String, dynamic> result) {
    final details = result['result'] as Map<String, dynamic>?;
    if (details != null) {
      final errors =
          ((details['details'] as Map?)?['errors'] as List? ?? const [])
              .cast<Map<String, dynamic>>();
      return SyncAllResult(
        syncedCount: details['synced_count'] as int? ?? 0,
        errors: errors,
      );
    }
    if (result['error'] != null) {
      return SyncAllResult(
        errors: [
          {'name': 'Sync', 'error': result['error']}
        ],
      );
    }
    return const SyncAllResult();
  }

  /// Invalidate all providers derived from account/snapshot data so every
  /// screen (summary card, chart, account list, snapshot banner) refreshes.
  void _refreshData() {
    ref.invalidate(accountsProvider);
    ref.invalidate(accountSnapshotsProvider);
    ref.invalidate(wealthSummaryProvider);
    ref.invalidate(wealthHistoryProvider);
  }

  /// Poll a sync task until completion.
  Future<Map<String, dynamic>?> _pollTask(
    dynamic repository,
    String taskId,
  ) async {
    const pollInterval = Duration(seconds: 2);
    const maxPolls = 180; // 6 minutes

    for (var i = 0; i < maxPolls; i++) {
      await Future.delayed(pollInterval);
      try {
        final status = await repository.getSyncTaskStatus(taskId);
        final taskStatus = status['status'] as String?;
        if (taskStatus == 'completed' || taskStatus == 'failed') {
          return status;
        }
      } catch (_) {
        // Keep polling
      }
    }
    return null;
  }

  /// Check if sync should run based on suppression threshold.
  Future<bool> shouldSync() async {
    final notificationService = ref.read(notificationServiceProvider);
    return notificationService.shouldSync();
  }

  /// Try to sync on app open if enabled and not recently synced.
  Future<void> trySyncOnAppOpen() async {
    final profile = await ref.read(profileProvider.future);
    if (profile == null || !profile.syncOnAppOpen) return;

    final shouldRun = await shouldSync();
    if (!shouldRun) {
      debugPrint('Skipping auto-sync: synced recently');
      return;
    }

    debugPrint('Auto-syncing on app open');
    await syncAll();
  }
}

/// Provider to update sync settings.
final syncSettingsProvider = Provider((ref) => SyncSettingsManager(ref));

class SyncSettingsManager {
  final Ref _ref;

  SyncSettingsManager(this._ref);

  /// Update sync-on-app-open setting (stored on server).
  Future<void> updateSyncOnAppOpen(bool value) async {
    final repository = _ref.read(profileRepositoryProvider);
    await repository.updateProfile(syncOnAppOpen: value);
    _ref.invalidate(profileProvider);
  }

  /// Update sync reminder settings (stored locally).
  Future<void> updateSyncReminder({
    bool? enabled,
    int? hour,
    int? minute,
    NotificationFrequency? frequency,
    bool? shiftWeekend,
    bool? skipHolidays,
  }) async {
    final notificationService = _ref.read(notificationServiceProvider);

    if (enabled != null) {
      await notificationService.setSyncReminderEnabled(enabled);
    }
    if (hour != null || minute != null) {
      final currentHour = hour ?? await notificationService.getSyncReminderHour();
      final currentMinute = minute ?? await notificationService.getSyncReminderMinute();
      await notificationService.setSyncReminderTime(currentHour, currentMinute);
    }
    if (frequency != null) {
      await notificationService.setSyncReminderFrequency(frequency);
    }
    if (shiftWeekend != null) {
      await notificationService.setSyncReminderShiftWeekend(shiftWeekend);
    }
    if (skipHolidays != null) {
      await notificationService.setSyncReminderSkipHolidays(skipHolidays);
    }

    // Schedule or cancel the notification using the persisted settings.
    final isEnabled = enabled ?? await notificationService.isSyncReminderEnabled();
    if (isEnabled) {
      await notificationService.scheduleSyncReminder(
        hour: await notificationService.getSyncReminderHour(),
        minute: await notificationService.getSyncReminderMinute(),
        frequency: await notificationService.getSyncReminderFrequency(),
        shiftWeekend: await notificationService.getSyncReminderShiftWeekend(),
        skipHolidays: await notificationService.getSyncReminderSkipHolidays(),
      );
    } else {
      await notificationService.cancelSyncReminder();
    }
  }

  /// Initialize sync reminders from local settings.
  ///
  /// Only schedules the reminder if permissions are already granted.
  /// Does NOT prompt for permissions - that only happens when the user
  /// explicitly enables the reminder in settings.
  Future<void> initializeSyncReminders() async {
    final notificationService = _ref.read(notificationServiceProvider);
    await notificationService.initialize();

    final enabled = await notificationService.isSyncReminderEnabled();
    if (enabled) {
      final hasPermission =
          await notificationService.hasNotificationPermission();
      if (hasPermission) {
        await notificationService.scheduleSyncReminder(
          hour: await notificationService.getSyncReminderHour(),
          minute: await notificationService.getSyncReminderMinute(),
          frequency: await notificationService.getSyncReminderFrequency(),
          shiftWeekend: await notificationService.getSyncReminderShiftWeekend(),
          skipHolidays: await notificationService.getSyncReminderSkipHolidays(),
        );
      }
    }
  }
}
