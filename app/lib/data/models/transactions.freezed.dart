// GENERATED CODE - DO NOT MODIFY BY HAND
// coverage:ignore-file
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'transactions.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

// dart format off
T _$identity<T>(T value) => value;

/// @nodoc
mixin _$TransactionRecord {

 int get id; int get account;@JsonKey(name: 'booking_date') String get bookingDate;@JsonKey(name: 'value_date') String? get valueDate; String get amount; String get currency; String get counterparty; String get description; String get source; int? get category;@JsonKey(name: 'category_name') String? get categoryName;@JsonKey(name: 'spread_months') int get spreadMonths;@JsonKey(name: 'is_transfer') bool get isTransfer;
/// Create a copy of TransactionRecord
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$TransactionRecordCopyWith<TransactionRecord> get copyWith => _$TransactionRecordCopyWithImpl<TransactionRecord>(this as TransactionRecord, _$identity);

  /// Serializes this TransactionRecord to a JSON map.
  Map<String, dynamic> toJson();


@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is TransactionRecord&&(identical(other.id, id) || other.id == id)&&(identical(other.account, account) || other.account == account)&&(identical(other.bookingDate, bookingDate) || other.bookingDate == bookingDate)&&(identical(other.valueDate, valueDate) || other.valueDate == valueDate)&&(identical(other.amount, amount) || other.amount == amount)&&(identical(other.currency, currency) || other.currency == currency)&&(identical(other.counterparty, counterparty) || other.counterparty == counterparty)&&(identical(other.description, description) || other.description == description)&&(identical(other.source, source) || other.source == source)&&(identical(other.category, category) || other.category == category)&&(identical(other.categoryName, categoryName) || other.categoryName == categoryName)&&(identical(other.spreadMonths, spreadMonths) || other.spreadMonths == spreadMonths)&&(identical(other.isTransfer, isTransfer) || other.isTransfer == isTransfer));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,id,account,bookingDate,valueDate,amount,currency,counterparty,description,source,category,categoryName,spreadMonths,isTransfer);

@override
String toString() {
  return 'TransactionRecord(id: $id, account: $account, bookingDate: $bookingDate, valueDate: $valueDate, amount: $amount, currency: $currency, counterparty: $counterparty, description: $description, source: $source, category: $category, categoryName: $categoryName, spreadMonths: $spreadMonths, isTransfer: $isTransfer)';
}


}

/// @nodoc
abstract mixin class $TransactionRecordCopyWith<$Res>  {
  factory $TransactionRecordCopyWith(TransactionRecord value, $Res Function(TransactionRecord) _then) = _$TransactionRecordCopyWithImpl;
@useResult
$Res call({
 int id, int account,@JsonKey(name: 'booking_date') String bookingDate,@JsonKey(name: 'value_date') String? valueDate, String amount, String currency, String counterparty, String description, String source, int? category,@JsonKey(name: 'category_name') String? categoryName,@JsonKey(name: 'spread_months') int spreadMonths,@JsonKey(name: 'is_transfer') bool isTransfer
});




}
/// @nodoc
class _$TransactionRecordCopyWithImpl<$Res>
    implements $TransactionRecordCopyWith<$Res> {
  _$TransactionRecordCopyWithImpl(this._self, this._then);

  final TransactionRecord _self;
  final $Res Function(TransactionRecord) _then;

/// Create a copy of TransactionRecord
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? id = null,Object? account = null,Object? bookingDate = null,Object? valueDate = freezed,Object? amount = null,Object? currency = null,Object? counterparty = null,Object? description = null,Object? source = null,Object? category = freezed,Object? categoryName = freezed,Object? spreadMonths = null,Object? isTransfer = null,}) {
  return _then(_self.copyWith(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,account: null == account ? _self.account : account // ignore: cast_nullable_to_non_nullable
as int,bookingDate: null == bookingDate ? _self.bookingDate : bookingDate // ignore: cast_nullable_to_non_nullable
as String,valueDate: freezed == valueDate ? _self.valueDate : valueDate // ignore: cast_nullable_to_non_nullable
as String?,amount: null == amount ? _self.amount : amount // ignore: cast_nullable_to_non_nullable
as String,currency: null == currency ? _self.currency : currency // ignore: cast_nullable_to_non_nullable
as String,counterparty: null == counterparty ? _self.counterparty : counterparty // ignore: cast_nullable_to_non_nullable
as String,description: null == description ? _self.description : description // ignore: cast_nullable_to_non_nullable
as String,source: null == source ? _self.source : source // ignore: cast_nullable_to_non_nullable
as String,category: freezed == category ? _self.category : category // ignore: cast_nullable_to_non_nullable
as int?,categoryName: freezed == categoryName ? _self.categoryName : categoryName // ignore: cast_nullable_to_non_nullable
as String?,spreadMonths: null == spreadMonths ? _self.spreadMonths : spreadMonths // ignore: cast_nullable_to_non_nullable
as int,isTransfer: null == isTransfer ? _self.isTransfer : isTransfer // ignore: cast_nullable_to_non_nullable
as bool,
  ));
}

}


