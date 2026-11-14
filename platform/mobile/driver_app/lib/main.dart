// G ROAD LINES Driver App.
// Safety first: large one-tap actions, "park before use" banner, no typing for routine events.
// GPS is collected only during an authorised, dispatched trip after the driver accepts the notice.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import 'api.dart';
import 'strings.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.instance.load();
  runApp(const DriverApp());
}

class DriverApp extends StatelessWidget {
  const DriverApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'GRL Driver',
        theme: ThemeData(colorSchemeSeed: const Color(0xFF0B4F8A), useMaterial3: true),
        darkTheme: ThemeData(colorSchemeSeed: const Color(0xFF0B4F8A), brightness: Brightness.dark, useMaterial3: true),
        home: Api.instance.token == null ? const LoginPage() : const TripsPage(),
      );
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final url = TextEditingController(text: Api.instance.baseUrl.isEmpty ? 'http://192.168.1.20:8000' : Api.instance.baseUrl);
  final phone = TextEditingController();
  final otp = TextEditingController();
  bool sent = false;
  String? msg;

  Future<void> _go() async {
    final api = Api.instance;
    await api.saveSession(url.text.trim(), null);
    try {
      if (!sent) {
        final r = await api.post('/auth/otp/request', {'phone': phone.text.trim()});
        setState(() {
          sent = true;
          msg = r['dev_otp'] != null ? 'DEVELOPMENT MOCK SMS OTP: ${r['dev_otp']}' : r['message'];
        });
      } else {
        final r = await api.post('/auth/otp/verify', {'phone': phone.text.trim(), 'otp': otp.text.trim(), 'device': 'android'});
        await api.saveSession(url.text.trim(), r['token']);
        if (mounted) Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const TripsPage()));
      }
    } on ApiException catch (e) {
      setState(() => msg = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(S.t('app'))),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(controller: url, decoration: const InputDecoration(labelText: 'Server address')),
          TextField(controller: phone, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Mobile number')),
          if (sent) TextField(controller: otp, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'OTP')),
          const SizedBox(height: 12),
          FilledButton(onPressed: _go, child: Text(sent ? S.t('signin') : 'Send OTP')),
          if (msg != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(msg!)),
          TextButton(onPressed: () => setState(() => S.toggle()), child: const Text('English / தமிழ்')),
        ]),
      );
}

class TripsPage extends StatefulWidget {
  const TripsPage({super.key});
  @override
  State<TripsPage> createState() => _TripsPageState();
}

class _TripsPageState extends State<TripsPage> {
  List trips = [];
  int pending = 0;
  String? msg;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final t = await Api.instance.get('/driver/trips');
      final p = await Api.instance.pending();
      setState(() {
        trips = t;
        pending = p;
      });
    } on ApiException catch (e) {
      if (e.status == 401 && mounted) {
        await Api.instance.saveSession(Api.instance.baseUrl, null);
        if (mounted) Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const LoginPage()));
      }
      setState(() => msg = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(S.t('myTrips')), actions: [
          IconButton(icon: const Icon(Icons.sync), onPressed: () async {
            try {
              final r = await Api.instance.flush();
              setState(() => msg = r);
            } on ApiException catch (e) {
              setState(() => msg = e.message);
            }
            _load();
          }),
        ]),
        body: RefreshIndicator(
          onRefresh: _load,
          child: ListView(children: [
            Container(color: Colors.amber.shade100, padding: const EdgeInsets.all(12), child: Text(S.t('park'))),
            if (pending > 0) ListTile(leading: const Icon(Icons.cloud_off), title: Text('$pending event(s) saved offline')),
            if (msg != null) ListTile(title: Text(msg!)),
            for (final t in trips)
              ListTile(
                title: Text('${t['code']} · ${t['vehicle_registration']}'),
                subtitle: Text('${t['status']} · ${(t['loads'] as List).map((l) => '${l['origin']}→${l['destination']}').join(', ')}'),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TripPage(trip: t))).then((_) => _load()),
              ),
            if (trips.isEmpty) const ListTile(title: Text('No trips assigned')),
          ]),
        ),
      );
}

