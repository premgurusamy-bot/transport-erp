import 'package:flutter_test/flutter_test.dart';
import 'package:grl_driver/api.dart';
import 'package:grl_driver/strings.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('event ids are unique 32-hex strings (idempotency keys)', () {
    final ids = List.generate(1000, (_) => newEventId());
    expect(ids.toSet().length, 1000);
    expect(ids.every((i) => RegExp(r'^[0-9a-f]{32}$').hasMatch(i)), isTrue);
  });

  test('offline queue keeps events with original time until synced', () async {
    SharedPreferences.setMockInitialValues({});
    await Api.instance.queue('trip_event', {'trip_id': 't1', 'event': 'departed'});
    await Api.instance.queue('gps_ping', {'trip_id': 't1', 'lat': 11.0, 'lng': 77.0});
    expect(await Api.instance.pending(), 2);
  });

  test('tamil strings fall back to english', () {
    S.lang = 'ta';
    expect(S.t('sos'), 'அவசர உதவி');
    expect(S.t('unknown'), 'unknown');
    S.lang = 'en';
  });
}