/// Adds pattern-matching-related methods to [TransactionRecord].
extension TransactionRecordPatterns on TransactionRecord {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _TransactionRecord value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _TransactionRecord() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _TransactionRecord value)  $default,){
final _that = this;
switch (_that) {
case _TransactionRecord():
return $default(_that);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _TransactionRecord value)?  $default,){
final _that = this;
switch (_that) {
case _TransactionRecord() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int id,  int account, @JsonKey(name: 'booking_date')  String bookingDate, @JsonKey(name: 'value_date')  String? valueDate,  String amount,  String currency,  String counterparty,  String description,  String source,  int? category, @JsonKey(name: 'category_name')  String? categoryName, @JsonKey(name: 'spread_months')  int spreadMonths, @JsonKey(name: 'is_transfer')  bool isTransfer)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _TransactionRecord() when $default != null:
return $default(_that.id,_that.account,_that.bookingDate,_that.valueDate,_that.amount,_that.currency,_that.counterparty,_that.description,_that.source,_that.category,_that.categoryName,_that.spreadMonths,_that.isTransfer);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int id,  int account, @JsonKey(name: 'booking_date')  String bookingDate, @JsonKey(name: 'value_date')  String? valueDate,  String amount,  String currency,  String counterparty,  String description,  String source,  int? category, @JsonKey(name: 'category_name')  String? categoryName, @JsonKey(name: 'spread_months')  int spreadMonths, @JsonKey(name: 'is_transfer')  bool isTransfer)  $default,) {final _that = this;
switch (_that) {
case _TransactionRecord():
return $default(_that.id,_that.account,_that.bookingDate,_that.valueDate,_that.amount,_that.currency,_that.counterparty,_that.description,_that.source,_that.category,_that.categoryName,_that.spreadMonths,_that.isTransfer);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int id,  int account, @JsonKey(name: 'booking_date')  String bookingDate, @JsonKey(name: 'value_date')  String? valueDate,  String amount,  String currency,  String counterparty,  String description,  String source,  int? category, @JsonKey(name: 'category_name')  String? categoryName, @JsonKey(name: 'spread_months')  int spreadMonths, @JsonKey(name: 'is_transfer')  bool isTransfer)?  $default,) {final _that = this;
switch (_that) {
case _TransactionRecord() when $default != null:
return $default(_that.id,_that.account,_that.bookingDate,_that.valueDate,_that.amount,_that.currency,_that.counterparty,_that.description,_that.source,_that.category,_that.categoryName,_that.spreadMonths,_that.isTransfer);case _:
  return null;

}
}

}

/// @nodoc
@JsonSerializable()