class TripPage extends StatefulWidget {
  final Map trip;
  const TripPage({super.key, required this.trip});
  @override
  State<TripPage> createState() => _TripPageState();
}

class _TripPageState extends State<TripPage> {
  late Map trip = widget.trip;
  String? msg;
  StreamSubscription<Position>? gps;
  final label = TextEditingController();
  static const checklist = ['brakes', 'steering', 'tyres', 'lights', 'horn', 'wipers', 'seat_belt', 'fire_extinguisher', 'leaks', 'load_securing'];
  final Map<String, String> check = {for (final c in checklist) c: 'ok'};

  bool get onTrip => ['dispatched', 'in_transit'].contains(trip['status']);

  @override
  void initState() {
    super.initState();
    _startGps();
  }

  @override
  void dispose() {
    gps?.cancel();
    super.dispose();
  }

  Future<void> _startGps() async {
    if (!onTrip || trip['gps_consent_at'] == null) return;
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
    if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) return;
    gps = Geolocator.getPositionStream(locationSettings: const LocationSettings(distanceFilter: 200)).listen((p) {
      final body = {'trip_id': trip['id'], 'lat': p.latitude, 'lng': p.longitude, 'recorded_at': p.timestamp.toUtc().toIso8601String()};
      Api.instance.sendOrQueue('/gps/ping', body, 'gps_ping', {'trip_id': trip['id'], 'lat': p.latitude, 'lng': p.longitude});
    });
  }

  Future<void> _do(Future<String> Function() f) async {
    try {
      final m = await f();
      setState(() => msg = m);
      final fresh = (await Api.instance.get('/trips/${trip['id']}'));
      setState(() => trip = fresh);
    } on ApiException catch (e) {
      setState(() => msg = e.message);
    }
  }

  Future<String> _event(String ev, [Map<String, dynamic> extra = const {}]) => Api.instance
      .sendOrQueue('/trips/${trip['id']}/events', {'event': ev, ...extra}, 'trip_event', {'trip_id': trip['id'], 'event': ev, ...extra});

  Widget big(String text, VoidCallback onTap, {Color? color}) => Padding(
        padding: const EdgeInsets.all(6),
        child: SizedBox(height: 64, child: FilledButton(style: FilledButton.styleFrom(backgroundColor: color), onPressed: onTap, child: Text(text, style: const TextStyle(fontSize: 18)))),
      );

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text('${trip['code']} · ${trip['status']}')),
        body: ListView(padding: const EdgeInsets.all(12), children: [
          Container(color: Colors.amber.shade100, padding: const EdgeInsets.all(10), child: Text(S.t('park'))),
          if (msg != null) Padding(padding: const EdgeInsets.all(8), child: Text(msg!, style: const TextStyle(fontWeight: FontWeight.bold))),
          for (final l in trip['loads'])
            ListTile(title: Text('Drop ${l['drop_seq']}: ${l['destination']} · ${l['packages']} pkg'), subtitle: Text('${l['consignee']} ${l['consignee_phone'] ?? ''} ${l['instructions'] ?? ''}')),
          if (trip['driver_ack_at'] == null) ...[
            const Text('G ROAD LINES collects your phone location only during this authorised trip.'),
            big('Accept trip & allow trip GPS', () => _do(() async {
                  await Api.instance.post('/trips/${trip['id']}/acknowledge', {'gps_consent': true});
                  return 'Trip accepted';
                })),
          ],
          if (['planned', 'ready'].contains(trip['status']) && trip['driver_ack_at'] != null) ...[
            const Text('Pre-trip inspection', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final c in checklist)
              SwitchListTile(title: Text(c.replaceAll('_', ' ')), subtitle: Text(check[c] == 'ok' ? 'OK' : 'DEFECT'), value: check[c] == 'ok', onChanged: (v) => setState(() => check[c] = v ? 'ok' : 'defect')),
            big('Submit inspection', () => _do(() => Api.instance.sendOrQueue('/inspections', {'vehicle_id': trip['vehicle_id'], 'trip_id': trip['id'], 'kind': 'pre_trip', 'checklist': check}, 'inspection',
                {'vehicle_id': trip['vehicle_id'], 'trip_id': trip['id'], 'kind': 'pre_trip', 'checklist': check}))),
            big('Arrived at pickup', () => _do(() => _event('arrived_pickup'))),
          ],
          Row(children: [
            Expanded(child: TextField(controller: label, decoration: const InputDecoration(labelText: 'Package label (QR)'))),
            IconButton(icon: const Icon(Icons.qr_code_scanner), onPressed: () => _do(() {
                  final stage = onTrip ? 'unloaded' : 'loaded';
                  final id = newEventId();
                  final body = {'label': label.text.trim(), 'trip_id': trip['id'], 'stage': stage, 'client_event_id': id};
                  label.clear();
                  return Api.instance.sendOrQueue('/scans', body, 'scan', {'label': body['label'], 'trip_id': trip['id'], 'stage': stage});
                })),
          ]),
          if (onTrip) ...[
            big('Departed', () => _do(() => _event('departed'))),
            big('Arrived at drop', () => _do(() => _event('arrived_drop'))),
            big('Delay +1 hour', () => _do(() => _event('delay', {'delay_minutes': 60, 'note': 'Reported by driver'}))),
            big('Start rest', () => _do(() => _event('rest_start'))),
            big('Breakdown', () => _do(() => _event('breakdown', {'note': 'Breakdown'}))),
            for (final l in trip['loads'])
              if (!['delivered', 'partial', 'failed'].contains(l['status']))
                big('Deliver ${l['booking_code']}', () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PodPage(trip: trip, load: l))).then((_) => _do(() async => 'Updated'))),
          ],
          big(S.t('sos'), () => _do(() async {
                Position? p;
                try {
                  p = await Geolocator.getCurrentPosition().timeout(const Duration(seconds: 8));
                } catch (_) {}
                return _event('sos', {'note': 'SOS', if (p != null) 'lat': p.latitude, if (p != null) 'lng': p.longitude});
              }), color: Colors.red),
        ]),
      );
}

