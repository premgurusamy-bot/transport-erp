// API client + offline queue for the Driver App. The app never talks to the database directly.
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiException implements Exception {
  final int status;
  final String code;
  final String message;
  ApiException(this.status, this.code, this.message);
  bool get isNetwork => status == 0;
  @override
  String toString() => message;
}

String newEventId() {
  final r = Random.secure();
  return List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

class Api {
  Api._();
  static final Api instance = Api._();

  String baseUrl = '';
  String? token;

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    baseUrl = p.getString('baseUrl') ?? '';
    token = p.getString('token');
  }

  Future<void> saveSession(String url, String? tok) async {
    final p = await SharedPreferences.getInstance();
    baseUrl = url;
    token = tok;
    await p.setString('baseUrl', url);
    if (tok == null) {
      await p.remove('token');
    } else {
      await p.setString('token', tok);
    }
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'X-GRL-App': 'driver',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<dynamic> get(String path) => _send('GET', path);
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) => _send('POST', path, body ?? {});

  Future<dynamic> _send(String method, String path, [Object? body]) async {
    final uri = Uri.parse('$baseUrl/api/v1$path');
    http.Response r;
    try {
      r = method == 'GET'
          ? await http.get(uri, headers: _headers).timeout(const Duration(seconds: 20))
          : await http.post(uri, headers: _headers, body: jsonEncode(body)).timeout(const Duration(seconds: 20));
    } catch (_) {
      throw ApiException(0, 'offline', 'No connection - saved on phone if possible');
    }
    final data = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 400) {
      final e = (data is Map ? data['error'] : null) ?? {};
      throw ApiException(r.statusCode, e['code'] ?? 'error', e['message'] ?? 'Error ${r.statusCode}');
    }
    return data;
  }

  // ---------------- offline queue (replayed idempotently by /sync/events)
  Future<void> queue(String type, Map<String, dynamic> payload) async {
    final p = await SharedPreferences.getInstance();
    final q = p.getStringList('queue') ?? [];
    q.add(jsonEncode({
      'client_event_id': newEventId(),
      'device_id': p.getString('device') ?? _device(p),
      'event_type': type,
      'payload': payload,
      'occurred_at': DateTime.now().toUtc().toIso8601String(),
      'source': 'app_offline',
    }));
    await p.setStringList('queue', q);
  }

  String _device(SharedPreferences p) {
    final d = newEventId();
    p.setString('device', d);
    return d;
  }

  Future<int> pending() async => ((await SharedPreferences.getInstance()).getStringList('queue') ?? []).length;

  Future<String> flush() async {
    final p = await SharedPreferences.getInstance();
    final q = p.getStringList('queue') ?? [];
    if (q.isEmpty) return 'Nothing to sync';
    final events = q.map((e) => jsonDecode(e)).toList();
    final res = await post('/sync/events', {'events': events});
    final done = {for (final r in res['results']) r['client_event_id']};
    final rejected = (res['results'] as List).where((r) => r['status'] == 'rejected').length;
    await p.setStringList('queue', q.where((e) => !done.contains(jsonDecode(e)['client_event_id'])).toList());
    return 'Synced ${done.length} (rejected $rejected)';
  }

  /// Try online; if the network is down, keep the event on the phone for later sync.
  Future<String> sendOrQueue(String path, Map<String, dynamic> body, String type, Map<String, dynamic> payload) async {
    try {
      await post(path, body);
      return 'Saved';
    } on ApiException catch (e) {
      if (e.isNetwork) {
        await queue(type, payload);
        return 'Saved offline - will sync';
      }
      rethrow;
    }
  }
}