class _TransactionRecord implements TransactionRecord {
  const _TransactionRecord({required this.id, required this.account, @JsonKey(name: 'booking_date') required this.bookingDate, @JsonKey(name: 'value_date') this.valueDate, required this.amount, required this.currency, this.counterparty = '', this.description = '', this.source = '', this.category, @JsonKey(name: 'category_name') this.categoryName, @JsonKey(name: 'spread_months') this.spreadMonths = 1, @JsonKey(name: 'is_transfer') this.isTransfer = false});
  factory _TransactionRecord.fromJson(Map<String, dynamic> json) => _$TransactionRecordFromJson(json);

@override final  int id;
@override final  int account;
@override@JsonKey(name: 'booking_date') final  String bookingDate;
@override@JsonKey(name: 'value_date') final  String? valueDate;
@override final  String amount;
@override final  String currency;
@override@JsonKey() final  String counterparty;
@override@JsonKey() final  String description;
@override@JsonKey() final  String source;
@override final  int? category;
@override@JsonKey(name: 'category_name') final  String? categoryName;
@override@JsonKey(name: 'spread_months') final  int spreadMonths;
@override@JsonKey(name: 'is_transfer') final  bool isTransfer;

/// Create a copy of TransactionRecord
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$TransactionRecordCopyWith<_TransactionRecord> get copyWith => __$TransactionRecordCopyWithImpl<_TransactionRecord>(this, _$identity);

@override
Map<String, dynamic> toJson() {
  return _$TransactionRecordToJson(this, );
}

@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _TransactionRecord&&(identical(other.id, id) || other.id == id)&&(identical(other.account, account) || other.account == account)&&(identical(other.bookingDate, bookingDate) || other.bookingDate == bookingDate)&&(identical(other.valueDate, valueDate) || other.valueDate == valueDate)&&(identical(other.amount, amount) || other.amount == amount)&&(identical(other.currency, currency) || other.currency == currency)&&(identical(other.counterparty, counterparty) || other.counterparty == counterparty)&&(identical(other.description, description) || other.description == description)&&(identical(other.source, source) || other.source == source)&&(identical(other.category, category) || other.category == category)&&(identical(other.categoryName, categoryName) || other.categoryName == categoryName)&&(identical(other.spreadMonths, spreadMonths) || other.spreadMonths == spreadMonths)&&(identical(other.isTransfer, isTransfer) || other.isTransfer == isTransfer));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,id,account,bookingDate,valueDate,amount,currency,counterparty,description,source,category,categoryName,spreadMonths,isTransfer);

@override
String toString() {
  return 'TransactionRecord(id: $id, account: $account, bookingDate: $bookingDate, valueDate: $valueDate, amount: $amount, currency: $currency, counterparty: $counterparty, description: $description, source: $source, category: $category, categoryName: $categoryName, spreadMonths: $spreadMonths, isTransfer: $isTransfer)';
}


}

