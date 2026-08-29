import 'package:freezed_annotation/freezed_annotation.dart';

part 'broker.freezed.dart';
part 'broker.g.dart';

@freezed
abstract class Broker with _$Broker {
  const factory Broker({
    required String code,
    required String name,
    @JsonKey(name: 'supports_auto_sync') @Default(false) bool supportsAutoSync,
    // Syncs fine, but stops mid-way for a code the user has to type in, so it
    // is left out of unattended runs ("Sync all", sync on app open).
    @JsonKey(name: 'requires_interactive_sync')
    @Default(false)
    bool requiresInteractiveSync,
  }) = _Broker;

  factory Broker.fromJson(Map<String, dynamic> json) => _$BrokerFromJson(json);
}