class PodPage extends StatefulWidget {
  final Map trip, load;
  const PodPage({super.key, required this.trip, required this.load});
  @override
  State<PodPage> createState() => _PodPageState();
}

class _PodPageState extends State<PodPage> {
  final otp = TextEditingController();
  final receiver = TextEditingController();
  late final count = TextEditingController(text: '${widget.load['packages']}');
  String condition = 'good';
  String? msg;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text('POD ${widget.load['booking_code']}')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          OutlinedButton(
              onPressed: () async {
                try {
                  final r = await Api.instance.post('/pod/otp', {'trip_id': widget.trip['id'], 'booking_id': widget.load['booking_id']});
                  setState(() => msg = r['dev_otp'] != null ? 'MOCK SMS OTP (development): ${r['dev_otp']}' : 'OTP sent to consignee');
                } on ApiException catch (e) {
                  setState(() => msg = e.message);
                }
              },
              child: const Text('Send OTP to consignee')),
          TextField(controller: otp, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'OTP from receiver')),
          TextField(controller: count, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Packages delivered')),
          TextField(controller: receiver, decoration: const InputDecoration(labelText: 'Receiver name')),
          DropdownButton<String>(value: condition, items: ['good', 'damaged', 'wet', 'open', 'short'].map((c) => DropdownMenuItem(value: c, child: Text(c))).toList(), onChanged: (v) => setState(() => condition = v!)),
          FilledButton(
              onPressed: () async {
                try {
                  await Api.instance.post('/pod', {
                    'trip_id': widget.trip['id'], 'booking_id': widget.load['booking_id'], 'delivered_count': int.tryParse(count.text) ?? 0,
                    'receiver_name': receiver.text, 'otp': otp.text.isEmpty ? null : otp.text, 'condition': condition,
                  });
                  if (context.mounted) Navigator.of(context).pop();
                } on ApiException catch (e) {
                  setState(() => msg = e.message);
                }
              },
              child: const Text('Submit POD')),
          if (msg != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(msg!)),
        ]),
      );
}