/// @nodoc
abstract mixin class _$TransactionRecordCopyWith<$Res> implements $TransactionRecordCopyWith<$Res> {
  factory _$TransactionRecordCopyWith(_TransactionRecord value, $Res Function(_TransactionRecord) _then) = __$TransactionRecordCopyWithImpl;
@override @useResult
$Res call({
 int id, int account,@JsonKey(name: 'booking_date') String bookingDate,@JsonKey(name: 'value_date') String? valueDate, String amount, String currency, String counterparty, String description, String source, int? category,@JsonKey(name: 'category_name') String? categoryName,@JsonKey(name: 'spread_months') int spreadMonths,@JsonKey(name: 'is_transfer') bool isTransfer
});




}
/// @nodoc
class __$TransactionRecordCopyWithImpl<$Res>
    implements _$TransactionRecordCopyWith<$Res> {
  __$TransactionRecordCopyWithImpl(this._self, this._then);

  final _TransactionRecord _self;
  final $Res Function(_TransactionRecord) _then;

/// Create a copy of TransactionRecord
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? id = null,Object? account = null,Object? bookingDate = null,Object? valueDate = freezed,Object? amount = null,Object? currency = null,Object? counterparty = null,Object? description = null,Object? source = null,Object? category = freezed,Object? categoryName = freezed,Object? spreadMonths = null,Object? isTransfer = null,}) {
  return _then(_TransactionRecord(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,account: null == account ? _self.account : account // ignore: cast_nullable_to_non_nullable
as int,bookingDate: null == bookingDate ? _self.bookingDate : bookingDate // ignore: cast_nullable_to_non_nullable
as String,valueDate: freezed == valueDate ? _self.valueDate : valueDate // ignore: cast_nullable_to_non_nullable
as String?,amount: null == amount ? _self.amount : amount // ignore: cast_nullable_to_non_nullable
as String,currency: null == currency ? _self.currency : currency // ignore: cast_nullable_to_non_nullable
as String,counterparty: null == counterparty ? _self.counterparty : counterparty // ignore: cast_nullable_to_non_nullable
as String,description: null == description ? _self.description : description // ignore: cast_nullable_to_non_nullable
as String,source: null == source ? _self.source : source // ignore: cast_nullable_to_non_nullable
as String,category: freezed == category ? _self.category : category // ignore: cast_nullable_to_non_nullable
as int?,categoryName: freezed == categoryName ? _self.categoryName : categoryName // ignore: cast_nullable_to_non_nullable
as String?,spreadMonths: null == spreadMonths ? _self.spreadMonths : spreadMonths // ignore: cast_nullable_to_non_nullable
as int,isTransfer: null == isTransfer ? _self.isTransfer : isTransfer // ignore: cast_nullable_to_non_nullable
as bool,
  ));
}


}


/// @nodoc
mixin _$TransactionPage {

 int get count; List<TransactionRecord> get results;
/// Create a copy of TransactionPage
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$TransactionPageCopyWith<TransactionPage> get copyWith => _$TransactionPageCopyWithImpl<TransactionPage>(this as TransactionPage, _$identity);

  /// Serializes this TransactionPage to a JSON map.
  Map<String, dynamic> toJson();


@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is TransactionPage&&(identical(other.count, count) || other.count == count)&&const DeepCollectionEquality().equals(other.results, results));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,count,const DeepCollectionEquality().hash(results));

@override
String toString() {
  return 'TransactionPage(count: $count, results: $results)';
}


}

/// @nodoc
abstract mixin class $TransactionPageCopyWith<$Res>  {
  factory $TransactionPageCopyWith(TransactionPage value, $Res Function(TransactionPage) _then) = _$TransactionPageCopyWithImpl;
@useResult
$Res call({
 int count, List<TransactionRecord> results
});




}
/// @nodoc
class _$TransactionPageCopyWithImpl<$Res>
    implements $TransactionPageCopyWith<$Res> {
  _$TransactionPageCopyWithImpl(this._self, this._then);

  final TransactionPage _self;
  final $Res Function(TransactionPage) _then;

/// Create a copy of TransactionPage
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? count = null,Object? results = null,}) {
  return _then(_self.copyWith(
count: null == count ? _self.count : count // ignore: cast_nullable_to_non_nullable
as int,results: null == results ? _self.results : results // ignore: cast_nullable_to_non_nullable
as List<TransactionRecord>,
  ));
}

}


/// Adds pattern-matching-related methods to [TransactionPage].
extension TransactionPagePatterns on TransactionPage {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _TransactionPage value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _TransactionPage() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _TransactionPage value)  $default,){
final _that = this;
switch (_that) {
case _TransactionPage():
return $default(_that);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _TransactionPage value)?  $default,){
final _that = this;
switch (_that) {
case _TransactionPage() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int count,  List<TransactionRecord> results)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _TransactionPage() when $default != null:
return $default(_that.count,_that.results);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int count,  List<TransactionRecord> results)  $default,) {final _that = this;
switch (_that) {
case _TransactionPage():
return $default(_that.count,_that.results);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int count,  List<TransactionRecord> results)?  $default,) {final _that = this;
switch (_that) {
case _TransactionPage() when $default != null:
return $default(_that.count,_that.results);case _:
  return null;

}
}

}

/// @nodoc
@JsonSerializable()

class _TransactionPage implements TransactionPage {
  const _TransactionPage({required this.count, final  List<TransactionRecord> results = const <TransactionRecord>[]}): _results = results;
  factory _TransactionPage.fromJson(Map<String, dynamic> json) => _$TransactionPageFromJson(json);

@override final  int count;
 final  List<TransactionRecord> _results;
@override@JsonKey() List<TransactionRecord> get results {
  if (_results is EqualUnmodifiableListView) return _results;
  // ignore: implicit_dynamic_type
  return EqualUnmodifiableListView(_results);
}


/// Create a copy of TransactionPage
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$TransactionPageCopyWith<_TransactionPage> get copyWith => __$TransactionPageCopyWithImpl<_TransactionPage>(this, _$identity);

@override
Map<String, dynamic> toJson() {
  return _$TransactionPageToJson(this, );
}

@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _TransactionPage&&(identical(other.count, count) || other.count == count)&&const DeepCollectionEquality().equals(other._results, _results));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,count,const DeepCollectionEquality().hash(_results));

@override
String toString() {
  return 'TransactionPage(count: $count, results: $results)';
}


}

/// @nodoc
abstract mixin class _$TransactionPageCopyWith<$Res> implements $TransactionPageCopyWith<$Res> {
  factory _$TransactionPageCopyWith(_TransactionPage value, $Res Function(_TransactionPage) _then) = __$TransactionPageCopyWithImpl;
@override @useResult
$Res call({
 int count, List<TransactionRecord> results
});




}
/// @nodoc
class __$TransactionPageCopyWithImpl<$Res>
    implements _$TransactionPageCopyWith<$Res> {
  __$TransactionPageCopyWithImpl(this._self, this._then);

  final _TransactionPage _self;
  final $Res Function(_TransactionPage) _then;

/// Create a copy of TransactionPage
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? count = null,Object? results = null,}) {
  return _then(_TransactionPage(
count: null == count ? _self.count : count // ignore: cast_nullable_to_non_nullable
as int,results: null == results ? _self._results : results // ignore: cast_nullable_to_non_nullable
as List<TransactionRecord>,
  ));
}


}


/// @nodoc
mixin _$TransactionCategory {

 int get id; String get name;
/// Create a copy of TransactionCategory
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$TransactionCategoryCopyWith<TransactionCategory> get copyWith => _$TransactionCategoryCopyWithImpl<TransactionCategory>(this as TransactionCategory, _$identity);

  /// Serializes this TransactionCategory to a JSON map.
  Map<String, dynamic> toJson();


@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is TransactionCategory&&(identical(other.id, id) || other.id == id)&&(identical(other.name, name) || other.name == name));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,id,name);

@override
String toString() {
  return 'TransactionCategory(id: $id, name: $name)';
}


}

/// @nodoc
abstract mixin class $TransactionCategoryCopyWith<$Res>  {
  factory $TransactionCategoryCopyWith(TransactionCategory value, $Res Function(TransactionCategory) _then) = _$TransactionCategoryCopyWithImpl;
@useResult
$Res call({
 int id, String name
});




}
/// @nodoc
class _$TransactionCategoryCopyWithImpl<$Res>
    implements $TransactionCategoryCopyWith<$Res> {
  _$TransactionCategoryCopyWithImpl(this._self, this._then);

  final TransactionCategory _self;
  final $Res Function(TransactionCategory) _then;

/// Create a copy of TransactionCategory
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? id = null,Object? name = null,}) {
  return _then(_self.copyWith(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,name: null == name ? _self.name : name // ignore: cast_nullable_to_non_nullable
as String,
  ));
}

}


/// Adds pattern-matching-related methods to [TransactionCategory].
extension TransactionCategoryPatterns on TransactionCategory {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _TransactionCategory value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _TransactionCategory() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _TransactionCategory value)  $default,){
final _that = this;
switch (_that) {
case _TransactionCategory():
return $default(_that);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _TransactionCategory value)?  $default,){
final _that = this;
switch (_that) {
case _TransactionCategory() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int id,  String name)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _TransactionCategory() when $default != null:
return $default(_that.id,_that.name);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int id,  String name)  $default,) {final _that = this;
switch (_that) {
case _TransactionCategory():
return $default(_that.id,_that.name);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int id,  String name)?  $default,) {final _that = this;
switch (_that) {
case _TransactionCategory() when $default != null:
return $default(_that.id,_that.name);case _:
  return null;

}
}

}

/// @nodoc
@JsonSerializable()

class _TransactionCategory implements TransactionCategory {
  const _TransactionCategory({required this.id, required this.name});
  factory _TransactionCategory.fromJson(Map<String, dynamic> json) => _$TransactionCategoryFromJson(json);

@override final  int id;
@override final  String name;

/// Create a copy of TransactionCategory
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$TransactionCategoryCopyWith<_TransactionCategory> get copyWith => __$TransactionCategoryCopyWithImpl<_TransactionCategory>(this, _$identity);

@override
Map<String, dynamic> toJson() {
  return _$TransactionCategoryToJson(this, );
}

@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _TransactionCategory&&(identical(other.id, id) || other.id == id)&&(identical(other.name, name) || other.name == name));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,id,name);

@override
String toString() {
  return 'TransactionCategory(id: $id, name: $name)';
}


}

/// @nodoc
abstract mixin class _$TransactionCategoryCopyWith<$Res> implements $TransactionCategoryCopyWith<$Res> {
  factory _$TransactionCategoryCopyWith(_TransactionCategory value, $Res Function(_TransactionCategory) _then) = __$TransactionCategoryCopyWithImpl;
@override @useResult
$Res call({
 int id, String name
});




}
/// @nodoc
class __$TransactionCategoryCopyWithImpl<$Res>
    implements _$TransactionCategoryCopyWith<$Res> {
  __$TransactionCategoryCopyWithImpl(this._self, this._then);

  final _TransactionCategory _self;
  final $Res Function(_TransactionCategory) _then;

/// Create a copy of TransactionCategory
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? id = null,Object? name = null,}) {
  return _then(_TransactionCategory(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,name: null == name ? _self.name : name // ignore: cast_nullable_to_non_nullable
as String,
  ));
}


}


/// @nodoc
mixin _$CategoryRule {

 int get id;@JsonKey(name: 'match_text') String get matchText; int get category;@JsonKey(name: 'category_name') String? get categoryName;@JsonKey(name: 'spread_months') int get spreadMonths; int get position;/// Regex rules are created on the web; the app renders them read-only.
@JsonKey(name: 'is_regex') bool get isRegex;
/// Create a copy of CategoryRule
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$CategoryRuleCopyWith<CategoryRule> get copyWith => _$CategoryRuleCopyWithImpl<CategoryRule>(this as CategoryRule, _$identity);

  /// Serializes this CategoryRule to a JSON map.
  Map<String, dynamic> toJson();


@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is CategoryRule&&(identical(other.id, id) || other.id == id)&&(identical(other.matchText, matchText) || other.matchText == matchText)&&(identical(other.category, category) || other.category == category)&&(identical(other.categoryName, categoryName) || other.categoryName == categoryName)&&(identical(other.spreadMonths, spreadMonths) || other.spreadMonths == spreadMonths)&&(identical(other.position, position) || other.position == position)&&(identical(other.isRegex, isRegex) || other.isRegex == isRegex));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,id,matchText,category,categoryName,spreadMonths,position,isRegex);

@override
String toString() {
  return 'CategoryRule(id: $id, matchText: $matchText, category: $category, categoryName: $categoryName, spreadMonths: $spreadMonths, position: $position, isRegex: $isRegex)';
}


}

/// @nodoc
abstract mixin class $CategoryRuleCopyWith<$Res>  {
  factory $CategoryRuleCopyWith(CategoryRule value, $Res Function(CategoryRule) _then) = _$CategoryRuleCopyWithImpl;
@useResult
$Res call({
 int id,@JsonKey(name: 'match_text') String matchText, int category,@JsonKey(name: 'category_name') String? categoryName,@JsonKey(name: 'spread_months') int spreadMonths, int position,@JsonKey(name: 'is_regex') bool isRegex
});




}
/// @nodoc
class _$CategoryRuleCopyWithImpl<$Res>
    implements $CategoryRuleCopyWith<$Res> {
  _$CategoryRuleCopyWithImpl(this._self, this._then);

  final CategoryRule _self;
  final $Res Function(CategoryRule) _then;

/// Create a copy of CategoryRule
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? id = null,Object? matchText = null,Object? category = null,Object? categoryName = freezed,Object? spreadMonths = null,Object? position = null,Object? isRegex = null,}) {
  return _then(_self.copyWith(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,matchText: null == matchText ? _self.matchText : matchText // ignore: cast_nullable_to_non_nullable
as String,category: null == category ? _self.category : category // ignore: cast_nullable_to_non_nullable
as int,categoryName: freezed == categoryName ? _self.categoryName : categoryName // ignore: cast_nullable_to_non_nullable
as String?,spreadMonths: null == spreadMonths ? _self.spreadMonths : spreadMonths // ignore: cast_nullable_to_non_nullable
as int,position: null == position ? _self.position : position // ignore: cast_nullable_to_non_nullable
as int,isRegex: null == isRegex ? _self.isRegex : isRegex // ignore: cast_nullable_to_non_nullable
as bool,
  ));
}

}


/// Adds pattern-matching-related methods to [CategoryRule].
extension CategoryRulePatterns on CategoryRule {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _CategoryRule value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _CategoryRule() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _CategoryRule value)  $default,){
final _that = this;
switch (_that) {
case _CategoryRule():
return $default(_that);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _CategoryRule value)?  $default,){
final _that = this;
switch (_that) {
case _CategoryRule() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int id, @JsonKey(name: 'match_text')  String matchText,  int category, @JsonKey(name: 'category_name')  String? categoryName, @JsonKey(name: 'spread_months')  int spreadMonths,  int position, @JsonKey(name: 'is_regex')  bool isRegex)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _CategoryRule() when $default != null:
return $default(_that.id,_that.matchText,_that.category,_that.categoryName,_that.spreadMonths,_that.position,_that.isRegex);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int id, @JsonKey(name: 'match_text')  String matchText,  int category, @JsonKey(name: 'category_name')  String? categoryName, @JsonKey(name: 'spread_months')  int spreadMonths,  int position, @JsonKey(name: 'is_regex')  bool isRegex)  $default,) {final _that = this;
switch (_that) {
case _CategoryRule():
return $default(_that.id,_that.matchText,_that.category,_that.categoryName,_that.spreadMonths,_that.position,_that.isRegex);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int id, @JsonKey(name: 'match_text')  String matchText,  int category, @JsonKey(name: 'category_name')  String? categoryName, @JsonKey(name: 'spread_months')  int spreadMonths,  int position, @JsonKey(name: 'is_regex')  bool isRegex)?  $default,) {final _that = this;
switch (_that) {
case _CategoryRule() when $default != null:
return $default(_that.id,_that.matchText,_that.category,_that.categoryName,_that.spreadMonths,_that.position,_that.isRegex);case _:
  return null;

}
}

}

/// @nodoc
@JsonSerializable()

class _CategoryRule implements CategoryRule {
  const _CategoryRule({required this.id, @JsonKey(name: 'match_text') required this.matchText, required this.category, @JsonKey(name: 'category_name') this.categoryName, @JsonKey(name: 'spread_months') this.spreadMonths = 1, this.position = 0, @JsonKey(name: 'is_regex') this.isRegex = false});
  factory _CategoryRule.fromJson(Map<String, dynamic> json) => _$CategoryRuleFromJson(json);

@override final  int id;
@override@JsonKey(name: 'match_text') final  String matchText;
@override final  int category;
@override@JsonKey(name: 'category_name') final  String? categoryName;
@override@JsonKey(name: 'spread_months') final  int spreadMonths;
@override@JsonKey() final  int position;
/// Regex rules are created on the web; the app renders them read-only.
@override@JsonKey(name: 'is_regex') final  bool isRegex;

/// Create a copy of CategoryRule
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$CategoryRuleCopyWith<_CategoryRule> get copyWith => __$CategoryRuleCopyWithImpl<_CategoryRule>(this, _$identity);

@override
Map<String, dynamic> toJson() {
  return _$CategoryRuleToJson(this, );
}

@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _CategoryRule&&(identical(other.id, id) || other.id == id)&&(identical(other.matchText, matchText) || other.matchText == matchText)&&(identical(other.category, category) || other.category == category)&&(identical(other.categoryName, categoryName) || other.categoryName == categoryName)&&(identical(other.spreadMonths, spreadMonths) || other.spreadMonths == spreadMonths)&&(identical(other.position, position) || other.position == position)&&(identical(other.isRegex, isRegex) || other.isRegex == isRegex));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode => Object.hash(runtimeType,id,matchText,category,categoryName,spreadMonths,position,isRegex);

@override
String toString() {
  return 'CategoryRule(id: $id, matchText: $matchText, category: $category, categoryName: $categoryName, spreadMonths: $spreadMonths, position: $position, isRegex: $isRegex)';
}


}

/// @nodoc
abstract mixin class _$CategoryRuleCopyWith<$Res> implements $CategoryRuleCopyWith<$Res> {
  factory _$CategoryRuleCopyWith(_CategoryRule value, $Res Function(_CategoryRule) _then) = __$CategoryRuleCopyWithImpl;
@override @useResult
$Res call({
 int id,@JsonKey(name: 'match_text') String matchText, int category,@JsonKey(name: 'category_name') String? categoryName,@JsonKey(name: 'spread_months') int spreadMonths, int position,@JsonKey(name: 'is_regex') bool isRegex
});




}
/// @nodoc
class __$CategoryRuleCopyWithImpl<$Res>
    implements _$CategoryRuleCopyWith<$Res> {
  __$CategoryRuleCopyWithImpl(this._self, this._then);

  final _CategoryRule _self;
  final $Res Function(_CategoryRule) _then;

/// Create a copy of CategoryRule
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? id = null,Object? matchText = null,Object? category = null,Object? categoryName = freezed,Object? spreadMonths = null,Object? position = null,Object? isRegex = null,}) {
  return _then(_CategoryRule(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,matchText: null == matchText ? _self.matchText : matchText // ignore: cast_nullable_to_non_nullable
as String,category: null == category ? _self.category : category // ignore: cast_nullable_to_non_nullable
as int,categoryName: freezed == categoryName ? _self.categoryName : categoryName // ignore: cast_nullable_to_non_nullable
as String?,spreadMonths: null == spreadMonths ? _self.spreadMonths : spreadMonths // ignore: cast_nullable_to_non_nullable
as int,position: null == position ? _self.position : position // ignore: cast_nullable_to_non_nullable
as int,isRegex: null == isRegex ? _self.isRegex : isRegex // ignore: cast_nullable_to_non_nullable
as bool,
  ));
}


}

// dart format on
